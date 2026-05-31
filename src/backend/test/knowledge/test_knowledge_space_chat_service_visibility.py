"""F026 tests for KnowledgeSpaceChatService double-filter retrieval.

Focuses on the new ``_retrieve_and_filter`` helper introduced by T005 and
its interactions with the existing chat entrypoints:

- Empty / non-empty index-filter strategies (AC-02 / AC-03 / AC-06).
- Result-layer post-filter dropping infeasible chunks (AC-02).
- Bounded retry expansion (AC-26).
- Structured ``permission_filter`` log fields (AC-27).
- ``chat_single_file`` view_file DEBUG log (AC-09).

The retriever_tool, KnowledgeRag vectorstore factories, and DAO calls are
all stubbed via monkeypatch + MagicMock; Milvus / ES never run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.knowledge.domain.services.knowledge_file_visibility_service import (
    IndexFilter,
)
from bisheng.knowledge.domain.services.knowledge_space_chat_service import (
    KnowledgeSpaceChatService,
)


def _make_doc(file_id: int, content: str = "") -> Document:
    return Document(page_content=content or f"chunk-{file_id}", metadata={"document_id": file_id})


def _make_service(*, is_admin: bool = False, user_id: int = 7) -> KnowledgeSpaceChatService:
    login_user = MagicMock()
    login_user.user_id = user_id
    login_user.user_name = f"user-{user_id}"
    login_user.is_admin = MagicMock(return_value=is_admin)
    svc = KnowledgeSpaceChatService(request=MagicMock(), login_user=login_user)
    svc.version_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# _retrieve_and_filter — the new AD-03 loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_and_filter_empty_strategy_skips_invocation(monkeypatch):
    """IndexFilter.strategy='empty' → returns [] without touching retriever."""
    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="empty", accessible_size=0)
    )
    visibility.post_filter_visible_files = AsyncMock()
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)
    invoke_mock = AsyncMock(return_value=[_make_doc(1)])
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=invoke_mock),
    )

    docs = await svc._retrieve_and_filter(
        space=space, query="q", candidate_file_ids=None, max_content=1000
    )

    assert docs == []
    visibility.build_index_prefilter.assert_awaited_once_with(10, None)
    visibility.post_filter_visible_files.assert_not_called()
    invoke_mock.assert_not_called()


@pytest.mark.asyncio
async def test_retrieve_and_filter_first_attempt_satisfies(monkeypatch):
    """First attempt returns docs all of which pass post-filter → no expansion."""
    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", accessible_size=3, milvus_expr="document_id in [1, 2, 3]"),
    )
    # All 3 file_ids are permitted.
    visibility.post_filter_visible_files = AsyncMock(return_value={1, 2, 3})
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)

    # Patch vectorstore init + retriever_tool to deterministic stub.
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    invoke_calls = []
    docs_first = [_make_doc(1), _make_doc(2), _make_doc(3)]

    async def fake_ainvoke(query):
        invoke_calls.append(query)
        return docs_first

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=fake_ainvoke),
    )

    docs = await svc._retrieve_and_filter(
        space=space, query="q", candidate_file_ids=None, max_content=1000
    )

    assert [int(d.metadata["document_id"]) for d in docs] == [1, 2, 3]
    visibility.post_filter_visible_files.assert_awaited_once()
    assert len(invoke_calls) == 1  # no expansion


@pytest.mark.asyncio
async def test_retrieve_and_filter_post_filter_drops_some(monkeypatch):
    """First attempt returns docs but only a subset passes post-filter."""
    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="none", accessible_size=10)
    )
    # Only file_ids 1 and 3 are permitted; 2 and 4 dropped.
    visibility.post_filter_visible_files = AsyncMock(return_value={1, 3})
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    docs_first = [_make_doc(1), _make_doc(2), _make_doc(3), _make_doc(4)]

    async def fake_ainvoke(query):  # noqa: ARG001
        return docs_first

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=fake_ainvoke),
    )

    docs = await svc._retrieve_and_filter(
        space=space, query="q", candidate_file_ids=None, max_content=1000
    )

    surviving_ids = sorted(int(d.metadata["document_id"]) for d in docs)
    assert surviving_ids == [1, 3]


@pytest.mark.asyncio
async def test_retrieve_and_filter_capped_at_two_attempts(monkeypatch):
    """AD-03: if both attempts produce 0 survivors, stop; no third attempt."""
    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="none", accessible_size=100)
    )
    visibility.post_filter_visible_files = AsyncMock(return_value=set())
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    invoke_count = 0

    async def fake_ainvoke(query):  # noqa: ARG001
        nonlocal invoke_count
        invoke_count += 1
        return [_make_doc(invoke_count * 10)]

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=fake_ainvoke),
    )

    docs = await svc._retrieve_and_filter(
        space=space, query="q", candidate_file_ids=None, max_content=1000
    )

    assert docs == []
    assert invoke_count == 2  # AD-03 hard cap


@pytest.mark.asyncio
async def test_retrieve_and_filter_expansion_succeeds_second_attempt(monkeypatch):
    """First attempt → 0 survivors; second attempt → survivors. Used."""
    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", accessible_size=5, milvus_expr="document_id in [1,2,3,4,5]")
    )

    # post_filter_visible_files called twice: first round nothing matches,
    # second round file_id 5 survives.
    post_filter_results = iter([set(), {5}])

    async def fake_post(space_id, file_ids):  # noqa: ARG001
        return next(post_filter_results)

    visibility.post_filter_visible_files = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    call_count = 0

    async def fake_ainvoke(query):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return [_make_doc(1), _make_doc(2)]  # both rejected
        return [_make_doc(3), _make_doc(5)]  # only 5 survives

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=fake_ainvoke),
    )

    docs = await svc._retrieve_and_filter(
        space=space, query="q", candidate_file_ids=None, max_content=1000
    )

    assert call_count == 2
    assert sorted(int(d.metadata["document_id"]) for d in docs) == [5]


@pytest.mark.asyncio
async def test_retrieve_and_filter_logs_structured_fields(monkeypatch, caplog):
    """AC-27: each retrieval attempt writes the permission_filter log fields."""
    import logging

    svc = _make_service()
    visibility = MagicMock()
    visibility.build_index_prefilter = AsyncMock(
        return_value=IndexFilter(strategy="in", accessible_size=2, milvus_expr="document_id in [1,2]")
    )
    visibility.post_filter_visible_files = AsyncMock(return_value={1})
    monkeypatch.setattr(svc, "_visibility_service", lambda: visibility)

    space = MagicMock(id=10)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    async def fake_ainvoke(query):  # noqa: ARG001
        return [_make_doc(1), _make_doc(2)]

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRetrieverTool",
        lambda **kwargs: MagicMock(ainvoke=fake_ainvoke),
    )

    # Hook loguru into caplog via the standard interceptor.
    from loguru import logger as loguru_logger

    sink_records = []

    def sink(message):
        sink_records.append(str(message))

    handler_id = loguru_logger.add(sink, level="INFO")
    try:
        await svc._retrieve_and_filter(
            space=space, query="q", candidate_file_ids=None, max_content=1000
        )
    finally:
        loguru_logger.remove(handler_id)

    permission_logs = [r for r in sink_records if "permission_filter" in r]
    assert permission_logs, "Expected a permission_filter log line per attempt"
    sample = permission_logs[0]
    for field in (
        "strategy=",
        "accessible_ids_size=",
        "prefilter_candidate_size=",
        "retrieval_attempts=",
        "post_filter_dropped_count=",
    ):
        assert field in sample, f"Missing log field {field!r} in: {sample!r}"


# ---------------------------------------------------------------------------
# chat_single_file — AC-09 DEBUG log (no functional change)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_single_file_logs_view_file_passed_debug(monkeypatch):
    """chat_single_file should emit a DEBUG log once view_file passes (AC-09)."""
    from loguru import logger as loguru_logger

    svc = _make_service()

    # Stub permission gate to succeed and return a file record.
    file_record = MagicMock(id=42, knowledge_id=10, file_name="test.pdf")
    monkeypatch.setattr(
        svc, "_require_file_view_permission", AsyncMock(return_value=file_record)
    )

    # Stub everything downstream so the generator can advance and yield.
    space = MagicMock(id=10)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=space),
    )
    session = MagicMock(chat_id="cid", flow_id="fid", name="title")
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.MessageSessionDao.afilter_session",
        AsyncMock(return_value=[session]),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_milvus_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_chat_service.KnowledgeRag.init_knowledge_es_vectorstore",
        AsyncMock(return_value=MagicMock(as_retriever=lambda **kw: MagicMock())),
    )

    # Patch space_rag to a no-op async generator so chat_single_file returns quickly.
    async def fake_space_rag(*args, **kwargs):  # noqa: ARG001
        if False:
            yield  # make this an async generator

    monkeypatch.setattr(svc, "space_rag", fake_space_rag)

    sink_records = []
    handler_id = loguru_logger.add(lambda m: sink_records.append(str(m)), level="DEBUG")
    try:
        async for _ in svc.chat_single_file(
            knowledge_id=10, file_id=42, query="q", model_id=1
        ):
            pass
    finally:
        loguru_logger.remove(handler_id)

    debug_lines = [
        r for r in sink_records
        if "view_file" in r and ("passed" in r or "checked" in r or "ok" in r.lower())
    ]
    assert debug_lines, (
        f"Expected a DEBUG log about the view_file check; got: {sink_records!r}"
    )
