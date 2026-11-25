"""§119: original receipt/Scope authority and native await-boundary controls."""

from copy import copy

import pytest
import sqlalchemy as sa

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile as File
from bisheng.resource_reference.application.contracts import TargetKey
from bisheng.resource_reference.application.target_verification import ReferenceTargetVerifier
from test.knowledge_unification import test_move_reference_ownership as base
from test.knowledge_unification.test_move_execution_fixtures import logical

store, tenant, moving, accepted, built = base.store, base.tenant, base.moving, base.accepted, base.built
ERRORS = (ResourceReferenceInvalidError, KnowledgeOperationPlanConflictError, ValueError)


@pytest.mark.parametrize(
    "bad",
    ["copied_receipt", "copied_scope", "other_verifier", "space_target", "before", "bad_expected", "no_tx", "pending"],
)
async def test_original_runtime_and_scope_cannot_be_forged_or_used_for_arbitrary_owner(built, bad):
    rt = base.compose(built)
    async with built.sessions() as session:
        await logical(session, built)
        receipts = await rt.runtime.verifier.averify_owner_targets(session, (TargetKey("knowledge_file", 81),))
        scope = rt.repo.target_owner_scope(session, receipts)
        if bad == "copied_receipt":
            receipts = (copy(receipts[0]),)
        elif bad == "copied_scope":
            scope = copy(scope)
        elif bad == "other_verifier":
            rt.repo.verifier = ReferenceTargetVerifier({"knowledge_file": rt.owner})
        elif bad == "space_target":
            receipts = await rt.runtime.verifier.averify_owner_targets(session, (TargetKey("knowledge_space", 11),))
        elif bad == "no_tx":
            await session.rollback()
        elif bad == "pending":
            session.add(File(id=900, tenant_id=101, knowledge_id=11, file_name="pending", file_type=1))

        async def call():
            if bad == "copied_scope":
                return await rt.repo.aupdate_file_target_ownership(session, scope=scope, expected_space_id=10)
            return await rt.runtime.arefresh_file_target_ownership(
                session,
                receipts=receipts,
                expected_space_id=11 if bad == "before" else True if bad == "bad_expected" else 10,
            )

        with pytest.raises(ERRORS):
            await call()
        if bad == "pending":
            assert len(session.new) == 1
        await session.rollback()


@pytest.mark.parametrize("change", ["tx", "nested", "tenant", "bypass"])
async def test_real_owner_await_context_change_rejected_before_any_brr_update(built, monkeypatch, change):
    base.compose(built)
    writes = []
    original = built.cutover.assert_logical_current
    async with built.sessions() as session:
        receipt = await logical(session, built)
        nested = None
        context = None

        if change == "tx":
            await session.rollback()
            await session.begin()
        elif change == "nested":
            nested = await session.begin_nested()
        else:
            context = tenant_execution_scope(202) if change == "tenant" else bypass_tenant_filter()
            context.__enter__()

        def capture(connection, cursor, statement, parameters, execution_context, many):
            if statement.startswith("UPDATE business_resource_reference"):
                writes.append(statement)

        sa.event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            with pytest.raises(ERRORS):
                original(receipt, session)
            assert not writes
        finally:
            sa.event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
            if context is not None:
                context.__exit__(None, None, None)
            if nested is not None:
                await nested.rollback()
            await session.rollback()


async def test_empty_inbound_is_valid_and_never_creates_a_source_or_rewrites_anything(built):
    base.compose(built)
    async with built.sessions() as session, session.begin():
        await session.execute(sa.delete(base.BRR.__table__).where(base.BRR.tenant_id == 101))
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        built.cutover.assert_logical_current(receipt, session)
        assert await session.scalar(sa.select(sa.func.count()).select_from(base.Source)) == 1


@pytest.mark.parametrize("zero", ["empty", "skipped"])
async def test_zero_index_items_still_real_cutover_r2_then_ready(moving, accepted, monkeypatch, zero):
    built = await base.pipeline(moving, accepted, monkeypatch, zero=zero)
    ids = tuple(row.file_id for row in built.confirmed.scope.files)
    await base.seed(built, rows=[base.binding(n + 1, ident) for n, ident in enumerate(ids)])
    base.compose(built)
    async with built.sessions() as session, session.begin():
        async with session.begin_nested():
            receipt = await logical(session, built)
            built.cutover.assert_logical_current(receipt, session)
            result = await base.mark(session, built, receipt)
            assert result.state == "succeeded"
    refs, _, _, marker = await base.facts(built)
    assert marker is not None and {row["target_space_id"] for row in refs} == {"10"}


async def test_reference_storage_write_failure_is_irrelevant_to_logical_move(built):
    async with built.sessions() as session, session.begin():
        await session.execute(sa.insert(base.BRR.__table__), [base.binding(10 + n) for n in range(401)])
    before = await base.facts(built)
    updates = []

    def fail(connection, cursor, statement, parameters, execution_context, many):
        if statement.startswith("UPDATE business_resource_reference"):
            updates.append(statement)
            raise RuntimeError("BRR writes are forbidden in move")

    async with built.sessions() as session, session.begin():
        engine = session.bind.sync_engine
        sa.event.listen(engine, "before_cursor_execute", fail)
        try:
            receipt = await logical(session, built)
            await base.mark(session, built, receipt)
        finally:
            sa.event.remove(engine, "before_cursor_execute", fail)
    after = await base.facts(built)
    assert not updates and after[:2] == before[:2] and after[3] is not None
