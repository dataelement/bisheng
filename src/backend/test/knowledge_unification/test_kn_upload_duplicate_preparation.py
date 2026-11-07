"""T889: reuse the actual preparation and original SQL duplicate candidates."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, event, select

from bisheng.api.v1.schemas import FileProcessBase, KnowledgeFileOne
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument as Document
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion as Version
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus
from test.knowledge_unification import test_legacy_file_processing_callers as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy


async def contents(context):
    async with context.sessions() as session:
        result = []
        for model in (KnowledgeFile, Document, Version):
            rows = await session.execute(select(model.__table__).order_by(model.id))
            result.append(tuple(dict(row) for row in rows.mappings()))
        return tuple(result)


@pytest.fixture
async def duplicate(legacy, monkeypatch, request):
    context = legacy.files.context
    cls = legacy.cls
    globals_ = cls.process_one_file.__func__.__globals__
    assert cls.process_one_file.__module__ == "_legacy_rules_service"
    path, _ = globals_["file_download"]("opaque-document")
    download = Mock(return_value=(path, "download.csv"))
    monkeypatch.setitem(globals_, "file_download", download)
    monkeypatch.setitem(globals_, "get_redis_client_sync", lambda: SimpleNamespace(get=lambda key: "document.txt"))
    name_only = getattr(request, "param", None) == "name"
    async with context.sessions() as session:
        root = await session.get(Knowledge, 40)
        session.add_all(
            KnowledgeFile(
                id=ident,
                knowledge_id=40,
                tenant_id=root.tenant_id,
                user_id=7,
                file_name=name,
                file_size=123,
                md5=md5,
                object_name=f"original/{ident}.txt",
                status=KnowledgeFileStatus.SUCCESS.value,
                split_rule='{"original":true}',
            )
            for ident, name, md5 in (
                ((91001, "document.txt", "different"),)
                if name_only
                else ((91001, "document.txt", "different"), (91002, "哈希原名.txt", "digest"))
            )
        )
        if not name_only:
            session.add(Document(id=92001, knowledge_id=40, primary_version_id=92001))
            session.add(Version(id=92001, document_id=92001, knowledge_file_id=91002, version_no=1, is_primary=True))
        await session.commit()
    request = FileProcessBase(knowledge_id=40)
    prepared = cls.prepare_one_file(
        context.user,
        root,
        KnowledgeFileOne(file_path="opaque-document"),
        {},
        processing_rule_request=request,
    )
    candidates = globals_["KnowledgeFileDao"].get_file_by_condition(
        knowledge_id=40,
        md5_=prepared.md5,
        file_name=prepared.original_file_name,
    )
    assert {row.id for row in candidates} == ({91001} if name_only else {91001, 91002})
    assert prepared.md5 == "digest" and prepared.download_name == "download.csv"
    return SimpleNamespace(
        legacy=legacy,
        cls=cls,
        globals=globals_,
        context=context,
        root=root,
        request=request,
        prepared=prepared,
        candidates=candidates,
        download=download,
    )


def no_secondary_work(duplicate, monkeypatch):
    blockers = []
    for owner, name in (
        (duplicate.globals["KnowledgeFileDao"], "get_file_by_condition"),
        (duplicate.globals["KnowledgeFileDao"], "add_file"),
        (duplicate.globals["KnowledgeFileDao"], "update"),
        (duplicate.globals["KnowledgeFileDao"], "delete_batch"),
        (duplicate.cls, "processing_snapshot_for_legacy_request"),
        (duplicate.cls, "_project_library_file_created"),
    ):
        blocker = Mock(side_effect=AssertionError(f"duplicate staging must not call {name}"))
        monkeypatch.setattr(owner, name, blocker)
        blockers.append(blocker)
    download = Mock(side_effect=AssertionError("duplicate staging must not download"))
    monkeypatch.setitem(duplicate.globals, "file_download", download)
    cleanup = Mock()
    monkeypatch.setattr(duplicate.cls, "remove_unused_file", cleanup)
    return blockers, download, cleanup


@pytest.mark.parametrize("duplicate,choice", [("md5", "md5"), ("name", "name")], indirect=["duplicate"])
async def test_original_candidate_selection_tmp_suffix_and_client_only_failed_response(duplicate, monkeypatch, choice):
    before = await contents(duplicate.context)
    blockers, download, cleanup = no_secondary_work(duplicate, monkeypatch)
    candidates = sorted(duplicate.candidates, key=lambda row: row.id)
    selected = candidates[-1] if choice == "md5" else candidates[0]
    old_name = selected.file_name
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        result = duplicate.cls.stage_prepared_duplicate(prepared=duplicate.prepared, repeat_files=tuple(candidates))
    finally:
        event.remove(Engine, "before_cursor_execute", capture)
    assert result is selected
    assert result.object_name == f"tmp/{selected.id}.csv"
    assert json.loads(result.remark) == {"new_name": "document.txt", "old_name": old_name}
    assert result.status == KnowledgeFileStatus.FAILED.value and result.split_rule == duplicate.prepared.split_rule
    assert result.file_size == duplicate.prepared.file_size
    assert duplicate.prepared.file_info.file_path == "opaque-document"
    duplicate.legacy.storage.put_object_tmp_sync.assert_called_once_with(
        result.object_name, duplicate.prepared.local_path
    )
    duplicate.legacy.storage.put_object_sync.assert_not_called()
    cleanup.assert_called_once_with("opaque-document")
    download.assert_not_called()
    assert not statements
    for blocker in blockers:
        blocker.assert_not_called()
    duplicate.legacy.publish.assert_not_called()
    assert await contents(duplicate.context) == before


@pytest.mark.parametrize("point", ["put", "cleanup"])
async def test_tmp_failure_does_not_persist_old_rows_or_early_cleanup(duplicate, monkeypatch, point):
    before = await contents(duplicate.context)
    _, download, cleanup = no_secondary_work(duplicate, monkeypatch)
    if point == "put":
        duplicate.legacy.storage.put_object_tmp_sync.side_effect = OSError("temporary object write failed")
    else:
        cleanup.side_effect = OSError("source cleanup failed")
    with pytest.raises(OSError):
        duplicate.cls.stage_prepared_duplicate(prepared=duplicate.prepared, repeat_files=duplicate.candidates)
    assert cleanup.call_count == (0 if point == "put" else 1)
    download.assert_not_called()
    duplicate.legacy.publish.assert_not_called()
    assert all(row.status == KnowledgeFileStatus.SUCCESS.value for row in duplicate.candidates)
    assert await contents(duplicate.context) == before


async def test_original_process_delegates_one_prepared_snapshot_to_duplicate_staging(duplicate, monkeypatch):
    actual = duplicate.cls.stage_prepared_duplicate
    spy = Mock(wraps=actual)
    monkeypatch.setattr(duplicate.cls, "stage_prepared_duplicate", spy)
    duplicate.download.reset_mock()
    resolver = Mock(wraps=duplicate.cls.processing_snapshot_for_legacy_request)
    monkeypatch.setattr(duplicate.cls, "processing_snapshot_for_legacy_request", resolver)
    before = await contents(duplicate.context)
    result = duplicate.cls.process_one_file(
        duplicate.context.user,
        duplicate.root,
        KnowledgeFileOne(file_path="opaque-document"),
        {},
        processing_rule_request=duplicate.request,
    )
    assert spy.call_count == duplicate.download.call_count == resolver.call_count == 1
    assert result.id == 91002 and result.status == KnowledgeFileStatus.FAILED.value
    assert result.split_rule == spy.call_args.kwargs["prepared"].split_rule
    assert await contents(duplicate.context) == before


async def test_original_skip_dedup_remains_a_real_new_file_not_a_duplicate_response(duplicate):
    before = await contents(duplicate.context)
    result = duplicate.cls.process_one_file(
        duplicate.context.user,
        duplicate.root,
        KnowledgeFileOne(file_path="opaque-document"),
        {},
        processing_rule_request=duplicate.request,
        skip_dedup=True,
    )
    after = await contents(duplicate.context)
    assert result.id not in {91001, 91002} and result.status == KnowledgeFileStatus.WAITING.value
    assert result.md5 == duplicate.prepared.md5
    assert len(after[0]) == len(before[0]) + 1 and after[1:] == before[1:]
    duplicate.legacy.storage.put_object_sync.assert_called_once()
    duplicate.legacy.storage.put_object_tmp_sync.assert_not_called()
    duplicate.legacy.publish.assert_not_called()
