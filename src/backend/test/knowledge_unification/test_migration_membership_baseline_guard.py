"""T1007 complete original Member baseline gates formal conversion.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
"""

import importlib

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_conversion_plan import ConversionPlanBuilder
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_row, record_from_values
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.services.unification_space_membership_plan import plan_space_creator_membership
from test.knowledge_unification import test_migration_space_membership_plan as original

native = original.native
own_tenant = original.own_tenant
inventoried = original.inventoried
NOW = original.NOW


def api():
    return importlib.import_module(
        "bisheng.knowledge.application.unification_space_membership_inventory"
    ).MembershipInventoryVerifier()


async def facts(db, *, keep=False, extra=0):
    if keep:
        await original.original.seed(db, [original.original.member(10)])
    if extra:
        await original.original.seed(
            db, [original.original.member(100 + i, user_id=100 + i, user_role="MEMBER") for i in range(extra)]
        )
    resources = (await UnificationResourceRepository().alist_resources(db.session)).items
    headers = (await UnificationSpaceMembershipRepository().apage_headers(db.session)).items
    baseline = [("resources", record_from_row(row)) for row in resources]
    creator = (await original.UnificationControlRepository().ainspect_users(db.session, user_ids=(7,)))[0]
    baseline.append(("control", record_from_row(creator)))
    plans = []
    for header in headers:
        _, members, _ = await original.facts(db, knowledge_id=header.knowledge_id)
        baseline.append(("control", record_from_row(header)))
        baseline.extend(("control", record_from_row(row)) for row in members)
        plan = plan_space_creator_membership(header, members, creator, planned_at=NOW)
        if plan is not None:
            plans.append(plan)
    builder = ConversionPlanBuilder(run_id="member-guard", writer_contract_version="f118-v1", planned_at=NOW)
    builder.add_resources(resources, creator_memberships=tuple(plans))
    return baseline, [("conversion", record_from_row(cmd)) for cmd in builder.finish()]


def consume(checker, baseline, commands):
    for section, row in baseline:
        checker.observe(kind="baseline", section=section, tenant_id=101, record=row)
    for section, row in commands:
        checker.observe(kind="plan", section=section, tenant_id=101, record=row)
    checker.finish()


def changed(row, **patch):
    data = row.data | patch
    if "row_digest" in data:
        data["row_digest"] = digest({k: v for k, v in data.items() if k != "row_digest"})
    return record_from_values(row.record_type, **data)


@pytest.mark.parametrize("keep", [False, True])
async def test_native_insert_and_keep_close_without_sql(inventoried, keep):
    checker = api()
    baseline, commands = await facts(inventoried, keep=keep, extra=3)
    count = len(inventoried.statements)
    consume(checker, baseline, commands)
    assert len(inventoried.statements) == count
    assert not inventoried.session.new and not inventoried.session.dirty


@pytest.mark.parametrize("missing", ["resource", "space_membership_header", "space_member", "creator", "command"])
async def test_missing_fact_or_command_blocks_complete_baseline(inventoried, missing):
    checker = api()
    baseline, commands = await facts(inventoried, extra=1)
    if missing == "command":
        commands = []
    else:
        baseline = [(s, r) for s, r in baseline if r.record_type != missing]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)


@pytest.mark.parametrize("tag", ["resource", "space_membership_header", "space_member", "command"])
async def test_duplicate_fact_or_command_rejected(inventoried, tag):
    checker = api()
    baseline, commands = await facts(inventoried, extra=1)
    values = commands if tag == "command" else baseline
    i = next(i for i, (_, r) in enumerate(values) if tag == "command" or r.record_type == tag)
    values.insert(i, values[i])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)


@pytest.mark.parametrize(
    "tag,patch",
    [
        ("space_membership_header", {"creator_user_id": 99}),
        ("space_membership_header", {"knowledge_type": 3}),
        ("space_membership_header", {"member_count": 0}),
        ("space_member", {"business_id": "01"}),
        ("space_member", {"business_type": "channel"}),
        ("space_member", {"knowledge_id": 2}),
        ("space_member", {"tenant_id": 202}),
        ("creator", {"exists": False}),
    ],
)
async def test_tampered_original_fact_rejected(inventoried, tag, patch):
    checker = api()
    baseline, commands = await facts(inventoried, extra=1)
    i = next(i for i, (_, r) in enumerate(baseline) if r.record_type == tag)
    section, row = baseline[i]
    baseline[i] = (section, changed(row, **patch))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)


@pytest.mark.parametrize(
    "patch",
    [
        {"creator_user_id": 9},
        {"before_member_count": 99},
        {"before_member_digest": "f" * 64},
        {"creator_template_digest": "f" * 64},
        {"creator_planned_at": "2026-11-09T00:00:00"},
        {"knowledge_id": 2},
        {"tenant_id": 202},
    ],
)
async def test_late_command_binds_original_set_owner_and_template(inventoried, patch):
    checker = api()
    baseline, commands = await facts(inventoried, extra=2)
    section, row = commands[0]
    commands[0] = (section, changed(row, **patch))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)


async def test_keep_retains_original_source_fields_pk_and_nullable_time(inventoried):
    checker = api()
    await original.original.seed(
        inventoried,
        [original.original.member(10, membership_source="department_admin", grant_binding_key="old", update_time=None)],
    )
    baseline, commands = await facts(inventoried)
    consume(checker, baseline, commands)
    section, row = commands[0]
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(api(), baseline, [(section, changed(row, existing_creator_member_id=11))])


@pytest.mark.parametrize("case", ["owner_role", "owner_state", "other_creator", "duplicate_owner"])
async def test_original_conflicts_match_pure_planner_rules(inventoried, case):
    checker = api()
    baseline, commands = await facts(inventoried, keep=True, extra=1)
    i = next(i for i, (_, r) in enumerate(baseline) if r.record_type == "space_member")
    section, row = baseline[i]
    patches = {"owner_role": {"user_role": "member"}, "owner_state": {"status": "PENDING"}}
    if case in patches:
        baseline[i] = (section, changed(row, **patches[case]))
    else:
        baseline.insert(i, (section, changed(row, id=9, user_id=8 if case == "other_creator" else 7)))
        h = next(i for i, (_, r) in enumerate(baseline) if r.record_type == "space_membership_header")
        hs, hr = baseline[h]
        baseline[h] = (hs, changed(hr, member_count=hr.data["member_count"] + 1))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)


async def test_existing_space_conflicting_members_are_kept_and_control_can_flush_first(inventoried):
    checker = api()
    await original.original.seed(
        inventoried, [original.original.member(10, space_id="2", user_id=8, status="REJECTED")]
    )
    baseline, commands = await facts(inventoried)
    consume(
        checker, [r for r in baseline if r[0] == "control"] + [r for r in baseline if r[0] == "resources"], commands
    )


async def test_original_row_digest_is_checked_separately(inventoried):
    checker = api()
    baseline, commands = await facts(inventoried, extra=1)
    i = next(i for i, (_, r) in enumerate(baseline) if r.record_type == "space_member")
    section, row = baseline[i]
    baseline[i] = (section, record_from_values(row.record_type, **(row.data | {"row_digest": "f" * 64})))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        consume(checker, baseline, commands)
