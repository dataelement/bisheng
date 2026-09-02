"""A folder's 存在异常 pill only counts files the current user may actually see.

A viewer / editor cannot see other people's failed uploads in the listing, so the
rollup must not light a folder up over files that are invisible to them. The
rollup reuses the listing's own visibility rule; these tests pin that wiring.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFile, KnowledgeFileStatus
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


class _Session:
    """Answers exec() calls in order: the status aggregate first, then the abnormal candidates."""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def exec(self, stmt):
        self.calls += 1
        rows = self._results.pop(0)
        return SimpleNamespace(all=lambda: rows)


def _service(monkeypatch, session_results, *, visible_ids):
    svc = object.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=42, tenant_id=1)
    session = _Session(session_results)

    @asynccontextmanager
    async def _fake_session():
        yield session

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", _fake_session)

    contexts = []

    async def _build_context(space_id):
        contexts.append(space_id)
        return {"binding_index": {}}

    async def _filter_visible(items, *, space_id, context=None):
        return [item for item in items if item.id in visible_ids]

    monkeypatch.setattr(svc, "_build_child_permission_context", _build_context, raising=False)
    monkeypatch.setattr(svc, "_filter_visible_child_items", _filter_visible, raising=False)
    return svc, session, contexts


def _folder(folder_id=10, space_id=7):
    return KnowledgeFile(id=folder_id, knowledge_id=space_id, file_type=FileType.DIR, file_level_path="", file_name="f")


def _failed_file(file_id, owner):
    return KnowledgeFile(
        id=file_id,
        knowledge_id=7,
        file_type=FileType.FILE,
        file_level_path="/10",
        file_name=f"{file_id}.pdf",
        status=KnowledgeFileStatus.FAILED.value,
        user_id=owner,
    )


async def test_invisible_failed_upload_does_not_mark_the_folder(monkeypatch):
    aggregate = [(KnowledgeFileStatus.SUCCESS.value, 3), (KnowledgeFileStatus.FAILED.value, 1)]
    svc, session, _ = _service(monkeypatch, [aggregate, [_failed_file(501, owner=99)]], visible_ids=set())

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is False
    # The retry signal is about the folder's contents, not the viewer — unchanged.
    assert result["has_failed_files"] is True
    assert session.calls == 2


async def test_visible_failed_upload_marks_the_folder(monkeypatch):
    aggregate = [(KnowledgeFileStatus.TIMEOUT.value, 1)]
    svc, _, contexts = _service(monkeypatch, [aggregate, [_failed_file(502, owner=42)]], visible_ids={502})

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is True
    assert contexts == [7], "permission context is built for the folder's space"


async def test_no_abnormal_files_skips_the_visibility_pass(monkeypatch):
    aggregate = [(KnowledgeFileStatus.SUCCESS.value, 2), (KnowledgeFileStatus.PROCESSING.value, 1)]
    svc, session, contexts = _service(monkeypatch, [aggregate], visible_ids={1, 2, 3})

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is False
    assert result["processing_file_num"] == 1
    assert session.calls == 1 and contexts == []
