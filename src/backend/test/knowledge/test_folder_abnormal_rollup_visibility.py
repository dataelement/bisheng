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
    """Answers exec() by statement shape: the folder status aggregate, the abnormal
    candidate rows, and an empty list for anything else the branch's rollup may ask."""

    def __init__(self, aggregate, candidates):
        self._aggregate = aggregate
        self._candidates = candidates
        self.kinds: list[str] = []

    async def exec(self, stmt):
        text = str(stmt)
        entity = None
        try:
            entity = stmt.column_descriptions[0].get("entity")
        except (AttributeError, IndexError, KeyError, TypeError):
            entity = None
        if "file_count" in text or "count(" in text.lower():
            self.kinds.append("aggregate")
            rows = self._aggregate
        elif entity is KnowledgeFile:
            self.kinds.append("candidates")
            rows = self._candidates
        else:
            self.kinds.append("other")
            rows = []
        return SimpleNamespace(all=lambda: rows)


def _service(monkeypatch, aggregate, candidates, *, visible_ids):
    svc = object.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=42, tenant_id=1)
    session = _Session(aggregate, candidates)

    @asynccontextmanager
    async def _fake_session():
        yield session

    # The service binds the session factory at module level (and, on some lines, re-imports it
    # inside the function) — patch both names so the fake is what actually runs.
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", _fake_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        _fake_session,
        raising=False,
    )

    contexts = []

    async def _build_context(space_id):
        contexts.append(space_id)
        return {"binding_index": {}}

    async def _filter_visible(items, *, space_id, context=None):
        return [item for item in items if item.id in visible_ids]

    monkeypatch.setattr(
        svc,
        "_file_change_visibility_service",
        lambda: SimpleNamespace(require_explicit_tenant=lambda: 1),
        raising=False,
    )
    monkeypatch.setattr(svc, "_build_child_permission_context", _build_context, raising=False)
    monkeypatch.setattr(svc, "_filter_visible_child_items", _filter_visible, raising=False)
    return svc, session, contexts


def _folder(folder_id=10, space_id=7):
    return KnowledgeFile(id=folder_id, knowledge_id=space_id, file_type=FileType.DIR, file_level_path="", file_name="f")


def _aggregate(*status_counts, folder_id=10):
    """Rows as the rollup's aggregate returns them.

    Every folder on the page is counted by one chunked UNION rather than a query
    each, so each row names the folder it belongs to.
    """
    return [(folder_id, status, count) for status, count in status_counts]


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
    aggregate = _aggregate((KnowledgeFileStatus.SUCCESS.value, 3), (KnowledgeFileStatus.FAILED.value, 1))
    svc, session, _ = _service(monkeypatch, aggregate, [_failed_file(501, owner=99)], visible_ids=set())

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is False
    # The retry signal is about the folder's contents, not the viewer — unchanged.
    assert result["has_failed_files"] is True
    assert session.kinds.count("candidates") == 1


async def test_visible_failed_upload_marks_the_folder(monkeypatch):
    aggregate = _aggregate((KnowledgeFileStatus.TIMEOUT.value, 1))
    svc, _, contexts = _service(monkeypatch, aggregate, [_failed_file(502, owner=42)], visible_ids={502})

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is True
    assert contexts == [7], "permission context is built for the folder's space"


async def test_no_abnormal_files_skips_the_visibility_pass(monkeypatch):
    aggregate = _aggregate((KnowledgeFileStatus.SUCCESS.value, 2), (KnowledgeFileStatus.PROCESSING.value, 1))
    svc, session, contexts = _service(monkeypatch, aggregate, [], visible_ids={1, 2, 3})

    (result,) = await svc._handle_file_folder_extra_info([_folder()])

    assert result["has_abnormal_files"] is False
    assert result["processing_file_num"] == 1
    assert session.kinds.count("candidates") == 0 and contexts == []
