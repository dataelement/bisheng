"""单文件合并的查询范围、规划复杂度及审计开销回归。"""

import copy
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, DefaultClause, Integer, MetaData, String, create_engine, text
from sqlalchemy.orm import declarative_base
from sqlmodel import Session

from scripts import merge_personal_knowledge_spaces as m
from test.scripts.test_merge_personal_knowledge_spaces import add_root_chain, file, runtime, scope, snapshot, space


@pytest.mark.parametrize("count", [10, 300])
def test_planning_indexes_whole_file_list_once(count):
    class CountedList(list):
        traversals = 0

        def __iter__(self):
            self.traversals += 1
            return super().__iter__()

    state = snapshot()
    state.files = CountedList(
        [file(1000 + i, "").model_copy(update={"knowledge_id": 20, "file_name": f"{i}.pdf"}) for i in range(count)]
    )
    assert len(m.build_plan(state).candidates) == count
    assert state.files.traversals <= 2


async def test_apply_uses_focused_rechecks_and_batches_report(monkeypatch, tmp_path):
    state, backend, _calls, args = runtime(monkeypatch, tmp_path)
    state.files = [
        file(200 + i, "").model_copy(update={"knowledge_id": 20, "file_name": f"{i}.pdf"}) for i in range(25)
    ]
    loads, writes = [], []
    original_load, save = backend.load, m.save_report

    async def tracked_load(tenant_id, **kwargs):
        loads.append(kwargs)
        return await original_load(tenant_id, **kwargs)

    def tracked_save(path, report):
        writes.append(report["pending"])
        save(path, report)

    monkeypatch.setattr(backend, "load", tracked_load)
    monkeypatch.setattr(m, "save_report", tracked_save)
    monkeypatch.setattr(m.time, "monotonic", lambda: 0)
    assert await m.run(args, backend=backend) == 0
    assert loads[0] == {"user_id": None, "metadata_only": True}
    assert all(item.get("user_id") == 7 for item in loads[1:])
    assert sum("candidate" in item for item in loads) == 50
    assert len(writes) == 4
    assert writes[-1] == 0 and backend.deleted == [20]


@pytest.fixture
def query_backend(monkeypatch):
    registry = declarative_base()

    class LoaderUser(registry):
        __tablename__ = "merge_query_user"
        user_id = Column(Integer, primary_key=True)
        user_name = Column(String)
        delete = Column(Integer)

    monkeypatch.setattr(m, "User", LoaderUser)
    monkeypatch.setattr(m.settings.multi_tenant, "enabled", False)
    engine = create_engine("sqlite://")
    models = [m.Knowledge, m.KnowledgeFile, m.KnowledgeDocument, m.KnowledgeDocumentVersion, m.KnowledgeSpaceScope]
    metadata = MetaData()
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            # 只调整内存测试表的 MySQL 专属默认值, 生产模型保持不变。
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
    metadata.create_all(engine)
    registry.metadata.create_all(engine)
    statements = []
    session = Session(engine, expire_on_commit=False)

    class Adapter:
        async def exec(self, statement):
            statements.append(statement)
            if statement.column_descriptions[0].get("entity") is m.ApprovalInstance:
                return SimpleNamespace(all=lambda: [])
            return session.exec(statement)

    @asynccontextmanager
    async def connection():
        yield Adapter()

    monkeypatch.setattr(m, "get_async_db_session", connection)
    state = snapshot()
    add_root_chain(state)
    candidate = m.build_plan(state).candidates[0]
    state.files += [
        file(101, ""),
        file(102, "").model_copy(update={"file_name": "other-target.pdf"}),
        file(203, "").model_copy(update={"knowledge_id": 20, "file_name": "other-source.pdf"}),
        file(900, "").model_copy(update={"knowledge_id": 99, "reference_document_id": 50, "share_source_file_id": 101}),
    ]
    state.spaces += [space(30, uid=8, name="李四的知识库"), space(40, uid=8, name="李四的知识库"), space(99)]
    state.scopes += [scope(30, "personal", 8), scope(40, "personal", 8), scope(99, "department")]
    for entry in state.scopes:
        entry.created_by = 7
    state.files += [file(1000 + i, "").model_copy(update={"knowledge_id": 99}) for i in range(100)]
    state.documents.append(m.KnowledgeDocument(id=900, tenant_id=1, knowledge_id=99, predecessor_logic_file_id=202))
    records = [*state.spaces, *state.files, *state.scopes, *state.documents, *state.versions]
    session.add_all([type(record)(**record.model_dump()) for record in records])
    session.add_all(
        [LoaderUser(user_id=7, user_name="张三", delete=0), LoaderUser(user_id=8, user_name="李四", delete=0)]
    )
    session.commit()
    yield m.MigrationBackend(), session, statements, candidate
    session.close()
    engine.dispose()


async def test_metadata_discovery_does_not_read_files_or_versions(query_backend):
    backend, _session, statements, _candidate = query_backend
    metadata = await backend.load(1, user_id=7, metadata_only=True)
    assert {s.id for s in metadata.spaces} == {10, 20}
    assert [u.user_id for u in metadata.users] == [7]
    assert not metadata.files and not metadata.documents and not metadata.versions
    forbidden = {m.KnowledgeFile, m.KnowledgeDocument, m.KnowledgeDocumentVersion}
    assert not any(
        description.get("entity") in forbidden
        for statement in statements
        for description in statement.column_descriptions
    )


async def test_scoped_queries_keep_external_reference_protection(query_backend):
    backend, _session, _statements, candidate = query_backend
    loaded = await backend.load(1, user_id=7)
    assert {f.id for f in loaded.files} == {101, 102, 201, 202, 203}
    assert loaded.referenced_document_ids == {50}
    assert {101, 202} <= loaded.referenced_file_ids
    plan = m.build_plan(loaded, 7)
    assert any(
        row.get("unit_id") == "document:50" and row["reason"] == "shared_or_locked_document" for row in plan.skipped
    )
    focused = await backend.load(1, user_id=7, candidate=candidate)
    assert {f.id for f in focused.files} == {101, 201, 202}
    assert {v.knowledge_file_id for v in focused.versions} == {201, 202}
    assert focused.referenced_document_ids == {50}
    assert {101, 202} <= focused.referenced_file_ids
    legacy = copy.copy(candidate)
    legacy.files = (focused.files[0],)
    with pytest.raises(m.PreflightError, match="overwrite_protected_document"):
        m.resolve_overwrites(legacy, focused, "")


async def test_scoped_loader_still_detects_storage_used_by_unrelated_space(query_backend):
    backend, session, _statements, _candidate = query_backend
    for sid in (20, 99):
        record = session.get(m.Knowledge, sid)
        record.collection_name = "shared-collection"
        session.add(record)
    session.commit()
    loaded = await backend.load(1, user_id=7)
    assert {s.id for s in loaded.spaces} == {10, 20, 99}
    group = m.find_groups(loaded, 7)[0][0]
    loaded.files.clear()
    loaded.documents.clear()
    assert m.cleanup_reason(loaded, group, group.sources[0], []) == "storage_used_by_another_space"


@pytest.mark.parametrize("kind", ["file", "document"])
async def test_deleted_space_check_detects_orphans_without_group(query_backend, kind):
    backend, session, _statements, _candidate = query_backend
    assert await backend.source_has_rows(12345) is False
    orphan = (
        m.KnowledgeFile(id=888, tenant_id=1, knowledge_id=12345, user_id=7, file_name="orphan.pdf")
        if kind == "file"
        else m.KnowledgeDocument(id=888, tenant_id=1, knowledge_id=12345)
    )
    session.add(orphan)
    session.commit()
    assert await backend.source_has_rows(12345) is True


async def test_focused_recheck_loads_new_version_members(query_backend):
    backend, session, _statements, candidate = query_backend
    reference = session.get(m.KnowledgeFile, 900)
    reference.reference_document_id = None
    reference.share_source_file_id = None
    predecessor = session.get(m.KnowledgeDocument, 900)
    predecessor.predecessor_logic_file_id = None
    session.add_all([reference, predecessor])
    session.commit()
    before = m.build_plan(await backend.load(1, user_id=7, candidate=candidate), 7, only_unit_id="document:50")
    session.add_all(
        [
            m.KnowledgeFile(
                id=204, tenant_id=1, knowledge_id=20, user_id=7, file_name="new.pdf", file_level_path="", status=2
            ),
            m.KnowledgeDocumentVersion(id=503, document_id=50, knowledge_file_id=204, version_no=3, is_primary=False),
        ]
    )
    session.commit()
    after = m.build_plan(await backend.load(1, user_id=7, candidate=candidate), 7, only_unit_id="document:50")
    assert len(before.candidates) == len(after.candidates) == 1
    assert {f.id for f in after.candidates[0].files} == {201, 202, 204}
    assert before.candidates[0].fingerprint() != after.candidates[0].fingerprint()
