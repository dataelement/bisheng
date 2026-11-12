"""T959: original acceptance bytes, validation order and same-object value exports."""

import ast
import importlib
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import select

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.knowledge.domain.models.knowledge_processing_item import KnowledgeProcessingItem
from bisheng.knowledge.domain.repositories import processing_job_repository as original
from bisheng.knowledge.domain.schemas.processing_job import ResourceVersionTarget
from test.knowledge_unification import test_job_repo as fixtures

job_tenant, job_session = fixtures.job_tenant, fixtures.job_session
repository, clock = fixtures.repository, fixtures.clock

# Captured against aa5e43e28's original complete acceptance projection. These
# constants deliberately include Unicode, escaping, 0, false and optional
# metadata facts, rather than deriving expectations with the extracted helper.
ORACLES = {
    "embedding_rebuild": "2c2a7df27f594ae679ab23207130501657baa19ced1cd6f81a08644294a9afc3",
    "file_reprocess": "15901c1027b030c1ea63b7bd733c30ec4d9ed071c377cbfad4b20f19ab1b4161",
    "file_resplit": "d1e440c782c46cc348102a5b5f6e86448d14eeb3aef662279f18f4689ac96b3b",
    "metadata_schema_change": "6802946d25a969c83141cb48a0b8f379e22d6d63660f07626e4516829f7861e0",
}
ACTOR = {"actor_type": "person", "actor_id": "7", "scope": {"values": [False, 0, "租户"]}}
PARAMETERS = {"operation_id": "freeze-\u03b1", "request_parameters": {"separator": ["\n", '"', "☃"], "size": 0}}
MANIFEST = [
    {
        "file_id": 8,
        "document_id": 108,
        "version_id": 208,
        "expected_space_id": 1,
        "expected_parent_id": None,
        "processing_snapshot": {"actual_rule": '保持\n"\\', "nested": {"zero": 0, "false": False, "empty": []}},
    },
    {
        "file_id": 9,
        "document_id": 109,
        "version_id": 209,
        "expected_space_id": 1,
        "expected_parent_id": 4,
        "processing_snapshot": {"actual_rule": "second", "payload": [0, False, None]},
    },
]


def schema():
    return importlib.import_module("bisheng.knowledge.domain.schemas.processing_job_acceptance")


def configuration():
    return original.ProcessingConfiguration(7, "index-7", 2, "b" * 64)


def items():
    return [
        original.NewProcessingItem(
            ResourceVersionTarget(**{key: row[key] for key in ("file_id", "document_id", "version_id")}),
            row["expected_space_id"],
            row["expected_parent_id"],
            deepcopy(row["processing_snapshot"]),
        )
        for row in reversed(MANIFEST)
    ]


def facts(kind, manifest):
    return schema().processing_request_facts(
        tenant_id=101,
        space_id=1,
        kind=kind,
        actor_user_id=11,
        actor_reference=ACTOR,
        parameters=PARAMETERS,
        manifest=manifest,
        configuration=configuration(),
        space_config_version=3,
    )


@pytest.mark.parametrize("kind", ORACLES)
async def test_original_native_repository_matches_frozen_full_acceptance_oracle(job_session, repository, kind):
    result = await repository.acreate(
        job_session,
        space_id=1,
        kind=kind,
        idempotency_key="original-oracle",
        actor_user_id=11,
        actor_reference=ACTOR,
        parameters=PARAMETERS,
        configuration=configuration(),
        items=items(),
        space_config_version=3,
    )
    assert result.job.request_hash == ORACLES[kind] and not result.reused
    rows = (await job_session.exec(select(KnowledgeProcessingItem).order_by(KnowledgeProcessingItem.file_id))).all()
    assert [row.processing_snapshot for row in rows] == [row["processing_snapshot"] for row in MANIFEST]
    assert result.job.parameters == PARAMETERS
    assert "scope_manifest" in vars(result.job)
    if kind == "metadata_schema_change":
        assert "processing_snapshot_digest" in result.job.scope_manifest[0]
        assert "processing_snapshot" not in result.job.scope_manifest[0]
    else:
        assert result.job.scope_manifest == MANIFEST
    await job_session.rollback()


@pytest.mark.parametrize("kind", ORACLES)
def test_new_projection_matches_original_bytes_and_shares_prepared_payloads(kind):
    api = schema()
    manifest = api.processing_manifest(1, items())
    assert manifest == MANIFEST
    actual = facts(kind, manifest)
    assert api._digest(actual) == ORACLES[kind]
    assert actual["scope_manifest"] is manifest and actual["parameters"] is PARAMETERS
    assert actual["actor_reference"] is ACTOR
    assert ("metadata_schema_revision" in actual) == (kind == "metadata_schema_change")
    assert ("metadata_schema_digest" in actual) == (kind == "metadata_schema_change")


@pytest.mark.parametrize(
    "name", ["ProcessingConfiguration", "NewProcessingItem", "JobRequestResult", "JobLease", "ItemLease", "_digest"]
)
def test_existing_consumers_keep_the_same_exported_class_or_function(name):
    assert getattr(original, name) is getattr(schema(), name)


def test_original_frozen_dataclass_defaults_and_non_slot_behavior_are_preserved():
    api = schema()
    config = api.ProcessingConfiguration(0, None)
    assert [field.name for field in fields(config)] == [
        "model_config_revision",
        "index_generation",
        "metadata_schema_revision",
        "metadata_schema_digest",
    ]
    assert config.__dict__ == {
        "model_config_revision": 0,
        "index_generation": None,
        "metadata_schema_revision": None,
        "metadata_schema_digest": None,
    }
    lease = api.JobLease("job", "lease", 1, datetime(2026, 11, 7))
    item_lease = api.ItemLease(lease, "item", "item-lease", 2, datetime(2026, 11, 7))
    assert item_lease.job is lease and api.JobRequestResult(None, False).reused is False
    with pytest.raises(FrozenInstanceError):
        config.model_config_revision = 1
    with pytest.raises(FrozenInstanceError):
        item_lease.item_id = "changed"


@pytest.mark.parametrize(
    "args",
    [
        (True, None),
        (-1, None),
        (0, ""),
        (0, "x" * 65),
        (0, None, 1, None),
        (0, None, None, "b" * 64),
        (0, None, False, "b" * 64),
    ],
)
def test_original_configuration_validation_is_preserved(args):
    with pytest.raises(ValueError):
        original.ProcessingConfiguration(*args)
    with pytest.raises(ValueError):
        schema().ProcessingConfiguration(*args)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), object()])
def test_digest_preserves_non_json_and_non_finite_rejection(bad):
    with pytest.raises((ValueError, TypeError)):
        original._digest({"invalid": bad})
    with pytest.raises((ValueError, TypeError)):
        schema()._digest({"invalid": bad})


@pytest.mark.parametrize("bad", ["duplicate", "space", "invalid_target"])
def test_manifest_preserves_validation_before_acceptance_hash(bad):
    values = items()
    if bad == "duplicate":
        values.append(values[0])
    elif bad == "space":
        values[0] = original.NewProcessingItem(values[0].target, 999, processing_snapshot={"nan": float("nan")})
    else:
        invalid = ResourceVersionTarget.model_construct(file_id=True, document_id=1, version_id=1)
        values[0] = original.NewProcessingItem(invalid, 999)
    with pytest.raises(ValueError):
        schema().processing_manifest(1, values)


def test_manifest_has_one_snapshot_copy_and_fact_projection_adds_no_large_payload_copy():
    copies = []

    class Counted(dict):
        def __deepcopy__(self, memo):
            copies.append(1)
            return {key: deepcopy(value, memo) for key, value in self.items()}

    value = original.NewProcessingItem(
        ResourceVersionTarget(file_id=8, document_id=108, version_id=208),
        1,
        processing_snapshot={"large": Counted(text="x" * 1000001)},
    )
    manifest = schema().processing_manifest(1, [value])
    assert len(copies) == 1
    actual = facts("embedding_rebuild", manifest)
    assert actual["scope_manifest"] is manifest and len(copies) == 1
    value.processing_snapshot["large"]["text"] = "caller changed"
    assert len(actual["scope_manifest"][0]["processing_snapshot"]["large"]["text"]) == 1000001


@pytest.mark.parametrize(
    "bad, message",
    [
        ("key", "idempotency_key"),
        ("actor", "trusted actor"),
        ("settings", "nonempty frozen scope"),
        ("duplicate", "duplicate file/version"),
    ],
)
async def test_original_native_validation_order_stays_before_projection_and_resource_locks(
    job_session, repository, bad, message
):
    args = {
        "space_id": 1,
        "kind": "embedding_rebuild",
        "idempotency_key": "order",
        "actor_user_id": 11,
        "actor_reference": ACTOR,
        "parameters": PARAMETERS,
        "configuration": configuration(),
        "items": items(),
    }
    if bad == "key":
        args.update(idempotency_key="", actor_reference={"nan": float("nan")}, items=[])
    elif bad == "actor":
        args.update(actor_user_id=True, items=[])
    elif bad == "settings":
        args.update(space_config_version=True, parameters=None)
    else:
        args["items"].append(args["items"][0])
        args["parameters"] = None
    with pytest.raises(ValueError, match=message):
        await repository.acreate(job_session, **args)
    assert not job_session.new and not job_session.dirty


@pytest.mark.parametrize("kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"])
async def test_original_empty_scope_gate_and_metadata_authority_remain_in_repository(job_session, repository, kind):
    error = ResourceReferenceInvalidError if kind == "metadata_schema_change" else ValueError
    with pytest.raises(error):
        await repository.acreate(
            job_session,
            space_id=1,
            kind=kind,
            idempotency_key="empty",
            actor_user_id=11,
            actor_reference=ACTOR,
            parameters=PARAMETERS,
            configuration=configuration(),
            items=[],
        )
    assert not job_session.new and not job_session.dirty


def test_new_schema_contains_only_values_and_pure_projection_not_sql_or_orchestration():
    tree = ast.parse(Path(schema().__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not any(
                word in (node.module or "").split(".")
                for word in ("sqlalchemy", "sqlmodel", "repositories", "application", "worker")
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"execute", "exec", "flush", "commit", "rollback", "uuid4", "now"}
