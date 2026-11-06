"""Frozen SQL-stage instructions over native facts, without business writes."""

import importlib
import json
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.reference_source_owner import KnowledgeReferenceSourceOwner
from bisheng.knowledge.application.unification_inventory_codec import digest, record_from_row
from bisheng.knowledge.domain.repositories.model_reference_repository import KnowledgeModelReferenceRepository
from bisheng.knowledge.domain.repositories.unification_inventory_repository import DefaultRow
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from test.knowledge_unification import test_migration_resource_repository as original

native = original.native
NOW = datetime(2026, 11, 7, 2, 3, 4)
IDENTITY = {"run_id": "sql-plan", "writer_contract_version": "f118-v1"}
KINDS = ("resources", "files", "documents", "versions", "tags", "tag_links")


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_conversion_plan")


async def acquire(database):
    async with AsyncSession(database.engine) as session, session.begin():
        return {kind: tuple(await original.collect(UnificationResourceRepository(), kind, session)) for kind in KINDS}


def build(module, rows, defaults=()):
    builder = module.ConversionPlanBuilder(**IDENTITY, planned_at=NOW)
    for kind in KINDS:
        values = rows.get(kind, ())
        for offset in range(0, max(1, len(values)), 200):
            getattr(builder, "add_" + kind)(values[offset : offset + 200])
    builder.add_defaults(defaults)
    return builder, tuple(builder.finish())


async def test_resource_command_preserves_full_original_and_neutral_fields_and_matches_actual_owner(module, native):
    await native.insert(
        original.Knowledge,
        [
            original.resource(40, is_released=True),
            original.resource(41, type=3, is_released=True),
            original.resource(42, type=1),
            original.resource(43, type=2),
        ],
    )
    rows = await acquire(native)
    before = rows["resources"][0]
    queries = len(native.queries)
    builder, commands = build(module, rows)
    assert len(native.queries) == queries
    resource = next(item for item in commands if isinstance(item, module.ResourceConversionCommand))
    assert resource.knowledge_id == 40 and resource.target_type == 3 and resource.target_is_released is False
    assert resource.target_migration_origin == IDENTITY["run_id"]
    assert resource.before_business_digest == before.old_business_digest
    expected = {name: getattr(before, name) for name in original.OLD_RESOURCE} | {"type": 3, "is_released": False}
    assert resource.after_business_digest == digest(expected)
    assert resource.before_neutral_digest == digest(asdict(before.neutral))
    assert resource.after_neutral_digest == digest(asdict(before.neutral) | {"migration_origin": IDENTITY["run_id"]})
    async with AsyncSession(native.engine) as session, session.begin():
        owner_row = await KnowledgeModelReferenceRepository().aload_source(session, 40)
    assert (
        resource.after_owner_configuration_digest
        == KnowledgeReferenceSourceOwner._snapshot(owner_row | {"type": 3}).configuration_digest
    )
    assert "private-" not in repr(commands) and not hasattr(resource, "__dict__")
    with pytest.raises(FrozenInstanceError):
        resource.target_type = 0
    with pytest.raises(KnowledgeOperationPlanConflictError):
        tuple(builder.finish())


async def test_creation_key_collision_is_final_projection_across_separate_pages(module, native):
    await native.insert(
        original.Knowledge,
        [original.resource(40, creation_request_id="same"), original.resource(41, type=3, creation_request_id="same")],
    )
    rows = await acquire(native)
    builder = module.ConversionPlanBuilder(**IDENTITY, planned_at=NOW)
    builder.add_resources(rows["resources"][:1])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        builder.add_resources(rows["resources"][1:])
        tuple(builder.finish())


async def test_v1_only_zero_relation_files_in_zero_or_space_all_states_not_directories(module, native):
    await native.insert(
        original.Knowledge,
        [
            original.resource(9000),
            original.resource(9001, type=3),
            original.resource(9002, type=1),
            original.resource(9003, type=2),
        ],
    )
    await native.insert(
        original.KnowledgeFile,
        [
            original.file(1, file_type=0),
            original.file(2, status=3),
            original.file(3, status=1),
            original.file(4, knowledge_id=9001),
            original.file(5, knowledge_id=9002),
            original.file(6, knowledge_id=9003),
        ],
    )
    rows = await acquire(native)
    _, commands = build(module, rows)
    plans = [item for item in commands if isinstance(item, module.InitializeV1Command)]
    assert {item.file_id for item in plans} == {2, 3, 4}
    for item in plans:
        assert item.planned_at == NOW and len(item.natural_key) == 64
        assert not hasattr(item, "document_id") and not hasattr(item, "version_id")
        assert item.before_relation_digest == digest(())
    assert tuple(build(module, rows)[1]) == commands


async def test_existing_all_version_chain_never_creates_extra_v1_and_bad_primary_is_blocked(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    await native.insert(original.KnowledgeFile, [original.file(1), original.file(2)])
    await native.insert(original.KnowledgeDocument, [original.data("documents", 1) | {"primary_version_id": 2}])
    await native.insert(
        original.KnowledgeDocumentVersion,
        [
            original.data("versions", 1) | {"is_primary": False},
            original.data("versions", 2) | {"document_id": 1, "version_no": 2},
        ],
    )
    rows = await acquire(native)
    assert not any(isinstance(item, module.InitializeV1Command) for item in build(module, rows)[1])
    with pytest.raises(KnowledgeOperationPlanConflictError):
        build(module, rows | {"documents": (replace(rows["documents"][0], primary_version_id=999),)})


async def test_tag_owner_and_exact_target_link_collision_keep_existing_eight(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    await native.insert(original.KnowledgeFile, [original.file(1)])
    await native.insert(original.Tag, [original.data("tags", 1)])
    await native.insert(
        original.TagLink,
        [
            original.data("tag_links", 1),
            original.data("tag_links", 2) | {"tag_id": 1, "resource_id": "1", "resource_type": 8},
        ],
    )
    rows = await acquire(native)
    commands = build(module, rows)[1]
    tag = next(item for item in commands if isinstance(item, module.TagConversionCommand))
    link = next(item for item in commands if isinstance(item, module.TagLinkConversionCommand))
    assert (tag.tag_id, tag.knowledge_id, tag.from_business_type, tag.to_business_type) == (
        1,
        9000,
        "knowledge",
        "knowledge_space",
    )
    assert (
        link.action == "drop_duplicate"
        and link.link_id == 1
        and link.survivor_link_id == 2
        and link.after_digest is None
    )
    assert all("private-" not in repr(item) for item in commands)


@pytest.mark.parametrize("foreign", ["other_space", "application", "missing_tag", "same_name"])
async def test_tag_shared_or_unproved_owner_or_same_name_collision_blocks(module, native, foreign):
    await native.insert(original.Knowledge, [original.resource(9000), original.resource(9001, type=3)])
    await native.insert(original.KnowledgeFile, [original.file(1), original.file(2, knowledge_id=9001)])
    await native.insert(original.Tag, [original.data("tags", 1)])
    links = [original.data("tag_links", 1)]
    if foreign == "other_space":
        links.append(original.data("tag_links", 2) | {"tag_id": 1, "resource_type": 8})
    elif foreign == "application":
        links.append(original.data("tag_links", 2) | {"tag_id": 1, "resource_type": 10, "resource_id": "app"})
    elif foreign == "missing_tag":
        links[0]["tag_id"] = 99
    else:
        await native.insert(
            original.Tag, [original.data("tags", 2) | {"name": "private-tag", "business_type": "knowledge_space"}]
        )
    await native.insert(original.TagLink, links)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        build(module, await acquire(native))


@pytest.mark.parametrize("changes", [{"model": "tampered"}, {"old_business_digest": "a" * 64}])
async def test_raw_before_digest_cannot_be_tampered(module, native, changes):
    await native.insert(original.Knowledge, [original.resource(40)])
    rows = await acquire(native)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        build(module, rows | {"resources": (replace(rows["resources"][0], **changes),)})


def default(value, key="linsight_llm", ident=1):
    return DefaultRow(ident, 101, key, json.dumps(value, ensure_ascii=False), NOW)


def test_default_exact_original_transforms_and_safe_new_slot_provenance(module):
    payload = {
        "models": [{"id": "11"}, {"id": "12"}],
        "task_model": {"id": "12"},
        "linsight_executor_mode": "legacy",
        "private-prompt": "never export",
    }
    row = default(payload)
    command = module.plan_default_conversion(row, **IDENTITY)
    assert command.selected_linsight_id == "12" and command.selected_chat_id == "12"
    assert command.drop_task_model and command.drop_executor_mode
    expected = {
        "models": payload["models"],
        "linsight_default_model_id": "12",
        "chat_default_model_id": "12",
        "private-prompt": "never export",
    }
    assert command.after_configuration_digest == digest({"key": "linsight_llm", "value": expected})
    assert {(item.source_slot, item.target_slot, item.target_id) for item in command.provenance} == {
        ("models.12.id", "linsight_default_model_id", "12"),
        ("models.12.id", "chat_default_model_id", "12"),
    }
    assert "never export" not in repr(command) and "private-prompt" not in json.dumps(record_from_row(command).data)
    assert payload["task_model"] == {"id": "12"}
    assert module.plan_default_conversion(default(expected), **IDENTITY) is None
    assert module.plan_default_conversion(default({"model_id": 11}, key="workflow_llm"), **IDENTITY) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"models": [{"id": True}]},
        {"models": [{"id": "model-name"}]},
        {"models": [{"id": "11"}], "task_model": {"id": False}},
        {"models": [{"id": "11"}], "chat_default_model_id": 0},
    ],
)
def test_invalid_original_default_ids_fail_instead_of_pure_helper_coercion(module, payload):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.plan_default_conversion(default(payload), **IDENTITY)


async def test_401_many_version_facts_are_compiled_once_without_sql_or_payload_retention(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    await native.insert(original.KnowledgeFile, [original.file(i) for i in range(1, 402)])
    rows = await acquire(native)
    count = len(native.queries)
    builder, commands = build(module, rows)
    assert (
        len(native.queries) == count and sum(isinstance(item, module.InitializeV1Command) for item in commands) == 401
    )
    assert "private-abstract" not in repr(vars(builder)) and "private-value" not in repr(vars(builder))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        builder.add_files(())


def test_builder_rejects_out_of_order_duplicate_oversized_or_unknown_batches(module):
    builder = module.ConversionPlanBuilder(**IDENTITY, planned_at=NOW)
    builder.add_files(())
    with pytest.raises(KnowledgeOperationPlanConflictError):
        builder.add_resources(())
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.ConversionPlanBuilder(**IDENTITY, planned_at="not-time")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.ConversionPlanBuilder(**(IDENTITY | {"run_id": "../bad"}), planned_at=NOW)
