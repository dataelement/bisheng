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
    args = {
        "run_id": RUN,
        "section": "resources",
        "scope": "tenant",
        "tenant_id": 101,
        "page_index": 0,
        "records": records,
    }
    return codec.encode_inventory_page(**(args | changes))


def decode(codec, content, **changes):
    args = {"run_id": RUN, "section": "resources", "scope": "tenant", "tenant_id": 101, "page_index": 0}
    return codec.decode_inventory_page(content, **(args | changes))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@pytest.mark.parametrize("owner,allowed", [(1, True), (101, True), (202, False)])
def test_role_fact_keeps_real_global_owner_without_relabeling_it_as_local(codec, owner, allowed):
    record = codec.record_from_values(
        "role_fact",
        id=5,
        exists=True,
        tenant_id=owner,
        role_type="custom",
        department_id=None,
        knowledge_space_file_limit=None,
        update_time=None,
        quota_digest=DIGEST,
        row_digest=DIGEST,
    )
    if allowed:
        page = encode(codec, (record,), section="control")
        assert decode(codec, page, section="control").records[0].data["tenant_id"] == owner
    else:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            encode(codec, (record,), section="control")


async def test_original_native_fields_include_private_payloads_that_cannot_be_artifacts(resource_native):
    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    await resource_native.insert(original.KnowledgeFile, [original.file(1)])
    async with AsyncSession(resource_native.engine) as session, session.begin():
        row = (await UnificationResourceRepository().alist_files(session)).items[0]
        assert row.abstract == "private-abstract" and row.user_metadata == {"private-value": "keep"}


@pytest.mark.parametrize("kind", original.MODELS)
async def test_native_resource_rows_encode_safe_scalars_and_full_original_digests(codec, resource_native, kind):
    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    if kind == "versions":
        await resource_native.insert(original.KnowledgeDocument, [original.data("documents", 1)])
        await resource_native.insert(original.KnowledgeFile, [original.file(1)])
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
            {
                "tenant_id": 101,
                "space_id": 9000,
                "file_id": 1,
                "object_kind": "original",
                "object_key": "private/object-key",
                "exists": True,
                "size": 8,
                "etag": "etag-is-not-sha",
            }
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
    assert envelope["records"][0] == {
        "record_type": "page",
        "section": "resources",
        "scope": "tenant",
        "tenant_id": 101,
        "page_index": 0,
        "record_count": 1,
    }
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


def test_permission_change_plan_has_closed_digests_and_explicit_namespace(codec):
    record = codec.record_from_values(
        "permission_plan",
        tenant_id=101,
        resource_type="knowledge_library",
        resource_id="40",
        target_resource_type="knowledge_space",
        plan_checksum=DIGEST,
        before_digest=DIGEST,
        after_grants_digest=DIGEST,
        visibility_deltas_digest=DIGEST,
        expected_use_changes_digest=DIGEST,
        mode_id=4,
        catalog_plan_checksum=DIGEST,
        target_mode_digest=DIGEST,
        after_digest=DIGEST,
        grant_count=1,
        assignee_count=1,
        visible_source_count=1,
    )
    assert decode(
        codec,
        encode(codec, (record,), section="conversion", kind="plan"),
        section="conversion",
        kind="plan",
    ).records == (record,)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        codec.record_from_values("permission_plan", **(record.data | {"actor_reference": "private-secret"}))


def orphan(codec, **changes):
    return codec.record_from_values(
        "queued_task_orphan",
        **(
            {
                "task_kind": "scheduler_queue",
                "task_id": "raw-key:occurrence-1",
                "space_id": None,
                "file_id": 909,
                "document_id": None,
                "version_id": None,
                "payload_tenant_id": 101,
                "state": "queued",
                "reason": "file_missing",
                "configuration_digest": DIGEST,
                "record_digest": DIGEST,
            }
            | changes
        ),
    )


def test_sources_manifest_entry_uses_source_codec_only(codec):
    entry = codec.record_from_values(
        "manifest_entry",
        section="sources",
        scope="tenant",
        tenant_id=101,
        page_index=0,
        record_count=1,
        descriptor=DESCRIPTOR,
        level=0,
    )
    content = encode(codec, (entry,), section="manifest", scope="global", tenant_id=None)
    assert decode(codec, content, section="manifest", scope="global", tenant_id=None).records == (entry,)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (object_fact(codec),), section="sources")


def test_global_orphan_task_preserves_claim_without_assigning_tenant(codec):
    row = orphan(codec)
    content = encode(codec, (row,), section="tasks", scope="global", tenant_id=None)
    assert decode(codec, content, section="tasks", scope="global", tenant_id=None).records == (row,)
    assert "tenant_id" not in row.data and row.data["payload_tenant_id"] == 101
    for changes in ({"reason": "network_error"}, {"payload_tenant_id": True}, {"file_id": 1.0}, {"tenant_id": 101}):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            orphan(codec, **changes)


@pytest.mark.parametrize(
    "section,scope,tenant", [("tasks", "tenant", 101), ("resources", "global", None), ("fga", "global", None)]
)
def test_orphan_is_never_a_tenant_task_or_other_section(codec, section, scope, tenant):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (orphan(codec),), section=section, scope=scope, tenant_id=tenant)


def material(codec, **changes):
    return codec.record_from_values(
        "evidence_material",
        **(
            {
                "material_kind": "backup",
                "environment": "test",
                "writer_contract_version": "f118-v1",
                "tenant_inventory_digest": DIGEST,
                "material_ref": DESCRIPTOR,
            }
            | changes
        ),
    )


def test_evidence_manifest_is_bounded_verification_only_and_keeps_declared_material_separate(codec):
    row = material(codec)
    content = encode(codec, (row,), section="evidence", scope="global", tenant_id=None, kind="verification")
    assert decode(codec, content, section="evidence", scope="global", tenant_id=None, kind="verification").records == (
        row,
    )
    for changes in (
        {"material_kind": "online_probe"},
        {"tenant_inventory_digest": False},
        {"credential": "private-secret"},
    ):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            material(codec, **changes)


@pytest.mark.parametrize(
    "changes", [{"kind": "baseline"}, {"scope": "tenant", "tenant_id": 101}, {"section": "resources"}]
)
def test_evidence_cannot_borrow_other_authority_or_tenant_page(codec, changes):
    args = {"section": "evidence", "scope": "global", "tenant_id": None, "kind": "verification"} | changes
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (material(codec),), **args)


async def test_conversion_commands_are_closed_plan_only_records_with_matching_run(codec, resource_native):
    plan = importlib.import_module("bisheng.knowledge.application.unification_conversion_plan")
    from test.knowledge_unification.test_migration_conversion_plan import IDENTITY, acquire, build, default

    await resource_native.insert(original.Knowledge, [original.resource(9000)])
    await resource_native.insert(original.KnowledgeFile, [original.file(1)])
    await resource_native.insert(original.Tag, [original.data("tags", 1)])
    await resource_native.insert(original.TagLink, [original.data("tag_links", 1)])
    commands = build(
        plan, await acquire(resource_native), (default({"models": [{"id": "11"}], "task_model": {"id": "11"}}),)
    )[1]
    assert len(commands) == 5
    for command in commands:
        record = codec.record_from_row(command)
        content = codec.encode_inventory_page(
            run_id=IDENTITY["run_id"],
            section="conversion",
            scope="tenant",
            tenant_id=101,
            page_index=0,
            records=(record,),
            kind="plan",
        )
        assert codec.decode_inventory_page(
            content,
            run_id=IDENTITY["run_id"],
            section="conversion",
            scope="tenant",
            tenant_id=101,
            page_index=0,
            kind="plan",
        ).records == (record,)
        assert b"private-" not in content
        for changes in ({"kind": "baseline"}, {"run_id": "wrong-run"}, {"section": "resources"}):
            args = {
                "run_id": IDENTITY["run_id"],
                "section": "conversion",
                "scope": "tenant",
                "tenant_id": 101,
                "page_index": 0,
                "records": (record,),
                "kind": "plan",
            } | changes
            with pytest.raises(KnowledgeOperationPlanConflictError):
                codec.encode_inventory_page(**args)
    resource = next(item for item in commands if isinstance(item, plan.ResourceConversionCommand))
    for changes in ({"target_type": True}, {"target_type": 0}, {"target_is_released": True}, {"schema_version": True}):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            codec.record_from_row(replace(resource, **changes))


def broker_fact(codec, **changes):
    return codec.record_from_values(
        "broker_task",
        **(
            {
                "tenant_id": 101,
                "task_kind": "bisheng.worker.knowledge.file_worker.parse_knowledge_file_celery",
                "task_id": "original-message:occurrence-1",
                "space_id": 9000,
                "file_id": 1,
                "document_id": None,
                "version_id": None,
                "state": "queued",
                "configuration_digest": DIGEST,
                "record_digest": DIGEST,
                "header_tenant_id": None,
            }
            | changes
        ),
    )


@pytest.mark.parametrize("state", ["queued", "unacked", "legacy_requires_reissue", "obsolete"])
def test_broker_known_tenant_facts_round_trip_only_in_exact_task_scope(codec, state):
    record = broker_fact(codec, state=state)
    assert decode(codec, encode(codec, (record,), section="tasks"), section="tasks").records == (record,)
    for override in ({"section": "resources"}, {"scope": "global", "tenant_id": None}, {"tenant_id": 202}):
        with pytest.raises(KnowledgeOperationPlanConflictError):
            encode(codec, (record,), **({"section": "tasks"} | override))


@pytest.mark.parametrize("state", ["global_control", "target_missing", "unacked_metadata_orphan"])
def test_broker_global_facts_keep_header_claim_without_assigning_it_authority(codec, state):
    record = broker_fact(
        codec,
        tenant_id=None,
        task_kind=None
        if state == "unacked_metadata_orphan"
        else "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
        state=state,
        header_tenant_id=202,
    )
    arguments = {"section": "tasks", "scope": "global", "tenant_id": None}
    assert decode(codec, encode(codec, (record,), **arguments), **arguments).records == (record,)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        encode(codec, (record,), section="tasks")


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "running"},
        {"tenant_id": None},
        {"task_kind": None},
        {"task_kind": "workflow.user.task"},
        {"state": "global_control"},
        {"header_tenant_id": True},
        {"file_id": 0},
        {"task_id": ""},
        {"body": "private prompt"},
        {"model_id": 11},
    ],
)
def test_broker_codec_rejects_unknown_state_claims_ids_and_raw_payload(codec, changes):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        broker_fact(codec, **changes)
