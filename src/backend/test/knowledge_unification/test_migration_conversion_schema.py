"""T841: one Domain DTO owner, preserving the actual producer and wire."""

import ast
import hashlib
import importlib
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from datetime import datetime
from pathlib import Path

import pytest

from bisheng.knowledge.application import unification_inventory_codec as codec
from bisheng.knowledge.domain.repositories.unification_inventory_repository import DefaultRow
from bisheng.knowledge.domain.schemas.unification_space_membership import creator_membership_template
from test.knowledge_unification import test_migration_conversion_plan as producer

native = producer.native
APP = "bisheng.knowledge.application.unification_conversion_plan"
DOMAIN = "bisheng.knowledge.domain.schemas.unification_conversion"
NOW = datetime(2026, 11, 7, 2, 3, 4)
BASE_FIELDS = "schema_version run_id writer_contract_version tenant_id command_key operation".split()
EXTRA_FIELDS = {
    "ConversionCommand": [],
    "ResourceConversionCommand": "knowledge_id before_business_digest after_business_digest before_neutral_digest after_neutral_digest after_inventory_business_revision_digest after_owner_configuration_digest target_type target_is_released target_migration_origin creator_user_id membership_action before_member_count before_member_digest existing_creator_member_id creator_template_digest creator_planned_at".split(),
    "InitializeV1Command": "knowledge_id file_id file_business_digest before_relation_digest natural_key document_template_digest version_template_digest file_level_path level planned_at".split(),
    "TagConversionCommand": "tag_id knowledge_id before_digest after_digest from_business_type to_business_type".split(),
    "TagLinkConversionCommand": "link_id file_id knowledge_id tag_id before_digest after_digest from_type to_type action survivor_link_id survivor_digest".split(),
    "DefaultSlotProvenance": "source_slot target_slot target_id".split(),
    "DefaultConversionCommand": "row_id key before_raw_row_digest before_configuration_digest after_configuration_digest after_business_revision_digest before_refs_digest after_refs_digest action selected_linsight_id selected_chat_id drop_task_model drop_executor_mode algorithm_version provenance".split(),
}


@pytest.fixture
def domain():
    return importlib.import_module(DOMAIN)


def examples(owner):
    def base(operation):
        return {
            "schema_version": 1,
            "run_id": "sql-schema",
            "writer_contract_version": "f118-v1",
            "tenant_id": 101,
            "command_key": "a" * 64,
            "operation": operation,
        }

    return (
        owner.ResourceConversionCommand(
            **base("resource_conversion"),
            knowledge_id=9000,
            before_business_digest="b" * 64,
            after_business_digest="c" * 64,
            before_neutral_digest="d" * 64,
            after_neutral_digest="e" * 64,
            after_inventory_business_revision_digest="f" * 64,
            after_owner_configuration_digest="1" * 64,
            target_type=3,
            target_is_released=False,
            target_migration_origin="sql-schema",
            creator_user_id=7,
            membership_action="insert",
            before_member_count=0,
            before_member_digest=codec.digest(()),
            existing_creator_member_id=None,
            creator_template_digest=codec.digest(
                creator_membership_template(knowledge_id=9000, creator_user_id=7, planned_at=NOW)
            ),
            creator_planned_at=NOW,
        ),
        owner.InitializeV1Command(
            **base("initialize_v1"),
            knowledge_id=9000,
            file_id=81,
            file_business_digest="b" * 64,
            before_relation_digest="c" * 64,
            natural_key="d" * 64,
            document_template_digest="e" * 64,
            version_template_digest="f" * 64,
            file_level_path=None,
            level=0,
            planned_at=NOW,
        ),
        owner.TagConversionCommand(
            **base("tag_conversion"),
            tag_id=5,
            knowledge_id=9000,
            before_digest="b" * 64,
            after_digest="c" * 64,
            from_business_type="knowledge",
            to_business_type="knowledge_space",
        ),
        owner.TagLinkConversionCommand(
            **base("tag_link_conversion"),
            link_id=6,
            file_id=81,
            knowledge_id=9000,
            tag_id=5,
            before_digest="b" * 64,
            after_digest="c" * 64,
            from_type=9,
            to_type=8,
            action="retag",
            survivor_link_id=6,
            survivor_digest="c" * 64,
        ),
        owner.DefaultConversionCommand(
            **base("default_conversion"),
            row_id=7,
            key="linsight_llm",
            before_raw_row_digest="b" * 64,
            before_configuration_digest="c" * 64,
            after_configuration_digest="d" * 64,
            after_business_revision_digest="e" * 64,
            before_refs_digest="f" * 64,
            after_refs_digest="1" * 64,
            action="first:last",
            selected_linsight_id="7",
            selected_chat_id="8",
            drop_task_model=True,
            drop_executor_mode=False,
            algorithm_version="sql-default-conversion-v1",
            provenance=(owner.DefaultSlotProvenance("models.7.id", "linsight_default_model_id", "7"),),
        ),
    )


@pytest.mark.parametrize("name", EXTRA_FIELDS)
def test_old_public_types_are_the_same_frozen_slotted_domain_objects(domain, name):
    app = importlib.import_module(APP)
    cls = getattr(domain, name)
    assert getattr(app, name) is cls and cls.__module__ == DOMAIN
    expected = EXTRA_FIELDS[name] if name == "DefaultSlotProvenance" else BASE_FIELDS + EXTRA_FIELDS[name]
    assert [field.name for field in fields(cls)] == expected
    assert all(field.default is MISSING and field.default_factory is MISSING for field in fields(cls))
    assert cls.__dataclass_params__.frozen
    if name in {"ConversionCommand", "DefaultSlotProvenance"}:
        assert cls.__bases__ == (object,)
    else:
        assert cls.__bases__ == (domain.ConversionCommand,)
    values = {field.name: None for field in fields(cls)}
    instance = cls(**values)
    assert not hasattr(instance, "__dict__")
    with pytest.raises(FrozenInstanceError):
        setattr(instance, expected[0], "changed")


def wire(owner):
    commands = examples(owner)
    commands += (replace(commands[3], action="drop_duplicate", after_digest=None, survivor_link_id=8),)
    records = tuple(codec.record_from_row(command) for command in commands)
    return codec.encode_inventory_page(
        run_id="sql-schema",
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        kind="plan",
        records=records,
    )


def test_canonical_command_bytes_and_lazy_codec_mapping_include_required_member_intent(domain):
    app = importlib.import_module(APP)
    assert wire(app) == wire(domain)
    # The Resource command adds the newly frozen required membership intent.
    assert (
        hashlib.sha256(wire(domain)).hexdigest() == "56d11abdae6a23ae25996d9a2fb12e3fb3187940b86c3e340ae6acf09ed81e83"
    )
    records = codec.decode_inventory_page(
        wire(domain),
        run_id="sql-schema",
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        kind="plan",
    ).records
    assert [record.record_type for record in records] == [*app.COMMAND_RECORD_TYPES.values(), "tag_link_conversion"]
    assert set(app.COMMAND_RECORD_TYPES) == {type(command) for command in examples(domain)}


def test_other_four_kinds_keep_bytes_measured_from_original_74f_examples(domain):
    commands = examples(domain)[1:]
    commands += (replace(commands[2], action="drop_duplicate", after_digest=None, survivor_link_id=8),)
    content = codec.encode_inventory_page(
        run_id="sql-schema",
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        kind="plan",
        records=tuple(codec.record_from_row(command) for command in commands),
    )
    assert hashlib.sha256(content).hexdigest() == "6a156db1da594a799474daa442a63a4b295442d36fda784fb9a5c73a6b6ff046"


def test_original_template_function_is_reexported_and_keeps_canonical_bytes(domain):
    app = importlib.import_module(APP)
    assert app.initial_version_templates is domain.initial_version_templates
    values = {
        "knowledge_id": 9000,
        "file_id": 81,
        "file_level_path": None,
        "level": 0,
        "planned_at": NOW,
        "natural_key": "d" * 64,
    }
    actual = domain.initial_version_templates(**values)
    assert codec.digest(actual) == "d9ca6000fbbe034af793211f5d8707efe75f367d5d930a17535fd93a93d24f8f"
    assert actual[0]["primary_version_key"] == actual[1]["document_key"] == values["natural_key"]
    assert actual[0]["create_time"] == actual[0]["update_time"] == NOW
    assert actual[1]["create_time"] == actual[1]["update_time"] == NOW
    assert "id" not in actual[0] and "document_id" not in actual[1]
    actual[0]["level"] = 99
    assert domain.initial_version_templates(**values)[0]["level"] == 0


def test_domain_owner_imports_only_stdlib_and_cannot_import_application_or_io(domain):
    tree = ast.parse(Path(domain.__file__).read_text())
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert set(imported) == {"dataclasses", "datetime"}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert {node.name for node in tree.body if isinstance(node, ast.ClassDef)} == set(EXTRA_FIELDS)


async def test_actual_native_producer_emits_domain_objects_consumable_by_original_codec(domain, native):
    app = importlib.import_module(APP)
    await native.insert(producer.original.Knowledge, [producer.original.resource(9000)])
    await native.insert(producer.original.KnowledgeFile, [producer.original.file(1)])
    await native.insert(producer.original.Tag, [producer.original.data("tags", 1)])
    await native.insert(producer.original.TagLink, [producer.original.data("tag_links", 1)])
    default = DefaultRow(7, 101, "linsight_llm", '{"models":[{"id":"7"}],"task_model":{"id":"7"}}', NOW)
    facts = await producer.acquire(native)
    query_count = len(native.queries)
    commands = producer.build(app, facts, (default,))[1]
    assert len(native.queries) == query_count
    assert {type(command) for command in commands} == {
        getattr(domain, cls.__name__) for cls in app.COMMAND_RECORD_TYPES
    }
    records = tuple(codec.record_from_row(command) for command in commands)
    content = codec.encode_inventory_page(
        run_id=producer.IDENTITY["run_id"],
        section="conversion",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        kind="plan",
        records=records,
    )
    assert (
        codec.decode_inventory_page(
            content,
            run_id=producer.IDENTITY["run_id"],
            section="conversion",
            scope="tenant",
            tenant_id=101,
            page_index=0,
            kind="plan",
        ).records
        == records
    )
