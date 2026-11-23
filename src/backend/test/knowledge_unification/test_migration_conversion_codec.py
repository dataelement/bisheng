"""Exact typed decoding of the existing M2 conversion wire, no new protocol."""

import importlib
from dataclasses import FrozenInstanceError

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_inventory_codec import (
    decode_inventory_page,
    encode_inventory_page,
    record_from_row,
    record_from_values,
)
from test.knowledge_unification import test_migration_conversion_repository as sql_native
from test.knowledge_unification import test_migration_frozen_plan_reader as actual_m2

resource_native = sql_native.resource_native
database = sql_native.database


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_conversion_codec")


def encode(records, **kwargs):
    return encode_inventory_page(
        run_id=sql_native.IDENTITY["run_id"],
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        records=tuple(records),
        kind="plan",
        **kwargs,
    )


def decode(module, content, **kwargs):
    return module.decode_sql_conversion_page(
        content,
        **(
            {
                "run_id": sql_native.IDENTITY["run_id"],
                "writer_contract_version": sql_native.IDENTITY["writer_contract_version"],
                "tenant_id": 101,
                "page_index": 0,
            }
            | kwargs
        ),
    )


async def test_real_native_five_kind_commands_roundtrip_every_field_and_original_domain_class(module, database):
    records = tuple(record_from_row(cmd) for cmd in database.commands)
    page = decode(module, encode(records))
    assert page.commands == database.commands and page.deferred == ()
    assert {cmd.operation for cmd in page.commands} == {
        "resource_conversion",
        "initialize_v1",
        "tag_conversion",
        "tag_link_conversion",
        "default_conversion",
    }
    assert all(type(old) is type(new) for old, new in zip(database.commands, page.commands, strict=True))
    assert tuple(record_from_row(cmd) for cmd in page.commands) == records
    assert not hasattr(page, "__dict__")
    with pytest.raises(FrozenInstanceError):
        page.commands = ()


@pytest.mark.parametrize("change", ["timezone", "microsecond", "space", "zero_fraction", "zulu"])
async def test_frozen_v1_time_cannot_be_normalized_to_a_different_wire_value(module, database, change):
    command = next(cmd for cmd in database.commands if cmd.operation == "initialize_v1")
    record = record_from_row(command)
    original = record.data["planned_at"]
    value = {
        "timezone": original + "+00:00",
        "microsecond": original + ".000001",
        "space": original.replace("T", " "),
        "zero_fraction": original + ".000000",
        "zulu": original + "Z",
    }[change]
    record = record_from_values(record.record_type, **(record.data | {"planned_at": value}))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(module, encode((record,)))


@pytest.mark.parametrize(
    "field,value",
    [("writer_contract_version", "another-writer"), ("tenant_id", 202), ("page_index", 1), ("run_id", "another-run")],
)
async def test_expected_identity_is_not_taken_from_untrusted_page_body(module, database, field, value):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(module, encode(tuple(record_from_row(cmd) for cmd in database.commands)), **{field: value})


async def test_central_codec_valid_nonconversion_record_is_rejected_in_conversion_section(module, database):
    rows = await sql_native.producer.acquire(database)
    file = record_from_row(rows["files"][0])
    content = encode((file,))  # The existing generic codec does not own section allowlists.
    assert decode_inventory_page(
        content,
        run_id=sql_native.IDENTITY["run_id"],
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        kind="plan",
    ).records == (file,)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(module, content)


async def test_wire_default_provenance_is_restored_to_the_original_frozen_domain_tuple(module, database):
    command = next(cmd for cmd in database.commands if cmd.operation == "default_conversion")
    decoded = decode(module, encode((record_from_row(command),))).commands[0]
    assert type(decoded.provenance) is tuple and decoded.provenance == command.provenance
    assert all(type(a) is type(b) for a, b in zip(decoded.provenance, command.provenance, strict=True))
    with pytest.raises(FrozenInstanceError):
        decoded.provenance[0].target_id = "999"


# The actual M2 producer remains the authority for deferred page records.
complete = actual_m2.complete
transport = actual_m2.transport
native = actual_m2.native


@pytest.fixture
async def real_frozen(complete, transport):
    from sqlmodel.ext.asyncio.session import AsyncSession

    await complete.insert(actual_m2.original.resources.Knowledge, [actual_m2.original.resources.resource(40, type=3)])
    async with AsyncSession(complete.engine) as session, session.begin():
        await actual_m2.original.permission.seed_rows(session)
    producer = importlib.import_module("bisheng.knowledge.application.unification_inventory")
    app = actual_m2.original.application(producer, transport)
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
    return producer, result


async def test_real_m2_deferred_records_remain_explicit_and_byte_exact(module, real_frozen, transport):
    producer, result = real_frozen
    app = producer.UnificationInventoryApplication(artifact_store=transport.store)
    deferred = []
    async for page in app.aiter_frozen_pages(result, **actual_m2.arguments(transport)):
        if page.kind != "plan" or page.section != "conversion":
            continue
        decoded = module.decode_sql_conversion_page(
            page.content,
            run_id=result.run_id,
            writer_contract_version=result.writer_contract_version,
            tenant_id=page.tenant_id,
            page_index=page.page_index,
        )
        records = decode_inventory_page(
            page.content,
            run_id=result.run_id,
            section="conversion",
            scope="tenant",
            tenant_id=page.tenant_id,
            page_index=page.page_index,
            kind="plan",
        ).records
        assert decoded.deferred == tuple(
            row for row in records if row.record_type in {"permission_plan", "source_decision"}
        )
        assert len(decoded.commands) + len(decoded.deferred) == len(records)
        deferred.extend(decoded.deferred)
    assert {row.record_type for row in deferred} == {"permission_plan", "source_decision"}
