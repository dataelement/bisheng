"""T1022 supplement: fresh native Sessions pin before their first target lock."""

from dataclasses import asdict

import pytest
from sqlalchemy import event, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.database.models.tenant import Tenant
from bisheng.llm.domain.services import model_reference_service as service_module
from bisheng.resource_reference.application.contracts import TransactionIdentity
from bisheng.resource_reference.domain.repositories.coverage_repository import CoverageRepository
from test.knowledge_unification import test_llm_refs as fixtures
from test.knowledge_unification import test_model_reference_sources as sources

model_owner_tenant = fixtures.model_owner_tenant
removal_session = fixtures.removal_session
impact = fixtures.impact


async def saved_sources(impact):
    session, service, _ = impact
    sources.metadata(service)
    for ident in ("a", "b", "c"):
        sources.seed(session, ident=ident)
    await session.commit()


def fresh_impact(active, service):
    ledger = fixtures.SqlLedger(active)
    service.coverage_factory = lambda _: CoverageRepository(ledger, global_port=ledger)
    return active, service, ledger


@pytest.mark.parametrize("stage", ["removal_return", "native_server_lock"])
@pytest.mark.parametrize("drift", ["replace", "nested"])
async def test_fresh_first_lock_transaction_is_never_replaced_before_pin(impact, monkeypatch, stage, drift):
    session, service, _ = impact
    await saved_sources(impact)
    async with AsyncSession(session.bind, expire_on_commit=False) as active:
        assert not active.in_transaction()
        fresh = fresh_impact(active, service)
        original_pins = []

        async def change():
            before = TransactionIdentity.capture(active)
            if drift == "replace":
                await active.rollback()
                await active.execute(select(Tenant.id).limit(1))
            else:
                await active.begin_nested()
            original_pins.append(before)
            assert TransactionIdentity.capture(active).transaction is not before.transaction

        if stage == "removal_return":
            method = service.repository.alock_removal_targets

            async def wrapped(*args, **kwargs):
                result = await method(*args, **kwargs)
                await change()
                return result

            monkeypatch.setattr(service.repository, "alock_removal_targets", wrapped)
        else:
            execute = active.execute

            async def wrapped(statement, *args, **kwargs):
                result = await execute(statement, *args, **kwargs)
                if (
                    not original_pins
                    and getattr(statement, "_for_update_arg", None) is not None
                    and any(getattr(table, "name", None) == "llm_server" for table in statement.get_final_froms())
                ):
                    await change()
                return result

            monkeypatch.setattr(active, "execute", wrapped)
        with fixtures.actor() as user, pytest.raises(ReferenceCoverageNotReadyError):
            await sources.first(fresh, user)
        assert original_pins


async def test_native_checkout_is_zero_sql_and_preserves_existing_result_cursor_and_sql(impact, monkeypatch):
    session, service, _ = impact
    await saved_sources(impact)
    statements = []

    def capture(_c, _cu, sql, _params, _ctx, _many):
        statements.append(sql)

    event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncSession(session.bind, expire_on_commit=False) as fresh:
            connection = await fresh.connection()
            assert fresh.in_transaction() and connection.in_transaction()
            TransactionIdentity.capture(fresh).assert_current(fresh)
            assert statements == []
        await session.execute(select(Tenant.id).limit(1))
        statements.clear()
        existing_connection, checkouts = session.connection, []

        async def existing_checkout(*args, **kwargs):
            checkouts.append("existing")
            return await existing_connection(*args, **kwargs)

        monkeypatch.setattr(session, "connection", existing_checkout)
        with fixtures.actor() as user:
            expected = await sources.first(impact, user)
        assert checkouts == []
        original_sql = tuple(statements)
        await session.commit()
        statements.clear()
        async with AsyncSession(session.bind, expire_on_commit=False) as fresh:
            assert not fresh.in_transaction()
            connection = fresh.connection

            async def checkout(*args, **kwargs):
                checkouts.append("fresh")
                return await connection(*args, **kwargs)

            monkeypatch.setattr(fresh, "connection", checkout)
            with fixtures.actor() as user:
                actual = await sources.first(fresh_impact(fresh, service), user)
            assert asdict(actual) == asdict(expected)
            assert tuple(statements) == original_sql
            assert checkouts == ["fresh"]
            print(
                {
                    "native_checkout_sql": 0,
                    "existing_checkout": 0,
                    "fresh_checkout": 1,
                    "sql": len(original_sql),
                    "cursor_and_result": "identical",
                }
            )
    finally:
        event.remove(session.bind.sync_engine, "before_cursor_execute", capture)


async def test_connection_failure_preserves_cause_and_never_calls_target_locks(impact, monkeypatch):
    session, service, _ = impact
    await session.commit()
    async with AsyncSession(session.bind, expire_on_commit=False) as fresh:
        error = OSError("native connection unavailable")

        async def unavailable(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(fresh, "connection", unavailable)
        locks, method = [], service.repository.alock_removal_targets

        async def lock(*args, **kwargs):
            locks.append(1)
            return await method(*args, **kwargs)

        monkeypatch.setattr(service.repository, "alock_removal_targets", lock)
        with fixtures.actor() as user, pytest.raises(ReferenceCoverageNotReadyError) as caught:
            await sources.first((fresh, service, None), user)
        assert caught.value.__cause__ is error and locks == [] and not fresh.in_transaction()


async def test_early_identity_callback_autobegin_is_pinned_without_extra_checkout(impact, monkeypatch):
    session, service, _ = impact
    await saved_sources(impact)
    async with AsyncSession(session.bind, expire_on_commit=False) as fresh:
        fresh_tuple = fresh_impact(fresh, service)
        stable, early_pin = service._stable_identity, []

        async def identity(*args, **kwargs):
            result = await stable(*args, **kwargs)
            if not early_pin:
                await fresh.execute(select(Tenant.id).limit(1))
                early_pin.append(TransactionIdentity.capture(fresh))
            return result

        async def redundant_checkout(*_args, **_kwargs):
            pytest.fail("the earlier callback already opened the original transaction")

        monkeypatch.setattr(service, "_stable_identity", identity)
        monkeypatch.setattr(fresh, "connection", redundant_checkout)
        with fixtures.actor() as user:
            result = await sources.first(fresh_tuple, user)
        assert result.check_complete and result.blocked
        early_pin[0].assert_current(fresh)


async def test_every_actual_removal_statement_runs_after_the_original_transaction_pin(impact, monkeypatch):
    session, service, _ = impact
    await saved_sources(impact)
    async with AsyncSession(session.bind, expire_on_commit=False) as fresh:
        pins, statements = [], []
        pin = service_module._InspectionScope.pin

        def pinned(scope):
            pin(scope)
            pins.append(scope.transaction)

        execute = fresh.execute

        async def checked(statement, *args, **kwargs):
            assert len(pins) == 1
            pins[0].assert_current(fresh)
            statements.append(statement)
            return await execute(statement, *args, **kwargs)

        monkeypatch.setattr(service_module._InspectionScope, "pin", pinned)
        monkeypatch.setattr(fresh, "execute", checked)
        with fixtures.actor() as user:
            result = await sources.first(fresh_impact(fresh, service), user)
        assert result.check_complete and result.blocked and len(statements) >= 3
        assert len(pins) == 1
