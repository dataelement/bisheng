"""Closed migration source pages preserve real DTOs without storing raw rows."""

import importlib
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_sources import (
    ReferenceInventoryRecord,
    RetiredInventoryRecord,
    RootInventoryRecord,
    SourceInventoryRecord,
)
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetFact
from bisheng.llm.domain.repositories.migration_target_repository import ModelMigrationTargetFact
from bisheng.resource_reference.application.contracts import SourceKey, SourceRootKey, SourceType, TargetKey

RUN = "f118-source-page-test"
DIGEST = "a" * 64
LIMIT = 16 * 1024 * 1024


@pytest.fixture
def codec():
    return importlib.import_module("bisheng.knowledge.application.unification_source_codec")


@pytest.fixture
def records(codec):
    root = SourceRootKey(101, SourceType.WORKFLOW_VERSION, "flow-a")
    source = SourceKey(101, SourceType.WORKFLOW_VERSION, "flow-a", "7")
    model = TargetKey("model", 12)
    file = TargetKey("knowledge_file", 81)
    return (
        RootInventoryRecord(root, 7, ("原状态", True, None, 1), DIGEST, 1, DIGEST),
        SourceInventoryRecord(source, "original-v1", DIGEST, DIGEST, 2, (1, 0), DIGEST),
        ReferenceInventoryRecord(
            source,
            "node/模型",
            model,
            "explicit_id",
            ModelMigrationTargetFact(model, True, 1, "embedding", False, 4, True, 1, DIGEST),
        ),
        ReferenceInventoryRecord(
            source,
            "node/file",
            file,
            "explicit_id",
            KnowledgeMigrationTargetFact(file, True, 101, 40, 3, 1, True, 101, DIGEST),
        ),
        RetiredInventoryRecord(
            root, SourceKey(101, SourceType.WORKFLOW_VERSION, "flow-a", "6"), (0, 1), DIGEST, DIGEST
        ),
    )


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def encode(codec, records=(), **changes):
    return codec.encode_source_page(run_id=RUN, tenant_id=101, page_index=0, records=records, **changes)


def decode(codec, content):
    return codec.decode_source_page(content, run_id=RUN, tenant_id=101, page_index=0)


def test_roundtrip_preserves_four_real_records_both_facts_and_foreign_scalar(codec, records):
    content = encode(codec, records)
    envelope = json.loads(content)
    assert set(envelope) == {"schema_version", "run_id", "kind", "records"}
    assert envelope["kind"] == "sources" and envelope["schema_version"] == 1
    assert envelope["records"][0] == {
        "record_type": "page",
        "tenant_id": 101,
        "page_index": 0,
        "record_count": 5,
    }
    page = decode(codec, content)
    assert (page.tenant_id, page.page_index, page.records) == (101, 0, records)
    assert content == canonical(envelope) and "原状态".encode() in content
    assert page.records[2].physical_fact.target_tenant_id == 1
    assert page.records[2].physical_fact.is_online is False
    assert not hasattr(page, "__dict__")
    with pytest.raises(FrozenInstanceError):
        page.page_index = 1


def test_empty_pages_are_explicit_and_bound_to_tenant_and_page(codec):
    first = encode(codec)
    other = codec.encode_source_page(run_id=RUN, tenant_id=202, page_index=0, records=())
    next_page = codec.encode_source_page(run_id=RUN, tenant_id=101, page_index=1, records=())
    assert len({first, other, next_page}) == 3 and decode(codec, first).records == ()
    for wrong in (other, next_page):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            decode(codec, wrong)


def test_page_limit_includes_header_without_silent_deduplication(codec, records):
    repeated = (records[0],) * 199
    content = encode(codec, repeated)
    assert len(json.loads(content)["records"]) == 200
    assert decode(codec, content).records == repeated
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (*repeated, records[0]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", True),
        ("tenant_id", 1.0),
        ("tenant_id", 0),
        ("page_index", -1),
        ("page_index", False),
        ("run_id", "../unsafe"),
    ],
)
def test_identity_types_reject_before_encoding(codec, field, value):
    args = {"run_id": RUN, "tenant_id": 101, "page_index": 0, "records": ()}
    args[field] = value
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.encode_source_page(**args)


@pytest.mark.parametrize(
    "path,value",
    [
        (("kind",), "baseline"),
        (("run_id",), "other-run"),
        (("schema_version",), True),
        (("records", 0, "record_count"), 99),
        (("records", 0, "tenant_id"), 202),
        (("records", 0, "page_index"), 0.0),
        (("records", 1, "record_type"), "raw_provider"),
        (("records", 1, "configuration_digest"), "bad"),
        (("records", 2, "business_revision_digest"), "A" * 64),
        (("records", 3, "physical_fact", "key", "target_id"), "13"),
        (("records", 3, "physical_fact", "exists"), 1),
        (("records", 3, "physical_fact", "server_id"), False),
        (("records", 4, "source_key", "tenant_id"), 202),
    ],
)
def test_closed_shapes_reject_tampered_facts_and_headers(codec, records, path, value):
    envelope = json.loads(encode(codec, records))
    node = envelope
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    with pytest.raises(KnowledgeOperationPlanConflictError):
        decode(codec, canonical(envelope))


def test_extra_raw_fields_and_arbitrary_objects_cannot_escape(codec, records):
    envelope = json.loads(encode(codec, records))
    envelope["records"][2]["provider_config"] = {"secret": "private-marker"}
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        decode(codec, canonical(envelope))
    assert "private-marker" not in str(caught.value)
    for bad in ([records[0]], (SimpleNamespace(provider_config="private-marker"),)):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            encode(codec, bad)


def test_duplicate_keys_noncanonical_and_nonfinite_payloads_are_rejected(codec):
    good = encode(codec)
    invalid = (
        b"",
        good.decode(),
        good.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
        json.dumps(json.loads(good), indent=2).encode(),
        good.replace(b'"record_count":0', b'"record_count":NaN'),
        good + b"\n",
        b"x" * (LIMIT + 1),
    )
    for content in invalid:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            decode(codec, content)


def test_encoding_enforces_byte_budget_and_preserves_absent_target_facts(codec, records):
    huge = replace(records[0], lifecycle=("x" * LIMIT,))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (huge,))
    missing = TargetKey("model", 999)
    fact = ModelMigrationTargetFact(missing, False, None, None, None, None, False, None, DIGEST)
    reference = replace(records[2], target=missing, physical_fact=fact)
    assert decode(codec, encode(codec, (reference,))).records == (reference,)


async def test_bytes_roundtrip_through_actual_artifact_store_contract(codec, records):
    objects = {}

    async def exists(*, bucket_name, object_name):
        return object_name in objects

    async def put(*, bucket_name, object_name, file, content_type):
        objects[object_name] = file

    async def get(*, bucket_name, object_name):
        return objects[object_name]

    store = UnificationArtifactStore(
        SimpleNamespace(bucket="durable", tmp_bucket="temporary", object_exists=exists, put_object=put, get_object=get)
    )
    content = encode(codec, records)
    descriptor = await store.aput_canonical(run_id=RUN, kind="sources", content=content)
    recovered = await store.aload_canonical(descriptor, run_id=RUN, kind="sources")
    assert decode(codec, recovered).records == records and len(objects) == 1
