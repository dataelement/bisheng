"""库内去重的保留规则及删除边界。"""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts import dedupe_knowledge_space_documents as mod


def file_row(file_id, *, space_id=1, **kwargs):
    return dict(
        id=file_id,
        knowledge_id=space_id,
        tenant_id=1,
        file_type=1,
        file_name=f"{file_id}.pdf",
        md5="a" * 32,
        status=2,
        create_time=datetime(2026, 9, 1),
        **kwargs,
    )


def inventory(files, *, documents=(), versions=(), approvals=()):
    return mod.Inventory(
        spaces=tuple({"id": i, "tenant_id": 1, "name": f"库{i}", "type": 3, "state": 1} for i in (1, 2)),
        scopes=tuple({"space_id": i, "level": "personal"} for i in (1, 2)),
        files=tuple(files),
        documents=tuple(documents),
        versions=tuple(versions),
        approvals=tuple(approvals),
        tenant_id=1,
    )


def test_within_space_across_folders_keep_newest_then_id():
    rows = [file_row(1, file_level_path="/100"), file_row(2, file_level_path="/200"), file_row(3, space_id=2)]
    rows[0]["create_time"] = datetime(2026, 9, 2)
    plan = mod.build_plan(inventory(rows))
    assert [(g.keep.entry_id, [x.entry_id for x in g.remove]) for g in plan.groups] == [(1, [2])]
    rows[0]["create_time"] = rows[1]["create_time"]
    assert mod.build_plan(inventory(rows)).groups[0].keep.entry_id == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"md5": None},
        {"md5": " "},
        {"status": 1},
        {"status": 3},
        {"deleted_at": datetime(2026, 9, 1)},
        {"entry_status": "preparing"},
        {"create_time": None},
        {"tenant_id": 2},
    ],
)
def test_ineligible_document_is_reported_and_never_deleted(changes):
    row = file_row(2)
    row.update(changes)
    plan = mod.build_plan(inventory([file_row(1), row]))
    assert not plan.groups
    assert any(s["entry_id"] == 2 for s in plan.skipped)


def test_only_primary_versions_compared_and_history_attached_to_deletion():
    rows = [file_row(1), file_row(2), file_row(3)]
    rows[0]["create_time"] = datetime(2026, 9, 8)
    docs = [{"id": 10, "tenant_id": 1, "knowledge_id": 1, "primary_version_id": 22}]
    versions = [
        {"id": 21, "document_id": 10, "knowledge_file_id": 1, "is_primary": False, "version_no": 1},
        {"id": 22, "document_id": 10, "knowledge_file_id": 2, "is_primary": True, "version_no": 2},
    ]
    plan = mod.build_plan(inventory(rows, documents=docs, versions=versions))
    assert plan.groups[0].keep.entry_id == 3
    assert plan.groups[0].remove[0].history_file_ids == (1, 2)


def test_publish_uses_canonical_primary_md5_and_approval_locks_document():
    rows = [
        file_row(1),
        file_row(2, reference_document_id=10, entry_type="share", entry_status="active", projection_status="ready"),
    ]
    rows[1]["md5"] = None
    docs = [{"id": 10, "tenant_id": 1, "knowledge_id": 1, "primary_version_id": 21, "lifecycle_status": "active"}]
    versions = [{"id": 21, "document_id": 10, "knowledge_file_id": 1, "is_primary": True, "version_no": 1}]
    inv = inventory(rows, documents=docs, versions=versions)
    candidates = mod.build_plan(inv).candidates
    assert candidates[2].md5 == "a" * 32
    for resource in ("10:8", "100:8"):
        approval = {
            "id": 99,
            "tenant_id": 1,
            "status": "pending",
            "scenario_code": "knowledge_space_file_publish_request",
            "business_resource_id": resource,
        }
        locked = mod.build_plan(replace(inv, approvals=(approval,)))
        assert (2 not in locked.candidates) == (resource == "10:8")


class FakeBackend:
    def __init__(self, inv):
        self.inv = inv
        self.calls = []
        self.before_delete = None
        self.fail = False

    async def scan(self, space_ids=None):
        return mod.build_plan(self.inv)

    async def delete(self, target):
        self.calls.append(target.entry_id)
        if self.fail:
            raise RuntimeError("delete failed")
        rows = tuple(
            dict(r, deleted_at=datetime(2026, 9, 8)) if r["id"] == target.entry_id else r for r in self.inv.files
        )
        self.inv = replace(self.inv, files=rows)
        return "soft_deleted"


async def test_dry_run_has_no_writes_and_apply_is_idempotent(tmp_path):
    backend = FakeBackend(inventory([file_row(1), file_row(2), file_row(3)]))
    events = []
    assert await mod.execute(backend, apply=False, emit=events.append) == 0
    assert backend.calls == []
    assert await mod.execute(backend, apply=True, emit=events.append) == 0
    assert backend.calls == [2, 1]
    assert await mod.execute(backend, apply=True, emit=events.append) == 0
    assert backend.calls == [2, 1]


async def test_changed_keeper_and_delete_failure_stop_writes():
    backend = FakeBackend(inventory([file_row(1), file_row(2), file_row(3)]))
    first = await backend.scan()
    backend.scan = AsyncMock(side_effect=[first, mod.build_plan(inventory([file_row(1), file_row(2)]))])
    events = []
    assert await mod.execute(backend, apply=True, emit=events.append) != 0
    assert backend.calls == []
    backend = FakeBackend(inventory([file_row(1), file_row(2), file_row(3)]))
    backend.fail = True
    assert await mod.execute(backend, apply=True, emit=events.append) != 0
    assert backend.calls == [2]


async def test_report_failure_prevents_delete():
    backend = FakeBackend(inventory([file_row(1), file_row(2)]))

    def fail(event):
        raise OSError("disk full")

    with pytest.raises(OSError):
        await mod.execute(backend, apply=True, emit=fail)
    assert backend.calls == []


def test_cli_apply_needs_no_actor_and_report_never_overwrites(tmp_path):
    assert mod.parse_args([]).apply is False
    assert mod.parse_args(["--apply"]).apply is True
    path = tmp_path / "report.jsonl"
    with mod.Report(path) as report:
        report.emit({"event": "test"})
    with pytest.raises(FileExistsError):
        with mod.Report(path):
            pass


async def test_cascade_cannot_delete_selected_keeper():
    rows = [
        file_row(1, reference_document_id=10, entry_type="manager", entry_status="active"),
        file_row(2, reference_document_id=10, entry_type="share", entry_status="active", projection_status="ready"),
    ]
    docs = [{"id": 10, "tenant_id": 1, "knowledge_id": 1, "primary_version_id": 21, "lifecycle_status": "active"}]
    versions = [{"id": 21, "document_id": 10, "knowledge_file_id": 1, "is_primary": True, "version_no": 1}]
    backend = FakeBackend(inventory(rows, documents=docs, versions=versions))
    events = []
    assert await mod.execute(backend, apply=True, emit=events.append) == 6
    assert not backend.calls
    assert events[0]["blocked"][0]["entry_id"] == 1


@pytest.fixture
async def orm_database(monkeypatch):
    """在独立 SQLite 中执行真实模型 SELECT, 不连接项目配置的数据库。"""
    from sqlalchemy import DefaultClause, MetaData, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.approval.domain.models.approval_instance import ApprovalInstance
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

    metadata = MetaData()
    models = [
        Knowledge,
        KnowledgeFile,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeSpaceScope,
        ApprovalInstance,
    ]
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def session_factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", session_factory)
    with bypass_tenant_filter():
        async with session_factory() as session:
            for tenant_id in (1, 2):
                session.add(Knowledge(id=tenant_id, tenant_id=tenant_id, name=f"库{tenant_id}", type=3, state=1))
                session.add(
                    KnowledgeSpaceScope(
                        space_id=tenant_id,
                        tenant_id=tenant_id,
                        level="personal",
                        owner_type="user",
                        owner_id=tenant_id,
                        update_time=datetime(2026, 9, 1),
                    )
                )
                for offset in (1, 2):
                    session.add(
                        KnowledgeFile(
                            id=tenant_id * 10 + offset,
                            tenant_id=tenant_id,
                            knowledge_id=tenant_id,
                            file_name=f"{offset}.pdf",
                            file_type=1,
                            md5="a" * 32,
                            status=2,
                            create_time=datetime(2026, 9, offset),
                        )
                    )
                session.add(
                    KnowledgeDocument(
                        id=tenant_id * 100,
                        tenant_id=tenant_id,
                        knowledge_id=tenant_id,
                        primary_version_id=tenant_id * 1000,
                    )
                )
                session.add(
                    KnowledgeDocumentVersion(
                        id=tenant_id * 1000,
                        document_id=tenant_id * 100,
                        knowledge_file_id=tenant_id * 10 + 1,
                        is_primary=True,
                        version_no=1,
                    )
                )
            await session.commit()
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def test_real_orm_scan_honors_tenant_and_actual_model_fields(orm_database):
    with mod.tenant_context(1):
        inv = await mod.load_inventory(1)
        assert {f["tenant_id"] for f in inv.files} == {1}
        assert {v["document_id"] for v in inv.versions} == {100}
        plan = mod.build_plan(inv)
        assert plan.groups[0].keep.entry_id == 12
        assert plan.groups[0].remove[0].entry_id == 11
        assert plan.groups[0].keep.uploaded_at.startswith("2026-09-02")


async def test_scoped_orm_keeps_cross_space_reference_and_orphan_version_visible(orm_database):
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope

    with mod.tenant_context(1):
        async with orm_database() as session:
            session.add(Knowledge(id=3, tenant_id=1, name="分发目标库", type=3, state=1))
            session.add(
                KnowledgeSpaceScope(
                    space_id=3,
                    tenant_id=1,
                    level="department",
                    owner_type="department",
                    owner_id=1,
                    update_time=datetime(2026, 9, 1),
                )
            )
            session.add(
                KnowledgeFile(
                    id=31,
                    tenant_id=1,
                    knowledge_id=3,
                    file_name="share.pdf",
                    file_type=1,
                    reference_document_id=100,
                    entry_type="share",
                    entry_status="active",
                    projection_status="ready",
                    status=2,
                    create_time=datetime(2026, 9, 3),
                )
            )
            session.add(
                KnowledgeDocumentVersion(id=999, document_id=999, knowledge_file_id=12, is_primary=True, version_no=1)
            )
            await session.commit()
        source = await mod.load_inventory(1, {1})
        plan = mod.build_plan(source, {1})
        assert 31 in plan.candidates[11].dependent_entry_ids
        assert 31 not in plan.candidates
        assert any(s["entry_id"] == 12 and s["reason"] == "invalid_document_or_primary_version" for s in plan.skipped)
        target = mod.build_plan(await mod.load_inventory(1, {3}), {3})
        assert target.candidates[31].content_id == 11
        assert target.candidates[31].md5 == "a" * 32


@pytest.mark.parametrize("outcome", ["soft_deleted", "pending_cleanup", "rolled_back_pending_cleanup", "denied"])
async def test_real_adapter_wires_version_and_distribution_services(orm_database, monkeypatch, outcome):
    import sys
    from types import ModuleType

    from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    # 复现旧部署中模块存在但没有新工厂函数的情况。
    factory_name = "bisheng.open_endpoints.domain.services.filelib_sync_factory"
    monkeypatch.setitem(sys.modules, factory_name, ModuleType(factory_name))
    seen = []

    async def business_delete(service, file_id):
        assert service.doc_repo is not None and service.version_repo is not None
        assert service.document_distribution_service is not None
        seen.append(file_id)
        if outcome == "denied":
            raise PermissionError("no permission")
        async with orm_database() as session:
            row = await session.get(KnowledgeFile, file_id)
            if outcome == "soft_deleted":
                row.deleted_at = datetime(2026, 9, 8)
            elif outcome == "rolled_back_pending_cleanup":
                row.knowledge_id = 3
                row.entry_status = "active"
                row.entry_type = "manager"
                row.reference_document_id = 100
                document = await session.get(KnowledgeDocument, 100)
                document.knowledge_id = 3
                session.add(document)
            else:
                row.entry_status = "deleting"
            session.add(row)
            await session.commit()

    monkeypatch.setattr(KnowledgeSpaceService, "delete_file", business_delete)
    with mod.tenant_context(1):
        backend = mod.Backend(1, set(), SimpleNamespace(tenant_id=1))
        target = (await backend.scan()).groups[0].remove[0]
        if outcome == "denied":
            with pytest.raises(PermissionError):
                await backend.delete(target)
        else:
            if outcome in {"pending_cleanup", "rolled_back_pending_cleanup"}:
                target = replace(target, entry_type="manager")
            assert await backend.delete(target) == outcome
        assert seen == [11]


@pytest.mark.parametrize("nested", [False, True])
async def test_auto_operator_selects_enabled_verified_global_admin(monkeypatch, nested):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.user.domain.models.user import UserDao
    from bisheng.user.domain.models.user_role import UserRoleDao

    key = {"user": "user:4", "relation": "super_admin", "object": "system:global"}
    fga = SimpleNamespace(read_tuples=AsyncMock(return_value=[{"key": key} if nested else key]))
    monkeypatch.setattr("bisheng.core.openfga.manager.aget_fga_client", AsyncMock(return_value=fga))
    monkeypatch.setattr(
        UserRoleDao,
        "aget_roles_user",
        AsyncMock(
            return_value=[
                SimpleNamespace(user_id=1),
                SimpleNamespace(user_id=2),
                SimpleNamespace(user_id=3),
            ]
        ),
    )
    users = {
        1: SimpleNamespace(user_id=1, user_name="disabled", delete=1),
        3: SimpleNamespace(user_id=3, user_name="former-admin", delete=0),
        4: SimpleNamespace(user_id=4, user_name="root-admin", delete=0),
    }
    monkeypatch.setattr(UserDao, "aget_user", AsyncMock(side_effect=lambda uid: users.get(uid)))

    async def init_user(uid, name, *, tenant_id):
        return SimpleNamespace(user_id=uid, user_name=name, tenant_id=tenant_id, is_global_super=uid == 4)

    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(side_effect=init_user))
    with mod.tenant_context(7):
        actor = await mod.resolve_operator(7)
        from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed

        assert get_current_tenant_id() == 7 and not is_tenant_filter_bypassed()
    assert actor.user_id == 4 and actor.tenant_id == 7


async def test_auto_operator_fails_when_no_real_enabled_admin(monkeypatch):
    from bisheng.user.domain.models.user_role import UserRoleDao

    monkeypatch.setattr(UserRoleDao, "aget_roles_user", AsyncMock(return_value=[]))
    monkeypatch.setattr("bisheng.core.openfga.manager.aget_fga_client", AsyncMock(return_value=None))
    with pytest.raises(ValueError, match="超级管理员"):
        await mod.resolve_operator(1)


async def test_missing_core_dependency_reports_no_business_delete(orm_database, monkeypatch):
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    def unavailable(session, actor):
        raise ImportError("missing core dependency")

    delete = AsyncMock()
    monkeypatch.setattr(mod, "build_delete_service", unavailable)
    monkeypatch.setattr(KnowledgeSpaceService, "delete_file", delete)
    events = []
    with mod.tenant_context(1):
        backend = mod.Backend(1, set(), SimpleNamespace(tenant_id=1))
        assert await mod.execute(backend, apply=True, emit=events.append) == 4
    delete.assert_not_awaited()
    assert events[-1]["failure_stage"] == "service_setup"
    assert "未调用业务删除" in events[-1]["note"]


@pytest.mark.parametrize("apply", [False, True])
async def test_run_only_resolves_admin_for_apply_and_audits_identity(monkeypatch, tmp_path, apply):
    import json

    from bisheng.common.services.config_service import settings

    monkeypatch.setattr(settings.multi_tenant, "enabled", False)
    monkeypatch.setattr("bisheng.core.context.manager.initialize_app_context", AsyncMock())
    monkeypatch.setattr("bisheng.core.context.manager.close_app_context", AsyncMock())
    actor = SimpleNamespace(user_id=8, user_name="admin", tenant_id=1, is_global_super=True)
    resolve = AsyncMock(return_value=actor)
    monkeypatch.setattr(mod, "resolve_operator", resolve)
    backend = FakeBackend(inventory([file_row(1), file_row(2)]))
    monkeypatch.setattr(mod, "Backend", lambda tenant, spaces, user: backend)
    path = tmp_path / "audit.jsonl"
    args = mod.parse_args(["--report-file", str(path), *(["--apply"] if apply else [])])
    assert await mod.run(args) == 0
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if apply:
        resolve.assert_awaited_once_with(1)
        assert next(e for e in events if e["event"] == "operator")["operator_user_id"] == 8
    else:
        resolve.assert_not_awaited()
        assert backend.calls == []
