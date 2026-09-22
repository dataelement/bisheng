"""科室技术诀窍迁移的来源范围、只读边界与任务提交契约。"""

import json
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from scripts import move_clinic_knowhow_to_public as m


def file(file_id=101, **changes):
    values = {
        "id": file_id,
        "knowledge_id": 10,
        "file_type": 1,
        "file_name": f"{file_id}.pdf",
        "deleted_at": None,
        "file_level_path": "",
        "file_encoding": "GF-JQ-SA-202609000001",
        "file_subcategory_code": "JQ01",
        "status": 2,
        "entry_type": "manager",
        "entry_status": "active",
        "user_metadata": {"filelib_sync_endpoint": "knowhow_sync"},
    }
    return NS(**(values | changes))


@pytest.fixture
def snapshot():
    return {
        "config": NS(
            portal=NS(
                document_types=[
                    NS(
                        code="JQ",
                        label="技术诀窍",
                        children=[
                            NS(code="JQ01", label="炼钢"),
                            NS(code="JQ02", label="轧钢"),
                        ],
                    )
                ]
            )
        ),
        "spaces": [
            NS(id=10, name="科室一"),
            NS(id=11, name="旧版科室"),
            NS(id=12, name="普通团队"),
            NS(id=20, name="技术诀窍"),
        ],
        "scopes": [
            NS(space_id=10, level="team_ks", owner_type="user"),
            NS(space_id=11, level="team", owner_type="user"),
            NS(space_id=12, level="team", owner_type="user_group"),
            NS(space_id=20, level="public", owner_type="tenant_root_department"),
        ],
        "bindings": [
            NS(space_id=10, department_id=1),
            NS(space_id=11, department_id=1),
            NS(space_id=12, department_id=1),
        ],
        "departments": [NS(id=1, status="active")],
        "files": [
            file(),
            file(102, knowledge_id=11, file_subcategory_code="JQ02"),
            file(103, knowledge_id=12),
            file(104, deleted_at="2026-09-20"),
            file(105, file_encoding="GF-STD-SA-202609000001"),
            file(200, knowledge_id=20, file_type=0, file_name="炼钢"),
            file(107, user_metadata={}),
        ],
        "versions": [],
    }


def test_scope_classification_and_existing_or_new_folder(snapshot):
    plan = m.build_plan(snapshot, 1)
    assert [row["id"] for row in plan["source_spaces"]] == [10, 11]
    assert plan["candidate_files"] == 2
    assert [(g["folder_name"], g["folder_id"], g["create_folder"]) for g in plan["groups"]] == [
        ("炼钢", 200, False),
        ("轧钢", None, True),
    ]
    assert [e["file_id"] for g in plan["groups"] for e in g["files"]] == [101, 102]
    assert plan["ingest_method"] == "接口同步"


@pytest.mark.parametrize(
    "metadata,included",
    [
        ({"filelib_sync_endpoint": "knowhow_sync"}, True),
        ({"external_file_id": "external-101"}, True),
        ({"filelib_sync_endpoint": "", "external_file_id": "external-101"}, True),
        ({"filelib_sync_endpoint": "", "external_file_id": None}, False),
        ({"source": "openapi"}, False),
        (None, False),
        ('{"external_file_id":"external-101"}', False),
    ],
)
def test_ingest_method_matches_portal_metadata_contract(snapshot, metadata, included):
    snapshot["files"][0].user_metadata = metadata
    plan = m.build_plan(snapshot, 1)
    ids = [e["file_id"] for g in plan["groups"] for e in g["files"]]
    assert (101 in ids) is included
    assert 107 not in ids


def test_mixed_ingest_method_version_chain_is_skipped_whole(snapshot):
    snapshot["versions"] = [NS(document_id=1, knowledge_file_id=101), NS(document_id=1, knowledge_file_id=107)]
    plan = m.build_plan(snapshot, 1)
    assert [e["file_id"] for g in plan["groups"] for e in g["files"]] == [102]
    assert plan["skipped"][0]["file_id"] == 101
    assert "版本链" in plan["skipped"][0]["reason"]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"entry_type": "share"}, "非有效原文件入口"),
        ({"entry_type": "publish"}, "非有效原文件入口"),
        ({"entry_status": "preparing"}, "非有效原文件入口"),
        ({"status": 3}, "文件尚未解析成功"),
        ({"file_subcategory_code": None}, "二级分类缺失或不属于技术诀窍"),
    ],
)
def test_unsafe_or_unclassified_files_are_reported(snapshot, changes, reason):
    snapshot["files"][0] = file(**changes)
    plan = m.build_plan(snapshot, 1)
    assert plan["candidate_files"] == 1
    assert plan["skipped"][0]["file_id"] == 101
    assert plan["skipped"][0]["reason"] == reason


def test_archived_department_and_missing_binding_are_not_clinics(snapshot):
    snapshot["departments"][0].status = "archived"
    assert m.build_plan(snapshot, 1)["source_spaces"] == []
    snapshot["departments"][0].status = "active"
    snapshot["bindings"] = []
    assert m.build_plan(snapshot, 1)["candidate_files"] == 0


@pytest.mark.parametrize("other_file", [102, 999])
def test_version_chain_cannot_split_categories_or_leave_an_unselected_version(snapshot, other_file):
    snapshot["versions"] = [NS(document_id=1, knowledge_file_id=101), NS(document_id=1, knowledge_file_id=other_file)]
    plan = m.build_plan(snapshot, 1)
    assert 101 not in [e["file_id"] for g in plan["groups"] for e in g["files"]]
    assert "版本链" in plan["skipped"][0]["reason"]


def test_complete_version_chain_is_submitted_as_whole(snapshot):
    snapshot["files"].append(file(106))
    snapshot["versions"] = [NS(document_id=1, knowledge_file_id=101), NS(document_id=1, knowledge_file_id=106)]
    plan = m.build_plan(snapshot, 1)
    assert [e["file_id"] for e in plan["groups"][0]["files"]] == [101, 106]


def test_ambiguous_targets_fail_closed(snapshot):
    snapshot["files"].append(file(201, knowledge_id=20, file_type=0, file_name="\u200b炼钢 "))
    plan = m.build_plan(snapshot, 1)
    assert plan["skipped"][0]["reason"] == "目标根目录存在多个同名目录"
    snapshot["spaces"].append(NS(id=21, name="技术诀窍"))
    snapshot["scopes"].append(NS(space_id=21, level="public", owner_type="tenant_root_department"))
    with pytest.raises(ValueError, match="缺失或重名"):
        m.build_plan(snapshot, 1)


def test_duplicate_subcategory_labels_fail_before_writes(snapshot):
    snapshot["config"].portal.document_types[0].children[1].label = "炼钢"
    with pytest.raises(ValueError, match="同名分类"):
        m.build_plan(snapshot, 1)


class FakeBackend:
    def __init__(self, snapshot):
        self.load_snapshot = AsyncMock(side_effect=lambda _, **kwargs: deepcopy(snapshot))
        self.operator = AsyncMock(return_value=NS(user_id=1))
        self.ensure_no_pending = AsyncMock()
        self.ensure_folder = AsyncMock(return_value=200)
        self.move_unit = AsyncMock(side_effect=self.move)

    @asynccontextmanager
    async def shared_storage(self, tenant_id):
        yield

    async def move(self, unit, checkpoint, **kwargs):
        unit["status"] = "succeeded"
        checkpoint()


@pytest.fixture
def backend(snapshot):
    snapshot["versions"] = [NS(document_id=1, knowledge_file_id=101), NS(document_id=2, knowledge_file_id=102)]
    return FakeBackend(snapshot)


def arguments(apply=False):
    argv = ["--tenant-id", "1"]
    if apply:
        argv += ["--apply", "--operator-id", "1"]
    return m.parse_args(argv)


async def test_dry_run_has_no_business_writes(backend, tmp_path):
    path = tmp_path / "report.json"
    assert await m.execute(arguments(), backend, path) == 0
    backend.operator.assert_not_awaited()
    backend.ensure_folder.assert_not_awaited()
    backend.move_unit.assert_not_awaited()
    assert json.loads(path.read_text())["status"] == "planned"
    assert path.stat().st_mode & 0o777 == 0o600


async def test_apply_runs_documents_directly_with_original_ids(backend, tmp_path):
    path = tmp_path / "report.json"
    assert await m.execute(arguments(True), backend, path) == 0
    report = json.loads(path.read_text())
    assert report["execution_mode"] == "rehome_shared"
    assert [u["document_id"] for u in report["units"]] == [1, 2]
    assert [u["files"][0]["file_id"] for u in report["units"]] == [101, 102]
    assert backend.move_unit.await_count == 2
    assert [call.kwargs for call in backend.load_snapshot.await_args_list] == [
        {},
        {"file_ids": {101}},
        {"file_ids": {102}},
    ]
    assert backend.ensure_folder.await_args_list[1].args[2] == "轧钢"


@pytest.mark.parametrize("same_folder", [False, True])
@pytest.mark.parametrize("force_rewrite", [False, True])
async def test_document_failure_is_recorded_and_next_document_runs(
    backend, snapshot, tmp_path, same_folder, force_rewrite
):
    if same_folder:
        snapshot["files"][1].file_subcategory_code = "JQ01"

    async def move(unit, checkpoint, **kwargs):
        assert kwargs == ({"force_rewrite": True} if force_rewrite else {})
        if unit["document_id"] == 1:
            unit.update(before={"backup": True}, status="syncing")
            checkpoint()
            raise RuntimeError("ES failed")
        unit["status"] = "succeeded"
        checkpoint()

    backend.move_unit.side_effect = move
    path = tmp_path / "report.json"
    args = arguments(True)
    args.force_rewrite = force_rewrite
    assert await m.execute(args, backend, path) == 2
    assert backend.move_unit.await_count == 2
    report = json.loads(path.read_text())
    assert report["status"] == "completed_with_errors"
    assert report["units"][0]["before"] == {"backup": True}
    assert report["units"][0]["status"] == "failed"
    assert report["units"][0]["failed_stage"] == "syncing"
    assert report["units"][0]["needs_recovery"] is True
    assert report["units"][1]["status"] == "succeeded"
    assert report["errors"][0]["document_id"] == 1
    assert report["errors"][0]["file_ids"] == [101]
    assert "RuntimeError: ES failed" in report["errors"][0]["traceback"]


async def test_old_batch_check_is_not_called(backend, tmp_path):
    backend.ensure_no_pending.side_effect = AssertionError("must not query old batches")
    assert await m.execute(arguments(True), backend, tmp_path / "report.json") == 0
    backend.ensure_no_pending.assert_not_awaited()
    assert backend.move_unit.await_count == 2


async def test_folder_failure_does_not_block_other_folders(backend, tmp_path):
    backend.ensure_folder.side_effect = [RuntimeError("folder failed"), 200]
    path = tmp_path / "report.json"
    assert await m.execute(arguments(True), backend, path) == 2
    assert backend.move_unit.await_count == 1
    assert backend.move_unit.await_args.args[0]["document_id"] == 2
    report = json.loads(path.read_text())
    assert report["errors"][0]["scope"] == "folder"
    assert report["errors"][0]["file_ids"] == [101]


@pytest.mark.parametrize("changes", [{"file_subcategory_code": "JQ02"}, {"user_metadata": {}}])
async def test_changed_classification_or_ingest_method_is_not_moved(backend, snapshot, tmp_path, changes):
    changed = deepcopy(snapshot)
    for key, value in changes.items():
        setattr(changed["files"][0], key, value)
    backend.load_snapshot.side_effect = [snapshot, changed, snapshot]
    path = tmp_path / "report.json"
    assert await m.execute(arguments(True), backend, path) == 2
    assert backend.move_unit.await_count == 1
    assert backend.move_unit.await_args.args[0]["document_id"] == 2
    assert "已变化" in json.loads(path.read_text())["errors"][0]["error"]


def test_apply_requires_real_operator_and_recovery_requires_apply():
    with pytest.raises(SystemExit):
        m.parse_args(["--apply"])
    with pytest.raises(SystemExit):
        m.parse_args(["--recover-report", "old.json"])


async def test_missing_canonical_documents_are_skipped(backend, snapshot, tmp_path):
    snapshot["versions"] = []
    path = tmp_path / "report.json"
    assert await m.execute(arguments(True), backend, path) == 0
    backend.move_unit.assert_not_awaited()
    assert json.loads(path.read_text())["status"] == "completed_with_skips"


@pytest.mark.parametrize("force_rewrite", [False, True])
async def test_recovery_uses_journal_even_when_files_left_source(backend, tmp_path, force_rewrite):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "execution_mode": "rehome_shared",
                "tenant_id": 1,
                "units": [{"document_id": 1, "status": "committing", "before": {"backup": True}}],
            }
        )
    )
    argv = ["--apply", "--operator-id", "1", "--tenant-id", "1", "--recover-report", str(path)]
    if force_rewrite:
        argv.append("--force-rewrite")
    args = m.parse_args(argv)
    assert await m.execute(args, backend, path) == 0
    backend.load_snapshot.assert_not_awaited()
    assert backend.move_unit.await_args.kwargs == {
        "recover": True,
        **({"force_rewrite": True} if force_rewrite else {}),
    }


async def test_recovery_failure_continues_and_preserves_prior_errors(backend, tmp_path):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "execution_mode": "rehome_shared",
                "tenant_id": 1,
                "errors": [{"error": "previous failure"}],
                "units": [{"document_id": i, "status": "failed", "before": {"backup": True}} for i in (1, 2)],
            }
        )
    )

    async def recover(unit, checkpoint, **kwargs):
        if unit["document_id"] == 1:
            raise RuntimeError("recovery failed")
        unit["status"] = "restored"
        checkpoint()

    backend.move_unit.side_effect = recover
    args = m.parse_args(["--apply", "--operator-id", "1", "--tenant-id", "1", "--recover-report", str(path)])
    assert await m.execute(args, backend, path) == 2
    assert backend.move_unit.await_count == 2
    report = json.loads(path.read_text())
    assert report["errors"][0]["error"] == "previous failure"
    assert report["summary"]["needs_recovery"] == 1
    assert report["summary"]["restored_documents"] == 1


@pytest.mark.parametrize("interruption", ["cancel", "report_unwritable"])
async def test_interruption_or_unwritable_report_stops_new_writes(backend, tmp_path, monkeypatch, interruption):
    import asyncio

    async def fail(unit, checkpoint):
        unit.update(before={"backup": True}, status="prepared")
        if interruption == "cancel":
            raise asyncio.CancelledError()

        def unwritable(*args):
            raise OSError("disk full")

        monkeypatch.setattr(m, "save_report", unwritable)
        checkpoint()

    backend.move_unit.side_effect = fail
    error = asyncio.CancelledError if interruption == "cancel" else m.ReportWriteError
    path = tmp_path / "report.json"
    with pytest.raises(error):
        await m.execute(arguments(True), backend, path)
    assert backend.move_unit.await_count == 1
    if interruption == "cancel":
        assert json.loads(path.read_text())["status"] == "needs_recovery"


async def test_real_database_scan_pages_excludes_deleted_and_loads_complete_version_chain(snapshot, monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import datetime

    from sqlalchemy import DefaultClause, MetaData, event, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.core import database
    from bisheng.database.models.department import Department
    from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
    from bisheng.knowledge.domain.models.knowledge import Knowledge
    from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceScope
    from bisheng.shougang_portal_config.domain.services.portal_config_service import ShougangPortalConfigService

    models = [
        Knowledge,
        KnowledgeSpaceScope,
        Department,
        DepartmentKnowledgeSpace,
        KnowledgeFile,
        KnowledgeDocumentVersion,
    ]
    metadata = MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all([Knowledge(**vars(row), tenant_id=1, type=3, user_id=1) for row in snapshot["spaces"]])
            session.add_all([KnowledgeSpaceScope(**vars(row), tenant_id=1, owner_id=1) for row in snapshot["scopes"]])
            session.add(Department(id=1, dept_id="D1", name="科室", tenant_id=1))
            session.add_all([DepartmentKnowledgeSpace(**vars(row), tenant_id=1) for row in snapshot["bindings"]])
            rows = [*snapshot["files"], *(file(index) for index in range(1000, 1501))]
            for row in rows:
                values = vars(row).copy()
                if values["deleted_at"]:
                    values["deleted_at"] = datetime(2026, 9, 20)
                session.add(KnowledgeFile(**values, tenant_id=1))
            session.add_all(
                [
                    KnowledgeDocumentVersion(document_id=1, knowledge_file_id=101, version_no=1),
                    KnowledgeDocumentVersion(document_id=1, knowledge_file_id=999, version_no=2),
                ]
            )
            await session.commit()

        @asynccontextmanager
        async def connection():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                yield session

        monkeypatch.setattr(database, "get_async_db_session", connection)
        monkeypatch.setattr(ShougangPortalConfigService, "get_config", AsyncMock(return_value=snapshot["config"]))
        statements = []
        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            lambda conn, cursor, statement, *args: statements.append(statement),
        )
        with m.tenant_context(1):
            actual = await m.Backend().load_snapshot(1)
            assert await m.Backend().ensure_folder(None, 20, "炼钢") == 200
            narrowed = await m.Backend().load_snapshot(1, file_ids={101})
            assert {row.id for row in narrowed["files"]} == {101, 200}
            assert {row.knowledge_file_id for row in narrowed["versions"]} == {101, 999}
            assert m.build_plan(narrowed, 1)["candidate_files"] == 0
        assert 104 not in [row.id for row in actual["files"]]
        assert {row.knowledge_file_id for row in actual["versions"]} == {101, 999}
        assert m.build_plan(actual, 1)["candidate_files"] == 502
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    finally:
        await engine.dispose()


def test_tenant_scope_forces_selected_tenant_and_restores_context(monkeypatch):
    from bisheng.common.services import config_service
    from bisheng.core.context.tenant import current_tenant_id, visible_tenant_ids
    from bisheng.core.database.tenant_filter import _resolve_tenant_id, _resolve_visible_tenant_ids

    monkeypatch.setattr(config_service, "settings", NS(multi_tenant=NS(enabled=True)))
    old = current_tenant_id.get(), visible_tenant_ids.get()
    with m.tenant_context(7):
        assert _resolve_visible_tenant_ids() is None
        assert _resolve_tenant_id() == 7
        with m.tenant_context(8):
            assert _resolve_tenant_id() == 8
        assert _resolve_tenant_id() == 7
    assert (current_tenant_id.get(), visible_tenant_ids.get()) == old


async def test_unfinished_report_does_not_block_new_apply(backend, tmp_path):
    (tmp_path / "old.json").write_text(
        json.dumps(
            {
                "execution_mode": "rehome_shared",
                "tenant_id": 1,
                "status": "planned",
                "units": [{"status": "prepared", "before": {"backup": True}}],
            }
        )
    )
    assert await m.execute(arguments(True), backend, tmp_path / "new.json") == 0
    assert backend.move_unit.await_count == 2
    assert json.loads((tmp_path / "old.json").read_text())["units"][0]["status"] == "prepared"


async def test_progress_logs_while_stage_is_waiting(monkeypatch, capsys):
    import asyncio

    observed = asyncio.Event()
    original = m.log_progress

    def observe(message):
        original(message)
        if "进行中" in message:
            observed.set()

    monkeypatch.setattr(m, "log_progress", observe)
    async with m.progress_stage("等待测试阶段", interval=0.001):
        await asyncio.wait_for(observed.wait(), timeout=1)
    output = capsys.readouterr().out
    assert "开始：等待测试阶段" in output  # noqa: RUF001
    assert "进行中：等待测试阶段" in output  # noqa: RUF001
    assert "完成：等待测试阶段" in output  # noqa: RUF001


@pytest.mark.parametrize("fail", [False, True])
async def test_shared_storage_needs_no_redis_lock_and_closes_on_exit(monkeypatch, fail):
    from unittest.mock import Mock

    from bisheng.core.cache import redis_manager
    from bisheng.knowledge.rag import shared_space_storage, shared_storage_reconcile

    redis = AsyncMock(side_effect=AssertionError("must not access Redis for maintenance locks"))
    monkeypatch.setattr(redis_manager, "get_redis_client", redis)
    route = NS(tenant_id=1)
    loader = Mock(return_value=route)
    monkeypatch.setattr(shared_space_storage, "load_tenant_routing_snapshot", loader)
    monkeypatch.setattr(shared_space_storage, "require_initialized_shared_routing", lambda tenant_id, value: value)
    store = NS(close=AsyncMock())
    factory = Mock(return_value=store)
    monkeypatch.setattr(shared_storage_reconcile, "SharedStorageReconcileAdapter", factory)
    backend = m.Backend()

    async def run():
        async with backend.shared_storage(1):
            assert backend.store is store
            assert await factory.call_args.kwargs["guard"]() is None
            if fail:
                raise RuntimeError("migration failed")

    if fail:
        with pytest.raises(RuntimeError, match="migration failed"):
            await run()
    else:
        await run()
    loader.assert_called_once_with(1)
    redis.assert_not_awaited()
    store.close.assert_awaited_once()
