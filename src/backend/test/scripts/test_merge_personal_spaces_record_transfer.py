"""合库以记录归属为准, 索引失败降级为待重新解析。"""

from unittest.mock import Mock

import pytest

from test.scripts.test_merge_personal_knowledge_spaces import file, m, space


@pytest.mark.parametrize("mode", ["milvus", "es", "empty", "milvus_read_error", "milvus_write_error", "es_write_error"])
def test_index_fallback_keeps_available_content(monkeypatch, mode):
    rows = [{"text": "content", "vector": [1.0], "document_id": 101, "knowledge_id": 10, "pk": 5}]
    read_m = Mock(return_value=(rows if mode in {"milvus", "milvus_write_error", "es_write_error"} else [], None))
    if mode == "milvus_read_error":
        read_m.side_effect = RuntimeError("milvus unavailable")
    read_es = Mock(
        return_value=[{"text": "content", "document_id": 101, "knowledge_id": 10}]
        if mode in {"es", "milvus_read_error"}
        else []
    )
    write_m, write_es = Mock(), Mock()
    if mode == "milvus_write_error":
        write_m.side_effect = RuntimeError("milvus insert failed")
    if mode == "es_write_error":
        write_es.side_effect = RuntimeError("es insert failed")
    monkeypatch.setattr(m, "_read_merge_milvus", read_m, raising=False)
    monkeypatch.setattr(m, "_read_merge_es", read_es, raising=False)
    monkeypatch.setattr(m, "_write_merge_milvus", write_m, raising=False)
    monkeypatch.setattr(m, "_write_merge_es", write_es, raising=False)
    result = m._transfer_record_indexes(file(101, ""), space(), space(20))
    assert bool(result["issues"]) == (mode != "milvus")
    if mode != "empty":
        assert write_es.call_count == 1
        assert write_es.call_args.args[0][0]["knowledge_id"] == 20
        assert write_es.call_args.args[0][0]["document_id"] == 101
    if mode == "milvus":
        read_es.assert_not_called()
        assert result["milvus_count"] == result["es_count"] == 1
    if mode == "milvus_write_error":
        assert result["es_count"] == 1 and result["milvus_count"] == 0
    if mode == "es_write_error":
        assert result["milvus_count"] == 1 and result["es_count"] == 0


@pytest.fixture
def record_db(monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy import DefaultClause, MetaData, create_engine, text
    from sqlmodel import Session

    from test.scripts.test_merge_personal_knowledge_spaces import add_root_chain, snapshot

    engine = create_engine("sqlite://")
    models = [
        m.Knowledge,
        m.KnowledgeSpaceScope,
        m.KnowledgeFile,
        m.KnowledgeDocument,
        m.KnowledgeDocumentVersion,
        m.KnowledgeFileSimilarityCandidate,
        m.PortalRecommendationFileProjection,
        m.ShareLink,
    ]
    metadata = MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)

    class Adapter:
        async def exec(self, statement):
            return session.exec(statement)

        async def get(self, model, identity):
            return session.get(model, identity)

        def add(self, row):
            session.add(row)

        async def commit(self):
            session.commit()

        async def rollback(self):
            session.rollback()

        async def refresh(self, row):
            session.refresh(row)

    @asynccontextmanager
    async def connection():
        yield Adapter()

    monkeypatch.setattr(m, "get_async_db_session", connection)
    state = snapshot()
    add_root_chain(state)
    state.files.append(file(101, "", object_name="keep/original.pdf"))
    state.files[0].object_name = "keep/original.pdf"
    state.files[1].object_name = "keep/version2.pdf"
    state.files = [m.KnowledgeFile(**row.model_dump()) for row in state.files]
    state.documents = [m.KnowledgeDocument(**row.model_dump()) for row in state.documents]
    state.versions = [m.KnowledgeDocumentVersion(**row.model_dump()) for row in state.versions]
    for scope in state.scopes:
        scope.created_by = 7
    session.add_all([*state.spaces, *state.scopes])
    for row in [*state.files, *state.documents, *state.versions]:
        session.add(row)
    session.commit()
    for row in [*state.files, *state.documents, *state.versions]:
        session.refresh(row)
    yield state, session
    session.close()
    engine.dispose()


@pytest.mark.parametrize("problem", ["none", "indexes", "cleanup", "permissions"])
async def test_record_merge_keeps_ids_objects_and_versions_despite_external_errors(
    record_db, monkeypatch, tmp_path, problem
):
    import copy
    from unittest.mock import AsyncMock

    state, db = record_db
    candidate = m.build_plan(copy.deepcopy(state)).candidates[0]
    expected_version_ids = [v.id for v in state.versions]
    backend = m.Backend()
    target = m.TargetContext(1, candidate.target_space, None, candidate.owner, "", 0)
    monkeypatch.setattr(backend, "ensure_space", AsyncMock(return_value=(None, target.space)))
    monkeypatch.setattr(backend, "prepare_folders", AsyncMock(return_value=target))
    monkeypatch.setattr(
        m,
        "_transfer_record_indexes",
        Mock(
            return_value={
                "via": "none" if problem == "indexes" else "milvus",
                "milvus_count": 0,
                "es_count": 0,
                "issues": ["both unavailable"] if problem == "indexes" else [],
            }
        ),
    )
    monkeypatch.setattr(
        m, "_cleanup_record_indexes", Mock(return_value=["cleanup timeout"] if problem == "cleanup" else [])
    )
    permissions = AsyncMock(side_effect=RuntimeError("FGA unavailable") if problem == "permissions" else None)
    monkeypatch.setattr(m, "_replace_permission_tuples", permissions)
    monkeypatch.setattr(m, "_clear_tag_links", AsyncMock())
    monkeypatch.setattr(m, "_refresh_merge_projections", AsyncMock(return_value=None))
    minio = Mock(side_effect=AssertionError("must not touch original objects"))
    monkeypatch.setattr(m, "get_minio_storage_sync", minio)
    journal = m.RollbackJournal(path=tmp_path / "record.jsonl", run_id="record")
    journal.open()
    result = await backend.execute(candidate, journal)
    journal.close()
    assert result["status"] == "success"
    assert result["requires_reparse"] == (problem != "none")
    db.expire_all()
    assert db.get(m.KnowledgeFile, 101) is None
    for fid, name in [(201, "keep/original.pdf"), (202, "keep/version2.pdf")]:
        row = db.get(m.KnowledgeFile, fid)
        assert row.knowledge_id == 10 and row.object_name == name
        assert row.status == (2 if problem == "none" else 3)
    doc = db.get(m.KnowledgeDocument, 50)
    assert doc.knowledge_id == 10 and doc.primary_version_id == 502
    assert [v.id for v in db.exec(m.select(m.KnowledgeDocumentVersion)).all()] == expected_version_ids
    minio.assert_not_called()
    state.files = list(db.exec(m.select(m.KnowledgeFile)).all())
    state.documents = [doc]
    group = m.find_groups(state)[0][0]
    assert m.cleanup_reason(state, group, group.sources[0], []) is None


async def test_changed_version_graph_rolls_back_overwrite_and_rehome(record_db):
    import copy

    state, db = record_db
    candidate = m.build_plan(copy.deepcopy(state)).candidates[0]
    db.get(m.KnowledgeDocumentVersion, 502).is_primary = False
    db.commit()
    target = m.TargetContext(1, candidate.target_space, None, candidate.owner, "", 0)
    with pytest.raises(m.PreflightError, match="version_graph_changed"):
        await m._rehome_file_records(candidate, target, {f.id: {"issues": []} for f in candidate.files})
    assert db.get(m.KnowledgeFile, 101) is not None
    assert db.get(m.KnowledgeFile, 201).knowledge_id == 20
    assert db.get(m.KnowledgeDocument, 50).knowledge_id == 20


@pytest.mark.parametrize("status,planned", [(2, True), (3, True), (6, True), (1, False), (4, False), (5, False)])
def test_planning_failed_files_and_different_models(status, planned):
    from test.scripts.test_merge_personal_knowledge_spaces import snapshot

    state = snapshot()
    state.files[0].status = status
    state.spaces[0].model = "different-model"
    assert bool(m.build_plan(state).candidates) is planned


@pytest.mark.parametrize("empty", [False, True])
async def test_empty_space_database_fallback_preserves_nonempty_source(record_db, empty):
    state, db = record_db
    if empty:
        for record in state.files:
            record.knowledge_id = 10
        for document in state.documents:
            document.knowledge_id = 10
        db.commit()
        await m._delete_empty_space_records(20)
        assert db.get(m.Knowledge, 20) is None
        assert db.exec(m.select(m.KnowledgeSpaceScope).where(m.KnowledgeSpaceScope.space_id == 20)).first() is None
        assert db.get(m.KnowledgeFile, 201).object_name == "keep/original.pdf"
    else:
        with pytest.raises(m.PreflightError, match="source_not_empty"):
            await m._delete_empty_space_records(20)
        assert db.get(m.Knowledge, 20) is not None
        assert db.get(m.KnowledgeFile, 201).knowledge_id == 20


async def test_empty_library_is_removed_even_if_external_cleanup_fails(record_db, monkeypatch, tmp_path):
    import copy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao

    state, db = record_db
    for record in state.files:
        record.knowledge_id = 10
    for document in state.documents:
        document.knowledge_id = 10
    db.commit()
    backend = m.Backend()
    monkeypatch.setattr(backend, "load", AsyncMock(return_value=copy.deepcopy(state)))
    monkeypatch.setattr(
        backend,
        "service_for",
        AsyncMock(return_value=SimpleNamespace(delete_space=AsyncMock(side_effect=RuntimeError("ES unavailable")))),
    )
    monkeypatch.setattr(SpaceChannelMemberDao, "clean_space_member", AsyncMock())
    monkeypatch.setattr(m, "_replace_resource_permission_tuples", AsyncMock())
    group = m.build_plan(state).groups[0]
    journal = m.RollbackJournal(path=tmp_path / "delete.jsonl", run_id="delete")
    journal.open()
    issues = await backend.delete_empty_source(
        group, group.sources[0], [], journal, {201: m.file_identity(state.files[0])}
    )
    journal.close()
    assert issues and "ES unavailable" in issues[0]
    db.expire_all()
    assert db.get(m.Knowledge, 20) is None
    assert db.get(m.KnowledgeFile, 201).status == 3


async def test_default_batch_merges_libraries_and_reports_reparse_ids(record_db, monkeypatch, tmp_path):
    import copy
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from bisheng.common.models.space_channel_member import SpaceChannelMemberDao

    state, db = record_db
    backend = m.Backend()

    async def load(tenant_id, **kwargs):
        current = copy.deepcopy(state)
        for field, model in [
            ("spaces", m.Knowledge),
            ("scopes", m.KnowledgeSpaceScope),
            ("files", m.KnowledgeFile),
            ("documents", m.KnowledgeDocument),
            ("versions", m.KnowledgeDocumentVersion),
        ]:
            setattr(current, field, [row.model_copy(deep=True) for row in db.exec(m.select(model)).all()])
        return current

    async def folders(candidate, *args):
        return m.TargetContext(1, candidate.target_space, None, candidate.owner, "", 0)

    monkeypatch.setattr(backend, "load", load)
    monkeypatch.setattr(backend, "initialize_apply", AsyncMock())
    monkeypatch.setattr(backend, "prepare_folders", folders)
    monkeypatch.setattr(
        backend,
        "service_for",
        AsyncMock(return_value=SimpleNamespace(delete_space=AsyncMock(side_effect=RuntimeError("ES unavailable")))),
    )
    monkeypatch.setattr(m, "_read_resource_permission_tuples", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "_replace_resource_permission_tuples", AsyncMock())
    monkeypatch.setattr(m, "_replace_permission_tuples", AsyncMock())
    monkeypatch.setattr(m, "_clear_tag_links", AsyncMock())
    monkeypatch.setattr(m, "_refresh_merge_projections", AsyncMock(return_value=None))
    monkeypatch.setattr(
        m,
        "_transfer_record_indexes",
        Mock(return_value={"via": "none", "milvus_count": 0, "es_count": 0, "issues": ["no readable index chunks"]}),
    )
    monkeypatch.setattr(m, "_cleanup_record_indexes", Mock(return_value=[]))
    monkeypatch.setattr(SpaceChannelMemberDao, "clean_space_member", AsyncMock())
    monkeypatch.setattr(m.settings.multi_tenant, "enabled", False)
    args = m.parse_args(["--all-users", "--apply", "--report-dir", str(tmp_path)])
    assert await m.run(args, backend=backend) == 0
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert report["status"] == "completed_with_reparse"
    assert report["pending"] == report["pending_sources"] == 0
    assert report["reparse_file_ids"] == [201, 202]
    assert report["source_counts"] == {"deleted": 1}
    assert [s.id for s in db.exec(m.select(m.Knowledge)).all()] == [10]
    assert {f.id for f in db.exec(m.select(m.KnowledgeFile)).all()} == {201, 202}
    assert not m.build_plan(await load(1)).groups
