"""Historical preparation crosses native SQL, permission journals and replay."""

import json
import stat
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_unification_run import KnowledgeUnificationRun
from bisheng.permission.application import control_state, sql_runtime
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ResourcePermissionMode,
)
from bisheng.permission.domain.repositories.projection_repository import ProjectionRepository
from bisheng.permission.domain.services.projection_service import ProjectionService
from scripts import prepare_f118_history as module
from test.knowledge_unification import test_migration_preflight as native_preflight
from test.knowledge_unification import test_migration_resource_repository as resources
from test.knowledge_unification import test_perm_migration_snapshot as permission
from test.knowledge_unification.test_model_share_projection_deferred import Marker, Transport

resource_native, native = native_preflight.resource_native, native_preflight.native


class FGA(Transport):
    def __init__(self):
        super().__init__()
        self.all_deletes = []
        self.scans = 0

    async def read_tuples(self, *, object, consistency, relation=None):
        assert consistency == "HIGHER_CONSISTENCY"
        return [
            {"user": user, "relation": rel, "object": obj}
            for user, rel, obj in sorted(self.present)
            if obj == object and (relation is None or relation == rel)
        ]

    async def iter_tuples(self, *, consistency):
        assert consistency == "HIGHER_CONSISTENCY"
        self.scans += 1
        for user, relation, obj in sorted(self.present):
            yield {"user": user, "relation": relation, "object": obj}

    async def write_atomic(self, *, writes, deletes):
        assert not writes
        self.all_deletes.extend(delta.key for delta in deletes)
        return await super().write_atomic(writes=writes, deletes=deletes)


@pytest.fixture
async def history(native, monkeypatch):
    metadata = sa.MetaData()
    for model in (KnowledgeUnificationRun, PermissionProjectionTuple):
        cloned = model.__table__.to_metadata(metadata)
        if model is PermissionProjectionTuple:
            cloned.c.id.type = sa.Integer()
    PermissionProjectionOperation.__table__.to_metadata(metadata).c.id.type = sa.Integer()
    async with native.engine.begin() as connection:
        await connection.run_sync(lambda conn: PermissionProjectionOperation.__table__.drop(conn))
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(native.engine, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        await permission.seed_catalog(session)
    await native.insert(Knowledge, [resources.resource(10, model=None)])
    await native.insert(
        KnowledgeFile,
        [
            resources.file(20, knowledge_id=10, file_type=0, file_level_path="", level=0),
            resources.file(30, knowledge_id=10, file_level_path="/20", level=0),
        ],
    )
    await native.insert(
        KnowledgeDocument, [{"id": 100, "tenant_id": 101, "knowledge_id": 10, "file_level_path": "/20", "level": 0}]
    )
    for ident, kind, parent, pid in (
        (20, "folder", "knowledge_library", "10"),
        (30, "knowledge_file", "folder", "20"),
        (999, "knowledge_file", "knowledge_library", "10"),
    ):
        await native.insert(
            ResourcePermissionMode,
            [
                {
                    "id": ident,
                    "tenant_id": 101,
                    "resource_type": kind,
                    "resource_id": str(ident),
                    "mode": "INHERIT",
                    "parent_type": parent,
                    "parent_id": pid,
                    "version": 1,
                    "projection_state": "CURRENT",
                }
            ],
        )
    monkeypatch.setattr(
        module,
        "business_models",
        lambda: {
            "folder": KnowledgeFile,
            "knowledge_file": KnowledgeFile,
            "knowledge_library": Knowledge,
            "knowledge_space": Knowledge,
        },
    )
    monkeypatch.setattr(sql_runtime, "get_async_db_session", sessions)
    monkeypatch.setattr(control_state, "get_async_db_session", sessions)
    async with module.global_session(sessions) as session:
        pin = await module.read_pin(session)
    state = control_state.SqlPermissionControlState()
    monkeypatch.setattr(state, "current_catalog", AsyncMock(return_value=SimpleNamespace(**pin)))
    fga = FGA()
    fga.present.update(
        {
            ("knowledge_library:10", "parent", "folder:20"),
            ("folder:20", "parent", "knowledge_file:30"),
            ("knowledge_library:10", "parent", "knowledge_file:30"),
            ("knowledge_library:10", "parent", "knowledge_file:999"),
            ("user:*", "permission_enabled", "knowledge_file:999"),
            ("service_account:*", "permission_enabled", "knowledge_file:999"),
            ("user:*", "inherit_mode", "knowledge_file:999"),
            ("user:7", "visible", "knowledge_file:999"),
        }
    )
    projections = ProjectionService(
        repository=ProjectionRepository(sessions),
        marker=Marker(),
        scope_guard=sql_runtime.SqlProjectionScopeGuard(),
        fga=fga,
        finalizer=sql_runtime.SqlProjectionFinalizer(),
    )
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(**pin, read_tuples=fga.read_tuples),
        state=state,
        marker=Marker(),
        decision=None,
        projection=projections,
        sources=None,
        owner=None,
        grants=None,
        modes=None,
        explain=None,
    )
    return SimpleNamespace(sessions=sessions, fga=fga, runtime=runtime, db=native)


async def test_preview_repair_and_same_plan_replay_keep_storage_bindings_and_audit(history):
    plan = await module.capture(history.sessions, history.fga)
    assert len(plan["levels"]) == 2 and len(plan["parents"]) == len(plan["purges"]) == 1
    assert history.fga.writes == 0 and history.fga.scans == 1
    before = set(history.fga.present)
    result = await module.apply(
        plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7
    )
    assert result["levels"] == 2 and result["purges"] == 1
    assert set(history.fga.present) < before and len(history.fga.all_deletes) == 6
    async with history.sessions() as session:
        assert (await session.get(KnowledgeFile, 30)).level == (await session.get(KnowledgeDocument, 100)).level == 1
        assert await session.get(ResourcePermissionMode, 999) is None
        root = await session.get(Knowledge, 10)
        assert (root.collection_name, root.index_name) == ("original-vector", "original-text")
        journals = (await session.exec(select(PermissionProjectionOperation))).all()
        assert len(journals) == 3 and all(row.status == "FINALIZED" for row in journals)
        assert (await session.exec(select(PermissionProjectionTuple))).all()
    writes = history.fga.writes
    await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes


async def test_changed_business_directory_blocks_parent_cleanup_before_projection(history):
    plan = await module.capture(history.sessions, history.fga)
    async with history.db.engine.begin() as connection:
        await connection.execute(sa.update(KnowledgeFile).where(KnowledgeFile.id == 30).values(file_level_path=""))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == 0


async def test_reappearing_parent_is_not_silently_certified_by_an_old_finalized_receipt(history):
    plan = await module.capture(history.sessions, history.fga)
    await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    writes = history.fga.writes
    history.fga.present.add(tuple(plan["parents"][0]["deletes"][0]))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes


async def test_reappearing_deleted_resource_relation_does_not_reuse_old_cleanup_as_proof(history):
    plan = await module.capture(history.sessions, history.fga)
    await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    writes = history.fga.writes
    history.fga.present.add(("user:7", "visible", "knowledge_file:999"))
    with pytest.raises(PermissionPublishNotReadyError):
        await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes


async def test_missing_folder_is_reported_without_guessing_or_deleting_file(history):
    async with history.db.engine.begin() as connection:
        await connection.execute(sa.update(KnowledgeFile).where(KnowledgeFile.id == 30).values(file_level_path="/404"))
    plan = await module.capture(history.sessions, history.fga)
    assert any(row == {"table": "knowledgefile", "id": 30, "reason": "invalid_parent_chain"} for row in plan["blocked"])
    assert not plan["parents"] and history.fga.writes == 0
    async with history.sessions() as session:
        assert (await session.get(KnowledgeFile, 30)).level == 0


async def test_active_frozen_run_blocks_preparation_without_fga_scan(history):
    with bypass_tenant_filter():
        async with history.sessions() as session, session.begin():
            session.add(
                KnowledgeUnificationRun(
                    tenant_id=101,
                    run_id="already-frozen",
                    phase="baseline_frozen",
                    baseline_ref={"object_key": "original", "sha256": "a" * 64},
                )
            )
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await module.capture(history.sessions, history.fga)
    assert history.fga.scans == 0


@pytest.mark.parametrize("bad", ["/01", "/1/1", "/1/", "x", "/-1"])
def test_noncanonical_or_cyclic_paths_are_not_automatically_repaired(bad):
    with pytest.raises(ValueError):
        module.folder_path(bad)


def test_backup_is_private_immutable_and_checked_before_replay(tmp_path):
    path, plan = tmp_path / "history.json", {"schema": 1, "selected": [{"id": 1}]}
    digest = module.save_plan(path, plan)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert module.load_plan(path) == plan and digest == module.checksum(plan)
    with pytest.raises(FileExistsError):
        module.save_plan(path, {"schema": 1})
    payload = json.loads(path.read_text())
    payload["plan"]["selected"].append({"id": 2})
    path.write_text(json.dumps(payload))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        module.load_plan(path)


async def test_untracked_incoming_fga_edge_keeps_deleted_resource_mirrors(history):
    history.fga.present.add(("knowledge_file:999", "legacy_relation", "workflow:still-live"))
    plan = await module.capture(history.sessions, history.fga)
    assert not plan["purges"]
    assert any(row["reason"] == "fga_downstream_exists" for row in plan["blocked"])
    assert history.fga.writes == 0


async def test_new_downstream_after_preview_blocks_before_any_write(history):
    plan = await module.capture(history.sessions, history.fga)
    history.fga.present.add(("knowledge_file:999", "legacy_relation", "workflow:still-live"))
    with pytest.raises(KnowledgeOperationPlanConflictError):
        await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == 0


async def test_deleted_permission_tree_is_cleaned_from_leaves_in_one_plan(history):
    await history.db.insert(
        ResourcePermissionMode,
        [
            {
                "id": 888,
                "tenant_id": 101,
                "resource_type": "folder",
                "resource_id": "888",
                "mode": "INHERIT",
                "parent_type": "knowledge_library",
                "parent_id": "10",
                "version": 1,
                "projection_state": "CURRENT",
            }
        ],
    )
    async with history.db.engine.begin() as connection:
        await connection.execute(
            sa.update(ResourcePermissionMode)
            .where(ResourcePermissionMode.id == 999)
            .values(parent_type="folder", parent_id="888")
        )
    history.fga.present.discard(("knowledge_library:10", "parent", "knowledge_file:999"))
    history.fga.present.update(
        {("folder:888", "parent", "knowledge_file:999"), ("knowledge_library:10", "parent", "folder:888")}
    )
    plan = await module.capture(history.sessions, history.fga)
    assert [item["mode"]["id"] for item in plan["purges"]] == [999, 888]
    await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    async with history.sessions() as session:
        assert await session.get(ResourcePermissionMode, 888) is None
        assert await session.get(ResourcePermissionMode, 999) is None


async def test_completed_projection_can_resume_sql_purge_after_database_failure(history, monkeypatch):
    from bisheng.permission.domain.repositories.deleted_resource_repository import DeletedResourceRepository

    plan = await module.capture(history.sessions, history.fga)
    original = DeletedResourceRepository.purge
    failures = []

    async def fail_once(self, *args):
        if not failures:
            failures.append(True)
            raise RuntimeError("SQL unavailable after FGA commit")
        await original(self, *args)

    monkeypatch.setattr(DeletedResourceRepository, "purge", fail_once)
    with pytest.raises(RuntimeError, match="SQL unavailable"):
        await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    writes = history.fga.writes
    await module.apply(plan, sessions=history.sessions, client=history.fga, runtime=history.runtime, operator_id=7)
    assert history.fga.writes == writes
    async with history.sessions() as session:
        assert await session.get(ResourcePermissionMode, 999) is None
