"""F026: exercise the space chat entry and the persisted citation boundary."""

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document

from bisheng.citation.domain.services import citation_resolve_service as resolve
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService as Registry
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService as Resolver
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.knowledge.application.provider_reads import ReadHandle
from bisheng.knowledge.domain.services import knowledge_space_chat_service as chat


def citation(monkeypatch):
    monkeypatch.setattr(Registry, "_load_knowledge_names", lambda docs: {})
    doc = Document(
        page_content="revision one",
        metadata=dict(
            knowledge_id=3,
            document_id=18,
            logical_document_id=9,
            version_id=31,
            version_no=1,
            generation=2,
            operation_epoch=4,
            chunk_id="chunk-8",
            chunk_index=7,
        ),
    )
    return Registry.build_rag_registry([doc])[0]


def provider_citation(monkeypatch, access_scope="per_user"):
    monkeypatch.setattr(Registry, "_load_knowledge_names", lambda docs: {})
    doc = Document(
        page_content="revision one",
        metadata=dict(
            knowledge_id=3,
            document_id=18,
            logical_document_id=9,
            version_id=31,
            version_no=1,
            generation=2,
            operation_epoch=4,
            chunk_id="chunk-8",
            chunk_index=7,
            document_name="远端文件.pdf",
            preview_url="https://provider.example/signed/preview",
            download_url="https://provider.example/signed/download",
            access_scope=access_scope,
        ),
    )
    return Registry.build_rag_registry([doc])[0]


class _Providers:
    """Request-scoped provider composition double; remembers the requested scope."""

    def __init__(self, route, hits):
        self.route_value = route
        self.hits = list(hits)
        self.selections = []
        self.queries = []

    async def route(self, space):
        return self.route_value

    async def retrieve(self, space, route, selection, query, max_content, visibility):
        self.selections.append(selection)
        self.queries.append(query)
        return [(space.id, doc) for doc in self.hits]


def use_provider(monkeypatch, route, hits=()):
    providers = _Providers(route, hits)

    @asynccontextmanager
    async def runtime():
        yield providers

    monkeypatch.setattr(
        "bisheng.knowledge.application.provider_runtime.request_provider_retrieval", runtime
    )
    return providers


def forbid_native(monkeypatch):
    """Any local Milvus/ES construction on a provider-bound space fails the test."""
    monkeypatch.setattr(
        chat.KnowledgeRag,
        "init_knowledge_milvus_vectorstore",
        AsyncMock(side_effect=AssertionError("native milvus built")),
    )
    monkeypatch.setattr(
        chat.KnowledgeRag,
        "init_knowledge_es_vectorstore",
        AsyncMock(side_effect=AssertionError("native es built")),
    )
    monkeypatch.setattr(
        chat.KnowledgeRetrieverTool,
        "ainvoke",
        AsyncMock(side_effect=AssertionError("native retriever used")),
    )


def forbid_local_enrichment(monkeypatch):
    """A provider citation must never sign a local MinIO URL or read a local file row."""

    def local_signing(*args, **kwargs):
        raise AssertionError("local MinIO share_url used for a provider citation")

    monkeypatch.setattr(resolve.KnowledgeService, "get_file_share_url", staticmethod(local_signing))
    monkeypatch.setattr(
        resolve.KnowledgeFileDao,
        "query_by_id_sync",
        Mock(side_effect=AssertionError("local file row read for a provider citation")),
    )


def resolver():
    svc = Resolver(Mock(), AsyncMock())
    svc._permitted_file_ids = AsyncMock(return_value={18})
    return svc


def test_registry_pins_physical_version_and_chunk(monkeypatch):
    payload = citation(monkeypatch).sourcePayload.model_dump()
    assert (payload["knowledgeId"], payload["documentId"]) == (3, 18)
    assert (
        payload["logicalDocumentId"],
        payload["versionId"],
        payload["versionNo"],
        payload["generation"],
        payload["operationEpoch"],
    ) == (9, 31, 1, 2, 4)
    assert payload["items"][0]["chunkId"] == "chunk-8"


@pytest.mark.parametrize(
    "folder,children,expected",
    [(None, [], [18]), (2, [12, 16], [12, 16]), (2, [], []), (0, [], None)],
)
async def test_space_chat_passes_exact_file_scope(monkeypatch, folder, children, expected):
    actor = NS(user_id=9, is_admin=False)
    svc = chat.KnowledgeSpaceChatService(None, actor)
    session = NS(chat_id="c", flow_id="s")
    svc.chat_session_repo = AsyncMock()
    svc.chat_session_repo.find_first_by_effective_entry.return_value = session
    svc.chat_session_repo.get_by_chat_and_effective_entry.return_value = session
    space = NS(id=3, type=3, tenant_id=4)
    monkeypatch.setattr(chat.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=space))
    monkeypatch.setattr(
        chat.SpaceFileDao,
        "get_children_by_prefix",
        AsyncMock(return_value=[NS(id=i, file_type=1) for i in children]),
    )
    svc._require_file_view_permission = AsyncMock(return_value=NS(id=18, knowledge_id=3))
    svc._require_folder_view_permission = AsyncMock(
        return_value=NS(id=2, knowledge_id=3, file_type=0, file_level_path="")
    )
    svc._require_space_view_permission = AsyncMock()
    svc.get_space_llm_config = AsyncMock(return_value=(None, NS(max_chunk_size=100)))
    svc._retrieve_and_filter = AsyncMock(return_value=["scoped result"])

    async def render(session, docs, *args):
        yield docs

    svc._render_rag_response = render
    if folder is None:
        monkeypatch.setattr(
            chat.KnowledgeRag,
            "init_knowledge_milvus_vectorstore",
            AsyncMock(side_effect=AssertionError("direct native search")),
            raising=False,
        )
        result = svc.chat_single_file(3, 18, "q", 1)
    else:
        result = svc.chat_folder(3, folder, "c", "q", 1)
    assert [v async for v in result] == [["scoped result"]]
    assert svc._retrieve_and_filter.await_args.kwargs["candidate_file_ids"] == expected


@pytest.mark.parametrize(
    "candidate,expected",
    [([18], (18,)), ([12, 16], (12, 16)), (None, None)],
)
async def test_provider_retrieval_keeps_the_scope_and_skips_native_index(monkeypatch, candidate, expected):
    """Single file stays that file; folder keeps its children; whole space stays None."""
    forbid_native(monkeypatch)
    hit = Document(page_content="remote chunk", metadata={"document_id": 18, "generation": 2})
    providers = use_provider(monkeypatch, route=object(), hits=[hit])
    svc = chat.KnowledgeSpaceChatService(None, NS(user_id=9, is_admin=False))
    docs = await svc._retrieve_and_filter(
        space=NS(id=3, type=3, tenant_id=4),
        query="q",
        candidate_file_ids=candidate,
        max_content=100,
    )
    assert docs == [hit]
    assert providers.selections[0].file_ids == expected
    assert providers.selections[0].tag_ref_ids == ()


@pytest.mark.parametrize(
    "folder,children,expected",
    [(None, [], (18,)), (2, [12, 16], (12, 16)), (0, [], None)],
)
async def test_space_chat_hands_the_provider_its_exact_scope(monkeypatch, folder, children, expected):
    """The chat entry must not widen its scope on the way into the provider."""
    forbid_native(monkeypatch)
    hit = Document(page_content="remote chunk", metadata={"document_id": 18})
    providers = use_provider(monkeypatch, route=object(), hits=[hit])
    svc = chat.KnowledgeSpaceChatService(None, NS(user_id=9, is_admin=False))
    session = NS(chat_id="c", flow_id="s")
    svc.chat_session_repo = AsyncMock()
    svc.chat_session_repo.find_first_by_effective_entry.return_value = session
    svc.chat_session_repo.get_by_chat_and_effective_entry.return_value = session
    monkeypatch.setattr(
        chat.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=NS(id=3, type=3, tenant_id=4))
    )
    monkeypatch.setattr(
        chat.SpaceFileDao,
        "get_children_by_prefix",
        AsyncMock(return_value=[NS(id=i, file_type=1) for i in children]),
    )
    svc._require_file_view_permission = AsyncMock(
        return_value=NS(id=18, knowledge_id=3, file_name="a.pdf")
    )
    svc._require_folder_view_permission = AsyncMock(
        return_value=NS(id=2, knowledge_id=3, file_type=0, file_level_path="")
    )
    svc._require_space_view_permission = AsyncMock()
    svc.get_space_llm_config = AsyncMock(return_value=(None, NS(max_chunk_size=100)))
    rendered = []

    async def render(session, docs, *args):
        rendered.append(docs)
        yield docs

    svc._render_rag_response = render
    if folder is None:
        chunks = [chunk async for chunk in svc.chat_single_file(3, 18, "q", 1)]
    else:
        chunks = [chunk async for chunk in svc.chat_folder(3, folder, "c", "q", 1)]
    assert chunks == [[hit]]
    assert rendered == [[hit]]
    assert providers.queries == ["q"]
    assert providers.selections[0].file_ids == expected


async def test_provider_citation_returns_only_local_controlled_urls(monkeypatch):
    item = provider_citation(monkeypatch)
    forbid_local_enrichment(monkeypatch)
    svc = resolver()
    svc.runtime_cache_service.get_citation.return_value = item

    async def issue(user, space, file, operation):
        return ReadHandle(space, file, 31, 2, 4, operation)

    monkeypatch.setattr(svc, "_issue_provider_handle", issue, raising=False)
    result = await svc.resolve_citation(item.citationId, NS(user_id=9))
    payload = result.sourcePayload
    assert payload.previewUrl == (
        "/api/v1/knowledge/space/3/files/18/content/preview?version_id=31&generation=2&epoch=4"
    )
    assert payload.downloadUrl == (
        "/api/v1/knowledge/space/3/files/18/content/download?version_id=31&generation=2&epoch=4"
    )
    assert payload.sourceUrl is None
    assert "provider.example" not in (payload.previewUrl + payload.downloadUrl)


@pytest.mark.parametrize("version,generation,epoch", [(31, 2, 4), (32, 2, 4), (31, 3, 4), (31, 2, 5)])
async def test_provider_citation_pins_version_generation_and_epoch(monkeypatch, version, generation, epoch):
    item = provider_citation(monkeypatch)
    forbid_local_enrichment(monkeypatch)
    svc = resolver()
    svc.runtime_cache_service.get_citation.return_value = item

    async def issue(user, space, file, operation):
        return ReadHandle(space, file, version, generation, epoch, operation)

    monkeypatch.setattr(svc, "_issue_provider_handle", issue, raising=False)
    if (version, generation, epoch) == (31, 2, 4):
        result = await svc.resolve_citation(item.citationId, NS(user_id=9))
        assert result.sourcePayload.previewUrl.startswith("/api/")
    else:
        with pytest.raises(NotFoundError) as err:
            await svc.resolve_citation(item.citationId, NS(user_id=9))
        assert err.value.kwargs["reason"] == "expired"


@pytest.mark.parametrize(
    "update",
    [
        {"generation": None, "operationEpoch": None},
        {"versionId": None, "generation": None, "operationEpoch": None},
    ],
)
async def test_provider_citation_with_incomplete_anchor_is_unavailable(monkeypatch, update):
    """A stale provider payload without its full version/generation anchor cannot be
    proven current: it must not be re-pointed at the current local/native text."""
    item = provider_citation(monkeypatch)
    item = item.model_copy(update={"sourcePayload": item.sourcePayload.model_copy(update=update)})
    forbid_local_enrichment(monkeypatch)
    svc = resolver()
    svc.runtime_cache_service.get_citation.return_value = item
    issue = AsyncMock(side_effect=AssertionError("issued a handle for an unanchored citation"))
    monkeypatch.setattr(svc, "_issue_provider_handle", issue, raising=False)
    with pytest.raises(NotFoundError) as err:
        await svc.resolve_citation(item.citationId, NS(user_id=9))
    assert err.value.kwargs["reason"] == "expired"
    issue.assert_not_awaited()


async def test_anonymous_knowledge_citation_is_refused(monkeypatch):
    item = provider_citation(monkeypatch)
    forbid_local_enrichment(monkeypatch)
    svc = resolver()
    svc.runtime_cache_service.get_citation.return_value = item
    with pytest.raises(NotFoundError) as err:
        await svc.resolve_citation(item.citationId, None)
    assert err.value.kwargs["reason"] == "forbidden"
    svc._permitted_file_ids.assert_not_awaited()


async def test_shared_provider_snippet_is_readable_without_the_original(monkeypatch):
    item = provider_citation(monkeypatch, access_scope="shared")
    forbid_local_enrichment(monkeypatch)
    svc = Resolver(Mock(), AsyncMock())
    svc._permitted_file_ids = AsyncMock(return_value=set())
    svc.runtime_cache_service.get_citation.return_value = item
    issue = AsyncMock(side_effect=AssertionError("issued the original for a shared snippet"))
    monkeypatch.setattr(svc, "_issue_provider_handle", issue, raising=False)
    result = await svc.resolve_citation(item.citationId, NS(user_id=9))
    payload = result.sourcePayload
    assert payload.snippet == "revision one"
    assert payload.documentName == "远端文件.pdf"
    assert (payload.previewUrl, payload.downloadUrl, payload.sourceUrl) == (None, None, None)
    issue.assert_not_awaited()


async def test_clearing_chat_history_keeps_knowledge_files_and_index(monkeypatch):
    svc = chat.KnowledgeSpaceChatService(None, NS(user_id=9, is_admin=False))
    session = NS(chat_id="c", flow_id="f")
    svc.chat_session_repo = AsyncMock()
    svc.chat_session_repo.find_first_by_effective_entry.return_value = session
    svc.chat_session_repo.get_by_chat_and_effective_entry.return_value = session
    svc._require_file_view_permission = AsyncMock(return_value=NS(id=18))
    svc._require_folder_view_permission = AsyncMock(
        return_value=NS(id=2, knowledge_id=3, file_type=0)
    )
    svc._require_space_view_permission = AsyncMock()
    forbid_native(monkeypatch)
    deleted = []
    monkeypatch.setattr(
        chat.ChatMessageDao,
        "adelete_by_user_chat_id",
        AsyncMock(side_effect=lambda **kwargs: deleted.append(kwargs) or True),
    )
    monkeypatch.setattr(
        chat.MessageSessionDao,
        "delete_session",
        Mock(side_effect=AssertionError("clearing history deleted the session")),
    )
    monkeypatch.setattr(
        chat.KnowledgeDao,
        "delete_knowledge",
        Mock(side_effect=AssertionError("clearing history deleted knowledge content")),
    )
    assert await svc.clear_file_history(3, 18) is True
    assert await svc.delete_chat_folder_history(3, 0, "c") is True
    assert deleted == [
        {"chat_id": "c", "user_id": 9},
        {"chat_id": "c", "user_id": 9},
    ]


async def test_deleting_a_folder_session_keeps_knowledge_files_and_index(monkeypatch):
    svc = chat.KnowledgeSpaceChatService(None, NS(user_id=9, is_admin=False))
    session = NS(chat_id="c", flow_id="f")
    svc.chat_session_repo = AsyncMock()
    svc.chat_session_repo.get_by_chat_and_effective_entry.return_value = session
    svc._require_space_view_permission = AsyncMock()
    forbid_native(monkeypatch)
    removed = []
    monkeypatch.setattr(
        chat.MessageSessionDao,
        "delete_session",
        AsyncMock(side_effect=lambda **kwargs: removed.append(kwargs)),
    )
    monkeypatch.setattr(
        chat.ChatMessageDao,
        "adelete_by_user_chat_id",
        AsyncMock(side_effect=AssertionError("deleting a session cleared messages")),
    )
    monkeypatch.setattr(
        chat.KnowledgeDao,
        "delete_knowledge",
        Mock(side_effect=AssertionError("deleting a session deleted knowledge content")),
    )
    assert await svc.delete_chat_folder_session(3, 0, "c") is True
    assert removed == [{"chat_id": "c"}]


@pytest.mark.parametrize(
    "actor,version,expect",
    [(None, 31, "forbidden"), (NS(user_id=9), 32, "expired"), (NS(user_id=9), 31, "ok")],
)
async def test_resolve_original_version_only(monkeypatch, actor, version, expect):
    item = citation(monkeypatch)
    svc = Resolver(Mock(), AsyncMock())
    svc.runtime_cache_service.get_citation.return_value = item
    svc._permitted_file_ids = AsyncMock(return_value={18})

    async def issue(user, space, file, operation):
        assert user is actor
        return ReadHandle(space, file, version, 2, 4, operation)

    monkeypatch.setattr(svc, "_issue_provider_handle", issue, raising=False)
    if expect != "ok":
        with pytest.raises(NotFoundError) as err:
            await svc.resolve_citation(item.citationId, actor)
        assert err.value.kwargs["reason"] == expect
    else:
        result = await svc.resolve_citation(item.citationId, actor)
        assert result.sourcePayload.previewUrl.startswith("/api/")
        assert result.sourcePayload.downloadUrl.startswith("/api/")