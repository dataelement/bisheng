"""T1022: the complete internal impact retains its original native lock TX.

覆盖 AC: AC-70, AC-71, AC-72, AC-73, AC-75, AC-76, AC-89
Real rollback/rebegin and SAVEPOINT changes occur after successful callbacks.
"""

import pytest
from sqlalchemy import event, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.const import LLMModelType
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer
from bisheng.resource_reference.application.contracts import TransactionIdentity
from test.knowledge_unification import test_llm_refs as original
from test.knowledge_unification import test_model_reference_sources as sources

model_owner_tenant = original.model_owner_tenant
removal_session = original.removal_session
impact = original.impact


async def prepare(impact):
    session, service, _ = impact
    sources.metadata(service)
    for ident in ("a", "b", "c"):
        sources.seed(session, ident=ident)
    await session.commit()
    await session.execute(select(Tenant.id).limit(1))
    return TransactionIdentity.capture(session)


class Drift:
    def __init__(self, session, mode):
        self.session, self.mode, self.changed = session, mode, False
        self.scope = None

    async def apply(self):
        assert not self.changed
        self.changed = True
        before = TransactionIdentity.capture(self.session)
        if self.mode == "replace":
            await self.session.rollback()
            await self.session.execute(select(Tenant.id).limit(1))
            assert TransactionIdentity.capture(self.session).transaction is not before.transaction
        elif self.mode == "nested":
            await self.session.begin_nested()
            assert TransactionIdentity.capture(self.session).transaction is not before.transaction
        else:
            self.scope = tenant_execution_scope(202)
            self.scope.__enter__()

    def restore(self):
        if self.scope is not None:
            self.scope.__exit__(None, None, None)


def after_call(monkeypatch, target, name, change, *, ordinal=1):
    method, calls = getattr(target, name), 0

    async def wrapped(*args, **kwargs):
        nonlocal calls
        result = await method(*args, **kwargs)
        calls += 1
        if calls == ordinal:
            await change.apply()
        return result

    monkeypatch.setattr(target, name, wrapped)


def install(monkeypatch, impact, stage, change):
    _, service, ledger = impact
    if stage == "authorize":
        after_call(monkeypatch, service, "_authorize", change)
    elif stage in ("identity_head", "identity_tail"):
        after_call(monkeypatch, service, "_stable_identity", change, ordinal=1 if stage.endswith("head") else 2)
    elif stage == "removal":
        after_call(monkeypatch, service.repository, "alock_removal_targets", change)
    elif stage == "owner":
        after_call(monkeypatch, service.runtime.verifier, "averify_owner_targets", change)
    elif stage in ("global_head", "global_tail"):
        after_call(monkeypatch, ledger, "aget_global_status", change, ordinal=1 if stage.endswith("head") else 2)
    elif stage in ("tenant_head", "tenant_tail"):
        after_call(monkeypatch, ledger, "aget_status", change, ordinal=1 if stage.endswith("head") else 12)
    elif stage == "disclosure":
        after_call(monkeypatch, service.disclosure_runtime, "adisclose_sources", change)
    elif stage == "capture_tail":
        # _authorize captures once; the successful final capture is second.
        after_call(monkeypatch, service.identity, "acapture", change, ordinal=2)
    else:
        method = service.runtime.repository.aiter_inbound_for_owner_pages

        async def pages(*args, **kwargs):
            async for page in method(*args, **kwargs):
                yield page
            await change.apply()

        monkeypatch.setattr(service.runtime.repository, "aiter_inbound_for_owner_pages", pages)


@pytest.mark.parametrize("mode", ["replace", "nested", "tenant"])
@pytest.mark.parametrize(
    "stage",
    [
        "authorize",
        "identity_head",
        "removal",
        "owner",
        "global_head",
        "tenant_head",
        "stream_tail",
        "disclosure",
        "global_tail",
        "tenant_tail",
        "capture_tail",
        "identity_tail",
    ],
)
async def test_successful_callback_cannot_release_original_locks_or_change_scope(impact, monkeypatch, stage, mode):
    session, _, _ = impact
    await prepare(impact)
    change = Drift(session, mode)
    install(monkeypatch, impact, stage, change)
    statements = []

    def record(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", record)
    try:
        with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError) as failure:
            await sources.first(impact, user)
        assert failure.value.Code == 10994 and change.changed
        assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in statements)
    finally:
        change.restore()
        event.remove(session.bind.sync_engine, "before_cursor_execute", record)


@pytest.mark.parametrize("mode", ["replace", "nested", "tenant"])
async def test_continuation_rechecks_its_own_tail_lock_transaction(impact, monkeypatch, mode):
    session, _, _ = impact
    await prepare(impact)
    with original.actor() as user:
        before = await sources.first(impact, user)
        assert before.source_page.has_more
        change = Drift(session, mode)
        # First inspection consumed two calls; the wrapper counts from here.
        install(monkeypatch, impact, "global_tail", change)
        try:
            with pytest.raises(ReferenceCoverageNotReadyError) as failure:
                await sources.following(impact, user, before.source_page.next_cursor)
            assert failure.value.Code == 10994 and change.changed
        finally:
            change.restore()


@pytest.mark.parametrize("removed", [False, True])
async def test_zero_models_or_zero_removed_targets_still_pin_the_lock_transaction(impact, monkeypatch, removed):
    session, service, _ = impact
    if not removed:
        session.add(LLMServer(id=5, tenant_id=101, name="empty", type="openai"))
    await prepare(impact)
    change = Drift(session, "replace")
    install(monkeypatch, impact, "global_tail", change)
    with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await service.ainspect_removed_models(
            session,
            identity=user,
            server_id=1 if removed else 5,
            retained_model_ids=(11, 12, 13, 14, 15) if removed else (),
        )
    assert change.changed


@pytest.mark.parametrize("nested", [False, True])
async def test_stable_native_transaction_and_existing_savepoint_are_preserved(impact, nested):
    session, _, _ = impact
    await prepare(impact)
    if nested:
        await session.begin_nested()
    before = TransactionIdentity.capture(session)
    with original.actor() as user:
        result = await sources.first(impact, user)
    before.assert_current(session)
    assert result.check_complete and result.blocked


async def test_fresh_native_session_autobegins_and_can_continue_on_another_fresh_session(impact):
    session, service, _ = impact
    await prepare(impact)
    await session.commit()
    cursor = None
    for _ in range(2):
        async with AsyncSession(session.bind, expire_on_commit=False) as active:
            assert not active.in_transaction()
            ledger = original.SqlLedger(active)
            from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository

            service.coverage_factory = lambda _, ledger=ledger: CoverageRepository(ledger, global_port=ledger)
            with original.actor() as user:
                if cursor is None:
                    result = await sources.first((active, service, ledger), user)
                    cursor = result.source_page.next_cursor
                    assert result.check_complete and result.source_page.has_more
                else:
                    page = await sources.following((active, service, ledger), user, cursor)
                    assert len(page.data) == 1 and not page.has_more
            assert active.in_transaction()


async def test_actual_asr_realtime_uses_the_same_model_id_target_and_original_five_types(impact):
    session, _, _ = impact
    session.add(
        LLMModel(id=16, server_id=1, tenant_id=101, model_name="realtime", model_type=LLMModelType.ASR_RT.value)
    )
    _, rows = original.seed(session, slots=1)
    rows[0].target_id = "16"
    await session.flush()
    with original.actor() as user:
        result = await original.inspect(impact, user, delete_server=True)
    assert {key.target_id for key in result.targets} == {"11", "12", "13", "14", "15", "16"}
    assert result.check_complete and result.blocked and sum(dict(result.slot_counts).values()) == 1


async def test_missing_native_session_is_not_a_compatibility_fallback(impact):
    _, service, _ = impact
    with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
        await service.ainspect_removed_models(object(), identity=user, server_id=1, retained_model_ids=())


@pytest.mark.parametrize("mode", ["replace", "nested", "tenant"])
async def test_later_disclosure_batch_still_uses_the_first_lock_pin(impact, monkeypatch, mode):
    session, service, _ = impact
    owner = sources.metadata(service)
    for index in range(401):
        sources.seed(session, ident=f"batch-{index:03}")
    await session.commit()
    await session.execute(select(Tenant.id).limit(1))
    change = Drift(session, mode)
    after_call(monkeypatch, service.disclosure_runtime, "adisclose_sources", change, ordinal=2)
    try:
        with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
            await sources.first(impact, user)
        assert change.changed and [len(batch) for batch in owner.calls] == [200, 200]
    finally:
        change.restore()


async def test_fresh_session_cannot_replace_the_naturally_started_transaction_at_tail(impact, monkeypatch):
    session, service, _ = impact
    await prepare(impact)
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as active:
        assert not active.in_transaction()
        ledger = original.SqlLedger(active)
        from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository

        service.coverage_factory = lambda _: CoverageRepository(ledger, global_port=ledger)
        fresh = active, service, ledger
        change = Drift(active, "replace")
        install(monkeypatch, fresh, "global_tail", change)
        with original.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
            await sources.first(fresh, user)
        assert change.changed
