"""单文件迁移只改归属; 数据库回滚及提交响应不确定时按报告恢复。"""

import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Column, DefaultClause, Integer, MetaData, Table, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstance
from bisheng.database.models.department import Department, UserDepartment
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
from scripts import move_personal_files_to_clinic as m


class PersonalTestUserRow(SQLModel, table=True):
    __tablename__ = "personal_script_test_user"
    user_id: int = Field(primary_key=True)
    user_name: str
    password: str
    delete: int = 0


class Store:
    embedding_model_id = "model-1"

    def __init__(self):
        self.data = {}
        self.fail_side = None
        self.calls = []
        for side in ("es", "milvus"):
            self.data[side] = [
                {
                    "tenant_id": 1,
                    "canonical_document_id": 400,
                    "canonical_version_id": 501,
                    "content_file_id": 101,
                    "content_generation": 4,
                    "embedding_model_id": "model-1",
                    "chunk_index": i,
                    "text": f"正文 {i}",
                    "membership_generation": 7,
                    "knowledge_ids": [10, 30],
                    **({"vector": [0.25, -0.5]} if side == "milvus" else {}),
                }
                for i in range(2)
            ]

    async def read(self, side, ids):
        return {400: deepcopy(self.data[side])}

    async def repair(self, side, plans):
        self.calls.append(side)
        plan = plans[0]
        for row in self.data[side]:
            row.update(plan.snapshot.expected_metadata)
        if self.fail_side == side:
            self.fail_side = None
            raise RuntimeError(f"{side} response lost")
        return {400: None}


async def setup_owner_fallback(direct, owner_state, *, enabled=True):
    backend, _unit, _checkpoint, connection, _, _ = direct
    async with connection() as session:
        session.add(PersonalTestUserRow(user_id=77, user_name="operator", password="test", delete=0))
        if owner_state == "missing":
            target = await session.get(Knowledge, 20)
            target.user_id = 999
            session.add(target)
        elif owner_state == "disabled":
            user = await session.get(PersonalTestUserRow, 9)
            user.delete = 1
            session.add(user)
        await session.commit()
    backend.operator_id = 77
    backend.use_operator_as_file_owner = enabled


@pytest.mark.parametrize("owner_state", ["missing", "disabled", "active"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_owner_fallback_is_opt_in_and_does_not_change_uploader_or_space_owner(direct, owner_state, enabled):
    backend, unit, checkpoint, connection, permissions, _ = direct
    await setup_owner_fallback(direct, owner_state, enabled=enabled)
    if owner_state != "active" and not enabled:
        with pytest.raises(ValueError, match="目标知识库所有者不存在或已禁用"):
            await backend.move_unit(unit, checkpoint)
        assert backend.store.calls == []
        backend.replace_permissions.assert_not_awaited()
        return
    await backend.move_unit(unit, checkpoint)
    effective_owner = 9 if owner_state == "active" else 77
    assert {p["user"] for p in permissions["101"] if p["relation"] == "owner"} == {f"user:{effective_owner}"}
    async with connection() as session:
        assert (await session.get(Knowledge, 20)).user_id == (999 if owner_state == "missing" else 9)
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert row.knowledge_id == 20
            assert row.user_id == 8 and row.original_uploader_id == 8
            assert row.user_name == next(f["user_name"] for f in unit["before"]["files"] if f["id"] == fid)


@pytest.mark.parametrize("committed", [False, True])
async def test_fallback_recovery_keeps_recorded_owner_when_operator_changes(direct, committed):
    backend, unit, checkpoint, _connection, permissions, _ = direct
    await setup_owner_fallback(direct, "disabled")
    if committed:
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    else:
        backend.store.fail_side = "es"
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    assert unit["owner_fallback"] == {"original_owner_id": 9, "operator_id": 77}
    backend.operator_id, backend.use_operator_as_file_owner = 88, False
    backend.refresh_metadata.side_effect = None
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == ("succeeded" if committed else "restored")
    assert permissions == (unit["desired_permissions"] if committed else unit["before"]["permissions"])
    assert unit["target_owner_id"] == 77


@pytest.mark.parametrize(
    "change", ["disabled_operator", "disabled_recorded_operator", "changed_target", "projection_busy"]
)
async def test_fallback_retains_other_guards(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_owner_fallback(direct, "missing")
    recover = change in {"disabled_recorded_operator", "changed_target"}
    if recover:
        backend.store.fail_side = "es"
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.store.calls.clear()
        backend.replace_permissions.reset_mock()
    async with connection() as session:
        if change in {"disabled_operator", "disabled_recorded_operator"}:
            row = await session.get(PersonalTestUserRow, 77)
            row.delete = 1
        elif change == "changed_target":
            row = await session.get(Knowledge, 20)
            row.user_id = 9
        else:
            row = await session.get(KnowledgeFile, 101)
            row.projection_status = "processing"
        session.add(row)
        await session.commit()
    with pytest.raises(ValueError):
        await backend.move_unit(unit, checkpoint, recover=recover)
    assert backend.store.calls == []
    backend.replace_permissions.assert_not_awaited()


@pytest.fixture
async def direct(monkeypatch):
    from celery.app.task import Task

    from bisheng.core import database
    from bisheng.user.domain.models import user as user_module

    monkeypatch.setattr(user_module, "User", PersonalTestUserRow)
    forbidden = Mock(side_effect=AssertionError("must not parse, embed, dispatch or use migration engine"))
    # 不加载真实解析器依赖; 迁移一旦调用解析或通用迁移引擎仍立即失败。
    for name, attr, value in (
        ("shared_space_content_loader", "load_shared_content_from_original", forbidden),
        ("knowledge_migration_service", "KnowledgeMigrationService", Mock(create_batch=forbidden)),
    ):
        module_name = f"bisheng.knowledge.domain.services.{name}"
        module = ModuleType(module_name)
        setattr(module, attr, value)
        monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.setattr(Task, "apply_async", forbidden)
    models = [
        Knowledge,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
        KnowledgeFile,
        KnowledgeSpaceScope,
        PersonalTestUserRow,
        ApprovalInstance,
        Department,
        UserDepartment,
        DepartmentKnowledgeSpace,
    ]
    metadata = MetaData()
    Table("user", metadata, Column("user_id", Integer, primary_key=True))
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def connection():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(database, "get_async_db_session", connection)
    async with connection() as session:
        session.add_all([PersonalTestUserRow(user_id=i, user_name=str(i), password="test", delete=0) for i in (8, 9)])
        session.add(Department(id=1, name="科室", dept_id="D1", tenant_id=1, org_level="office", status="active"))
        session.add(UserDepartment(id=1, user_id=8, department_id=1, is_primary=1))
        session.add(DepartmentKnowledgeSpace(id=1, space_id=20, department_id=1, tenant_id=1))
        session.add(KnowledgeSpaceScope(space_id=10, level="personal", owner_type="user", owner_id=8, tenant_id=1))
        for fid, sid, name, path, level in [(99, 10, "A", "", 0), (98, 10, "B", "/99", 1), (199, 20, "A", "", 0)]:
            session.add(
                KnowledgeFile(
                    id=fid,
                    knowledge_id=sid,
                    tenant_id=1,
                    file_type=0,
                    file_name=name,
                    file_level_path=path,
                    level=level,
                )
            )
        session.add_all(
            [
                Knowledge(id=i, name="技术诀窍" if i == 20 else str(i), type=3, user_id=9, tenant_id=1)
                for i in [10, 20, 30]
            ]
        )
        session.add(KnowledgeSpaceScope(space_id=20, level="team_ks", owner_type="user", owner_id=9, tenant_id=1))
        session.add(
            KnowledgeDocument(
                id=400,
                knowledge_id=10,
                tenant_id=1,
                file_level_path="/99/98",
                level=2,
                primary_version_id=501,
                content_generation=4,
            )
        )
        session.add_all(
            [
                KnowledgeDocumentVersion(
                    id=vid, knowledge_file_id=fid, document_id=400, version_no=n, is_primary=n == 2
                )
                for vid, fid, n in [(500, 106, 1), (501, 101, 2)]
            ]
        )
        for fid in [101, 106, 103]:
            session.add(
                KnowledgeFile(
                    id=fid,
                    knowledge_id=30 if fid == 103 else 10,
                    tenant_id=1,
                    user_id=8,
                    file_name=f"{fid}.pdf",
                    status=2,
                    file_level_path="/99/98",
                    level=2,
                    object_name=f"original/{fid}.pdf",
                    bbox_object_name=f"bbox/{fid}",
                    md5=f"hash-{fid}",
                    file_encoding="GF-JQ-SA-202609000001",
                    file_subcategory_code="JQ01",
                    user_metadata={"filelib_sync_endpoint": "knowhow"},
                    reference_document_id=400 if fid != 106 else None,
                    entry_type="share" if fid == 103 else "manager" if fid == 101 else None,
                    entry_status="active" if fid != 106 else None,
                    projection_status="ready",
                    desired_content_generation=4,
                    applied_content_generation=4,
                    desired_entry_generation=7,
                    applied_entry_generation=7,
                )
            )
        session.add(
            KnowledgeFile(
                id=200,
                knowledge_id=20,
                tenant_id=1,
                file_name="B",
                file_type=0,
                file_level_path="/199",
                level=1,
                status=2,
            )
        )
        await session.commit()
    backend = m.Backend()
    backend.store = Store()
    backend.refresh_metadata = AsyncMock()
    permissions = {
        str(fid): [
            {"user": "folder:99", "relation": "parent", "object": f"knowledge_file:{fid}"},
            {"user": "user:8", "relation": "owner", "object": f"knowledge_file:{fid}"},
        ]
        for fid in [101, 106]
    }
    backend.read_permissions = AsyncMock(side_effect=lambda fid: deepcopy(permissions[str(fid)]))

    async def replace(fid, rows):
        permissions[str(fid)] = deepcopy(rows)

    backend.replace_permissions = AsyncMock(side_effect=replace)
    unit = {
        "tenant_id": 1,
        "document_id": 400,
        "target_space_id": 20,
        "folder_id": 200,
        "folder_name": "A/B",
        "folder_parts": ["A", "B"],
        "category_code": "JQ",
        "status": "candidate",
        "files": [
            {
                "file_id": i,
                "space_id": 10,
                "source_path": "/99/98",
                "source_level": 2,
                "original_uploader_id": None,
                "user_id": 8,
                "uploader_id": 8,
                "uploader_source": "user_id",
                "primary_department_id": 1,
                "office_id": 1,
                "target_space_id": 20,
            }
            for i in [101, 106]
        ],
    }
    checkpoints = []

    def checkpoint():
        checkpoints.append(deepcopy(unit))

    try:
        with m.tenant_context(1):
            yield backend, unit, checkpoint, connection, permissions, forbidden
    finally:
        await engine.dispose()


@pytest.mark.parametrize("route_changed", [False, True])
async def test_current_uploader_fallback_is_loaded_and_revalidated_before_move(direct, route_changed):
    backend, _unit, _checkpoint, connection, _, forbidden = direct
    async with connection() as session:
        session.add(PersonalTestUserRow(user_id=7, user_name="original", password="test", delete=0))
        session.add(Department(id=2, name="无绑定科室", dept_id="D2", tenant_id=1, org_level="office", status="active"))
        session.add(UserDepartment(id=2, user_id=7, department_id=2, is_primary=1))
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            row.original_uploader_id = 7
            session.add(row)
        await session.commit()
    snapshot = await backend.load_snapshot(1)
    plan = m.build_plan(snapshot, 1, ("A", "B"))
    assert plan["candidate_files"] == 2 and plan["skipped"] == []
    group = plan["groups"][0]
    assert group["target_space_id"] == 20
    assert all(entry["uploader_source"] == "user_id" for entry in group["files"])
    unit = m.document_units(snapshot, group, plan)[0]
    unit["folder_id"] = 200
    if route_changed:
        async with connection() as session:
            membership = await session.get(UserDepartment, 2)
            membership.department_id = 1
            session.add(membership)
            await session.commit()
        with pytest.raises(m.SkipFile, match="上传人主组织、科室或科室库绑定已变化"):
            await backend.move_unit(unit, lambda: None)
        assert backend.store.calls == [] and "before" not in unit
    else:
        await backend.move_unit(unit, lambda: None)
    async with connection() as session:
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert row.knowledge_id == (10 if route_changed else 20)
            assert row.user_id == 8 and row.original_uploader_id == 7
    forbidden.assert_not_called()


async def setup_department_target(direct):
    from sqlmodel import select

    _backend, _unit, _checkpoint, connection, _, _ = direct
    async with connection() as session:
        session.add(Department(id=2, name="部门", dept_id="D2", tenant_id=1, org_level="dept", status="active"))
        office = await session.get(Department, 1)
        office.parent_id = 2
        session.add(office)
        binding = await session.get(DepartmentKnowledgeSpace, 1)
        binding.department_id = 2
        session.add(binding)
        scope = (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == 20))).one()
        scope.level, scope.owner_type, scope.owner_id = "department", "department", 2
        session.add(scope)
        await session.commit()


@pytest.mark.parametrize("unversioned", [False, True])
@pytest.mark.parametrize("failure", [None, "permissions", "refresh"])
@pytest.mark.parametrize("api_sync_only", [False, True])
async def test_department_fallback_moves_and_recovers_with_recorded_department(
    direct, unversioned, failure, api_sync_only
):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    if unversioned:
        await setup_unversioned(direct)
    await setup_department_target(direct)
    if api_sync_only:
        await setup_leaf_destination(direct)
    snapshot = await backend.load_snapshot(1)
    plan = m.build_plan(snapshot, 1, ("A", "B"), api_sync_only=api_sync_only)
    assert plan["candidate_files"] == (1 if unversioned else 2)
    planned = m.document_units(snapshot, plan["groups"][0], plan)[0]
    unit.update(planned, folder_id=300 if api_sync_only else 200)
    original_replace = backend.replace_permissions.side_effect
    if failure == "permissions":

        async def fail_replace(fid, rows):
            await original_replace(fid, rows)
            raise RuntimeError("permission response lost")

        backend.replace_permissions.side_effect = fail_replace
    elif failure == "refresh":
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    if failure:
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.replace_permissions.side_effect = original_replace
        backend.refresh_metadata.side_effect = None
        async with connection() as session:
            membership = await session.get(UserDepartment, 1)
            membership.is_primary = 0
            session.add(membership)
            await session.commit()
        await backend.move_unit(unit, checkpoint, recover=True)
    else:
        await backend.move_unit(unit, checkpoint)
    restored = failure == "permissions"
    async with connection() as session:
        for entry in unit["files"]:
            row = await session.get(KnowledgeFile, entry["file_id"])
            assert row.knowledge_id == (10 if restored else 20)
            assert row.user_id == 8 and row.original_uploader_id == (None if restored else 8)
            assert row.file_level_path == ("/99/98" if restored else "/300" if api_sync_only else "/199/200")
    assert unit["status"] == ("restored" if restored else "succeeded")
    expected_permissions = unit["before"]["permissions"] if restored else unit["desired_permissions"]
    assert all(permissions[fid] == tuples for fid, tuples in expected_permissions.items())
    forbidden.assert_not_called()


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("change", ["owner", "level", "binding"])
async def test_department_fallback_rejects_target_changes_before_move_or_recovery(direct, recover, change):
    from sqlmodel import select

    backend, unit, checkpoint, connection, _, _ = direct
    await setup_department_target(direct)
    snapshot = await backend.load_snapshot(1)
    plan = m.build_plan(snapshot, 1)
    unit.update(m.document_units(snapshot, plan["groups"][0], plan)[0], folder_id=200)
    if recover:
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.refresh_metadata.side_effect = None
    async with connection() as session:
        if change == "binding":
            row = await session.get(DepartmentKnowledgeSpace, 1)
            row.department_id = 1
        else:
            row = (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == 20))).one()
            if change == "owner":
                row.owner_id = 1
            else:
                row.level, row.owner_type = "team_ks", "user"
        session.add(row)
        await session.commit()
    backend.replace_permissions.reset_mock()
    calls = len(backend.store.calls)
    with pytest.raises(ValueError, match=r"目标部门库(范围|绑定)已变化"):
        await backend.move_unit(unit, checkpoint, recover=recover)
    backend.replace_permissions.assert_not_awaited()
    assert len(backend.store.calls) == calls


async def test_clinic_plan_cannot_accept_department_target_without_new_preview(direct):
    backend, unit, checkpoint, _connection, _, _ = direct
    await setup_department_target(direct)
    with pytest.raises(ValueError, match="目标科室库范围已变化"):
        await backend.move_unit(unit, checkpoint)
    backend.replace_permissions.assert_not_awaited()


async def setup_unparsed(direct, status=3, content="empty"):
    backend, _unit, _checkpoint, connection, _, _ = direct
    async with connection() as session:
        for fid in (101, 106, 103):
            row = await session.get(KnowledgeFile, fid)
            row.status = status
            row.remark = "保留原解析原因"
            row.projection_status = "failed"
            row.applied_content_generation = 0
            row.applied_entry_generation = 0
            session.add(row)
        await session.commit()
    if content == "empty":
        backend.store.data = {"es": [], "milvus": []}
    elif content == "es_only":
        backend.store.data["milvus"] = []
    elif content == "partial":
        backend.store.data["milvus"] = backend.store.data["milvus"][:1]


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("failure", [None, "before_commit", "after_commit"])
async def test_parsed_file_with_failed_projection_requires_opt_in_and_preserves_failure(direct, enabled, failure):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    await setup_unparsed(direct, status=2, content="es_only")
    async with connection() as session:
        await session.delete(await session.get(KnowledgeFile, 103))
        await session.commit()
    for row in backend.store.data["es"]:
        row["knowledge_ids"] = [10]
    if enabled:
        unit["allow_failed_projection"] = True
    if failure == "before_commit":
        backend.store.fail_side = "es"
    elif failure == "after_commit":
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    if not enabled:
        with pytest.raises(m.SkipFile, match="共享投影"):
            await backend.move_unit(unit, checkpoint)
        backend.replace_permissions.assert_not_awaited()
        return
    if failure:
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.refresh_metadata.side_effect = None
        await backend.move_unit(unit, checkpoint, recover=True)
    else:
        await backend.move_unit(unit, checkpoint)
    restored = failure == "before_commit"
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        assert row.knowledge_id == (10 if restored else 20)
        assert (row.status, row.projection_status, row.applied_content_generation, row.applied_entry_generation) == (
            2,
            "failed",
            0,
            0,
        )
    assert permissions == (unit["before"]["permissions"] if restored else unit["desired_permissions"])
    assert unit["status"] == ("restored" if restored else "succeeded")
    assert backend.store.data["milvus"] == []
    forbidden.assert_not_called()


@pytest.mark.parametrize("change", ["lease", "processing", "shared_entry", "content_generation"])
async def test_failed_projection_opt_in_keeps_concurrency_and_shared_entry_guards(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_unparsed(direct, status=2)
    unit["allow_failed_projection"] = True
    async with connection() as session:
        if change != "shared_entry":
            await session.delete(await session.get(KnowledgeFile, 103))
        row = await session.get(KnowledgeFile, 101)
        if change == "lease":
            row.projection_lease_owner = "worker"
        elif change == "processing":
            row.projection_status = "processing"
        elif change == "content_generation":
            row.desired_content_generation = 999
        session.add(row)
        await session.commit()
    with pytest.raises(m.SkipFile):
        await backend.move_unit(unit, checkpoint)
    assert "before" not in unit
    backend.replace_permissions.assert_not_awaited()


@pytest.mark.parametrize("status", [None, 3, 5, 6, 7])
@pytest.mark.parametrize("content", ["empty", "es_only", "partial"])
async def test_unparsed_move_preserves_parse_state_and_partial_content(direct, status, content):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    await setup_unparsed(direct, status, content)
    original = deepcopy(backend.store.data)
    await backend.move_unit(unit, checkpoint)
    assert unit["status"] == "succeeded"
    async with connection() as session:
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert (row.knowledge_id, row.file_level_path, row.user_id, row.status, row.remark) == (
                20,
                "/199/200",
                8,
                status,
                "保留原解析原因",
            )
            assert row.projection_status == "failed"
            assert row.applied_content_generation == row.applied_entry_generation == 0
    for side, rows in backend.store.data.items():
        assert len(rows) == len(original[side])
        for row, old in zip(rows, original[side], strict=True):
            assert row["knowledge_ids"] == [20, 30]
            assert row["text"] == old["text"] and row.get("vector") == old.get("vector")
    assert permissions["101"] == unit["desired_permissions"]["101"]
    forbidden.assert_not_called()


@pytest.mark.parametrize("committed", [False, True])
async def test_unparsed_recovery_keeps_failed_projection(direct, committed):
    backend, unit, checkpoint, connection, permissions, _ = direct
    await setup_unparsed(direct, content="es_only")
    if committed:
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    else:
        backend.store.fail_side = "es"
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    backend.refresh_metadata.side_effect = None
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == ("succeeded" if committed else "restored")
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        assert row.knowledge_id == (20 if committed else 10)
        assert (row.status, row.projection_status, row.applied_content_generation, row.applied_entry_generation) == (
            3,
            "failed",
            0,
            0,
        )
    assert permissions == (unit["desired_permissions"] if committed else unit["before"]["permissions"])
    assert backend.store.data["milvus"] == []


async def setup_without_manager(direct, *, content="empty", reference=False, status=3):
    _backend, _unit, _checkpoint, connection, _, _ = direct
    await setup_unparsed(direct, status=status, content=content)
    async with connection() as session:
        await session.delete(await session.get(KnowledgeFile, 103))
        row = await session.get(KnowledgeFile, 101)
        row.reference_document_id = 400 if reference else None
        row.entry_type = row.entry_status = None
        session.add(row)
        await session.commit()


@pytest.mark.parametrize("failure", [None, "permissions", "refresh"])
@pytest.mark.parametrize("reference", [False, True])
async def test_versioned_without_manager_move_and_recovery(direct, failure, reference):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    await setup_without_manager(direct, reference=reference)
    async with connection() as session:
        original_files = {fid: (await session.get(KnowledgeFile, fid)).model_dump() for fid in (101, 106)}
        original_versions = [(await session.get(KnowledgeDocumentVersion, vid)).model_dump() for vid in (500, 501)]
    if failure == "permissions":
        replace = backend.replace_permissions.side_effect

        async def lose_response(fid, rows):
            await replace(fid, rows)
            backend.replace_permissions.side_effect = replace
            raise RuntimeError("permission response lost")

        backend.replace_permissions.side_effect = lose_response
    elif failure == "refresh":
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    if failure:
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.refresh_metadata.side_effect = None
        await backend.move_unit(unit, checkpoint, recover=True)
    else:
        await backend.move_unit(unit, checkpoint)
    restored = failure == "permissions"
    assert unit["status"] == ("restored" if restored else "succeeded")
    async with connection() as session:
        document = await session.get(KnowledgeDocument, 400)
        assert (document.knowledge_id, document.file_level_path, document.primary_version_id) == (
            10 if restored else 20,
            "/99/98" if restored else "/199/200",
            501,
        )
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert (row.knowledge_id, row.file_level_path) == (document.knowledge_id, document.file_level_path)
            for key in (
                "status",
                "remark",
                "user_id",
                "user_name",
                "object_name",
                "reference_document_id",
                "entry_type",
                "entry_status",
                "projection_status",
                "desired_entry_generation",
                "applied_entry_generation",
                "desired_content_generation",
                "applied_content_generation",
            ):
                assert getattr(row, key) == original_files[fid][key]
        assert [
            (await session.get(KnowledgeDocumentVersion, vid)).model_dump() for vid in (500, 501)
        ] == original_versions
    assert permissions == (unit["before"]["permissions"] if restored else unit["desired_permissions"])
    assert backend.store.calls == []
    assert backend.store.data == {"es": [], "milvus": []}
    forbidden.assert_not_called()


@pytest.mark.parametrize("status", [None, 5, 6, 7])
async def test_versioned_without_manager_accepts_static_parse_states(direct, status):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_without_manager(direct, status=status)
    await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert row.knowledge_id == 20 and row.status == status
            assert row.entry_type is None


@pytest.mark.parametrize(
    "change",
    [
        "primary",
        "location",
        "parsed_history",
        "foreign_reference",
        "inactive_manager",
        "share",
        "lease",
        "approval",
        "content",
        "missing_version_file",
    ],
)
async def test_versioned_without_manager_rejects_invalid_or_busy_state(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_without_manager(direct)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 106)
        if change == "primary":
            row = await session.get(KnowledgeDocument, 400)
            row.primary_version_id = 500
        elif change == "location":
            row = await session.get(KnowledgeDocument, 400)
            row.knowledge_id = 30
        elif change == "parsed_history":
            row.status = 2
        elif change == "foreign_reference":
            row.reference_document_id = 999
        elif change == "inactive_manager":
            row.reference_document_id, row.entry_type, row.entry_status = 400, "manager", "deleted"
        elif change == "share":
            session.add(
                KnowledgeFile(
                    id=103,
                    knowledge_id=30,
                    tenant_id=1,
                    file_name="share.pdf",
                    reference_document_id=400,
                    entry_type="share",
                    entry_status="active",
                    status=3,
                )
            )
        elif change == "lease":
            row.projection_lease_owner = "worker"
        elif change == "approval":
            session.add(
                ApprovalInstance(
                    tenant_id=1,
                    scenario_code="file_move",
                    scenario_name="迁移",
                    handler_key="file_move",
                    business_key="test",
                    business_resource_type="knowledge_file",
                    business_resource_id="101",
                    business_name="test",
                    applicant_user_id=8,
                    applicant_user_name="test",
                    status="pending",
                )
            )
        elif change == "content":
            backend.store.data["es"] = Store().data["es"]
        elif change == "missing_version_file":
            await session.delete(row)
        if change != "missing_version_file":
            session.add(row)
        await session.commit()
    with pytest.raises(ValueError):
        await backend.move_unit(unit, checkpoint, force_rewrite=True)
    assert "before" not in unit
    backend.replace_permissions.assert_not_awaited()
    assert backend.store.calls == []
    async with connection() as session:
        assert (await session.get(KnowledgeFile, 101)).knowledge_id == 10


async def test_versioned_without_manager_rejects_new_content_before_commit(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_without_manager(direct)
    read = backend.store.read
    calls = 0

    async def new_content(side, ids):
        nonlocal calls
        calls += 1
        if calls == 3:
            backend.store.data["es"] = Store().data["es"]
        return await read(side, ids)

    backend.store.read = new_content
    with pytest.raises(RuntimeError, match="同步后分块或向量发生变化"):
        await backend.move_unit(unit, checkpoint)
    assert "before" in unit
    assert backend.store.calls == []
    async with connection() as session:
        assert (await session.get(KnowledgeDocument, 400)).knowledge_id == 10


async def test_versioned_without_manager_recovery_refuses_activated_entry(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_without_manager(direct)
    backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        row.reference_document_id, row.entry_type, row.entry_status = 400, "manager", "active"
        session.add(row)
        await session.commit()
    backend.replace_permissions.reset_mock()
    with pytest.raises(ValueError, match="入口发生变化"):
        await backend.move_unit(unit, checkpoint, recover=True)
    backend.replace_permissions.assert_not_awaited()


async def setup_unversioned(direct):
    backend, unit, _checkpoint, connection, _, _ = direct
    await setup_unparsed(direct)
    async with connection() as session:
        for model, ids in (
            (KnowledgeDocumentVersion, (500, 501)),
            (KnowledgeDocument, (400,)),
            (KnowledgeFile, (103, 106)),
        ):
            for row_id in ids:
                await session.delete(await session.get(model, row_id))
        file = await session.get(KnowledgeFile, 101)
        file.reference_document_id = file.entry_type = file.entry_status = None
        session.add(file)
        await session.commit()
    unit.update(document_id=-101, unversioned=True, files=unit["files"][:1])
    backend.store.read = AsyncMock(side_effect=AssertionError("unversioned file has no canonical index"))


async def setup_leaf_destination(direct):
    _backend, unit, _checkpoint, connection, _, _ = direct
    async with connection() as session:
        session.add(
            KnowledgeFile(id=300, knowledge_id=20, tenant_id=1, file_name="B", file_type=0, file_level_path="", level=0)
        )
        await session.commit()
    unit.update(api_sync_only=True, folder_id=300, folder_parts=["B"], folder_name="B")
    for item in unit["files"]:
        item.update(folder_parts=["A", "B"], target_folder_parts=["B"])


@pytest.mark.parametrize("kind", ["canonical", "without_manager", "unversioned"])
@pytest.mark.parametrize("stage", ["normal", "source_changed", "recovery_source_changed"])
async def test_api_sync_scope_is_rechecked_under_lock_and_during_recovery(direct, kind, stage):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    if kind == "without_manager":
        await setup_without_manager(direct)
    elif kind == "unversioned":
        await setup_unversioned(direct)
    await setup_leaf_destination(direct)
    if stage == "normal":
        await backend.move_unit(unit, checkpoint)
        assert unit["status"] == "succeeded"
        async with connection() as session:
            for item in unit["files"]:
                row = await session.get(KnowledgeFile, item["file_id"])
                assert row.knowledge_id == 20
                assert row.file_level_path == "/300" and row.level == 1
                assert row.user_id == row.original_uploader_id == 8
                assert row.user_metadata == {"filelib_sync_endpoint": "knowhow"}
        forbidden.assert_not_called()
        return
    if stage == "recovery_source_changed":
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        row.user_metadata = {}
        session.add(row)
        await session.commit()
    saved_permissions = deepcopy(permissions)
    backend.replace_permissions.reset_mock()
    with pytest.raises(m.SkipFile, match="不再标记为接口同步"):
        await backend.move_unit(unit, checkpoint, recover=stage == "recovery_source_changed")
    backend.replace_permissions.assert_not_awaited()
    assert permissions == saved_permissions
    async with connection() as session:
        assert (await session.get(KnowledgeFile, 101)).knowledge_id == (20 if "recovery" in stage else 10)


@pytest.mark.parametrize("kind", ["canonical", "without_manager", "unversioned"])
@pytest.mark.parametrize("committed", [False, True])
async def test_api_sync_leaf_destination_recovery_preserves_source_and_target(direct, kind, committed):
    backend, unit, checkpoint, connection, permissions, _ = direct
    if kind == "without_manager":
        await setup_without_manager(direct)
    elif kind == "unversioned":
        await setup_unversioned(direct)
    await setup_leaf_destination(direct)
    if committed:
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    else:
        replace = backend.replace_permissions.side_effect

        async def lost_response(fid, rows):
            await replace(fid, rows)
            backend.replace_permissions.side_effect = replace
            raise RuntimeError("permission response lost")

        backend.replace_permissions.side_effect = lost_response
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    backend.refresh_metadata.side_effect = None
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == ("succeeded" if committed else "restored")
    async with connection() as session:
        for item in unit["files"]:
            row = await session.get(KnowledgeFile, item["file_id"])
            assert (row.knowledge_id, row.file_level_path, row.level) == (
                (20, "/300", 1) if committed else (10, "/99/98", 2)
            )
        if kind != "unversioned":
            document = await session.get(KnowledgeDocument, 400)
            assert (document.knowledge_id, document.file_level_path, document.level) == (
                (20, "/300", 1) if committed else (10, "/99/98", 2)
            )
    expected_permissions = unit["desired_permissions"] if committed else unit["before"]["permissions"]
    assert {fid: permissions[fid] for fid in expected_permissions} == expected_permissions
    assert unit["desired_permissions"]["101"][1]["user"] == "folder:300"


@pytest.mark.parametrize("which", ["source", "target"])
async def test_api_sync_leaf_mode_still_rechecks_full_source_and_target_names(direct, which):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_leaf_destination(direct)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 99 if which == "source" else 300)
        row.file_name = "changed"
        session.add(row)
        await session.commit()
    with pytest.raises(m.SkipFile, match=r"目录.*变化"):
        await backend.move_unit(unit, checkpoint)
    backend.replace_permissions.assert_not_awaited()


@pytest.mark.parametrize("unversioned", [False, True])
async def test_api_sync_leaf_destination_never_overwrites_same_name_file(direct, unversioned):
    backend, unit, checkpoint, connection, _, _ = direct
    if unversioned:
        await setup_unversioned(direct)
    await setup_leaf_destination(direct)
    async with connection() as session:
        session.add(
            KnowledgeFile(
                id=999,
                knowledge_id=20,
                tenant_id=1,
                file_name="101.pdf",
                file_level_path="/300",
                level=1,
                status=3,
                object_name="keep-existing",
            )
        )
        await session.commit()
    if unversioned:
        with pytest.raises(m.SkipFile, match="同名"):
            await backend.move_unit(unit, checkpoint)
    else:
        await backend.move_unit(unit, checkpoint)
        assert unit["status"] == "skipped" and unit["reason_code"] == "target_file_conflict"
    assert "before" not in unit
    backend.replace_permissions.assert_not_awaited()
    async with connection() as session:
        assert (await session.get(KnowledgeFile, 101)).knowledge_id == 10
        assert (await session.get(KnowledgeFile, 999)).object_name == "keep-existing"


async def test_api_sync_legacy_recovery_keeps_full_target_from_report(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    unit["api_sync_only"] = True
    for item in unit["files"]:
        item["folder_parts"] = ["A", "B"]
    backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    backend.refresh_metadata.side_effect = None
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == "succeeded"
    async with connection() as session:
        assert (await session.get(KnowledgeFile, 101)).file_level_path == "/199/200"


@pytest.mark.parametrize("change", ["parsing", "rebuilding", "lease", "content", "new_chunks"])
async def test_unparsed_move_rejects_busy_or_changing_content(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_unparsed(direct, content="es_only")
    if change in {"parsing", "rebuilding", "lease"}:
        async with connection() as session:
            file = await session.get(KnowledgeFile, 101)
            if change == "lease":
                file.projection_lease_owner = "worker"
            else:
                file.status = 1 if change == "parsing" else 4
            session.add(file)
            await session.commit()
        with pytest.raises(m.SkipFile):
            await backend.move_unit(unit, checkpoint)
        backend.replace_permissions.assert_not_awaited()
        assert not backend.store.calls
    else:
        repair = backend.store.repair

        async def changed(side, plans):
            result = await repair(side, plans)
            if change == "content":
                backend.store.data["es"][0]["text"] = "changed"
            else:
                backend.store.data["milvus"] = [{**backend.store.data["es"][0], "vector": [0.25, -0.5]}]
            return result

        backend.store.repair = changed
        with pytest.raises(RuntimeError, match="分块或向量发生变化"):
            await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        assert (await session.get(KnowledgeFile, 101)).knowledge_id == 10


@pytest.mark.parametrize("change", ["version", "parsed", "busy", "conflict"])
async def test_unversioned_rechecks_before_any_write(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    await setup_unversioned(direct)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        if change == "version":
            session.add(
                KnowledgeDocumentVersion(id=501, knowledge_file_id=101, document_id=400, version_no=1, is_primary=True)
            )
        elif change == "conflict":
            session.add(
                KnowledgeFile(id=999, knowledge_id=20, tenant_id=1, file_name=row.file_name, file_level_path="/199/200")
            )
        else:
            row.status = 2 if change == "parsed" else 1
            session.add(row)
        await session.commit()
    with pytest.raises(ValueError):
        await backend.move_unit(unit, checkpoint)
    assert "before" not in unit
    backend.replace_permissions.assert_not_awaited()


@pytest.mark.parametrize("failure", [None, "permission", "after_commit"])
async def test_unversioned_move_and_recovery_preserve_file(direct, failure):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    await setup_unversioned(direct)
    original_replace = backend.replace_permissions.side_effect
    if failure == "permission":

        async def fail_after_write(fid, rows):
            await original_replace(fid, rows)
            raise RuntimeError("permission response lost")

        backend.replace_permissions.side_effect = fail_after_write
    elif failure == "after_commit":
        backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    if failure:
        with pytest.raises(RuntimeError):
            await backend.move_unit(unit, checkpoint)
        backend.replace_permissions.side_effect = original_replace
        backend.refresh_metadata.side_effect = None
        await backend.move_unit(unit, checkpoint, recover=True)
    else:
        await backend.move_unit(unit, checkpoint)
    restored = failure == "permission"
    assert unit["status"] == ("restored" if restored else "succeeded")
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        assert (row.knowledge_id, row.file_level_path, row.status, row.remark, row.user_id, row.object_name) == (
            10 if restored else 20,
            "/99/98" if restored else "/199/200",
            3,
            "保留原解析原因",
            8,
            "original/101.pdf",
        )
        assert row.reference_document_id is None and row.entry_type is None
        assert (await session.get(KnowledgeDocument, 400)) is None
    assert permissions["101"] == (unit["before"]["permissions"] if restored else unit["desired_permissions"])["101"]
    backend.store.read.assert_not_awaited()
    forbidden.assert_not_called()


async def assert_state(connection, space, membership):
    async with connection() as session:
        document = await session.get(KnowledgeDocument, 400)
        assert (document.knowledge_id, document.primary_version_id, document.content_generation) == (space, 501, 4)
        for fid in [101, 106]:
            file = await session.get(KnowledgeFile, fid)
            assert (file.knowledge_id, file.status, file.user_id, file.object_name) == (
                space,
                2,
                8,
                f"original/{fid}.pdf",
            )
        manager = await session.get(KnowledgeFile, 101)
        assert manager.desired_content_generation == manager.applied_content_generation == 4
        assert manager.desired_entry_generation == manager.applied_entry_generation == membership
        assert manager.projection_status == "ready"
        share = await session.get(KnowledgeFile, 103)
        assert share.knowledge_id == 30
        assert (await session.get(KnowledgeDocumentVersion, 501)).knowledge_file_id == 101


async def test_direct_move_preserves_ids_vectors_versions_and_other_memberships(direct):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    original = deepcopy(backend.store.data)
    await backend.move_unit(unit, checkpoint)
    assert unit["status"] == "succeeded"
    await assert_state(connection, 20, 8)
    for side, rows in backend.store.data.items():
        for i, row in enumerate(rows):
            assert row["knowledge_ids"] == [20, 30]
            assert row["text"] == original[side][i]["text"]
            assert row.get("vector") == original[side][i].get("vector")
    assert permissions["101"] == unit["desired_permissions"]["101"]
    forbidden.assert_not_called()
    async with connection() as session:
        for fid in (101, 106):
            row = await session.get(KnowledgeFile, fid)
            assert (row.file_level_path, row.level, row.original_uploader_id, row.original_knowledge_id) == (
                "/199/200",
                2,
                8,
                10,
            )


@pytest.mark.parametrize("side", ["es", "milvus"])
@pytest.mark.parametrize(
    "field,value",
    [("knowledge_ids", [10, 30]), ("knowledge_id", None), ("membership_generation", "8")],
)
async def test_index_verification_reports_side_field_value_and_keeps_recovery(direct, side, field, value):
    backend, unit, checkpoint, connection, _, _ = direct
    repair = backend.store.repair

    async def mismatched_readback(target, plans):
        result = await repair(target, plans)
        if target == side:
            backend.store.data[side][0][field] = value
        return result

    backend.store.repair = mismatched_readback
    with pytest.raises(RuntimeError, match="共享索引归属写入未确认") as error:
        await backend.move_unit(unit, checkpoint)
    assert side in str(error.value)
    assert field in str(error.value)
    detail = unit["index_verification"]["samples"][0]
    assert detail["side"] == side
    assert detail["field"] == field
    assert detail["actual"] == repr(value)
    assert detail["actual_type"] == type(value).__name__
    assert unit["before"]
    await assert_state(connection, 10, 7)


@pytest.mark.parametrize("side", ["es", "milvus"])
@pytest.mark.parametrize("force_rewrite", [False, True])
async def test_existing_index_drift_uses_database_memberships_only_when_forced(direct, side, force_rewrite):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    for row in backend.store.data[side]:
        row.update(knowledge_ids=[20, 999], knowledge_id=999, membership_generation=12)
    original_permissions = deepcopy(permissions)
    if not force_rewrite:
        with pytest.raises(ValueError, match="共享索引归属与数据库不一致"):
            await backend.move_unit(unit, checkpoint)
        assert backend.store.calls == []
        assert permissions == original_permissions
        await assert_state(connection, 10, 7)
        return

    await backend.move_unit(unit, checkpoint, force_rewrite=True)
    await assert_state(connection, 20, 13)
    for rows in backend.store.data.values():
        assert all(row["knowledge_ids"] == [20, 30] for row in rows)
        assert all(row["knowledge_id"] == 20 for row in rows)
        assert all(row["membership_generation"] == 13 for row in rows)
    drift = unit["initial_index_drift"]
    assert drift["database_knowledge_ids"] == [10, 30]
    assert drift["samples"][0]["side"] == side
    assert drift["samples"][0]["actual"] == "[20, 999]"
    assert unit["status"] == "succeeded"
    assert permissions["101"] == unit["desired_permissions"]["101"]
    forbidden.assert_not_called()


async def test_force_existing_drift_still_rejects_wrong_content_identity(direct):
    backend, unit, checkpoint, connection, permissions, _ = direct
    backend.store.data["milvus"][0].update(knowledge_ids=[999], canonical_version_id=999)
    original_permissions = deepcopy(permissions)
    with pytest.raises(ValueError, match="共享内容标识不一致"):
        await backend.move_unit(unit, checkpoint, force_rewrite=True)
    assert backend.store.calls == []
    assert permissions == original_permissions
    await assert_state(connection, 10, 7)


@pytest.mark.parametrize("side", ["es", "milvus"])
@pytest.mark.parametrize("persistent", [False, True])
async def test_force_rewrite_retries_only_mismatched_side_and_never_commits_bad_metadata(direct, side, persistent):
    backend, unit, checkpoint, connection, _, forbidden = direct
    repair = backend.store.repair

    async def mismatched_readback(target, plans):
        result = await repair(target, plans)
        if target == side and (persistent or backend.store.calls.count(side) == 1):
            backend.store.data[side][0]["knowledge_id"] = None
        return result

    backend.store.repair = mismatched_readback
    if persistent:
        with pytest.raises(RuntimeError, match="共享索引归属写入未确认"):
            await backend.move_unit(unit, checkpoint, force_rewrite=True)
        await assert_state(connection, 10, 7)
        assert unit["rewrite_attempts"] == 2
        assert unit["index_verification"]["samples"][0]["side"] == side
    else:
        await backend.move_unit(unit, checkpoint, force_rewrite=True)
        await assert_state(connection, 20, 8)
        assert unit["status"] == "succeeded"
        assert unit["rewrite_attempts"] == 1
        assert "index_verification" not in unit
    assert backend.store.calls.count(side) == (3 if persistent else 2)
    assert backend.store.calls.count("milvus" if side == "es" else "es") == 1
    assert unit["rewrite_history"][0]["samples"][0]["field"] == "knowledge_id"
    forbidden.assert_not_called()


async def test_force_rewrite_does_not_retry_changed_content(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    repair = backend.store.repair

    async def changed_content(side, plans):
        result = await repair(side, plans)
        if side == "milvus":
            backend.store.data[side][0]["vector"] = [0.5, 0.5]
        return result

    backend.store.repair = changed_content
    with pytest.raises(RuntimeError, match="分块或向量发生变化"):
        await backend.move_unit(unit, checkpoint, force_rewrite=True)
    assert backend.store.calls == ["es", "milvus"]
    await assert_state(connection, 10, 7)


@pytest.mark.parametrize("side", ["es", "milvus"])
async def test_external_partial_failure_rolls_back_db_and_report_recovers_to_source(direct, side):
    backend, unit, checkpoint, connection, permissions, forbidden = direct
    backend.store.fail_side = side
    with pytest.raises(RuntimeError, match="response lost"):
        await backend.move_unit(unit, checkpoint)
    await assert_state(connection, 10, 7)
    assert unit["status"] == "syncing"
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == "restored"
    await assert_state(connection, 10, 9)
    assert permissions == unit["before"]["permissions"]
    assert all(row["knowledge_ids"] == [10, 30] for rows in backend.store.data.values() for row in rows)
    forbidden.assert_not_called()


async def test_committed_db_with_refresh_failure_recovers_to_target(direct):
    backend, unit, checkpoint, connection, _permissions, _ = direct
    backend.refresh_metadata.side_effect = RuntimeError("refresh failed")
    with pytest.raises(RuntimeError, match="refresh failed"):
        await backend.move_unit(unit, checkpoint)
    await assert_state(connection, 20, 8)
    backend.refresh_metadata.side_effect = None
    await backend.move_unit(unit, checkpoint, recover=True)
    await assert_state(connection, 20, 9)
    assert unit["status"] == "succeeded"


@pytest.mark.parametrize(
    "change", ["missing", "wrong_file", "text", "generation", "busy", "uploader", "tenant", "deleted"]
)
async def test_invalid_content_or_changed_source_never_writes(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    if change == "missing":
        backend.store.data["milvus"] = []
    elif change == "wrong_file":
        backend.store.data["es"][0]["content_file_id"] = 99
    elif change == "text":
        backend.store.data["es"][0]["text"] = "corrupt"
    else:
        async with connection() as session:
            file = await session.get(KnowledgeFile, 101)
            key, value = {
                "generation": ("applied_content_generation", 3),
                "busy": ("projection_status", "processing"),
                "uploader": ("original_uploader_id", 999),
                "tenant": ("tenant_id", 2),
                "deleted": ("deleted_at", datetime.now()),
            }[change]
            setattr(file, key, value)
            session.add(file)
            await session.commit()
    with pytest.raises(ValueError):
        await backend.move_unit(unit, checkpoint)
    assert not backend.store.calls
    backend.replace_permissions.assert_not_awaited()
    assert "before" not in unit


async def test_name_conflict_skips_without_modifying_existing_file(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    async with connection() as session:
        session.add(
            KnowledgeFile(id=300, knowledge_id=20, tenant_id=1, file_name="101.pdf", file_level_path="/199/200")
        )
        await session.commit()
    await backend.move_unit(unit, checkpoint)
    assert unit["status"] == "skipped"
    assert not backend.store.calls
    await assert_state(connection, 10, 7)


async def test_recovery_rejects_content_changed_after_failure(direct):
    backend, unit, checkpoint, connection, _, _ = direct
    backend.store.fail_side = "es"
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        file = await session.get(KnowledgeFile, 101)
        file.md5 = "new-content"
        session.add(file)
        await session.commit()
    with pytest.raises(ValueError, match="发生变化"):
        await backend.move_unit(unit, checkpoint, recover=True)


async def test_permission_failure_is_recoverable_without_index_changes(direct):
    backend, unit, checkpoint, connection, permissions, _ = direct
    original_replace = backend.replace_permissions.side_effect

    async def failed(fid, rows):
        await original_replace(fid, rows)
        raise RuntimeError("permission response lost")

    backend.replace_permissions.side_effect = failed
    with pytest.raises(RuntimeError, match="permission response lost"):
        await backend.move_unit(unit, checkpoint)
    assert backend.store.calls == []
    await assert_state(connection, 10, 7)
    backend.replace_permissions.side_effect = original_replace
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == "restored"
    assert permissions == unit["before"]["permissions"]


async def test_commit_response_lost_does_not_restore_old_permissions(direct):
    backend, unit, checkpoint, connection, permissions, _ = direct
    original_context = backend.locked_document

    @asynccontextmanager
    async def uncertain(unit):
        async with original_context(unit) as context:
            commit = context[0].commit

            async def lost_response():
                await commit()
                raise RuntimeError("commit response lost")

            context[0].commit = lost_response
            yield context

    backend.locked_document = uncertain
    with pytest.raises(RuntimeError, match="commit response lost"):
        await backend.move_unit(unit, checkpoint)
    await assert_state(connection, 20, 8)
    backend.locked_document = original_context
    await backend.move_unit(unit, checkpoint, recover=True)
    assert unit["status"] == "succeeded"
    assert permissions == unit["desired_permissions"]


async def test_real_permission_adapter_uses_journal_not_background_retries(monkeypatch):
    from bisheng.permission.domain.services.permission_service import PermissionService

    backend = m.Backend()
    before = [{"user": "folder:10", "relation": "parent", "object": "knowledge_file:101"}]
    after = [{"user": "folder:20", "relation": "parent", "object": "knowledge_file:101"}]
    backend.read_permissions = AsyncMock(side_effect=[before, after])
    writer = AsyncMock()
    monkeypatch.setattr(PermissionService, "batch_write_tuples", writer)
    await backend.replace_permissions(101, after)
    assert writer.await_args.kwargs == {"raise_on_failure": True, "stop_on_failure": True, "record_failures": False}
    assert [operation.action for operation in writer.await_args.args[0]] == ["delete", "write"]


@pytest.mark.parametrize("row_tenant", [None, 1])
def test_shared_rows_use_routing_tenant_not_legacy_scalar(row_tenant):
    from types import SimpleNamespace as NS

    rows = Store().data
    for values in rows.values():
        for row in values:
            if row_tenant is None:
                row.pop("tenant_id")
            else:
                row["tenant_id"] = row_tenant
    assert m.validate_chunks(
        rows, {"tenant_id": 7}, NS(id=400, content_generation=4), NS(id=501, knowledge_file_id=101), "model-1"
    )


async def test_recovery_refuses_new_external_grants(direct):
    backend, unit, checkpoint, connection, permissions, _ = direct
    backend.store.fail_side = "es"
    with pytest.raises(RuntimeError):
        await backend.move_unit(unit, checkpoint)
    permissions["101"].append({"user": "user:99", "relation": "viewer", "object": "knowledge_file:101"})
    with pytest.raises(ValueError, match="权限存在"):
        await backend.move_unit(unit, checkpoint, recover=True)
    await assert_state(connection, 10, 7)


async def test_refresh_metadata_only_updates_ownership_fields_without_body(monkeypatch):
    from types import SimpleNamespace as NS

    from bisheng.core import database
    from bisheng.core.search.elasticsearch import manager
    from bisheng.knowledge.domain.repositories.implementations import (
        knowledge_fulltext_source_repository_impl as source_module,
    )
    from bisheng.knowledge.domain.services import portal_recommendation_projection_service as projection_module

    source = NS(
        knowledge_id=20,
        knowledge_name="技术诀窍",
        knowledge_level="public",
        knowledge_business_domain_codes=["SA"],
        folder_path="炼钢",
        source_path="技术诀窍/炼钢/101.pdf",
    )
    source_repository = Mock(return_value=NS(get_current_snapshot=AsyncMock(return_value=source)))
    monkeypatch.setattr(source_module, "KnowledgeFulltextSourceRepositoryImpl", source_repository)
    client = NS(
        indices=NS(exists=AsyncMock(return_value=True)),
        mget=AsyncMock(return_value={"docs": [{"found": True, "_seq_no": 1, "_primary_term": 2}]}),
        update=AsyncMock(),
    )
    monkeypatch.setattr(manager, "get_es_connection", AsyncMock(return_value=client))
    projection = NS(refresh_file=AsyncMock(return_value=True))
    monkeypatch.setattr(projection_module, "PortalRecommendationProjectionService", Mock(return_value=projection))

    @asynccontextmanager
    async def connection():
        yield NS(commit=AsyncMock())

    monkeypatch.setattr(database, "get_async_db_session", connection)
    backend = m.Backend()
    await backend.refresh_metadata({"files": [{"file_id": 101}]})
    call = client.update.await_args.kwargs
    assert call["doc"] == vars(source)
    assert call["if_seq_no"] == 1 and call["if_primary_term"] == 2
    assert "content" not in call["doc"]
    projection.refresh_file.assert_awaited_once()


async def test_root_file_moves_to_root_with_space_parent(direct):
    backend, unit, checkpoint, connection, permissions, _ = direct
    async with connection() as session:
        for model, row_id in [(KnowledgeFile, 101), (KnowledgeFile, 106), (KnowledgeDocument, 400)]:
            row = await session.get(model, row_id)
            row.file_level_path, row.level = "", 0
            session.add(row)
        await session.commit()
    unit.update(folder_id=None, folder_parts=[], folder_name="")
    for item in unit["files"]:
        item.update(source_path="", source_level=0)
    await backend.move_unit(unit, checkpoint)
    async with connection() as session:
        row = await session.get(KnowledgeFile, 101)
        assert (row.knowledge_id, row.file_level_path, row.level) == (20, "", 0)
    from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (
        KnowledgeDocumentPermissionActivationService,
    )

    expected = KnowledgeDocumentPermissionActivationService._parent_operation(row, action="write")
    assert {entry["user"] for entry in permissions["101"] if entry["relation"] == "parent"} == {expected.user}


@pytest.mark.parametrize("change", ["binding", "primary", "folder", "scope"])
async def test_live_route_changes_are_rejected_before_external_writes(direct, change):
    backend, unit, checkpoint, connection, _, _ = direct
    async with connection() as session:
        if change == "binding":
            row = await session.get(DepartmentKnowledgeSpace, 1)
            row.department_id = 999
        elif change == "primary":
            row = await session.get(UserDepartment, 1)
            row.is_primary = 0
        elif change == "folder":
            row = await session.get(KnowledgeFile, 99)
            row.file_name = "renamed"
        else:
            from sqlmodel import select

            row = (await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == 10))).one()
            row.level = "team"
        session.add(row)
        await session.commit()
    with pytest.raises(m.SkipFile):
        await backend.move_unit(unit, checkpoint)
    assert backend.store.calls == []
    assert "before" not in unit


async def test_scan_paginates_read_only_and_preserves_full_version_chain(direct):
    from sqlalchemy import event

    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    register_tenant_filter_events()

    backend, _unit, _checkpoint, connection, _, _ = direct
    async with connection() as session:
        session.add_all(
            [
                KnowledgeFile(
                    id=i,
                    knowledge_id=10,
                    tenant_id=1,
                    file_name=f"{i}.pdf",
                    file_type=1,
                    user_id=8,
                    file_level_path="/99/98",
                    level=2,
                    status=2,
                )
                for i in range(1000, 1501)
            ]
        )
        session.add(
            KnowledgeFile(id=900, knowledge_id=10, tenant_id=1, file_name="deleted.pdf", deleted_at=datetime.now())
        )
        session.add(Knowledge(id=80, name="其他租户", tenant_id=2, user_id=8, type=3))
        session.add(KnowledgeSpaceScope(space_id=80, level="personal", owner_type="user", owner_id=8, tenant_id=2))
        session.add(KnowledgeFile(id=901, knowledge_id=80, tenant_id=2, file_name="other.pdf"))
        await session.commit()
        engine = session.bind.sync_engine
    statements = []

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        actual = await backend.load_snapshot(1)
        assert len([f for f in actual["files"] if f.file_type == 1]) == 503
        assert {f.id for f in actual["files"]}.isdisjoint({103, 900, 901})
        assert 80 not in {s.id for s in actual["spaces"]}
        plan = m.build_plan(actual, 1, ("A", "B"))
        assert plan["candidate_files"] == 2
        assert len(plan["skipped"]) == 501
        narrow = await backend.load_snapshot(1, file_ids={101})
        assert {v.knowledge_file_id for v in narrow["versions"]} == {101, 106}
        assert m.build_plan(narrow, 1, ("A", "B"))["candidate_files"] == 0
        assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    finally:
        event.remove(engine, "before_cursor_execute", record)


async def test_create_only_missing_directory_segments_and_reuse_on_retry(direct, monkeypatch):
    from types import SimpleNamespace as NS

    backend, _unit, _checkpoint, connection, _, _ = direct
    created, checkpoints = [], []
    group = {}

    async def add_folder(service, target_id, name, parent_id=None):
        assert group["created_folders"][-1]["status"] == "creating"
        async with connection() as session:
            parent = await session.get(KnowledgeFile, parent_id) if parent_id else None
            row = KnowledgeFile(
                id=300 + len(created),
                tenant_id=1,
                knowledge_id=target_id,
                file_type=0,
                file_name=name,
                file_level_path=m.target_path(parent),
                level=parent.level + 1 if parent else 0,
            )
            session.add(row)
            await session.commit()
            created.append(row.id)
            return row

    # 此测试只验证脚本的目录规划, 目录创建仍使用原有 ORM 仿真。
    module_name = "bisheng.knowledge.domain.services.knowledge_space_service"
    module = ModuleType(module_name)
    module.KnowledgeSpaceService = Mock(return_value=NS(add_folder=lambda *args: add_folder(None, *args)))
    monkeypatch.setitem(sys.modules, module_name, module)

    def checkpoint():
        checkpoints.append(deepcopy(group))

    actor = NS(tenant_id=1, user_id=9)
    folder_id = await backend.ensure_folder(actor, 20, ["A", "D", "E"], group, checkpoint)
    assert folder_id == 301 and created == [300, 301]
    assert await backend.ensure_folder(actor, 20, ["A", "D", "E"], group, checkpoint) == 301
    assert created == [300, 301]
    assert all(item["status"] == "created" for item in group["created_folders"])
    assert checkpoints[0]["created_folders"][0]["status"] == "creating"
