"""部门迁移的独立部署、原记录迁移及定向查询回归。"""

import ast
from pathlib import Path

import pytest

from scripts import move_department_files_to_personal as m
from test.scripts.test_move_department_files_to_personal import personal, snapshot


def test_deployable_without_other_scripts():
    tree = ast.parse(Path(m.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(name == "scripts" or name.startswith("scripts.") for name in imports if name)


@pytest.mark.parametrize("status", [3, 6])
def test_failed_source_and_model_difference_are_migratable(status):
    state = snapshot()
    personal(state)
    state.files[2].status = status
    state.spaces[-1].model = "other-model"
    plan = m.build_plan(state, "待整理")
    assert len(plan.candidates) == 1
    assert not plan.skipped


@pytest.fixture
def database(monkeypatch):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import Column, DefaultClause, Integer, MetaData, String, create_engine, text
    from sqlalchemy.orm import declarative_base
    from sqlmodel import Session

    from test.scripts.test_move_department_files_to_personal import add_chain, add_existing_target

    registry = declarative_base()

    class Owner(registry):
        __tablename__ = "department_move_owner"
        user_id = Column(Integer, primary_key=True)
        user_name = Column(String)
        delete = Column(Integer)

    monkeypatch.setattr(m, "User", Owner)
    monkeypatch.setattr(m.settings.multi_tenant, "enabled", False)
    engine = create_engine("sqlite://")
    metadata = MetaData()
    for model in [
        m.Knowledge,
        m.KnowledgeSpaceScope,
        m.KnowledgeFile,
        m.KnowledgeDocument,
        m.KnowledgeDocumentVersion,
        m.KnowledgeFileSimilarityCandidate,
        m.PortalRecommendationFileProjection,
        m.ShareLink,
    ]:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    metadata.create_all(engine)
    registry.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    statements = []

    class Adapter:
        async def exec(self, statement):
            statements.append(statement)
            descriptions = getattr(statement, "column_descriptions", [])
            if descriptions and descriptions[0].get("entity") is m.ApprovalInstance:
                return SimpleNamespace(all=lambda: [])
            return db.exec(statement)

        async def get(self, model, key):
            return db.get(model, key)

        def add(self, row):
            db.add(row)

        async def flush(self):
            db.flush()

        async def commit(self):
            db.commit()

        async def rollback(self):
            db.rollback()

        async def refresh(self, row):
            db.refresh(row)

    @asynccontextmanager
    async def connection():
        yield Adapter()

    monkeypatch.setattr(m, "get_async_db_session", connection)
    state = snapshot()
    personal(state)
    add_chain(state)
    add_existing_target(state)
    for scope in state.scopes:
        scope.created_by = 7
    for file in state.files:
        if file.file_type == 1:
            file.object_name = f"original/{file.id}.pdf"
    for row in [*state.spaces, *state.scopes, *state.files, *state.documents, *state.versions]:
        db.add(type(row)(**row.model_dump()))
    db.add(Owner(user_id=7, user_name="张三", delete=0))
    db.commit()
    backend = m.Backend()
    service = SimpleNamespace(login_user=SimpleNamespace(user_id=7))
    monkeypatch.setattr(backend, "service_for", AsyncMock(return_value=service))
    monkeypatch.setattr(backend, "initialize_apply", AsyncMock())
    permissions = {
        fid: [
            {"user": "folder:12", "relation": "parent", "object": f"knowledge_file:{fid}"},
            {"user": "user:7", "relation": "owner", "object": f"knowledge_file:{fid}"},
        ]
        for fid in [101, 102, 201]
    }

    async def read(fid):
        return tuple(permissions.get(fid, []))

    async def write(fid, rows):
        permissions[fid] = list(rows)

    monkeypatch.setattr(m, "_read_permission_tuples", read)
    monkeypatch.setattr(m, "_replace_permission_tuples", write)
    monkeypatch.setattr(
        m,
        "_read_resource_permission_tuples",
        AsyncMock(return_value=[{"user": "user:7", "relation": "owner", "object": "knowledge_space:20"}]),
    )
    monkeypatch.setattr(m, "_clear_tag_links", AsyncMock(return_value=None))
    monkeypatch.setattr(m, "_refresh_merge_projections", AsyncMock(return_value=None))
    yield SimpleNamespace(
        db=db, backend=backend, statements=statements, permissions=permissions, service=service, engine=engine
    )
    db.close()
    engine.dispose()


@pytest.mark.parametrize("failure", ["none", "empty", "milvus_read", "es_write", "cleanup"])
async def test_real_batch_rehomes_records_and_full_chain(database, monkeypatch, tmp_path, failure):
    import json
    from unittest.mock import Mock

    env = database
    row = {"text": "test content", "vector": [1.0], "document_id": 101, "knowledge_id": 10, "pk": 1}
    read = Mock(return_value=([row], None))
    if failure == "empty":
        read.return_value = ([], None)
    if failure == "milvus_read":
        read.side_effect = RuntimeError("Milvus unavailable")
    monkeypatch.setattr(m, "_read_merge_milvus", read)
    monkeypatch.setattr(m, "_read_merge_es", Mock(return_value=[] if failure == "empty" else [{"text": "from ES"}]))
    monkeypatch.setattr(m, "_write_merge_milvus", Mock())
    monkeypatch.setattr(
        m, "_write_merge_es", Mock(side_effect=RuntimeError("ES unavailable") if failure == "es_write" else None)
    )
    cleanup = Mock(return_value=["cleanup ES unavailable"] if failure == "cleanup" else [])
    monkeypatch.setattr(m, "_cleanup_record_indexes", cleanup)
    args = m.parse_args(["--folder-name", "待整理", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 0
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == ("completed" if failure == "none" else "completed_with_reparse")
    assert report["pending"] == 0
    assert report["reparse_file_ids"] == ([] if failure == "none" else [101, 102])
    env.db.expire_all()
    for fid in [101, 102]:
        f = env.db.get(m.KnowledgeFile, fid)
        assert (f.knowledge_id, f.user_id, f.file_level_path, f.object_name) == (20, 7, "/21/22", f"original/{fid}.pdf")
        assert f.status == (2 if failure == "none" else 3)
        assert {"user": "folder:22", "relation": "parent", "object": f"knowledge_file:{fid}"} in env.permissions[fid]
        assert all(r["user"] != "folder:12" for r in env.permissions[fid])
    assert env.db.get(m.KnowledgeFile, 201) is None
    document = env.db.get(m.KnowledgeDocument, 50)
    assert (document.knowledge_id, document.file_level_path, document.primary_version_id) == (20, "/21/22", 502)
    assert {v.id for v in env.db.exec(m.select(m.KnowledgeDocumentVersion)).all()} == {501, 502}
    assert env.db.get(m.Knowledge, 10) is not None
    assert env.db.get(m.KnowledgeFile, 11) is not None
    assert env.db.get(m.KnowledgeFile, 12) is not None
    assert not m.build_plan(await env.backend.load(1, folder_name="待整理", source_space_id=10), "待整理").candidates


@pytest.mark.parametrize("failure", ["permissions", "database", "journal"])
async def test_failed_critical_step_preserves_source_and_old_target(database, monkeypatch, tmp_path, failure):
    import copy
    import json
    from unittest.mock import Mock

    from sqlalchemy import event

    env = database
    original = copy.deepcopy(env.permissions)
    monkeypatch.setattr(m, "_transfer_record_indexes", Mock(return_value={"issues": [], "via": "milvus"}))
    cleanup = Mock(return_value=[])
    monkeypatch.setattr(m, "_cleanup_record_indexes", cleanup)
    if failure == "permissions":
        write = m._replace_permission_tuples

        async def broken(fid, rows):
            await write(fid, rows)
            if fid == 102 and rows[0].get("relation") == "owner":
                raise RuntimeError("permission failure")

        monkeypatch.setattr(m, "_replace_permission_tuples", broken)
    if failure == "database":

        def fail_delete(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("DELETE FROM knowledgefile"):
                raise RuntimeError("delete failure")

        event.listen(env.engine, "before_cursor_execute", fail_delete)
    if failure == "journal":
        record = m.record_event

        def broken(journal, kind, payload):
            if kind == "permission_transfer_started":
                raise OSError("disk full")
            record(journal, kind, payload)

        monkeypatch.setattr(m, "record_event", broken)
    args = m.parse_args(["--folder-name", "待整理", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 3
    env.db.expire_all()
    assert env.db.get(m.KnowledgeFile, 201) is not None
    assert env.db.get(m.KnowledgeFile, 101).knowledge_id == 10
    assert env.db.get(m.KnowledgeDocument, 50).knowledge_id == 10
    assert env.permissions[101] == original[101]
    assert env.permissions[102] == original[102]
    cleanup.assert_not_called()
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["status"] == "failed"


async def test_queries_limit_files_and_keep_external_reference_protection(database):
    from test.scripts.test_move_department_files_to_personal import file, space

    env = database
    env.db.add(space(99, name="unrelated"))
    extra = file(999, "", share_source_file_id=101)
    env.db.add(m.KnowledgeFile(**{**extra.model_dump(), "knowledge_id": 99}))
    env.db.commit()
    env.statements.clear()
    discovery = await env.backend.load(1, metadata_only=True)
    assert {s.id for s in discovery.spaces} == {10} and not discovery.files
    assert not any("FROM knowledgefile" in str(s) for s in env.statements)
    state = await env.backend.load(1, folder_name="待整理", source_space_id=10)
    assert 999 not in {f.id for f in state.files}
    assert 101 in state.referenced_file_ids
    assert not m.build_plan(state, "待整理").candidates
    assert all("WHERE" in str(s) for s in env.statements if "FROM knowledgefile" in str(s))


async def test_same_name_later_department_replaces_entire_previous_chain(database, monkeypatch, tmp_path):
    import json
    from unittest.mock import Mock

    from test.scripts.test_move_department_files_to_personal import file, folder, scope, space

    env = database
    env.db.add(space(30))
    dep_scope = scope(30)
    dep_scope.created_by = 7
    env.db.add(dep_scope)
    env.db.add(folder(31, "待整理", sid=30))
    env.db.add(folder(32, "制度", "/31", sid=30))
    source = file(301, "/31/32")
    env.db.add(m.KnowledgeFile(**{**source.model_dump(), "knowledge_id": 30, "object_name": "original/301.pdf"}))
    env.db.commit()
    monkeypatch.setattr(
        m,
        "_transfer_record_indexes",
        Mock(
            side_effect=lambda f, *a: (
                {"via": "none", "issues": ["no chunks"]} if f.id != 301 else {"via": "milvus", "issues": []}
            )
        ),
    )
    monkeypatch.setattr(m, "_cleanup_record_indexes", Mock(return_value=[]))
    args = m.parse_args(["--folder-name", "待整理", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 0
    env.db.expire_all()
    assert {f.id for f in env.db.exec(m.select(m.KnowledgeFile).where(m.KnowledgeFile.file_type == 1)).all()} == {301}
    assert env.db.get(m.KnowledgeDocument, 50) is None
    assert not env.db.exec(m.select(m.KnowledgeDocumentVersion)).all()
    result = env.db.get(m.KnowledgeFile, 301)
    assert (result.knowledge_id, result.file_level_path, result.status) == (20, "/21/22", 2)
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["planned"][1]["replaces_planned_unit_ids"] == ["document:50"]
    assert report["reparse_file_ids"] == []
    assert env.db.get(m.Knowledge, 10) and env.db.get(m.Knowledge, 30)


async def test_missing_personal_library_creates_once_and_keeps_directory_tree(database, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, Mock

    from test.scripts.test_move_department_files_to_personal import folder, scope, space

    env = database
    env.db.exec(m.delete(m.KnowledgeFile).where(m.KnowledgeFile.knowledge_id == 20))
    env.db.exec(m.delete(m.KnowledgeSpaceScope).where(m.KnowledgeSpaceScope.space_id == 20))
    env.db.exec(m.delete(m.Knowledge).where(m.Knowledge.id == 20))
    env.db.commit()

    async def create(user):
        target = space(20, name="张三的知识库")
        s = scope(20, "personal")
        s.created_by = 7
        env.db.add(target)
        env.db.add(s)
        env.db.commit()
        env.db.refresh(target)
        return target

    async def add(sid, name, parent):
        row = folder(21 if parent is None else 22, name, "" if parent is None else f"/{parent}", sid)
        env.db.add(row)
        env.db.commit()
        env.db.refresh(row)
        return row

    env.service.ensure_personal_default_space_for_owner = AsyncMock(side_effect=create)
    env.service.add_folder = AsyncMock(side_effect=add)
    monkeypatch.setattr(m, "_transfer_record_indexes", Mock(return_value={"via": "none", "issues": ["no chunks"]}))
    monkeypatch.setattr(m, "_cleanup_record_indexes", Mock(return_value=[]))
    args = m.parse_args(["--folder-name", "待整理", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 0
    env.service.ensure_personal_default_space_for_owner.assert_awaited_once()
    assert env.service.add_folder.await_count == 2
    assert env.db.get(m.KnowledgeFile, 101).file_level_path == "/21/22"


async def test_preview_never_changes_records_or_permissions(database, tmp_path):
    import copy

    env = database
    before = copy.deepcopy(env.permissions)
    args = m.parse_args(["--folder-name", "待整理", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 0
    env.backend.initialize_apply.assert_not_awaited()
    env.backend.service_for.assert_not_awaited()
    assert env.permissions == before
    assert env.db.get(m.KnowledgeFile, 101).knowledge_id == 10
    assert env.db.get(m.KnowledgeFile, 201).knowledge_id == 20


async def test_invalid_lowest_personal_library_is_not_silently_replaced(database):
    from test.scripts.test_move_department_files_to_personal import scope, space

    env = database
    first = env.db.get(m.Knowledge, 20)
    first.user_id = 99
    env.db.add(first)
    env.db.add(space(30, name="张三的知识库"))
    target_scope = scope(30, "personal")
    target_scope.created_by = 7
    env.db.add(target_scope)
    env.db.commit()
    state = await env.backend.load(1, folder_name="待整理", source_space_id=10)
    plan = m.build_plan(state, "待整理")
    assert not plan.candidates
    assert plan.skipped[0]["reason"] == "invalid_personal_space"


async def test_uncertain_commit_never_restores_department_access_to_moved_file(database, monkeypatch, tmp_path):
    from unittest.mock import Mock

    env = database
    original = m._rehome_file_records

    async def lost_response(*args):
        await original(*args)
        raise RuntimeError("commit response lost")

    monkeypatch.setattr(m, "_rehome_file_records", lost_response)
    monkeypatch.setattr(m, "_transfer_record_indexes", Mock(return_value={"via": "none", "issues": ["no chunks"]}))
    cleanup = Mock(return_value=[])
    monkeypatch.setattr(m, "_cleanup_record_indexes", cleanup)
    args = m.parse_args(["--folder-name", "待整理", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=env.backend) == 3
    env.db.expire_all()
    for fid in [101, 102]:
        assert env.db.get(m.KnowledgeFile, fid).knowledge_id == 20
        assert not any(row["user"] == "folder:12" for row in env.permissions[fid])
        assert any(row["user"] == "folder:22" for row in env.permissions[fid])
    cleanup.assert_not_called()
