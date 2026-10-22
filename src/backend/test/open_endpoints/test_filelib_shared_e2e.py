from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI
from langchain_core.documents import Document

from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_repository_impl import KnowledgeRepositoryImpl
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import SharedContentIngestionTarget
from bisheng.knowledge.domain.services.knowledge_document_entry_resolver import KnowledgeDocumentEntryResolver
from bisheng.open_endpoints.api import dependencies
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.services.filelib_file_source_service import FilelibFileSourceService
from bisheng.open_endpoints.domain.services.filelib_retrieve_source_service import FilelibRetrieveSourceService
from bisheng.open_endpoints.domain.services.filelib_space_command_service import FilelibSpaceCommandService
from bisheng.open_endpoints.domain.services.filelib_space_content_service import FilelibSpaceContentService
from bisheng.open_endpoints.domain.services.filelib_space_query_service import FilelibSpaceQueryService
from test.open_endpoints.test_filelib_shared_content import real_text_utilities as utilities_fixture
from test.open_endpoints.test_filelib_shared_repository import repository as repository_fixture

real_text_utilities = utilities_fixture
repository = repository_fixture


async def test_http_shared_document_round_trip_preserves_other_space_content(
    repository, real_text_utilities, monkeypatch
):
    """HTTP + actual Filelib services/ORM/resolver/direct writer; external backends are controlled."""
    session = repository.session
    user = SimpleNamespace(user_id=5, tenant_id=1)
    for space_id in (7, 8):
        session.add(Knowledge(id=space_id, tenant_id=1, user_id=5, name=f"space-{space_id}", type=3, state=1))
    await session.commit()
    route = SimpleNamespace(
        tenant_id=1,
        routing_version=1,
        write_frozen=False,
        embedding_model_id=7,
        index_name="tenant_shared",
        collection_name="tenant_vectors",
    )
    owner = SimpleNamespace(
        _require_read_permission=AsyncMock(),
        require_root_upload_permission=AsyncMock(),
        _get_effective_permission_ids=AsyncMock(return_value={"view_file", "delete_file"}),
    )
    query = FilelibSpaceQueryService(request=None, user=user, repository=repository, space_service=owner)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_query_service.aresolve_space_shared_routing",
        AsyncMock(return_value=route),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.repositories.implementations.knowledge_mcp_repository_impl.aresolve_space_shared_routing",
        AsyncMock(return_value=route),
    )
    originals = {"original/99.txt"}
    storage = SimpleNamespace(
        bucket="files",
        object_exists=AsyncMock(side_effect=lambda bucket_name, object_name: object_name in originals),
        get_object=AsyncMock(side_effect=AssertionError("there is no text preview")),
        get_share_link=AsyncMock(return_value="https://files.example/original/99.txt?signature=controlled"),
        clear_minio_share_host=lambda value: value.removeprefix("https://files.example"),
    )
    versions = KnowledgeDocumentVersionRepositoryImpl(session)
    resolver = KnowledgeDocumentEntryResolver(
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=versions,
        file_repository=repository,
        permission_loader=AsyncMock(return_value={"view_file", "delete_file"}),
    )
    query.content_service = FilelibSpaceContentService(
        repository=repository, resolver=resolver, storage=storage, guard=query, user=user
    )
    command = FilelibSpaceCommandService(query=query)
    shared = {}

    class Writer:
        async def upsert_content(self, request):
            identity = request.identity
            shared[int(identity.canonical_document_id)] = [
                {
                    "text": chunk.text,
                    "metadata": {
                        **chunk.metadata,
                        "chunk_index": chunk.chunk_index,
                        "canonical_document_id": int(identity.canonical_document_id),
                        "canonical_version_id": int(identity.canonical_version_id),
                        "content_generation": identity.content_generation,
                        "knowledge_ids": list(request.knowledge_ids),
                    },
                }
                for chunk in request.chunks
            ]

        async def update_membership(self, request):
            for chunk in shared.get(int(request.canonical_document_id), []):
                chunk["metadata"]["knowledge_ids"] = list(request.knowledge_ids)

    writer = Writer()
    target = SharedContentIngestionTarget(1, 100, 200, 99, 3, 1, (7,))
    direct = "bisheng.knowledge.domain.services.shared_space_direct_ingestion_service."
    monkeypatch.setattr(
        direct + "LLMService.get_bisheng_knowledge_embedding_sync",
        MagicMock(return_value=SimpleNamespace(embed_documents=lambda values: [[0.1, 0.2] for _ in values])),
    )
    monkeypatch.setattr(direct + "SharedSpaceDirectIngestionService._prepare_target", AsyncMock(return_value=target))
    monkeypatch.setattr(direct + "SharedSpaceDirectIngestionService._finalize_target", AsyncMock())
    monkeypatch.setattr(direct + "build_shared_space_components_for_tenant", lambda *args, **kwargs: (writer, None))
    cmd = "bisheng.open_endpoints.domain.services.filelib_space_command_service."
    monkeypatch.setattr(cmd + "save_download_file", lambda *args: "/tmp/f112-controlled.txt")
    monkeypatch.setattr(cmd + "QuotaService.get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=None))

    async def save_input(*args, **kwargs):
        file = KnowledgeFile(
            id=99,
            tenant_id=1,
            knowledge_id=7,
            user_id=5,
            updater_id=5,
            file_type=1,
            file_name="data.txt",
            object_name="original/99.txt",
            file_encoding="CODE",
            status=5,
        )
        session.add(file)
        await session.commit()
        await session.refresh(file)
        return await repository.get_space(7), [], [file], []

    async def persist(file_id, status, remark=""):
        file = await session.get(KnowledgeFile, file_id)
        file.status, file.remark = status, remark
        if status == 2:
            session.add(
                KnowledgeDocument(
                    id=100,
                    tenant_id=1,
                    knowledge_id=7,
                    primary_version_id=200,
                    content_generation=3,
                    lifecycle_status="active",
                )
            )
            session.add(
                KnowledgeDocumentVersion(
                    id=200, tenant_id=1, document_id=100, knowledge_file_id=99, version_no=1, is_primary=True
                )
            )
            file.reference_document_id, file.entry_type, file.entry_status = 100, "manager", "active"
            file.projection_status = "ready"
            file.desired_content_generation = file.applied_content_generation = 3
            file.desired_entry_generation = file.applied_entry_generation = 1
        await session.commit()
        await session.refresh(file)
        return file

    monkeypatch.setattr(cmd + "KnowledgeService.asave_knowledge_file", save_input)
    monkeypatch.setattr(repository, "persist_parse_result", persist)

    def matches(chunk, filters):
        for clause in filters:
            if "term" in clause:
                for field, expected in clause["term"].items():
                    actual = chunk["metadata"].get(field.removeprefix("metadata."))
                    if expected not in actual if isinstance(actual, list) else actual != expected:
                        return False
            if "range" in clause:
                if chunk["metadata"]["chunk_index"] < clause["range"]["metadata.chunk_index"]["gte"]:
                    return False
        return True

    async def search(**request):
        assert request["index"] == "tenant_shared"
        chunks = shared.get(100, [])
        if "aggs" in request:
            filters = request["aggs"]["entries"]["filters"]["filters"]
            return {
                "aggregations": {
                    "entries": {
                        "buckets": {
                            key: {
                                "first": {
                                    "hits": {
                                        "hits": [{"_source": c} for c in chunks if matches(c, value["bool"]["filter"])][
                                            :1
                                        ]
                                    }
                                }
                            }
                            for key, value in filters.items()
                        }
                    }
                }
            }
        selected = [c for c in chunks if matches(c, request["query"]["bool"]["filter"])]
        return {"hits": {"hits": [{"_source": c} for c in selected[: request["size"]]]}}

    es = SimpleNamespace(search=search)
    for module in ("knowledge_mcp_repository_impl", "filelib_space_repository_impl"):
        monkeypatch.setattr(
            f"bisheng.knowledge.domain.repositories.implementations.{module}.get_es_connection",
            AsyncMock(return_value=es),
        )

    async def list_page(*args, **kwargs):
        assert kwargs["include_titles"] is False
        rows = await repository.scan_files([7], file_type=1)
        return rows, len(rows), True

    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_query_service.KnowledgeService.aget_knowledge_files",
        list_page,
    )
    source_links = FilelibRetrieveSourceService(
        file_repository=repository, version_repository=versions, storage=storage
    )
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_retrieve_source_service.KnowledgeUtils", real_text_utilities
    )
    source = FilelibFileSourceService(
        request=None,
        login_user=user,
        file_repository=repository,
        knowledge_repository=KnowledgeRepositoryImpl(session),
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=versions,
        source_service=source_links,
    )
    source.space_service = owner

    async def retrieved(**kwargs):
        file = await repository.find_by_id(99)
        rows = await repository.chunks(file, (100, 200, 3), from_index=0)
        return [
            (
                7,
                Document(
                    page_content=c["text"], metadata={**c["metadata"], "document_id": 99, "document_name": "data.txt"}
                ),
            )
            for c in rows
        ]

    monkeypatch.setattr(
        filelib,
        "build_knowledge_space_chat_service_for_openapi",
        lambda **kwargs: SimpleNamespace(aretrieve_chunks=retrieved),
    )
    monkeypatch.setattr(filelib, "build_filelib_space_query_service", lambda **kwargs: query)

    @asynccontextmanager
    async def use_user(*args):
        yield user

    async def batch_delete(space_id, file_ids, folder_ids):
        assert space_id == 8 and not folder_ids
        for file_id in file_ids:
            entry = await session.get(KnowledgeFile, file_id)
            entry.deleted_at, entry.entry_status = datetime(2026, 10, 22), "invalid"
        await session.commit()
        for chunk in shared[100]:
            chunk["metadata"]["knowledge_ids"] = [7]

    owner.batch_delete = batch_delete
    app = FastAPI()
    app.include_router(filelib.router, prefix="/api/v2")

    def override(value):
        return lambda: value

    for dependency, value in [
        (dependencies.get_filelib_request_user, user),
        (dependencies.get_filelib_space_query_service, query),
        (dependencies.get_filelib_space_command_service, command),
        (dependencies.get_filelib_file_source_service, source),
        (dependencies.get_filelib_developer_token_principal, SimpleNamespace(user=user)),
        (dependencies.get_filelib_user_context_service, SimpleNamespace(use_user=use_user)),
        (dependencies.get_filelib_knowledge_document_repository, resolver.document_repository),
        (dependencies.get_filelib_knowledge_document_version_repository, versions),
        (dependencies.get_knowledge_file_repository, repository),
        (dependencies.get_filelib_retrieve_source_service, source_links),
        (
            filelib.get_async_retrieval_runtime,
            SimpleNamespace(config=SimpleNamespace(total_timeout_seconds=10, source_link_timeout_seconds=2)),
        ),
    ]:
        app.dependency_overrides[dependency] = override(value)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://controlled") as client:
        response = await client.post(
            "/api/v2/filelib/chunks_string",
            json={
                "knowledge_id": 7,
                "documents": [
                    {"page_content": "段落一", "metadata": {"source": "data.txt", "abstract": "共享摘要"}},
                    {"page_content": "段落二", "metadata": {"source": "data.txt"}},
                ],
            },
        )
        assert response.status_code == 200 and response.json()["data"]["status"] == 2
        listing = (await client.get("/api/v2/filelib/file/list?knowledge_id=7")).json()["data"]
        assert listing["total"] == 1 and listing["data"][0]["title"] == "共享摘要"
        detail = (await client.get("/api/v2/filelib/file/detail?file_encoding=CODE")).json()["data"]
        assert detail["content"] == "段落一\n段落二" and detail["chunk_count"] == 2
        hits = (
            await client.post("/api/v2/filelib/retrieve", json={"query": "段落", "knowledge_base_ids": [7]})
        ).json()["data"]
        assert hits["total"] == 2 and hits["chunks"][0]["source_full_url"].startswith("https://files.example/")
        address = (await client.get("/api/v2/filelib/file/source_url?file_id=99")).json()["data"]
        assert address["file_id"] == 99 and "original/99.txt" in address["source_full_url"]
        session.add(
            KnowledgeFile(
                id=12,
                tenant_id=1,
                knowledge_id=8,
                file_type=1,
                file_name="data.txt",
                status=2,
                reference_document_id=100,
                entry_type="publish",
                entry_status="active",
                projection_status="ready",
                desired_content_generation=3,
                applied_content_generation=3,
                desired_entry_generation=1,
                applied_entry_generation=1,
                object_name=None,
                file_size=0,
            )
        )
        await session.commit()
        for chunk in shared[100]:
            chunk["metadata"]["knowledge_ids"] = [7, 8]
        cleared = await client.delete("/api/v2/filelib/clear/8")
        assert cleared.status_code == 200 and (await repository.get_space(8)).state == 1
        assert await repository.find_by_id(12) is None and originals == {"original/99.txt"}
        remaining = (await client.get("/api/v2/filelib/file/detail?file_encoding=CODE")).json()["data"]
        assert remaining["content"] == detail["content"] and len(shared[100]) == 2
