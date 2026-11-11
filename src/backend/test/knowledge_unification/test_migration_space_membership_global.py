"""T997: real global SPACE foreign-parent proof, reached from Control/M2."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import SpaceChannelMember as Member
from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    get_current_tenant_id,
    is_tenant_filter_bypassed,
    set_current_tenant_id,
)
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
)
from test.knowledge_unification import test_migration_control_repository as original
from test.knowledge_unification.test_migration_space_membership_inventory import member

control_native = original.native


@pytest.fixture
async def native(control_native):
    metadata = sa.MetaData()
    root = Knowledge.__table__.to_metadata(metadata)
    root.c.tenant_id.nullable = True  # Real legacy corruption, not a production schema change.
    Member.__table__.to_metadata(metadata)
    async with control_native.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    await control_native.insert(
        Knowledge,
        [
            {"id": ident, "tenant_id": tenant, "type": kind, "user_id": 7, "name": str(ident)}
            for ident, tenant, kind in ((1, 101, 0), (2, 202, 3), (3, 101, 1), (4, 202, 2))
        ],
    )
    control_native.queries.clear()
    control_native.statements.clear()
    control_native.writes.clear()
    return control_native


async def run(native, *, control=False):
    async with AsyncSession(native.engine) as session, session.begin():
        repo = UnificationControlRepository() if control else UnificationSpaceMembershipRepository()
        return await repo.avalidate_global_integrity(session)


@pytest.mark.parametrize(
    "business_id",
    [
        "",
        " 1",
        "1 ",
        "+1",
        "01",
        "0",
        "-1",
        "1.0",
        "1e0",
        "\uff11",
        "\u0661",
        "²",
        "9223372036854775808",
        "999999999999999999999999999999999999",
    ],
)
@pytest.mark.parametrize("control", [False, True])
async def test_every_raw_space_alias_is_rejected_including_inactive_noncreator_sources(native, business_id, control):
    await native.insert(
        Member, [member(17, business_id, user_role="ADMIN", status="REJECTED", membership_source="historical-source")]
    )
    native.writes.clear()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(native, control=control)
    assert not native.writes and get_current_tenant_id() == 101 and not is_tenant_filter_bypassed()
    assert not any("FROM knowledge" in sql for sql, _ in native.queries)


@pytest.mark.parametrize(
    ("parent", "tenant", "kind"), [(9, 101, 0), (6, 999, 0), (6, None, 0), (6, 0, 0), (6, -1, 0), (6, 101, 99)]
)
@pytest.mark.parametrize("control", [False, True])
async def test_actual_missing_parent_tenant_and_unknown_type_cannot_be_hidden_by_joins(
    native, parent, tenant, kind, control
):
    if parent != 9:
        await native.insert(Knowledge, [{"id": parent, "tenant_id": tenant, "type": kind, "name": "unclassified"}])
    await native.insert(Member, [member(17, str(parent))])
    native.writes.clear()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(native, control=control)
    assert not native.writes
    queries = [(sql, params) for sql, params in native.queries if "FROM knowledge" in sql]
    assert len(queries) == 1 and "LEFT OUTER JOIN tenant" in queries[0][0]


async def test_global_reads_cover_foreign_tenants_all_states_and_qa_retired_parents_without_changing_rows(native):
    values = [
        member(
            i,
            str(i),
            user_role=("CREATOR", "ADMIN", "MEMBER")[i % 3],
            status=("ACTIVE", "PENDING", "REJECTED")[i % 3],
            membership_source="unchanged",
        )
        for i in range(1, 5)
    ]
    values.append(member(9, "not-a-root", business_type="CHANNEL"))
    await native.insert(Member, values)
    native.writes.clear()
    assert await run(native, control=True) is None
    assert len(native.queries) == 6  # Four old controls, one Member page, one exact numeric Root batch.
    assert sum("m2_control_row" in sql for sql, _ in native.queries) == 4
    assert get_current_tenant_id() == 101 and not is_tenant_filter_bypassed() and not native.writes
    root_sql, params = next((sql, params) for sql, params in native.queries if "FROM knowledge" in sql)
    assert set(params) == {1, 2, 3, 4} and all(type(value) is int for value in params)
    assert "space_channel_member" not in root_sql and "CAST" not in root_sql.upper()
    async with native.engine.connect() as connection:
        stored = (await connection.execute(sa.select(Member.__table__).order_by(Member.id))).mappings().all()
    assert len(stored) == 5 and {row["membership_source"] for row in stored[:4]} == {"unchanged"}
    assert stored[-1]["business_id"] == "not-a-root"


async def test_empty_space_rows_need_no_fake_parent_or_write(native):
    await native.insert(Member, [member(1, "garbage", business_type="CHANNEL")])
    native.queries.clear()
    native.writes.clear()
    assert await run(native) is None
    assert len(native.queries) == 1 and "space_channel_member" in native.queries[0][0]
    assert not native.writes


async def test_largest_int64_parent_is_looked_up_as_an_exact_numeric_pk(native):
    maximum = 2**63 - 1
    await native.insert(Knowledge, [{"id": maximum, "tenant_id": 202, "type": 3, "name": "last"}])
    await native.insert(Member, [member(1, str(maximum))])
    assert await run(native) is None
    params = next(params for sql, params in native.queries if "FROM knowledge" in sql)
    assert params == (maximum,) and type(params[0]) is int


@pytest.mark.parametrize("control", [False, True])
async def test_raw_orphan_after_two_full_pages_is_not_reported_as_complete(native, control):
    await native.insert(Member, [member(i * 2, "1" if i < 401 else "999") for i in range(1, 402)])
    native.queries.clear()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await run(native, control=control)
    member_sql = [(sql, params) for sql, params in native.queries if "FROM space_channel_member" in sql]
    assert len(member_sql) == 3 and all("LIMIT" in sql and params[-2:] == (201, 0) for sql, params in member_sql)


@pytest.mark.parametrize("control", [False, True])
async def test_original_pending_objects_are_not_flushed_refreshed_or_replaced(native, control):
    await native.insert(Member, [member(1)])
    async with AsyncSession(native.engine) as session, session.begin():
        stored = await session.get(Member, 1)
        stored.business_id = "dirty-alias"
        pending = Member(business_id="bad-new", business_type="space", user_id=77, user_role="member")
        session.add(pending)
        native.queries.clear()
        native.writes.clear()
        flushes = []
        sa.event.listen(session.sync_session, "before_flush", lambda *_: flushes.append(True))
        repo = UnificationControlRepository() if control else UnificationSpaceMembershipRepository()
        assert await repo.avalidate_global_integrity(session) is None
        assert stored.business_id == "dirty-alias" and stored in session.dirty and pending in session.new
        assert not flushes and not native.writes
        assert list(session.identity_map.values()) == [stored]
        await session.rollback()


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("changed", ["tenant", "transaction", "failure"])
@pytest.mark.parametrize("boundary", ["first", "parent"])
async def test_every_real_await_rechecks_original_context_and_restores_short_bypass(
    native, monkeypatch, control, changed, boundary
):
    await native.insert(Member, [member(1)])
    async with AsyncSession(native.engine) as session, session.begin():
        execute, tokens, nested, calls = session.execute, [], [], []
        at = (6 if control else 2) if boundary == "parent" else 1

        async def mutation(*args, **kwargs):
            result = await execute(*args, **kwargs)
            calls.append(1)
            if len(calls) != at:
                return result
            if changed == "tenant":
                tokens.append(set_current_tenant_id(202))
            elif changed == "transaction":
                nested.append(await session.begin_nested())
            else:
                raise RuntimeError("after actual native read")
            return result

        monkeypatch.setattr(session, "execute", mutation)
        repo = UnificationControlRepository() if control else UnificationSpaceMembershipRepository()
        try:
            with pytest.raises(RuntimeError if changed == "failure" else KnowledgeOperationPlanConflictError):
                await repo.avalidate_global_integrity(session)
            assert len(native.queries) == at and not is_tenant_filter_bypassed()
        finally:
            for token in reversed(tokens):
                current_tenant_id.reset(token)
            for active in reversed(nested):
                await active.rollback()


@pytest.mark.parametrize("value", [None, 0, -1, True, "101"])
async def test_global_member_entry_needs_original_concrete_tenant_before_any_query(native, value):
    async with AsyncSession(native.engine) as session, session.begin():
        token = set_current_tenant_id(value)
        try:
            with pytest.raises(KnowledgeOperationPlanConflictError):
                await UnificationSpaceMembershipRepository().avalidate_global_integrity(session)
        finally:
            current_tenant_id.reset(token)
    assert not native.queries


async def test_global_member_entry_refuses_autobegin_and_ambient_bypass(native):
    async with AsyncSession(native.engine) as session:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await UnificationSpaceMembershipRepository().avalidate_global_integrity(session)
        assert not session.in_transaction()
        async with session.begin():
            with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
                await UnificationSpaceMembershipRepository().avalidate_global_integrity(session)
    assert not native.queries and not is_tenant_filter_bypassed()
