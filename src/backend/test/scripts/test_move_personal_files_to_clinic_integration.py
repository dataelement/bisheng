"""单文件迁移只改归属; 数据库回滚及提交响应不确定时按报告恢复。"""

from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime
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
    from bisheng.knowledge.domain.services import shared_space_content_loader
    from bisheng.knowledge.domain.services.knowledge_migration_service import KnowledgeMigrationService

    forbidden = Mock(side_effect=AssertionError("must not parse, embed, dispatch or use migration engine"))
    monkeypatch.setattr(shared_space_content_loader, "load_shared_content_from_original", forbidden)
    monkeypatch.setattr(KnowledgeMigrationService, "create_batch", forbidden)
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

    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

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

    monkeypatch.setattr(KnowledgeSpaceService, "add_folder", add_folder)

    def checkpoint():
        checkpoints.append(deepcopy(group))

    actor = NS(tenant_id=1, user_id=9)
    folder_id = await backend.ensure_folder(actor, 20, ["A", "D", "E"], group, checkpoint)
    assert folder_id == 301 and created == [300, 301]
    assert await backend.ensure_folder(actor, 20, ["A", "D", "E"], group, checkpoint) == 301
    assert created == [300, 301]
    assert all(item["status"] == "created" for item in group["created_folders"])
    assert checkpoints[0]["created_folders"][0]["status"] == "creating"
