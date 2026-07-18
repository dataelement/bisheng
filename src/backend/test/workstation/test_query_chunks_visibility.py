"""F029 tests for WorkStationService.queryChunksFromDB view_file filtering.

Covers the workstation chat path where the user picks multiple knowledge
spaces and asks a question. The helpers added by T007 are tested in
isolation here; full queryChunksFromDB integration is left to T012 E2E.

ACs covered:
- AC-11: KB without view_space is silently skipped, INFO-logged, not in
  the success list.
- AC-12: KB whose visible-file set is empty (either via index strategy or
  via post-filter) contributes 0 docs.
- AC-13: Multi-KB partial visibility — each KB filtered independently.
- AC-14: org_bucket (legacy knowledge_library) path remains untouched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.documents import Document

from bisheng.api.services.workstation import WorkStationService
from bisheng.api.v1.schema.chat_schema import UseKnowledgeBaseParam


def _make_doc(file_id: int, content: str = "") -> Document:
    return Document(
        page_content=content or f"chunk-{file_id}",
        metadata={
            "document_id": file_id,
            "document_name": f"doc-{file_id}.txt",
            "knowledge_id": 100,
        },
    )


# ---------------------------------------------------------------------------
# Stage 1 — is_space_visible gate (AC-11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filter_visible_space_kb_ids_drops_no_view_space(monkeypatch):
    """``_filter_visible_space_kb_ids`` keeps only space-bucket kb_ids the
    user has view_space on; org-bucket kb_ids are returned untouched.
    """
    visibility_calls: list[int] = []

    async def fake_is_space_visible(self, space_id: int) -> bool:
        visibility_calls.append(space_id)
        # Only KB 1 is visible; KB 2 is not.
        return space_id == 1

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.is_space_visible",
        fake_is_space_visible,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=False)
    result = await WorkStationService._filter_visible_space_kb_ids(
        login_user=login_user,
        space_bucket=[1, 2],
        org_bucket=[100],
    )

    # Only KB 1 from space_bucket survives; org_bucket passes through.
    assert sorted(result["space_kb_ids"]) == [1]
    assert sorted(result["org_kb_ids"]) == [100]
    assert sorted(result["skipped_kb_ids"]) == [2]
    assert sorted(visibility_calls) == [1, 2]


@pytest.mark.asyncio
async def test_filter_visible_space_kb_ids_admin_bypasses(monkeypatch):
    """Admin users bypass the is_space_visible probe (covered by service
    short-circuits) → all KB ids preserved.
    """
    calls: list[int] = []

    async def fake_is_space_visible(self, space_id: int) -> bool:
        calls.append(space_id)
        return True

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.is_space_visible",
        fake_is_space_visible,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=True)
    result = await WorkStationService._filter_visible_space_kb_ids(
        login_user=login_user,
        space_bucket=[1, 2, 3],
        org_bucket=[100],
    )

    assert sorted(result["space_kb_ids"]) == [1, 2, 3]
    assert sorted(result["org_kb_ids"]) == [100]
    assert result["skipped_kb_ids"] == []


# ---------------------------------------------------------------------------
# Stage 3 — post-filter docs by view_file (AC-12, AC-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_filter_kb_docs_drops_inaccessible_files(monkeypatch):
    """post_filter_visible_files reports only {1, 3} → docs for 2 and 4 dropped."""
    async def fake_post(self, space_id, file_ids):
        return {1, 3}

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=False)

    raw_docs = [_make_doc(1), _make_doc(2), _make_doc(3), _make_doc(4)]
    survivors = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=login_user, kb_id=10, docs=raw_docs
    )

    assert sorted(int(d.metadata["document_id"]) for d in survivors) == [1, 3]


@pytest.mark.asyncio
async def test_post_filter_kb_docs_empty_when_nothing_permitted(monkeypatch):
    """User has zero permitted files → empty docs (AC-12 second route)."""
    async def fake_post(self, space_id, file_ids):
        return set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=False)

    raw_docs = [_make_doc(5), _make_doc(6)]
    survivors = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=login_user, kb_id=10, docs=raw_docs
    )
    assert survivors == []


@pytest.mark.asyncio
async def test_post_filter_kb_docs_admin_returns_all_input():
    """Admin users skip the FGA round-trip — input docs returned as-is."""
    login_user = MagicMock(user_id=99)
    login_user.is_admin = MagicMock(return_value=True)

    raw_docs = [_make_doc(1), _make_doc(2)]
    survivors = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=login_user, kb_id=10, docs=raw_docs
    )
    assert survivors is raw_docs or survivors == raw_docs


@pytest.mark.asyncio
async def test_post_filter_kb_docs_no_docs_short_circuits(monkeypatch):
    """Empty input → empty output, no FGA calls."""
    calls = []

    async def fake_post(self, space_id, file_ids):
        calls.append(space_id)
        return set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=False)

    survivors = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=login_user, kb_id=10, docs=[]
    )
    assert survivors == []
    assert calls == []


# ---------------------------------------------------------------------------
# AC-14 — org_bucket KBs are not visited by the post-filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_filter_kb_docs_org_bucket_passthrough(monkeypatch):
    """When the caller flags kb_id as org_bucket (is_space_bucket=False),
    docs are returned as-is regardless of view_file (AC-14).
    """
    fga_called = False

    async def fake_post(self, space_id, file_ids):
        nonlocal fga_called
        fga_called = True
        return set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_visibility_service."
        "KnowledgeFileVisibilityService.post_filter_visible_files",
        fake_post,
    )

    login_user = MagicMock(user_id=42)
    login_user.is_admin = MagicMock(return_value=False)

    raw_docs = [_make_doc(7)]
    survivors = await WorkStationService._post_filter_kb_docs_by_view_file(
        login_user=login_user, kb_id=10, docs=raw_docs, is_space_bucket=False
    )
    assert survivors == raw_docs
    assert fga_called is False


# ---------------------------------------------------------------------------
# Workstation org-KB retrieval path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_chunks_org_kb_uses_use_permission_and_bypasses_legacy_auth(monkeypatch):
    permission_calls = []
    vector_calls = []

    async def fake_filter_ids(self, login_user, knowledge_ids, permission_id):
        permission_calls.append((knowledge_ids, permission_id))
        return [100]

    async def fake_get_vectorstore(**kwargs):
        vector_calls.append(kwargs)
        return {
            100: {
                "knowledge": SimpleNamespace(id=100, name="kb-100"),
                "milvus": object(),
                "es": None,
            }
        }

    class FakeKnowledgeRetrieverTool:
        def __init__(self, **kwargs):
            pass

        async def ainvoke(self, payload):
            return [_make_doc(1, "answer chunk")]

    class FakeMultiRetriever:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service."
        "KnowledgePermissionService.filter_knowledge_ids_by_permission_async",
        fake_filter_ids,
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service."
        "KnowledgeRag.get_multi_knowledge_vectorstore",
        fake_get_vectorstore,
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.KnowledgeRetrieverTool",
        FakeKnowledgeRetrieverTool,
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service.MultiRetriever",
        FakeMultiRetriever,
    )

    login_user = MagicMock(user_id=42, user_name="sarah")
    login_user.is_admin = MagicMock(return_value=False)

    formatted, docs, failures = await WorkStationService.queryChunksFromDB(
        question="related question",
        use_knowledge_param=UseKnowledgeBaseParam(organization_knowledge_ids=[100]),
        max_token=1000,
        login_user=login_user,
    )

    assert failures == []
    assert [doc.page_content for doc in docs] == ["answer chunk"]
    assert "[file content begin]\nanswer chunk\n[file content end]" in formatted[0]
    assert permission_calls == [([100], "use_kb")]
    assert vector_calls == [
        {
            "invoke_user_id": 42,
            "knowledge_ids": [100],
            "check_auth": False,
        }
    ]


@pytest.mark.asyncio
async def test_query_chunks_org_kb_init_failure_is_reported(monkeypatch):
    async def fake_filter_ids(self, login_user, knowledge_ids, permission_id):
        return [100]

    async def fake_get_vectorstore(**kwargs):
        raise RuntimeError("embedding init failed")

    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service."
        "KnowledgePermissionService.filter_knowledge_ids_by_permission_async",
        fake_filter_ids,
    )
    monkeypatch.setattr(
        "bisheng.workstation.domain.services.workstation_service."
        "KnowledgeRag.get_multi_knowledge_vectorstore",
        fake_get_vectorstore,
    )

    login_user = MagicMock(user_id=42, user_name="sarah")
    login_user.is_admin = MagicMock(return_value=False)

    formatted, docs, failures = await WorkStationService.queryChunksFromDB(
        question="related question",
        use_knowledge_param=UseKnowledgeBaseParam(organization_knowledge_ids=[100]),
        max_token=1000,
        login_user=login_user,
    )

    assert formatted == []
    assert docs == []
    assert failures == [
        {
            "id": 100,
            "name": "",
            "error": "embedding init failed",
        }
    ]
