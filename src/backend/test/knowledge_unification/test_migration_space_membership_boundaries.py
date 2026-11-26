"""T987 native boundaries: complete facts retain caller SQL/session state.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
No Member repair, grant, global orphan claim or M2 application wiring.
"""

from dataclasses import fields
from datetime import datetime

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.domain.repositories import unification_space_membership_repository as module
from test.knowledge_unification import test_migration_space_membership_inventory as original

native = original.native
own_tenant = original.own_tenant
Member, Knowledge = original.Member, original.Knowledge


def test_member_column_ssot_and_dto_cover_the_actual_sql_table_and_closed_schema():
    assert set(module.MEMBER_COLUMNS) == set(Member.__table__.c.keys())
    assert len(module.MEMBER_COLUMNS) == len(set(module.MEMBER_COLUMNS))
    assert {part.name for part in fields(module.SpaceMembershipRow)} == {
        "tenant_id",
        "knowledge_id",
        *module.MEMBER_COLUMNS,
    }
    assert set(codec._SCHEMAS["space_member"]) == {"tenant_id", "knowledge_id", *module.MEMBER_COLUMNS, "row_digest"}
    assert set(codec._SCHEMAS["space_membership_header"]) == {*module.HEADER_COLUMNS, "row_digest"}


async def test_full_pk_pages_nullable_enum_and_original_source_facts_roundtrip(native):
    values = [
        original.member(
            ident * 2,
            str(1 + ident % 2),
            user_id=ident % 5,
            user_role=("CREATOR", "ADMIN", "MEMBER")[ident % 3],
            status=("ACTIVE", "PENDING", "REJECTED")[ident % 3],
            membership_source="original-unclassified-source" if ident % 2 else "manual",
            grant_binding_key=f"binding-{ident}" if ident % 2 else None,
            grant_subject_type="user_group" if ident % 2 else None,
            grant_subject_id=ident if ident % 2 else None,
            grant_model_id="retired:original-model" if ident % 2 else None,
            grant_relation="viewer" if ident % 2 else None,
            grant_include_children=bool(ident % 2),
            is_pinned=bool(ident % 2),
            create_time=datetime(2020, 2, 3, 4, 5, 6, 123456),
            update_time=None,
        )
        for ident in range(1, 402)
    ]
    await original.seed(native, values)
    repository = module.UnificationSpaceMembershipRepository()
    headers = await repository.apage_headers(native.session)
    assert [(row.knowledge_id, row.member_count) for row in headers.items] == [(1, 200), (2, 201)]
    native.statements.clear()
    after, rows, sizes = None, [], []
    while True:
        page = await repository.apage_members(native.session, knowledge_ids=(2, 1), after_id=after)
        sizes.append(len(page.items))
        rows.extend(page.items)
        if page.next_after is None:
            break
        after = page.next_after
    assert sizes == [200, 200, 1] and [row.id for row in rows] == list(range(2, 803, 2))
    assert len(native.statements) == 6 and max(len(params) for _, params in native.statements) <= 6
    assert {row.user_role for row in rows} == {"creator", "admin", "member"}
    assert {row.status for row in rows} == {"ACTIVE", "PENDING", "REJECTED"}
    assert all(row.tenant_id == 101 and row.knowledge_id == int(row.business_id) for row in rows)
    assert all(row.update_time is None and row.create_time == values[0]["create_time"] for row in rows)
    assert rows[0].grant_binding_key == "binding-1" and rows[1].grant_binding_key is None
    assert not native.session.identity_map
    for start in range(0, len(rows), 199):
        records = tuple(codec.record_from_row(row) for row in rows[start : start + 199])
        args = {
            "run_id": "member-boundaries",
            "section": "control",
            "scope": "tenant",
            "tenant_id": 101,
            "page_index": start,
        }
        content = codec.encode_inventory_page(**args, records=records)
        assert codec.decode_inventory_page(content, **args).records == records
        for row, record in zip(rows[start : start + 199], records, strict=True):
            assert record.data["row_digest"] == codec.digest(
                {part.name: getattr(row, part.name) for part in fields(row)}
            )
    print({"roots": 2, "members": len(rows), "member_pages": sizes, "sql": len(native.statements)})


async def test_exact_full_page_needs_no_lookahead_continuation_or_orm_refresh(native):
    await original.seed(native, [original.member(ident) for ident in range(1, 201)])
    original_member = await native.session.get(Member, 1)
    original_root = await native.session.get(Knowledge, 1)
    original_member.user_role = "admin"
    original_member.grant_binding_key = "caller-unflushed"
    original_root.user_id = None
    original_root.type = 2
    pending = Member(business_id="1", business_type="space", user_id=99, user_role="member")
    native.session.add(pending)
    native.statements.clear()
    repository = module.UnificationSpaceMembershipRepository()
    headers = await repository.apage_headers(native.session)
    page = await repository.apage_members(native.session, knowledge_ids=(1,))
    assert headers.items[0].member_count == 200 and headers.items[0].creator_user_id == 7
    assert len(page.items) == 200 and page.next_after is None
    assert page.items[0].user_role == "creator" and page.items[0].grant_binding_key is None
    assert original_member.user_role == "admin" and original_member.grant_binding_key == "caller-unflushed"
    assert original_root.user_id is None and original_root.type == 2
    assert original_member in native.session.dirty and original_root in native.session.dirty
    assert pending in native.session.new and pending.id is None
    assert {id(row) for row in native.session.identity_map.values()} == {id(original_member), id(original_root)}
    assert all(query.lstrip().upper().startswith("SELECT") for query, _ in native.statements)


@pytest.mark.parametrize("method", ["apage_headers", "apage_members"])
@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 201},
        {"limit": True},
        {"limit": 1.0},
        {"limit": "1"},
        {"limit": None},
        {"after_id": 0},
        {"after_id": -1},
        {"after_id": True},
        {"after_id": "1"},
        {"after_id": 1.0},
    ],
)
async def test_invalid_limits_and_cursors_fail_before_any_sql(native, method, arguments):
    kwargs = {"knowledge_ids": (1,)} if method == "apage_members" else {}
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await getattr(module.UnificationSpaceMembershipRepository(), method)(native.session, **kwargs, **arguments)
    assert not native.statements


@pytest.mark.parametrize("tenant", [None, 0, -1, True, "101"])
async def test_bad_context_cannot_autobegin_or_read_even_empty_roots(native, tenant):
    token = set_current_tenant_id(tenant)
    try:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await module.UnificationSpaceMembershipRepository().apage_members(native.session, knowledge_ids=())
    finally:
        current_tenant_id.reset(token)
    assert not native.statements


@pytest.mark.parametrize("method", ["apage_headers", "apage_members"])
async def test_native_external_transaction_is_required_before_autobegin(native, method):
    await native.session.commit()
    kwargs = {"knowledge_ids": (1,)} if method == "apage_members" else {}
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await getattr(module.UnificationSpaceMembershipRepository(), method)(native.session, **kwargs)
    assert not native.session.in_transaction() and not native.statements


@pytest.mark.parametrize("method", ["apage_headers", "apage_members"])
@pytest.mark.parametrize("change", ["tenant", "transaction"])
async def test_sql_await_cannot_hide_context_or_nested_transaction_change(native, monkeypatch, method, change):
    execute, tokens, nested = native.session.execute, [], []

    async def changed(*args, **kwargs):
        result = await execute(*args, **kwargs)
        if change == "tenant":
            tokens.append(set_current_tenant_id(202))
        else:
            nested.append(await native.session.begin_nested())
        return result

    monkeypatch.setattr(native.session, "execute", changed)
    kwargs = {"knowledge_ids": (1,)} if method == "apage_members" else {}
    try:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await getattr(module.UnificationSpaceMembershipRepository(), method)(native.session, **kwargs)
        assert len(native.statements) == 1
    finally:
        for token in reversed(tokens):
            current_tenant_id.reset(token)
        for transaction in reversed(nested):
            await transaction.rollback()


async def test_empty_tenant_and_empty_exact_selection_have_no_false_parent_claim(native):
    token = set_current_tenant_id(303)
    try:
        repository = module.UnificationSpaceMembershipRepository()
        assert (await repository.apage_headers(native.session)).items == ()
        assert len(native.statements) == 1
        native.statements.clear()
        assert (await repository.apage_members(native.session, knowledge_ids=())).items == ()
        assert not native.statements
    finally:
        current_tenant_id.reset(token)
