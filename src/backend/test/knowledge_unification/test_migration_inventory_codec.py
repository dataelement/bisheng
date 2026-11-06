"""M2 private facts are explicit projections, never original payload dumps."""

import importlib
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.domain.repositories.unification_resource_repository import UnificationResourceRepository
from test.knowledge_unification import test_migration_resource_repository as original

resource_native = original.native
RUN = "formal-m2"
DIGEST = "a" * 64
DESCRIPTOR = {"object_key": "backup/original", "sha256": DIGEST}


@pytest.fixture
def codec():
    return importlib.import_module("bisheng.knowledge.application.unification_inventory_codec")


def encode(codec, records=(), **changes):
    args = dict(run_id=RUN, section="resources", scope="tenant", tenant_id=101, page_index=0, records=records)
    return codec.encode_inventory_page(**(args | changes))


def decode(codec, content, **changes):
    args = dict(run_id=RUN, section="resources", scope="tenant", tenant_id=101, page_index=0)
    return codec.decode_inventory_page(content, **(args | changes))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


async def test_original_native_fields_include_private_payloads_that_cannot_be_artifacts(resource_native):
    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    await resource_native.insert(original.KnowledgeFile, [original.file(1)])
    async with AsyncSession(resource_native.engine) as session, session.begin():
        row = (await UnificationResourceRepository().alist_files(session)).items[0]
        assert row.abstract == "private-abstract" and row.user_metadata == {"private-value": "keep"}


@pytest.mark.parametrize("kind", original.MODELS)
async def test_native_resource_rows_encode_safe_scalars_and_full_original_digests(codec, resource_native, kind):
    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    await resource_native.insert(original.MODELS[kind], [original.data(kind, 1)])
    async with AsyncSession(resource_native.engine) as session, session.begin():
        row = (await getattr(UnificationResourceRepository(), f"alist_{kind}")(session)).items[0]
        record = codec.record_from_row(row)
        content = encode(codec, (record,))
        assert b"private-" not in content and "private-" not in repr(record)
        assert decode(codec, content).records == (record,)
        assert record.data["id"] == 1
        assert "abstract" not in record.data and "questions" not in record.data and "answers" not in record.data
        assert "user_metadata" not in record.data and "remark" not in record.data
        digest_name = "old_business_digest" if kind == "resources" else "row_digest"
        assert len(record.data[digest_name]) == 64
        assert not hasattr(record, "__dict__")
        with pytest.raises(FrozenInstanceError):
            record.record_type = "changed"


async def test_file_payload_change_changes_digest_without_exporting_text_and_only_web_system_locator_escapes(
    codec, resource_native
):
    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    await resource_native.insert(original.KnowledgeFile, [original.file(1)])
    async with AsyncSession(resource_native.engine) as session, session.begin():
        row = (await UnificationResourceRepository().alist_files(session)).items[0]
        first = codec.record_from_row(row)
        second = codec.record_from_row(
            replace(
                row,
                abstract="a different private body",
                user_metadata={"html_snapshot_object_name": "html/original", "private-field": "private-content"},
            )
        )
        assert first.data["row_digest"] != second.data["row_digest"]
        assert first.data["user_metadata_digest"] != second.data["user_metadata_digest"]
        assert second.data["html_snapshot_object_name"] == "html/original"
        assert "private-content" not in second.data_json and "different private body" not in second.data_json


def object_fact(codec, **changes):
    return codec.record_from_values(
        "physical_object",
        **(
            dict(
                tenant_id=101,
                space_id=9000,
                file_id=1,
                object_kind="original",
                object_key="private/object-key",
                exists=True,
                size=8,
                etag="etag-is-not-sha",
            )
            | changes
        ),
    )


def test_required_port_shapes_are_closed_private_and_preserve_original_physical_facts(codec):
    obj = object_fact(codec)
    index = codec.record_from_values(
        "physical_index",
        tenant_id=101,
        space_id=9000,
        index_name="private-index",
        collection_name="private-collection",
        es_exists=True,
        milvus_exists=True,
        es_mapping_digest=DIGEST,
        milvus_schema_digest=DIGEST,
        es_count=2,
        milvus_count=3,
        identifier_compatible=True,
    )
    task = codec.record_from_values(
        "queued_task",
        tenant_id=101,
        task_kind="legacy_scheduler",
        task_id="original-task",
        space_id=9000,
        file_id=1,
        document_id=None,
        version_id=None,
        state="queued",
        configuration_digest=DIGEST,
        record_digest=DIGEST,
    )
    for record in (obj, index, task):
        assert "private-" not in repr(record)
        assert decode(codec, encode(codec, (record,))).records == (record,)
    assert index.data["es_count"] != index.data["milvus_count"]
    assert obj.data["etag"] == "etag-is-not-sha"
    with pytest.raises(KnowledgeOperationPlanConflictError):
        object_fact(codec, provider_config="private-secret")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        object_fact(codec, object_kind="unknown")


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": True},
        {"tenant_id": 101.0},
        {"page_index": False},
        {"page_index": -1},
        {"run_id": "../bad"},
        {"scope": "global"},
        {"section": "unknown"},
        {"records": []},
    ],
)
def test_page_identity_and_types_fail_closed(codec, changes):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"exists": 1},
        {"size": False},
        {"file_id": 1.0},
        {"tenant_id": 202},
        {"object_key": "https://signed.invalid/key"},
    ],
)
def test_physical_shape_cannot_coerce_types_borrow_tenant_or_store_urls(codec, changes):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        record = object_fact(codec, **changes)
        encode(codec, (record,))


def test_canonical_header_counter_extra_keys_and_duplicate_keys_are_rejected(codec):
    good = encode(codec, (object_fact(codec),))
    envelope = json.loads(good)
    assert len(envelope["records"]) == 2
    assert envelope["records"][0] == dict(
        record_type="page", section="resources", scope="tenant", tenant_id=101, page_index=0, record_count=1
    )
    for name, value in (("record_count", True), ("record_count", 2), ("tenant_id", 202), ("scope", "global")):
        bad = json.loads(good)
        bad["records"][0][name] = value
        with pytest.raises(KnowledgeOperationPlanConflictError):
            decode(codec, canonical(bad))
    for bad in (
        b"",
        good + b"\n",
        good.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'),
        b"x" * (16 * 1024 * 1024 + 1),
    ):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            decode(codec, bad)
    envelope["records"][1]["provider_config"] = "private-secret"
    with pytest.raises(KnowledgeOperationPlanConflictError) as error:
        decode(codec, canonical(envelope))
    assert "private-secret" not in str(error.value)


def test_page_boundary_is_199_facts_plus_header_and_global_scope_is_explicit(codec):
    record = object_fact(codec)
    assert len(decode(codec, encode(codec, (record,) * 199)).records) == 199
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (record,) * 200)
    tuple_record = codec.record_from_values(
        "fga_tuple", user="user:7", relation="visible", object="knowledge_library:1"
    )
    content = encode(codec, (tuple_record,), scope="global", tenant_id=None, section="fga")
    assert decode(codec, content, scope="global", tenant_id=None, section="fga").records == (tuple_record,)


async def test_layered_manifests_are_bounded_and_real_store_can_read_every_node(codec):
    objects = {}

    async def exists(**kwargs):
        return kwargs["object_name"] in objects

    async def put(**kwargs):
        objects[kwargs["object_name"]] = kwargs["file"]

    async def get(**kwargs):
        return objects[kwargs["object_name"]]

    store = UnificationArtifactStore(
        SimpleNamespace(bucket="durable", tmp_bucket="tmp", object_exists=exists, put_object=put, get_object=get)
    )
    entries = (
        codec.record_from_values(
            "manifest_entry",
            section="resources",
            scope="tenant",
            tenant_id=101,
            page_index=index,
            record_count=1,
            descriptor={"object_key": f"pages/{index}", "sha256": DIGEST},
            level=0,
        )
        for index in range(401)
    )
    metadata = codec.record_from_values(
        "run",
        writer_contract_version="f118-v1",
        environment="original",
        tenant_count=1,
        tenant_inventory_digest=DIGEST,
        backup_ref=DESCRIPTOR,
        schema_ref=DESCRIPTOR,
        catalog_digest=DIGEST,
        authorization_model_checksum=DIGEST,
        baseline_ref=None,
    )
    nodes = list(codec.iter_manifest_nodes(run_id=RUN, kind="baseline", entries=entries, metadata=metadata))
    assert len(nodes) == 4 and sum(node.is_root for node in nodes) == 1 and nodes[-1].is_root
    for node in nodes:
        envelope = json.loads(node.content)
        assert len(envelope["records"]) <= 200
        descriptor = await store.aput_canonical(run_id=RUN, kind="baseline", content=node.content)
        assert descriptor == node.descriptor
        assert await store.aload_canonical(descriptor, run_id=RUN, kind="baseline") == node.content
