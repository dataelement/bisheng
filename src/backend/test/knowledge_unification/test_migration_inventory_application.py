"""Actual SQL/SourceInventory/PinnedReader/Store orchestration, no live IO."""

import hashlib
import importlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ReferenceCoverageNotReadyError
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.database import tenant_filter
from bisheng.core.openfga.client import FGAClient
from bisheng.knowledge.application.unification_artifacts import UnificationArtifactStore
from bisheng.knowledge.application.unification_inventory_codec import (
    InventoryRecord,
    digest,
    encode_inventory_page,
    record_from_values,
)
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.permission.application.migration_read import PinnedMigrationPermissionReader
from test.knowledge_unification import test_migration_inventory_repository as raw
from test.knowledge_unification import test_migration_preflight as preflight
from test.knowledge_unification import test_migration_resource_repository as resources
from test.knowledge_unification import test_perm_migration_snapshot as permission

resource_native = preflight.resource_native
native = preflight.native
RUN = {
    "run_id": "formal-m2",
    "writer_contract_version": "f118-v1",
    "environment": "test",
    "backup_ref": {"object_key": "backups/original", "sha256": "b" * 64},
    "schema_ref": {"object_key": "schema/original", "sha256": "c" * 64},
}


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_inventory")


@pytest.fixture
async def complete(native, monkeypatch):
    models = (*raw.TABLES, KnowledgeUnificationRun)
    names = {model.__tablename__ for model in models if "tenant_id" in model.__table__.c} - {"user_tenant"}
    previous = tenant_filter._discover_tenant_aware_tables()
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: previous | names)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    async with native.engine.begin() as connection:
        for model in models:
            await connection.run_sync(lambda conn, model=model: model.__table__.create(conn, checkfirst=True))
    async with AsyncSession(native.engine) as session, session.begin():
        await permission.seed_catalog(session)
    await native.insert(resources.Knowledge, [resources.resource(9000, model="11")])
    await native.insert(resources.KnowledgeFile, [resources.file(1)])
    await native.insert(
        raw.LLMServer,
        [{"id": 1, "tenant_id": 1, "name": "Root", "type": "openai", "config": {"private-secret": "not artifact"}}],
    )
    await native.insert(
        raw.LLMModel,
        [
            {
                "id": 11,
                "tenant_id": 1,
                "server_id": 1,
                "model_name": "saved offline",
                "model_type": "llm",
                "online": False,
            }
        ],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        session.add(raw.flow("zero-version"))
    return native


@pytest.fixture
def transport():
    objects, requests = {}, []
    inputs = dict(RUN)
    for material_kind in ("backup", "schema"):
        record = record_from_values(
            "evidence_material",
            material_kind=material_kind,
            environment="test",
            writer_contract_version="f118-v1",
            tenant_inventory_digest=digest((1, 101, 202)),
            material_ref=RUN[f"{material_kind}_ref"],
        )
        content = encode_inventory_page(
            run_id=RUN["run_id"],
            section="evidence",
            scope="global",
            tenant_id=None,
            page_index=0,
            records=(record,),
            kind="verification",
        )
        checksum = hashlib.sha256(content).hexdigest()
        key = f"f118/unification/{RUN['run_id']}/verification/{checksum}.json"
        objects[key] = content
        inputs[f"{material_kind}_ref"] = {"object_key": key, "sha256": checksum}

    async def exists(**kwargs):
        return kwargs["object_name"] in objects

    async def put(**kwargs):
        objects[kwargs["object_name"]] = kwargs["file"]

    async def get(**kwargs):
        return objects[kwargs["object_name"]]

    store = UnificationArtifactStore(
        SimpleNamespace(bucket="durable", tmp_bucket="temporary", object_exists=exists, put_object=put, get_object=get)
    )

    @asynccontextmanager
    async def reader_factory(catalog):
        pin = catalog.authorization
        client = FGAClient("http://offline", pin.store_id, pin.model_id)
        await client._http.aclose()

        def handler(request):
            requests.append(request)
            if request.url.path.endswith("/read"):
                return httpx.Response(
                    200,
                    json={
                        "tuples": [{"key": {"user": "user:7", "relation": "use", "object": "knowledge_library:9000"}}]
                    },
                )
            return httpx.Response(200, text="")  # revoked Root sharing: no current grants

        client._http = httpx.AsyncClient(base_url="http://offline", transport=httpx.MockTransport(handler))

        async def discover(*args, **kwargs):
            return SimpleNamespace(store_id=pin.store_id, model_id=pin.model_id, model_checksum=pin.model_checksum)

        async with PinnedMigrationPermissionReader(
            OpenFGAConf(), catalog, discovery=discover, client_factory=lambda **kwargs: client
        ) as reader:
            yield reader

    return SimpleNamespace(
        store=store,
        objects=objects,
        requests=requests,
        reader_factory=reader_factory,
        inputs=inputs,
        initial_objects=frozenset(objects),
    )


class Physical:
    def __init__(self, mode=None):
        self.calls = []
        self.mode = mode

    async def aiter_facts(self, *, resource_requests, object_requests):
        assert type(resource_requests) is tuple and type(object_requests) is tuple
        assert len(resource_requests) <= 199 and len(object_requests) <= 199
        self.calls.append((resource_requests, object_requests))
        for row in resource_requests:
            value = row.data
            fact = record_from_values(
                "physical_index",
                tenant_id=value["tenant_id"],
                space_id=value["id"],
                index_name=value["index_name"],
                collection_name=value["collection_name"],
                es_exists=True,
                milvus_exists=True,
                es_mapping_digest="a" * 64,
                milvus_schema_digest="a" * 64,
                es_count=0,
                milvus_count=1,
                identifier_compatible=True,
            )
            if self.mode == "wrong_section":
                yield row
            elif self.mode == "missing":
                continue
            else:
                yield fact
            if self.mode == "duplicate":
                yield fact
        for row in object_requests:
            value = row.data
            for field, kind in (
                ("object_name", "original"),
                ("preview_file_object_name", "preview"),
                ("bbox_object_name", "bbox"),
                ("thumbnails", "thumbnail"),
                ("html_snapshot_object_name", "html_snapshot"),
            ):
                if value[field]:
                    yield record_from_values(
                        "physical_object",
                        tenant_id=value["tenant_id"],
                        space_id=value["knowledge_id"],
                        file_id=value["id"],
                        object_kind=kind,
                        object_key=value[field],
                        exists=True,
                        size=5,
                        etag="not-a-content-sha",
                    )


class Queued:
    def __init__(self):
        self.calls = []

    async def aiter_facts(self, *, tenant_ids):
        self.calls.append(tenant_ids)
        yield record_from_values(
            "queued_task",
            tenant_id=101,
            task_kind="legacy_scheduler",
            task_id="saved-job",
            space_id=9000,
            file_id=1,
            document_id=None,
            version_id=None,
            state="queued",
            configuration_digest="a" * 64,
            record_digest="d" * 64,
        )


class EmptyBroker:
    async def aiter_facts(self, *, tenant_ids):
        assert tenant_ids == (1, 101, 202)
        for record in ():
            yield record


def application(module, transport, **changes):
    return module.UnificationInventoryApplication(
        **(
            {
                "artifact_store": transport.store,
                "sharing_reader_factory": transport.reader_factory,
                "physical_reader": Physical(),
                "queued_task_reader": Queued(),
                "broker_reader": EmptyBroker(),
            }
            | changes
        )
    )


async def count_runs(engine):
    async with engine.connect() as connection:
        return (
            await connection.execute(sa.select(sa.func.count()).select_from(KnowledgeUnificationRun.__table__))
        ).scalar_one()


async def test_actual_default_composition_freezes_all_tenants_and_private_baseline_once(module, complete, transport):
    physical, queued = Physical(), Queued()
    app = application(module, transport, physical_reader=physical, queued_task_reader=queued)
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await app.arun(session, **transport.inputs)
        assert result.tenant_ids == (1, 101, 202) and session.in_transaction()
    assert await count_runs(complete.engine) == 3 and queued.calls == [(1, 101, 202)]
    contents = [json.loads(content) for content in transport.objects.values()]
    records = [row for page in contents for row in page["records"]]
    assert all(len(page["records"]) <= 200 for page in contents)
    assert any(row.get("disposition") == "existing_saved_slot" for row in records)
    assert any(row.get("record_type") == "root" and row["root_key"]["source_id"] == "zero-version" for row in records)
    assert any(row.get("record_type") == "fga_tuple" and row["relation"] == "use" for row in records)
    assert sum(request.url.path.endswith("/read") for request in transport.requests) == 1
    assert sum(request.url.path.endswith("/streamed-list-objects") for request in transport.requests) == 2
    assert not any(
        b"private-" in content or b"not artifact" in content or b"questions" in content
        for content in transport.objects.values()
    )
    assert result.baseline_ref != result.plan_ref
    plan = json.loads(transport.objects[result.plan_ref["object_key"]])
    assert plan["records"][1]["baseline_ref"] == result.baseline_ref


@pytest.mark.parametrize("port", ["physical_reader", "queued_task_reader", "broker_reader", "sharing_reader_factory"])
async def test_missing_required_real_port_fails_closed_without_run_writes(module, complete, transport, port):
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await application(module, transport, **{port: None}).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


@pytest.mark.parametrize("mode", ["wrong_section", "missing", "duplicate"])
async def test_wrong_or_incomplete_physical_record_cannot_prove_section_coverage(module, complete, transport, mode):
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport, physical_reader=Physical(mode)).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


async def test_late_tenant_failure_keeps_all_artifacts_unbound_and_all_runs_absent(module, complete, transport):
    await complete.insert(resources.Knowledge, [resources.resource(9900, 202, type=99)])
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport).arun(session, **transport.inputs)
    assert transport.objects and await count_runs(complete.engine) == 0


async def test_replay_reads_original_manifest_only_and_does_not_reclassify_or_call_ports(module, complete, transport):
    async with AsyncSession(complete.engine) as session, session.begin():
        result = await application(module, transport).arun(session, **transport.inputs)
    transport.requests.clear()
    async with complete.engine.begin() as connection:
        await connection.execute(sa.delete(raw.LLMModel))
    async with AsyncSession(complete.engine) as session, session.begin():
        assert (
            await application(
                module, transport, physical_reader=None, queued_task_reader=None, sharing_reader_factory=None
            ).arun(session, **transport.inputs)
            == result
        )
    assert transport.requests == []
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport).arun(
                session, **(transport.inputs | {"backup_ref": transport.inputs["backup_ref"] | {"sha256": "f" * 64}})
            )


async def test_pending_business_and_external_rollback_never_escape_m2_transaction(module, complete, transport):
    async with AsyncSession(complete.engine) as session, session.begin():
        session.add(raw.flow("caller-pending"))
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport).arun(session, **transport.inputs)
        assert session.new and frozenset(transport.objects) == transport.initial_objects
        await session.rollback()
    async with AsyncSession(complete.engine) as session:
        await session.begin()
        await application(module, transport).arun(session, **transport.inputs)
        await session.rollback()
    assert await count_runs(complete.engine) == 0


async def test_uploaded_content_readback_corruption_blocks_freeze(module, complete, transport):
    async def corrupted(**kwargs):
        return b"changed"

    transport.store.storage.get_object = corrupted
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await application(module, transport).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


async def test_unreadable_material_manifest_blocks_before_formal_inventory(module, complete, transport):
    del transport.objects[transport.inputs["backup_ref"]["object_key"]]
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            await application(module, transport).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


async def test_schema_material_cannot_be_used_as_backup_evidence(module, complete, transport):
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport).arun(
                session, **(transport.inputs | {"backup_ref": transport.inputs["schema_ref"]})
            )
    assert await count_runs(complete.engine) == 0


async def test_global_orphan_keeps_original_claim_without_source_or_tenant_reassignment(module, complete, transport):
    class WithOrphan(Queued):
        async def aiter_facts(self, *, tenant_ids):
            async for item in super().aiter_facts(tenant_ids=tenant_ids):
                yield item
            yield record_from_values(
                "queued_task_orphan",
                task_kind="scheduler_queue",
                task_id="old:occurrence-1",
                space_id=None,
                file_id=999,
                document_id=None,
                version_id=None,
                payload_tenant_id=202,
                state="queued",
                reason="file_missing",
                configuration_digest="a" * 64,
                record_digest="d" * 64,
            )

    async with AsyncSession(complete.engine) as session, session.begin():
        await application(module, transport, queued_task_reader=WithOrphan()).arun(session, **transport.inputs)
    pages = [json.loads(content) for content in transport.objects.values()]
    orphan_page = next(
        page for page in pages if any(row.get("record_type") == "queued_task_orphan" for row in page["records"])
    )
    assert orphan_page["records"][0]["scope"] == "global" and orphan_page["records"][0]["tenant_id"] is None
    assert "tenant_id" not in orphan_page["records"][1] and orphan_page["records"][1]["payload_tenant_id"] == 202


async def test_actual_401_resource_source_inventory_reuses_directories_and_bounded_pages(module, complete, transport):
    await complete.insert(resources.Knowledge, [resources.resource(ident, model=None) for ident in range(10000, 10401)])
    physical = Physical()
    complete.queries.clear()
    async with AsyncSession(complete.engine) as session, session.begin():
        await application(module, transport, physical_reader=physical).arun(session, **transport.inputs)
    assert sum(len(rows) for rows, _ in physical.calls) == 402
    assert sum("FROM knowledge " in sql for sql, _ in complete.queries) <= 30
    assert sum("FROM llm_model" in sql for sql, _ in complete.queries) <= 8
    assert sum(request.url.path.endswith("/streamed-list-objects") for request in transport.requests) == 2
    source_pages = [
        json.loads(content) for content in transport.objects.values() if json.loads(content)["kind"] == "sources"
    ]
    assert len(source_pages) >= 5 and all(len(page["records"]) <= 200 for page in source_pages)


async def test_required_reader_cannot_smuggle_business_pending_into_ledger_flush(module, complete, transport):
    async with AsyncSession(complete.engine) as session, session.begin():

        class Dirty(Queued):
            async def aiter_facts(self, *, tenant_ids):
                async for item in super().aiter_facts(tenant_ids=tenant_ids):
                    yield item
                session.add(raw.flow("unrelated-pending"))

        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport, queued_task_reader=Dirty()).arun(session, **transport.inputs)
        assert session.new
        await session.rollback()
    assert await count_runs(complete.engine) == 0


async def test_actual_reader_must_be_bound_to_the_same_sql_catalog_pin(module, complete, transport):
    original = transport.reader_factory

    @asynccontextmanager
    async def different(catalog):
        changed = replace(catalog, authorization=replace(catalog.authorization, model_id="other-model"))
        async with original(changed) as reader:
            yield reader

    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport, sharing_reader_factory=different).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


@pytest.mark.parametrize("compatibility", [False, 0, "false"])
async def test_incompatible_or_malformed_physical_identifiers_cannot_freeze(module, complete, transport, compatibility):
    class Incompatible(Physical):
        async def aiter_facts(self, **kwargs):
            async for fact in super().aiter_facts(**kwargs):
                if fact.record_type == "physical_index":
                    yield InventoryRecord(
                        "physical_index",
                        json.dumps(
                            fact.data | {"identifier_compatible": compatibility}, sort_keys=True, separators=(",", ":")
                        ),
                    )
                else:
                    yield fact

    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport, physical_reader=Incompatible()).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


@pytest.mark.parametrize("absent", [True, False])
async def test_compatible_absent_empty_or_different_native_counts_do_not_gain_new_gate(
    module, complete, transport, absent
):
    class Compatible(Physical):
        async def aiter_facts(self, **kwargs):
            async for fact in super().aiter_facts(**kwargs):
                if fact.record_type == "physical_index":
                    value = fact.data | {
                        "es_exists": not absent,
                        "milvus_exists": not absent,
                        "es_count": None if absent else 0,
                        "milvus_count": None if absent else 1,
                        "es_mapping_digest": None if absent else "a" * 64,
                        "milvus_schema_digest": None if absent else "b" * 64,
                        "identifier_compatible": True,
                    }
                    yield record_from_values("physical_index", **value)
                else:
                    yield fact

    async with AsyncSession(complete.engine) as session, session.begin():
        result = await application(module, transport, physical_reader=Compatible()).arun(session, **transport.inputs)
    assert result.tenant_ids == (1, 101, 202) and await count_runs(complete.engine) == 3


async def test_full_m2_refuses_final_creation_collision_without_writing_run(module, complete, transport):
    await complete.insert(
        resources.Knowledge,
        [
            resources.resource(9100, creation_request_id="collision"),
            resources.resource(9101, type=3, creation_request_id="collision"),
        ],
    )
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError):
            await application(module, transport).arun(session, **transport.inputs)
    assert await count_runs(complete.engine) == 0


async def test_full_m2_frozen_v1_commands_use_one_run_timestamp_across_tenants(
    module, complete, transport, monkeypatch
):
    planned = datetime(2026, 11, 7, 3, 4, 5)
    calls = []

    def clock():
        calls.append(True)
        return planned

    monkeypatch.setattr(module, "unification_now", clock, raising=False)
    await complete.insert(resources.Knowledge, [resources.resource(1000, 1, model=None)])
    await complete.insert(resources.KnowledgeFile, [resources.file(2, 1, knowledge_id=1000)])
    async with AsyncSession(complete.engine) as session, session.begin():
        await application(module, transport).arun(session, **transport.inputs)
    commands = [
        row
        for content in transport.objects.values()
        for row in json.loads(content)["records"]
        if row.get("record_type") == "initialize_v1"
    ]
    assert {row["tenant_id"] for row in commands} == {1, 101}
    assert {row["planned_at"] for row in commands} == {planned.isoformat()} and calls == [True]


async def test_full_m2_keeps_original_default_sources_and_freezes_safe_after_commands(module, complete, transport):
    value = '{"models":[{"id":"11"}],"task_model":{"id":"11"},"private":"never export"}'
    await complete.insert(
        raw.TenantSystemModelConfig, [{"id": 701, "tenant_id": 101, "key": "linsight_llm", "value": value}]
    )
    complete.queries.clear()
    async with AsyncSession(complete.engine) as session, session.begin():
        await application(module, transport).arun(session, **transport.inputs)
    pages = [json.loads(content) for content in transport.objects.values()]
    command = next(row for page in pages for row in page["records"] if row.get("record_type") == "default_conversion")
    assert command["selected_linsight_id"] == "11" and command["selected_chat_id"] == "11"
    assert any(
        row.get("record_type") == "source" and row["source_key"]["source_type"] == "model_default"
        for page in pages
        for row in page["records"]
    )
    assert all(b"never export" not in content for content in transport.objects.values())
    # Each tenant: one original NameCatalog projection, one preflight own row
    # projection and one original source projection; none is repeated per slot.
    assert sum("FROM tenant_system_model_config" in sql for sql, _ in complete.queries) == 9
    async with complete.engine.connect() as connection:
        assert (
            await connection.execute(
                sa.select(raw.TenantSystemModelConfig.value).where(raw.TenantSystemModelConfig.id == 701)
            )
        ).scalar_one() == value


@pytest.mark.parametrize("business_id", ["09000", "999999"])
async def test_actual_m2_refuses_raw_space_alias_or_orphan_before_any_artifact_freeze(
    module, complete, transport, business_id
):
    await complete.insert(
        SpaceChannelMember,
        [
            {
                "id": 71,
                "business_id": business_id,
                "business_type": "SPACE",
                "user_id": 7,
                "user_role": "ADMIN",
                "status": "REJECTED",
                "membership_source": "original-source",
            }
        ],
    )
    before = dict(transport.objects)
    async with AsyncSession(complete.engine) as session, session.begin():
        with pytest.raises(KnowledgeOperationPlanConflictError) as error:
            await application(module, transport).arun(session, **transport.inputs)
        assert "unification_space_membership_global" in error.value.kwargs["reason"]
    assert transport.objects == before and not transport.requests
