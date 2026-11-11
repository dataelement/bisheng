"""T1005: original Preflight and builder consume real membership inventory.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
No inventory App, SQL writer, Grant, Source or alternate execution entry.
"""

import importlib
from dataclasses import replace
from datetime import datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.models.space_channel_member import SpaceChannelMember as Member
from bisheng.knowledge.domain.repositories.unification_control_repository import UnificationControlRepository
from bisheng.knowledge.domain.repositories.unification_space_membership_repository import (
    UnificationSpaceMembershipRepository,
)
from bisheng.knowledge.domain.services.unification_fingerprints import digest
from bisheng.knowledge.domain.services.unification_space_membership_plan import plan_space_creator_membership
from test.knowledge_unification import test_migration_conversion_plan as builder_fixture
from test.knowledge_unification import test_migration_preflight as original
from test.knowledge_unification import test_migration_space_membership_inventory as member_fixture

resource_native, native = original.resource_native, original.native
NOW = datetime(2026, 11, 7, 2, 3, 4)


@pytest.fixture
async def complete(native):
    async with native.engine.begin() as connection:
        await connection.run_sync(lambda active: Member.__table__.create(active, checkfirst=True))
    return native


async def collect(database, *, memberships=None, controls=None):
    module = importlib.import_module("bisheng.knowledge.application.unification_preflight")
    async with AsyncSession(database.engine) as session, session.begin():
        before = len(database.queries)
        rows = [
            item
            async for item in module.UnificationPreflight(memberships=memberships, controls=controls).aiter_tenant(
                session,
                permission_planner=module.ResourceRetirementPlanner(catalog_plan=original.catalog_plan()),
                planned_at=NOW,
            )
        ]
        assert not session.new and not session.dirty and not session.deleted and not session.identity_map
    return rows, database.queries[before:]


async def acquire_plans(database):
    reader = UnificationSpaceMembershipRepository()
    async with AsyncSession(database.engine) as session, session.begin():
        header = (await reader.apage_headers(session)).items[0]
        members = (await reader.apage_members(session, knowledge_ids=(header.knowledge_id,))).items
        creator = (await UnificationControlRepository().ainspect_users(session, user_ids=(7,)))[0]
    return (plan_space_creator_membership(header, members, creator, planned_at=NOW),)


@pytest.mark.parametrize("keep", [False, True])
async def test_actual_producer_emits_header_then_complete_members_and_binds_flat_command(complete, keep):
    await complete.insert(original.original.Knowledge, [original.original.resource(9000)])
    await original.seed_original_modes(complete, (9000,))
    if keep:
        await complete.insert(
            Member,
            [
                member_fixture.member(
                    10,
                    "9000",
                    membership_source="department_admin",
                    department_admin_promoted_from_role="member",
                    relation="editor",
                    grant_subject_type="department",
                    grant_subject_id=19,
                    grant_relation="viewer",
                    grant_model_id="original-model",
                    grant_binding_key="original-binding",
                    grant_include_children=True,
                    is_pinned=True,
                    update_time=None,
                )
            ],
        )
    else:
        await complete.insert(
            Member, [member_fixture.member(10, "9000", user_id=8, user_role="MEMBER", status="REJECTED")]
        )
    records, _ = await collect(complete)
    expected = (await acquire_plans(complete))[0]
    command = next(record.data for _, record in records if record.record_type == "resource_conversion")
    assert command["creator_user_id"] == 7 and command["membership_action"] == ("keep" if keep else "insert")
    assert command["before_member_count"] == 1 and command["before_member_digest"] == expected.before_member_digest
    assert command["creator_template_digest"] == expected.creator_template_digest
    assert command["existing_creator_member_id"] == (10 if keep else None)
    assert command["creator_planned_at"] == (None if keep else NOW.isoformat())
    control = [record for section, record in records if section == "control"]
    header_at = next(i for i, record in enumerate(control) if record.record_type == "space_membership_header")
    assert control[header_at + 1].record_type == "space_member"
    member = control[header_at + 1].data
    assert member["id"] == 10 and member["knowledge_id"] == 9000
    if keep:
        assert member["grant_binding_key"] == "original-binding" and member["is_pinned"] is True
    creators = [row.data for row in control if row.record_type == "creator"]
    assert creators == [{"user_id": 7, "exists": True, "delete": 1}]


async def test_mixed_original_types_only_inventory_zero_and_space_and_never_repair_existing_space(complete):
    await complete.insert(
        original.original.Knowledge, [original.original.resource(9000 + kind, type=kind) for kind in (0, 1, 2, 3)]
    )
    await complete.insert(
        Member,
        [
            member_fixture.member(10, "9003", user_role="MEMBER", status="PENDING"),
            member_fixture.member(11, "9003", user_id=8),
        ],
    )
    await original.seed_original_modes(complete, (9000,))
    records, _ = await collect(complete)
    headers = [row.data for _, row in records if row.record_type == "space_membership_header"]
    assert [(row["knowledge_id"], row["knowledge_type"], row["member_count"]) for row in headers] == [
        (9000, 0, 0),
        (9003, 3, 2),
    ]
    assert [row.data["knowledge_id"] for _, row in records if row.record_type == "resource_conversion"] == [9000]
    assert [row.data["id"] for _, row in records if row.record_type == "space_member"] == [10, 11]


@pytest.mark.parametrize(
    "members",
    [
        [member_fixture.member(10, "9000", user_role="MEMBER")],
        [member_fixture.member(10, "9000", status="PENDING")],
        [member_fixture.member(10, "9000"), member_fixture.member(11, "9000")],
        [member_fixture.member(10, "9000", user_id=8)],
    ],
)
async def test_original_member_conflicts_block_actual_preflight(complete, members):
    await complete.insert(original.original.Knowledge, [original.original.resource(9000)])
    await complete.insert(Member, members)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(complete)


@pytest.mark.parametrize("bad", ["missing", "count", "owner", "tenant", "type", "id", "last_member"])
async def test_reader_evidence_must_match_actual_resource_and_all_member_pages(complete, bad):
    await complete.insert(original.original.Knowledge, [original.original.resource(9000)])
    await complete.insert(
        Member, [member_fixture.member(i, "9000", user_id=8, user_role="MEMBER") for i in range(1, 402)]
    )

    class Broken(UnificationSpaceMembershipRepository):
        async def apage_headers(self, *args, **kwargs):
            page = await super().apage_headers(*args, **kwargs)
            if not page.items or bad == "last_member":
                return page
            if bad == "missing":
                return replace(page, items=(), next_after=None)
            changes = {
                "count": {"member_count": 400},
                "owner": {"creator_user_id": 8},
                "tenant": {"tenant_id": 202},
                "type": {"knowledge_type": 3},
                "id": {"knowledge_id": 9001},
            }[bad]
            return replace(page, items=(replace(page.items[0], **changes),))

        async def apage_members(self, *args, **kwargs):
            page = await super().apage_members(*args, **kwargs)
            return replace(page, next_after=None) if bad == "last_member" else page

    with pytest.raises(KnowledgeOperationPlanConflictError):
        await collect(complete, memberships=Broken())


async def test_omitted_resource_cannot_hide_an_additional_real_header(complete):
    await complete.insert(original.original.Knowledge, [original.original.resource(9000)])
    module = importlib.import_module("bisheng.knowledge.application.unification_preflight")
    resources = module.UnificationResourceRepository()

    async def omitted(session, **kwargs):
        page = await type(resources).alist_resources(resources, session, **kwargs)
        return replace(page, items=(), next_after=None)

    resources.alist_resources = omitted
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            _ = [
                row
                async for row in module.UnificationPreflight(resources=resources).aiter_tenant(
                    session,
                    permission_planner=module.ResourceRetirementPlanner(catalog_plan=original.catalog_plan()),
                    planned_at=NOW,
                )
            ]


@pytest.mark.parametrize("bad", ["missing", "duplicate", "extra", "tenant", "owner", "null_time", "type3"])
async def test_builder_requires_one_exact_plan_per_normal_root_before_stage_zero_command(complete, bad):
    await complete.insert(
        original.original.Knowledge, [original.original.resource(9000, type=3 if bad == "type3" else 0)]
    )
    facts = await builder_fixture.acquire(complete)
    # Get a legitimate NORMAL plan from the same real Root before testing a
    # producer pairing error; no empty Header is synthesized.
    if bad == "type3":
        async with complete.engine.begin() as connection:
            await connection.execute(original.original.Knowledge.__table__.update().values(type=0))
    plans = await acquire_plans(complete)
    if bad == "missing":
        plans = ()
    elif bad == "duplicate":
        plans *= 2
    elif bad in {"extra", "tenant", "owner", "null_time"}:
        changes = {
            "extra": {"knowledge_id": 9001},
            "tenant": {"tenant_id": 202},
            "owner": {"creator_user_id": 8},
            "null_time": {"planned_at": None},
        }[bad]
        plans = (replace(plans[0], **changes),)
    module = importlib.import_module("bisheng.knowledge.application.unification_conversion_plan")
    builder = module.ConversionPlanBuilder(**builder_fixture.IDENTITY, planned_at=NOW)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        builder.add_resources(facts["resources"], creator_memberships=plans)


async def test_builder_copies_actual_plan_once_and_preserves_old_resource_business_digests(complete):
    await complete.insert(original.original.Knowledge, [original.original.resource(9000)])
    facts, plans = await builder_fixture.acquire(complete), await acquire_plans(complete)
    module = importlib.import_module("bisheng.knowledge.application.unification_conversion_plan")
    builder = module.ConversionPlanBuilder(**builder_fixture.IDENTITY, planned_at=NOW)
    builder.add_resources(facts["resources"], creator_memberships=plans)
    command = next(iter(builder.finish()))
    assert command.before_business_digest == facts["resources"][0].old_business_digest
    assert command.before_member_digest == plans[0].before_member_digest == digest(())
    assert command.creator_planned_at == NOW and command.creator_user_id == facts["resources"][0].user_id
