"""T1003: exact original wire restoration includes signed creator time.

覆盖 AC: AC-55, AC-57, AC-80, AC-83, AC-85.
The facts are acquired by the actual Member/Creator readers, not fabricated.
"""

from dataclasses import replace

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application import unification_conversion_codec as decoder
from bisheng.knowledge.application import unification_inventory_codec as codec
from test.knowledge_unification import test_migration_membership_command_schema as schema

native, own_tenant, inventoried, member_plan = schema.native, schema.own_tenant, schema.inventoried, schema.member_plan


def encode(record):
    return codec.encode_inventory_page(
        run_id="member-command",
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        records=(record,),
        kind="plan",
    )


def decode(record):
    return decoder.decode_sql_conversion_page(
        encode(record), run_id="member-command", writer_contract_version="f118-v1", tenant_id=101, page_index=0
    ).commands[0]


@pytest.mark.parametrize("member_plan", ["insert", "keep"], indirect=True)
async def test_actual_fact_command_roundtrip_restores_exact_domain_time_and_canonical_bytes(member_plan):
    command = schema.command(member_plan)
    original = codec.record_from_row(command)
    restored = decode(original)
    assert restored == command and type(restored) is type(command)
    assert restored.creator_planned_at == command.creator_planned_at
    assert codec.record_from_row(restored) == original


@pytest.mark.parametrize(
    "changes",
    [
        {"membership_action": "promote"},
        {"existing_creator_member_id": 10},
        {"creator_planned_at": None},
        {"creator_planned_at": "not-a-date"},
        {"creator_planned_at": "2026-11-09T08:09:10+00:00"},
        {"creator_planned_at": "2026-11-09T08:09:10.000001"},
        {"creator_planned_at": "2026-11-09 08:09:10"},
        {"creator_planned_at": "2026-11-09T08:09:10.000000"},
        {"creator_planned_at": "2026-11-09T08:09:10Z"},
    ],
)
async def test_insert_rejects_ambiguous_branch_or_unsigned_noncanonical_time(member_plan, changes):
    original = codec.record_from_row(schema.command(member_plan))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(codec.record_from_values(original.record_type, **(original.data | changes)))


@pytest.mark.parametrize("member_plan", ["keep"], indirect=True)
@pytest.mark.parametrize(
    "changes",
    [{"existing_creator_member_id": None}, {"creator_planned_at": "2026-11-09T08:09:10"}, {"before_member_count": 0}],
)
async def test_keep_requires_actual_existing_member_and_no_generated_timestamp(member_plan, changes):
    original = codec.record_from_row(schema.command(member_plan))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(codec.record_from_values(original.record_type, **(original.data | changes)))


@pytest.mark.parametrize(
    "changes",
    [
        {"creator_user_id": True},
        {"before_member_count": True},
        {"existing_creator_member_id": True},
        {"creator_template_digest": None},
        {"before_member_digest": "not-hash"},
        {"creator_planned_at": 1},
    ],
)
async def test_native_field_types_remain_strict_before_restoration(member_plan, changes):
    original = codec.record_from_row(schema.command(member_plan))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values(original.record_type, **(original.data | changes))


async def test_omitted_or_all_null_legacy_membership_never_falls_back(member_plan):
    original = codec.record_from_row(schema.command(member_plan))
    for values in (
        {name: value for name, value in original.data.items() if name not in schema.MEMBER_FIELDS},
        original.data | dict.fromkeys(schema.MEMBER_FIELDS),
    ):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            codec.record_from_values(original.record_type, **values)
    altered = replace(schema.command(member_plan), creator_planned_at="2026-11-09T08:09:10")
    assert decode(codec.record_from_row(altered)).creator_planned_at == schema.NOW
