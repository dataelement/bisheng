"""T1001: real member facts become required flat Resource command fields.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
These native before facts and value commands confer no SQL write authority.
"""

from dataclasses import MISSING, FrozenInstanceError, asdict, fields

import pytest

from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.domain.schemas import unification_conversion as domain
from bisheng.knowledge.domain.services.unification_space_membership_plan import plan_space_creator_membership
from test.knowledge_unification import test_migration_space_membership_plan as native_plan

native, own_tenant, inventoried = native_plan.native, native_plan.own_tenant, native_plan.inventoried
NOW = native_plan.NOW
MEMBER_FIELDS = (
    "creator_user_id",
    "membership_action",
    "before_member_count",
    "before_member_digest",
    "existing_creator_member_id",
    "creator_template_digest",
    "creator_planned_at",
)


def flat(plan):
    return {name: getattr(plan, "planned_at" if name == "creator_planned_at" else name) for name in MEMBER_FIELDS}


def command(plan, **changes):
    return domain.ResourceConversionCommand(
        **(
            {
                "schema_version": 1,
                "run_id": "member-command",
                "writer_contract_version": "f118-v1",
                "tenant_id": plan.tenant_id,
                "command_key": "a" * 64,
                "operation": "resource_conversion",
                "knowledge_id": plan.knowledge_id,
                "before_business_digest": "b" * 64,
                "after_business_digest": "c" * 64,
                "before_neutral_digest": "d" * 64,
                "after_neutral_digest": "e" * 64,
                "after_inventory_business_revision_digest": "f" * 64,
                "after_owner_configuration_digest": "1" * 64,
                "target_type": 3,
                "target_is_released": False,
                "target_migration_origin": "member-command",
                **flat(plan),
            }
            | changes
        )
    )


@pytest.fixture
async def member_plan(inventoried, request):
    if getattr(request, "param", "insert") == "keep":
        await native_plan.original.seed(inventoried, [native_plan.original.member(10, update_time=None)])
    header, members, creator = await native_plan.facts(inventoried)
    return plan_space_creator_membership(header, members, creator, planned_at=NOW)


@pytest.mark.parametrize("member_plan", ["insert", "keep"], indirect=True)
async def test_native_member_plan_is_flat_required_and_codec_closed(member_plan, inventoried):
    before = len(inventoried.statements)
    value = command(member_plan)
    assert len(inventoried.statements) == before
    assert tuple(part.name for part in fields(value))[-7:] == MEMBER_FIELDS
    assert {name: getattr(value, name) for name in MEMBER_FIELDS} == flat(member_plan)
    assert all(part.default is MISSING and part.default_factory is MISSING for part in fields(value))
    record = codec.record_from_row(value)
    assert set(record.data) == {part.name for part in fields(value)}
    assert record.data["creator_planned_at"] == (NOW.isoformat() if member_plan.membership_action == "insert" else None)
    assert "membership" not in record.data and "creator_membership" not in record.data
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.creator_user_id = 99


@pytest.mark.parametrize("missing", MEMBER_FIELDS)
async def test_legacy_omitted_member_fields_cannot_construct_a_new_resource_command(member_plan, missing):
    values = asdict(command(member_plan))
    values.pop(missing)
    with pytest.raises(TypeError):
        domain.ResourceConversionCommand(**values)


def test_explicit_wire_schema_has_required_flat_keys_and_only_two_semantic_nullable_fields():
    declared = codec._SCHEMAS["resource_conversion"]
    expected = {
        "creator_user_id": "positive",
        "membership_action": "str",
        "before_member_count": "nonnegative",
        "before_member_digest": "hash",
        "existing_creator_member_id": "positive?",
        "creator_template_digest": "hash",
        "creator_planned_at": "str?",
    }
    assert {name: declared.get(name) for name in MEMBER_FIELDS} == expected
