"""T993: pure creator-member plans from real complete original SQL facts.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
The native defaults oracle writes only its isolated SQLite fixture; planning
never executes that write or grants any migration/permission authority.
"""

import ast
import importlib
from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, update

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import BusinessTypeEnum, MembershipStatusEnum, UserRoleEnum
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.repositories.unification_control_repository import (
    CreatorFact,
    UnificationControlRepository,
)
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    MEMBER_COLUMNS,
    SpaceMembershipHeader,
    SpaceMembershipRow,
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.user.domain.models.user import User
from test.knowledge_unification import test_migration_space_membership_inventory as original

native = original.native
own_tenant = original.own_tenant
NOW = datetime(2026, 11, 9, 8, 9, 10)


def api():
    schema = importlib.import_module("bisheng.knowledge.domain.schemas.unification_space_membership")
    service = importlib.import_module("bisheng.knowledge.domain.services.unification_space_membership_plan")
    return schema, service.plan_space_creator_membership


@pytest.fixture
async def inventoried(native):
    await native.session.run_sync(lambda active: User.__table__.create(active.connection(), checkfirst=True))
    await native.session.execute(insert(User.__table__), {"user_id": 7, "user_name": "original-owner", "password": ""})
    return native


async def facts(native, *, knowledge_id=1):
    reader = UnificationSpaceMembershipRepository()
    header = next(row for row in (await reader.apage_headers(native.session)).items if row.knowledge_id == knowledge_id)
    assert type(header) is SpaceMembershipHeader
    rows, after = [], None
    while True:
        page = await reader.apage_members(native.session, knowledge_ids=(knowledge_id,), after_id=after)
        rows.extend(page.items)
        if page.next_after is None:
            break
        after = page.next_after
    creator = (await UnificationControlRepository().ainspect_users(native.session, user_ids=(7,)))[0]
    return header, tuple(rows), creator


def kept_template(row):
    return {name: getattr(row, name) for name in MEMBER_COLUMNS if name != "id"}


async def test_empty_normal_produces_frozen_insert_plan_and_exact_original_member_default_template(inventoried):
    header, rows, creator = await facts(inventoried)
    schema, plan = api()
    before_sql = len(inventoried.statements)
    result = plan(header, rows, creator, planned_at=NOW)
    template = schema.creator_membership_template(knowledge_id=1, creator_user_id=7, planned_at=NOW)
    assert len(inventoried.statements) == before_sql
    model = original.Member(
        business_id="1",
        business_type=BusinessTypeEnum.SPACE,
        user_id=7,
        user_role=UserRoleEnum.CREATOR,
        status=MembershipStatusEnum.ACTIVE,
        create_time=NOW,
        update_time=NOW,
    )
    expected = {name: getattr(model, name) for name in MEMBER_COLUMNS if name != "id"}
    expected = {name: getattr(value, "value", value) for name, value in expected.items()}
    assert template == expected and set(template) == set(MEMBER_COLUMNS) - {"id"}
    assert type(result) is schema.CreatorMembershipPlan
    assert asdict(result) == {
        "tenant_id": 101,
        "knowledge_id": 1,
        "creator_user_id": 7,
        "membership_action": "insert",
        "before_member_count": 0,
        "before_member_digest": digest(()),
        "existing_creator_member_id": None,
        "creator_template_digest": digest(template),
        "planned_at": NOW,
    }
    with pytest.raises(FrozenInstanceError):
        result.membership_action = "keep"
    assert not hasattr(result, "__dict__")


async def test_template_matches_actual_aadd_space_creator_sql_defaults_with_explicit_signed_times(inventoried):
    schema, _ = api()
    root = await inventoried.session.get(original.Knowledge, 2)
    actual = await KnowledgeModelReferenceRepository().aadd_space_creator(inventoried.session, root, user_id=7)
    assert type(actual.create_time) is datetime and type(actual.update_time) is datetime
    _, rows, _ = await facts(inventoried, knowledge_id=2)
    expected = kept_template(rows[0]) | {"create_time": NOW, "update_time": NOW}
    template = schema.creator_membership_template(knowledge_id=2, creator_user_id=7, planned_at=NOW)
    assert template == expected
    await inventoried.session.execute(insert(original.Member.__table__), template)
    _, inserted, _ = await facts(inventoried, knowledge_id=2)
    assert kept_template(inserted[-1]) == template


async def test_unique_active_owner_keeps_all_sources_and_original_timestamp_fields(inventoried):
    await original.seed(
        inventoried,
        [
            original.member(
                10,
                membership_source="department_admin",
                department_admin_promoted_from_role="member",
                relation="manager",
                grant_subject_type="department",
                grant_subject_id=19,
                grant_relation="editor",
                grant_include_children=True,
                grant_model_id="retired-original",
                grant_binding_key="signed-original",
                is_pinned=True,
                update_time=None,
            ),
            original.member(20, user_id=8, user_role="MEMBER", status="REJECTED"),
        ],
    )
    header, rows, creator = await facts(inventoried)
    _, plan = api()
    before_sql = len(inventoried.statements)
    result = plan(header, rows, creator, planned_at=NOW)
    assert result.membership_action == "keep" and result.existing_creator_member_id == 10
    assert result.planned_at is None and result.before_member_count == 2
    assert result.before_member_digest == digest(tuple(asdict(row) for row in rows))
    assert result.creator_template_digest == digest(kept_template(rows[0]))
    assert len(inventoried.statements) == before_sql
    for name in MEMBER_COLUMNS:
        if name == "id":
            continue
        value = getattr(rows[0], name)
        changed = (
            (NOW if value is None else None)
            if name in {"create_time", "update_time"}
            else (not value if type(value) is bool else value + 1 if type(value) is int else "other-source")
        )
        if name in {"business_id", "business_type", "user_id", "user_role", "status"}:
            continue
        if name in {"relation", "grant_relation"}:
            changed = "viewer"
        newer = plan(header, (replace(rows[0], **{name: changed}), rows[1]), creator, planned_at=NOW)
        assert newer.before_member_digest != result.before_member_digest
        assert newer.creator_template_digest != result.creator_template_digest


@pytest.mark.parametrize("delete", [0, 1])
async def test_actual_soft_deleted_creator_is_the_same_historical_owner(inventoried, delete):
    await inventoried.session.execute(update(User.__table__).values(delete=delete))
    header, rows, creator = await facts(inventoried)
    assert creator == CreatorFact(7, True, delete)
    assert api()[1](header, rows, creator, planned_at=NOW).creator_user_id == 7


@pytest.mark.parametrize(
    "values",
    [
        [original.member(10, user_role="MEMBER")],
        [original.member(10, user_role="ADMIN")],
        [original.member(10, status="PENDING")],
        [original.member(10, status="REJECTED")],
        [original.member(10), original.member(11)],
        [original.member(10, user_id=8)],
        [original.member(10), original.member(11, user_id=8)],
    ],
)
async def test_real_member_conflicts_are_blocked_without_promotion_activation_or_first_row_selection(
    inventoried, values
):
    await original.seed(inventoried, values)
    header, rows, creator = await facts(inventoried)
    before_sql = len(inventoried.statements)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        api()[1](header, rows, creator, planned_at=NOW)
    assert len(inventoried.statements) == before_sql


async def test_other_users_noncreator_sources_stay_frozen_while_missing_owner_gets_insert(inventoried):
    await original.seed(
        inventoried,
        [
            original.member(10, user_id=8, user_role="ADMIN", status="PENDING"),
            original.member(20, user_id=8, user_role="MEMBER", status="REJECTED"),
        ],
    )
    header, rows, creator = await facts(inventoried)
    result = api()[1](header, rows, creator, planned_at=NOW)
    assert result.membership_action == "insert" and result.before_member_count == 2
    assert result.before_member_digest == digest(tuple(asdict(row) for row in rows))
    assert rows[0].status == "PENDING" and rows[1].status == "REJECTED"


async def test_existing_space_returns_no_plan_even_with_historical_conflicting_members_or_missing_creator(inventoried):
    await original.seed(
        inventoried,
        [original.member(10, "2", user_role="MEMBER", status="PENDING"), original.member(20, "2", user_id=8)],
    )
    header, rows, _ = await facts(inventoried, knowledge_id=2)
    assert api()[1](header, rows, None, planned_at=NOW) is None
    with pytest.raises(KnowledgeOperationPlanConflictError):
        api()[1](header, rows[:-1], None, planned_at=NOW)


@pytest.mark.parametrize(
    "creator",
    [
        None,
        CreatorFact(7, False, None),
        CreatorFact(8, True, 0),
        CreatorFact(True, True, 0),
        CreatorFact(7, 1, 0),
        CreatorFact(7, True, True),
        {},
    ],
)
async def test_missing_or_untyped_creator_fact_never_guesses_new_owner(inventoried, creator):
    header, rows, _ = await facts(inventoried)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        api()[1](header, rows, creator, planned_at=NOW)


@pytest.mark.parametrize(
    "changes",
    [
        {"knowledge_type": 1},
        {"knowledge_type": 2},
        {"knowledge_type": True},
        {"tenant_id": True},
        {"knowledge_id": 0},
        {"creator_user_id": None},
        {"creator_user_id": 0},
        {"creator_user_id": True},
        {"member_count": True},
        {"member_count": -1},
        {"member_count": 1},
    ],
)
async def test_bad_headers_or_unproven_count_fail_closed(inventoried, changes):
    header, rows, creator = await facts(inventoried)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        api()[1](replace(header, **changes), rows, creator, planned_at=NOW)


@pytest.mark.parametrize(
    "failure",
    [
        "tenant",
        "root",
        "business_id",
        "channel",
        "duplicate",
        "decreasing",
        "missing_tail",
        "list",
        "raw_dict",
        "bool_pk",
        "bool_user",
        "bool_subject",
        "int_flag",
        "str_time",
    ],
)
async def test_incomplete_or_cross_scope_members_and_untyped_raw_fields_cannot_be_signed(inventoried, failure):
    await original.seed(
        inventoried,
        [original.member(10, user_id=8, user_role="MEMBER"), original.member(20, user_id=9, user_role="ADMIN")],
    )
    header, rows, creator = await facts(inventoried)
    changes = {
        "tenant": {"tenant_id": 202},
        "root": {"knowledge_id": 2},
        "business_id": {"business_id": "01"},
        "channel": {"business_type": "channel"},
        "bool_pk": {"id": True},
        "bool_user": {"user_id": True},
        "bool_subject": {"grant_subject_id": True},
        "int_flag": {"is_pinned": 1},
        "str_time": {"update_time": "now"},
    }
    if failure in changes:
        rows = (replace(rows[0], **changes[failure]), rows[1])
    elif failure == "duplicate":
        rows = (rows[0], rows[0])
    elif failure == "decreasing":
        rows = tuple(reversed(rows))
    elif failure == "missing_tail":
        rows = rows[:-1]
    elif failure == "list":
        rows = list(rows)
    elif failure == "raw_dict":
        rows = (asdict(rows[0]), rows[1])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        api()[1](header, rows, creator, planned_at=NOW)


@pytest.mark.parametrize("when", [None, "2026-11-09", NOW.replace(microsecond=1), NOW.replace(tzinfo=UTC)])
async def test_planned_time_is_explicit_native_naive_seconds_not_runtime_now(inventoried, when):
    header, rows, creator = await facts(inventoried)
    schema, plan = api()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        plan(header, rows, creator, planned_at=when)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        schema.creator_membership_template(knowledge_id=1, creator_user_id=7, planned_at=when)


@pytest.mark.parametrize(
    "changes",
    [
        {"knowledge_id": True},
        {"knowledge_id": 0},
        {"knowledge_id": "1"},
        {"creator_user_id": True},
        {"creator_user_id": 0},
        {"creator_user_id": "7"},
    ],
)
def test_persistable_template_rejects_untyped_or_nonpositive_ids(changes):
    schema, _ = api()
    with pytest.raises(KnowledgeOperationPlanConflictError):
        schema.creator_membership_template(**({"knowledge_id": 1, "creator_user_id": 7, "planned_at": NOW} | changes))


async def test_insert_template_signs_the_supplied_time_deterministically(inventoried):
    header, rows, creator = await facts(inventoried)
    _, plan = api()
    first = plan(header, rows, creator, planned_at=NOW)
    assert plan(header, rows, creator, planned_at=NOW) == first
    second = plan(header, rows, creator, planned_at=NOW.replace(second=11))
    assert second.before_member_digest == first.before_member_digest
    assert second.creator_template_digest != first.creator_template_digest
    assert second.planned_at == NOW.replace(second=11)


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_other_member_scale_is_one_linear_collection_without_any_sql(inventoried, monkeypatch, count):
    await original.seed(
        inventoried,
        [original.member(ident, user_id=8 + ident % 3, user_role="MEMBER") for ident in range(1, count + 1)],
    )
    header, rows, creator = await facts(inventoried)
    expected = digest(tuple(asdict(row) for row in rows))
    field_names = {part.name for part in fields(SpaceMembershipRow)}
    getattribute, reads = SpaceMembershipRow.__getattribute__, {}

    def tracked(row, name):
        if name in field_names:
            ident = getattribute(row, "id")
            reads[ident] = reads.get(ident, 0) + 1
        return getattribute(row, name)

    monkeypatch.setattr(SpaceMembershipRow, "__getattribute__", tracked)
    before_sql = len(inventoried.statements)
    result = api()[1](header, rows, creator, planned_at=NOW)
    assert result.membership_action == "insert" and result.before_member_digest == expected
    assert result.before_member_count == count and len(reads) == count
    assert max(reads.values()) <= len(field_names) + 6
    assert len(inventoried.statements) == before_sql
    print({"members": count, "field_reads": sum(reads.values()), "max_reads_per_row": max(reads.values()), "sql": 0})


def test_new_plan_and_template_have_no_sql_io_clock_uuid_or_grant_calls():
    schema, plan = api()
    service = importlib.import_module(plan.__module__)
    for module in (schema, service):
        tree = ast.parse(Path(module.__file__).read_text())
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not calls & {"execute", "exec", "flush", "commit", "add", "add_all", "now", "utcnow", "uuid4", "open"}
        assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))
    imports = [
        node.module
        for node in ast.walk(ast.parse(Path(schema.__file__).read_text()))
        if isinstance(node, ast.ImportFrom)
    ]
    assert not any(name and ("repositories" in name or ".services." in name) for name in imports)
