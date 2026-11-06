"""M2 preflight consumes real native facts, not an authorization matrix."""

import importlib
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.database import tenant_filter
from bisheng.database.models.role import Role
from bisheng.database.models.tenant import UserTenant
from bisheng.database.models.user_role import UserRole
from bisheng.knowledge.application.unification_sources import ReferenceInventoryRecord
from bisheng.knowledge.domain.repositories.unification_target_repository import KnowledgeMigrationTargetRepository
from bisheng.permission.domain.repositories.f118_migration_snapshot_repository import (
    PermissionMigrationSnapshotRepository,
)
from bisheng.permission.migration import f118_plan
from bisheng.resource_reference.application.contracts import SourceKey, TargetKey
from bisheng.user.domain.models.user import User
from test.knowledge_unification import test_migration_resource_repository as original
from test.knowledge_unification import test_perm_migration as pure
from test.knowledge_unification import test_perm_migration_snapshot as snapshot

resource_native = original.native


@pytest.fixture
def module():
    return importlib.import_module("bisheng.knowledge.application.unification_preflight")


@pytest.fixture
async def native(resource_native, monkeypatch):
    models = (User, UserTenant, Role, UserRole, *snapshot.TABLES)
    names = {model.__tablename__ for model in models if "tenant_id" in model.__table__.c} - {"user_tenant"}
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | names)
    previous = tenant_filter._discover_tenant_aware_tables()
    monkeypatch.setattr(tenant_filter, "_discover_tenant_aware_tables", lambda: previous | names)
    metadata = sa.MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        if "tenant_id" in table.c:
            table.c.tenant_id.nullable = True
        if model is UserRole:
            table.c.id.autoincrement = False
    async with resource_native.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            User.__table__.insert(), [{"user_id": 7, "user_name": "historical", "password": "-", "delete": 1}]
        )
    return resource_native


def catalog_plan():
    return pure.catalog_plan(f118_plan)


async def collect(module, session):
    return [item async for item in module.UnificationPreflight().aiter_tenant(session, catalog_plan=catalog_plan())]


async def test_real_original_type_retirement_creator_and_quota_facts_preserve_history(module, native):
    await native.insert(
        original.Knowledge,
        [
            original.resource(9000, type=0),
            original.resource(9001, type=1),
            original.resource(9002, type=2),
            original.resource(9003, type=3),
        ],
    )
    await native.insert(
        original.KnowledgeFile,
        [original.file(1, file_source="channel", file_size=17), original.file(2, file_source="upload", file_size=99)],
    )
    async with AsyncSession(native.engine) as session, session.begin():
        items = await collect(module, session)
        plans = [
            item.data for section, item in items if section == "conversion" and item.record_type == "conversion_plan"
        ]
        assert [(item["resource_id"], item["target_type"], item["action"]) for item in plans] == [
            (9000, 3, "convert_type0"),
            (9001, 1, "inventory_only"),
            (9002, 2, "inventory_only"),
            (9003, 3, "retain_space"),
        ]
        creators = [item.data for section, item in items if item.record_type == "creator"]
        assert creators == [{"user_id": 7, "exists": True, "delete": 1}]
        usage = next(item.data for _, item in items if item.record_type == "quota_usage")
        assert usage["stored_bytes"] == 17 and usage["personal_space_count"] == 1
        assert not session.new and not session.dirty


@pytest.mark.parametrize("change", [{"type": 99}, {"user_id": 888}])
async def test_unknown_type_or_globally_absent_creator_blocks(module, native, change):
    await native.insert(original.Knowledge, [original.resource(9000, **change)])
    async with (
        AsyncSession(native.engine) as session,
        session.begin(),
        pytest.raises(KnowledgeOperationPlanConflictError),
    ):
        await collect(module, session)


async def test_legacy_overdeep_chain_and_null_empty_paths_are_preserved_not_new_write_capped(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    folders = [
        original.file(
            i, file_type=0, level=i - 1, file_level_path="" if i == 1 else "/" + "/".join(map(str, range(1, i)))
        )
        for i in range(1, 12)
    ]
    await native.insert(original.KnowledgeFile, [*folders, original.file(20, file_level_path=None)])
    async with AsyncSession(native.engine) as session, session.begin():
        records = await collect(module, session)
        deep = next(item.data for _, item in records if item.record_type == "file" and item.data["id"] == 11)
        assert deep["level"] == 10 and deep["file_level_path"].endswith("/10")
    ancestor_reads = [query for query in native.queries if "knowledgefile.id IN" in query[0]]
    assert len(ancestor_reads) == 1


@pytest.mark.parametrize(
    "path,level,parent_type,parent_tenant",
    [("/1/1", 2, 0, 101), ("/1", 1, 1, 101), ("/1", 1, 0, 202), ("/missing", 1, 0, 101), ("/1", 2, 0, 101)],
)
async def test_real_ancestor_bad_chains_are_explicitly_rejected(
    module, native, path, level, parent_type, parent_tenant
):
    await native.insert(original.Knowledge, [original.resource(9000), original.resource(8000, 202)])
    await native.insert(
        original.KnowledgeFile,
        [
            original.file(1, parent_tenant, knowledge_id=9000 if parent_tenant == 101 else 8000, file_type=parent_type),
            original.file(2, file_level_path=path, level=level),
        ],
    )
    async with (
        AsyncSession(native.engine) as session,
        session.begin(),
        pytest.raises(KnowledgeOperationPlanConflictError),
    ):
        await collect(module, session)


async def test_doc_version_primary_chain_and_unregistered_file_plan_are_distinct(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    await native.insert(original.KnowledgeFile, [original.file(1), original.file(2)])
    await native.insert(original.KnowledgeDocument, [original.data("documents", 1) | {"primary_version_id": 1}])
    await native.insert(original.KnowledgeDocumentVersion, [original.data("versions", 1)])
    async with AsyncSession(native.engine) as session, session.begin():
        records = await collect(module, session)
        assert [
            item.data["resource_id"]
            for _, item in records
            if item.record_type == "conversion_plan" and item.data["action"] == "register_v1"
        ] == [2]
    async with native.engine.begin() as connection:
        await connection.execute(sa.update(original.KnowledgeDocument).values(primary_version_id=999))
    async with (
        AsyncSession(native.engine) as session,
        session.begin(),
        pytest.raises(KnowledgeOperationPlanConflictError),
    ):
        await collect(module, session)


async def test_native_401_files_use_bounded_pages_and_unique_creator_ancestor_reads(module, native):
    await native.insert(original.Knowledge, [original.resource(9000)])
    await native.insert(
        original.KnowledgeFile,
        [original.file(1, file_type=0)] + [original.file(i, file_level_path="/1", level=1) for i in range(2, 403)],
    )
    native.queries.clear()
    async with AsyncSession(native.engine) as session, session.begin():
        records = await collect(module, session)
    assert sum(item.record_type == "file" for _, item in records) == 402
    assert len(native.queries) <= 35
    assert sum("FROM user" in sql for sql, _ in native.queries) == 1
    assert sum("knowledgefile.id IN" in sql for sql, _ in native.queries) == 1


async def test_actual_permission_snapshot_keeps_inactive_protected_and_compiles_once(module, native):
    async with AsyncSession(native.engine) as session, session.begin():
        await snapshot.seed_catalog(session)
        original_permission = await snapshot.seed_rows(session)
        records = await collect(module, session)
        assert sum(item.record_type == "assignee" for _, item in records) == len(original_permission.assignees)
        assert any(item.data["protected"] for _, item in records if item.record_type == "assignee")
        assert any(item.data["state"] == "INACTIVE" for _, item in records if item.record_type == "assignee")
        assert sum(item.record_type == "permission_plan" for _, item in records) == 1


@pytest.mark.parametrize("bad", ["null_tenant", "absent_tenant", "bad_grant_parent"])
async def test_global_permission_integrity_never_hides_orphan_rows(native, bad):
    table = snapshot.PermissionGrantAssignee if bad == "bad_grant_parent" else snapshot.ResourcePermissionMode
    async with AsyncSession(native.engine) as session, session.begin():
        await snapshot.seed_rows(session)
    async with native.engine.begin() as connection:
        await connection.execute(
            sa.update(table).values(
                **(
                    {"grant_id": 999}
                    if bad == "bad_grant_parent"
                    else {"tenant_id": None if bad == "null_tenant" else 999}
                )
            )
        )
    async with AsyncSession(native.engine) as session, session.begin(), pytest.raises(PermissionMigrationBlockedError):
        await PermissionMigrationSnapshotRepository().avalidate_global_integrity(session)


async def test_explicit_missing_is_not_foreign_retired_or_existing_offline_and_no_proof_is_created(module, native):
    await native.insert(
        original.Knowledge, [original.resource(9000), original.resource(8000, 202), original.resource(7000, type=2)]
    )
    source = SourceKey(101, "workflow_version", "flow", "v1")
    keys = tuple(TargetKey("knowledge_space", str(i)) for i in (9000, 9999, 8000, 7000))
    async with AsyncSession(native.engine) as session, session.begin():
        facts = await KnowledgeMigrationTargetRepository().ainspect(session, source_key=source, targets=keys)
    rows = [
        ReferenceInventoryRecord(source, f"slot-{i}", key, "explicit_id", fact)
        for i, (key, fact) in enumerate(zip(keys, facts, strict=True))
    ]
    assert module.source_decision(rows[0], tenant_id=101).data["disposition"] == "existing_saved_slot"
    assert module.source_decision(rows[1], tenant_id=101).data["disposition"] == "initial_missing"
    for row in rows[2:]:
        with pytest.raises(KnowledgeOperationPlanConflictError):
            module.source_decision(row, tenant_id=101)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.source_decision(replace(rows[1], origin="resolved_name"), tenant_id=101)
