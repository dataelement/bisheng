"""Retain original old indexes without certifying incompatible identifiers."""

from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.knowledge.application.unification_conversion import UnificationSQLConversionApplication
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page, record_from_values
from bisheng.knowledge.application.unification_physical_retention import (
    PhysicalRetentionInventoryVerifier,
    retention_record,
)
from test.knowledge_unification import test_migration_inventory_application as original
from test.knowledge_unification import test_migration_resource_repository as resources

resource_native = original.resource_native
native = original.native
complete = original.complete
transport = original.transport
module = original.module


def resource():
    return record_from_values(
        "resource",
        tenant_id=101,
        id=9000,
        type=0,
        user_id=7,
        state=1,
        model="11",
        index_name="original-text",
        collection_name="original-vector",
        creation_request_id=None,
        creation_payload_hash=None,
        old_business_digest="1" * 64,
        neutral_digest="2" * 64,
    )


def physical():
    return record_from_values(
        "physical_index",
        tenant_id=101,
        space_id=9000,
        index_name="original-text",
        collection_name="original-vector",
        es_exists=True,
        milvus_exists=True,
        es_mapping_digest="a" * 64,
        milvus_schema_digest="b" * 64,
        es_count=17,
        milvus_count=23,
        identifier_compatible=False,
    )


def verify(root, fact, proof=None, extra=()):
    validator = PhysicalRetentionInventoryVerifier()
    for kind, section, record in (
        ("baseline", "resources", root),
        ("baseline", "physical", fact),
        *((("plan", "physical", proof),) if proof is not None else ()),
        *extra,
    ):
        validator.observe(kind=kind, section=section, tenant_id=101, record=record)
    validator.finish()


def test_opaque_index_is_preserved_with_its_real_false_schema_flag_and_counts():
    root, fact = resource(), physical()
    proof = retention_record(resource=root.data, physical=fact.data, managed_file_count=0)
    verify(root, fact, proof)
    assert fact.data["identifier_compatible"] is False
    assert fact.data["es_count"] == 17 and fact.data["milvus_count"] == 23
    assert proof.data["managed_file_count"] == 0
    assert root.data["collection_name"] == "original-vector"


@pytest.mark.parametrize("count", [1, 2, -1, False, None])
def test_nonempty_or_unproven_sql_file_set_still_blocks(count):
    with pytest.raises(KnowledgeOperationPlanConflictError):
        retention_record(resource=resource().data, physical=physical().data, managed_file_count=count)


@pytest.mark.parametrize("change", ["missing_proof", "binding", "schema", "count", "scope", "false_empty", "duplicate"])
def test_frozen_proof_is_bound_to_complete_original_resource_and_physical_facts(change):
    root, fact = resource(), physical()
    proof = retention_record(resource=root.data, physical=fact.data, managed_file_count=0)
    extra = ()
    if change == "missing_proof":
        proof = None
    elif change == "binding":
        fact = record_from_values("physical_index", **(fact.data | {"collection_name": "different"}))
    elif change == "schema":
        fact = record_from_values("physical_index", **(fact.data | {"milvus_schema_digest": "f" * 64}))
    elif change == "count":
        fact = record_from_values("physical_index", **(fact.data | {"milvus_count": 24}))
    elif change == "scope":
        proof = record_from_values("physical_index_retention", **(proof.data | {"space_id": 9001}))
    elif change == "false_empty":
        extra = (
            (
                "baseline",
                "resources",
                record_from_values(
                    "file",
                    id=1,
                    tenant_id=101,
                    knowledge_id=9000,
                    file_type=0,
                    level=0,
                    file_level_path=None,
                    status=None,
                    file_source=None,
                    file_size=None,
                    object_name=None,
                    preview_file_object_name=None,
                    bbox_object_name=None,
                    thumbnails=None,
                    html_snapshot_object_name=None,
                    row_digest="a" * 64,
                    split_rule_digest="a" * 64,
                    user_metadata_digest="a" * 64,
                ),
            ),
        )
    else:
        extra = (("plan", "physical", proof),)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        verify(root, fact, proof, extra)


class LegacyPhysical(original.Physical):
    async def aiter_facts(self, **kwargs):
        async for fact in super().aiter_facts(**kwargs):
            if fact.record_type == "physical_index":
                yield record_from_values(
                    "physical_index",
                    **(
                        fact.data
                        | {
                            "identifier_compatible": False,
                            "es_count": 17,
                            "milvus_count": 23,
                        }
                    ),
                )
            else:
                yield fact


async def freeze_empty(module, complete, transport):
    async with complete.engine.begin() as connection:
        await connection.execute(sa.delete(resources.KnowledgeFile))
    app = original.application(module, transport, physical_reader=LegacyPhysical())
    async with AsyncSession(complete.engine) as session, session.begin():
        frozen = await app.arun(session, **transport.inputs)
    return app, frozen


async def test_native_m2_and_frozen_replay_keep_bindings_and_never_replace_schema_fact(module, complete, transport):
    app, frozen = await freeze_empty(module, complete, transport)
    records = []
    async for page in app.aiter_frozen_pages(
        frozen,
        environment=transport.inputs["environment"],
        backup_ref=transport.inputs["backup_ref"],
        schema_ref=transport.inputs["schema_ref"],
    ):
        if page.section == "physical":
            decoded = decode_inventory_page(
                page.content,
                run_id=frozen.run_id,
                section=page.section,
                scope=page.scope,
                tenant_id=page.tenant_id,
                page_index=page.page_index,
                kind=page.kind,
            )
            records.extend((page.kind, row) for row in decoded.records)
    old = [row.data for kind, row in records if row.record_type == "physical_index"]
    proof = [row.data for kind, row in records if row.record_type == "physical_index_retention"]
    assert len(old) == len(proof) == 1
    assert old[0]["identifier_compatible"] is False and old[0]["milvus_count"] == 23
    assert proof[0]["managed_file_count"] == 0
    async with complete.engine.connect() as connection:
        row = (
            (await connection.execute(sa.select(resources.Knowledge.__table__).where(resources.Knowledge.id == 9000)))
            .mappings()
            .one()
        )
    assert row["index_name"] == "original-text" and row["collection_name"] == "original-vector"
    assert row["type"] == 0
    assert all(not request.url.path.endswith(("/write", "/authorization-models")) for request in transport.requests)


@pytest.mark.parametrize("change", ["new_file", "new_folder", "binding", "foreign_scope"])
async def test_native_retained_binding_guard_rejects_drift_before_sql_conversion(module, complete, transport, change):
    await freeze_empty(module, complete, transport)
    async with complete.engine.begin() as connection:
        if change in {"new_file", "new_folder"}:
            await connection.execute(
                resources.KnowledgeFile.__table__.insert(),
                resources.file(99, file_type=0 if change == "new_folder" else 1),
            )
        elif change == "binding":
            await connection.execute(
                sa.update(resources.Knowledge.__table__).where(resources.Knowledge.id == 9000).values(index_name="new")
            )
        else:
            await connection.execute(
                sa.update(resources.Knowledge.__table__).where(resources.Knowledge.id == 9000).values(tenant_id=202)
            )

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    application = UnificationSQLConversionApplication(artifact_store=transport.store, session_factory=sessions)
    with tenant_execution_scope(1):
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await application.arun(**transport.inputs)
    assert caught.value.kwargs["reason"] in {
        "unification_resource_retained_index_live_state_changed",
        "unification_resource_file_count_resource_scope_changed",
    }
    async with complete.engine.connect() as connection:
        phases = set((await connection.execute(sa.select(original.KnowledgeUnificationRun.phase))).scalars())
        kind = (
            await connection.execute(sa.select(resources.Knowledge.type).where(resources.Knowledge.id == 9000))
        ).scalar_one()
    assert phases == {"baseline_frozen"} and kind == 0


async def test_original_sql_conversion_and_resume_preserve_existing_index_bindings(module, complete, transport):
    await freeze_empty(module, complete, transport)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(complete.engine, expire_on_commit=False) as session:
            yield session

    application = UnificationSQLConversionApplication(artifact_store=transport.store, session_factory=sessions)
    with tenant_execution_scope(1):
        first = await application.arun(**transport.inputs)
        replay = await application.arun(**transport.inputs)
    assert first.sql_complete and replay.sql_complete
    async with complete.engine.connect() as connection:
        row = (
            (await connection.execute(sa.select(resources.Knowledge.__table__).where(resources.Knowledge.id == 9000)))
            .mappings()
            .one()
        )
    assert row["type"] == 3
    assert (row["index_name"], row["collection_name"]) == ("original-text", "original-vector")
