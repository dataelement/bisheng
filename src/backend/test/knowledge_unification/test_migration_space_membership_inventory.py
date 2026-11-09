"""T986: original SPACE membership is explicit, bounded inventory, not a grant.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
Native SQLite proves paging/tenancy/codec, not MySQL locks or a formal freeze.
"""

import importlib
from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.models.space_channel_member import SpaceChannelMember as Member
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.domain.models.knowledge import Knowledge
from test.knowledge_unification.test_ref_repo import tenant as tenant

NOW = datetime(2026, 11, 9, 6, 7, 8)


def api():
    return importlib.import_module("bisheng.knowledge.domain.repositories.unification_space_membership_repository")


@pytest.fixture
async def native():
    engine = create_async_engine("sqlite+aiosqlite://")
    statements = []

    def capture(_conn, _cursor, statement, params, _context, _many):
        statements.append((statement, params))

    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: Knowledge.__table__.create(conn))
        await connection.run_sync(lambda conn: Member.__table__.create(conn))
        await connection.execute(
            sa.insert(Knowledge.__table__),
            [
                {"id": ident, "tenant_id": owner, "type": kind, "user_id": 7, "name": str(ident)}
                for ident, owner, kind in ((1, 101, 0), (2, 101, 3), (3, 101, 1), (4, 101, 2), (5, 202, 0))
            ],
        )
    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncSession(engine) as session, session.begin():
            yield SimpleNamespace(engine=engine, session=session, statements=statements)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()


def member(ident, space_id="1", **changes):
    return {
        "id": ident,
        "business_id": space_id,
        "business_type": "SPACE",
        "user_id": 7,
        "user_role": "CREATOR",
        "status": "ACTIVE",
        "membership_source": "manual",
        "department_admin_promoted_from_role": None,
        "relation": None,
        "grant_subject_type": None,
        "grant_subject_id": None,
        "grant_relation": None,
        "grant_include_children": False,
        "grant_model_id": None,
        "grant_binding_key": None,
        "is_pinned": False,
        "create_time": NOW,
        "update_time": NOW,
        **changes,
    }


async def seed(native, values):
    await native.session.execute(sa.insert(Member.__table__), values)
    native.statements.clear()


async def test_headers_make_zero_members_explicit_and_do_not_convert_or_include_qa(native):
    repo = api().UnificationSpaceMembershipRepository()
    page = await repo.apage_headers(native.session)
    assert [
        (row.knowledge_id, row.tenant_id, row.knowledge_type, row.creator_user_id, row.member_count)
        for row in page.items
    ] == [
        (1, 101, 0, 7, 0),
        (2, 101, 3, 7, 0),
    ]
    assert page.next_after is None
    assert len(native.statements) == 2
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in native.statements)
    with pytest.raises(FrozenInstanceError):
        page.items[0].member_count = 99
    record = codec.record_from_row(page.items[0])
    assert record.record_type == "space_membership_header" and record.data["member_count"] == 0
    assert record.data["row_digest"] == codec.digest(
        {part.name: getattr(page.items[0], part.name) for part in fields(page.items[0])}
    )


async def test_exact_parent_reads_preserve_all_member_source_columns_and_conflicts_as_facts(native):
    await seed(
        native,
        [
            member(10),
            member(
                11,
                user_role="MEMBER",
                status="PENDING",
                user_id=8,
                membership_source="department_admin",
                department_admin_promoted_from_role="member",
                relation="editor",
                grant_subject_type="department",
                grant_subject_id=19,
                grant_relation="editor",
                grant_include_children=True,
                grant_model_id="editor",
                grant_binding_key="original-binding",
                is_pinned=True,
            ),
            member(12),  # Duplicates must remain facts for the later preflight.
            member(13, "2"),
            member(14, "5"),
            member(15, "1", business_type="CHANNEL"),
        ],
    )
    module = api()
    repo = module.UnificationSpaceMembershipRepository()
    headers = await repo.apage_headers(native.session)
    assert [(row.knowledge_id, row.member_count) for row in headers.items] == [(1, 3), (2, 1)]
    page = await repo.apage_members(native.session, knowledge_ids=(1,), limit=2)
    assert [row.id for row in page.items] == [10, 11] and page.next_after == 11
    last = await repo.apage_members(native.session, knowledge_ids=(1,), after_id=page.next_after, limit=2)
    assert [row.id for row in last.items] == [12] and last.next_after is None
    row = page.items[1]
    assert {part.name for part in fields(row)} == {"tenant_id", "knowledge_id", *Member.__table__.c.keys()}
    assert (row.business_type, row.user_role, row.status, row.relation, row.grant_relation) == (
        "space",
        "member",
        "PENDING",
        "editor",
        "editor",
    )
    assert (row.tenant_id, row.knowledge_id, row.grant_subject_id, row.grant_include_children, row.is_pinned) == (
        101,
        1,
        19,
        True,
        True,
    )
    assert row.create_time == NOW and row.update_time == NOW
    record = codec.record_from_row(row)
    assert record.record_type == "space_member" and record.data["grant_binding_key"] == "original-binding"
    args = {"run_id": "member-native", "section": "control", "scope": "tenant", "tenant_id": 101, "page_index": 0}
    content = codec.encode_inventory_page(**args, records=(record,))
    assert codec.decode_inventory_page(content, **args).records == (record,)
    for changes in ({"user_id": True}, {"grant_include_children": 1}, {"unexpected": "field"}):
        with pytest.raises(ReferenceCoverageNotReadyError):
            codec.record_from_values(record.record_type, **(record.data | changes))


@pytest.mark.parametrize("ids", [(5,), (3,), (4,), (999,), (1, 5)])
async def test_every_selected_parent_must_be_owned_and_in_the_conversion_namespace(native, ids):
    repo = api().UnificationSpaceMembershipRepository()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await repo.apage_members(native.session, knowledge_ids=ids)
    assert not any("space_channel_member" in sql.lower() for sql, _ in native.statements)


@pytest.mark.parametrize("ids", [(True,), (0,), (1, 1), [1], tuple(range(1, 202))])
async def test_invalid_target_batches_fail_before_sql(native, ids):
    repo = api().UnificationSpaceMembershipRepository()
    with pytest.raises((ValueError, KnowledgeOperationPlanConflictError)):
        await repo.apage_members(native.session, knowledge_ids=ids)
    assert not native.statements


async def test_empty_selection_no_scope_claim_and_context_change_or_bypass_rejected(native):
    repo = api().UnificationSpaceMembershipRepository()
    assert (await repo.apage_members(native.session, knowledge_ids=())).items == ()
    assert not native.statements
    with tenant_execution_scope(202):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await repo.apage_members(native.session, knowledge_ids=(1,))
    with bypass_tenant_filter(), pytest.raises(KnowledgeOperationPlanConflictError):
        await repo.apage_headers(native.session)


async def test_inventory_does_not_flush_or_refresh_pending_member_changes(native):
    repo = api().UnificationSpaceMembershipRepository()
    pending = Member(business_id="1", business_type="space", user_id=7, user_role="creator")
    native.session.add(pending)
    assert (await repo.apage_headers(native.session)).items[0].member_count == 0
    assert not (await repo.apage_members(native.session, knowledge_ids=(1,))).items
    assert pending.id is None and pending in native.session.new
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in native.statements)


@pytest.mark.parametrize("count", [200, 401, 10001])
async def test_native_many_spaces_and_sparse_members_follow_page_budget(native, count):
    await native.session.execute(
        sa.insert(Knowledge.__table__),
        [
            {"id": ident, "tenant_id": 101, "type": 0, "user_id": 7, "name": str(ident)}
            for ident in range(1000, 1000 + count)
        ],
    )
    await seed(native, [member(ident, str(ident)) for ident in (1000, 1000 + count // 2, 999 + count)])
    repo = api().UnificationSpaceMembershipRepository()
    after, headers = None, []
    while True:
        page = await repo.apage_headers(native.session, after_id=after)
        headers.extend(page.items)
        if page.next_after is None:
            break
        after = page.next_after
    assert len(headers) == count + 2 and sum(row.member_count for row in headers) == 3
    assert len(native.statements) == 2 * ((count + 2 + 199) // 200)
    native.statements.clear()
    rows = []
    for start in range(0, len(headers), 200):
        selected = tuple(row.knowledge_id for row in headers[start : start + 200])
        page = await repo.apage_members(native.session, knowledge_ids=selected)
        assert page.next_after is None
        rows.extend(page.items)
    assert len(rows) == 3
    assert len(native.statements) == 2 * ((count + 2 + 199) // 200)
    assert max(len(params) for _, params in native.statements) <= 205
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in native.statements)
