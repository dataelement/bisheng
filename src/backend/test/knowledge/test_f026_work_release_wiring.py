"""Work's real HTTP route must dispatch by the binding, not a hint on the space row."""

import json
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from langchain_core.documents import Document
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.dsh.domain.services.work_capabilities import WorkCapabilitiesService
from bisheng.knowledge.api import dependencies as deps
from bisheng.knowledge.api.endpoints.knowledge_space import router
from bisheng.knowledge.application import provider_retrieval, provider_v1_runtime
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderGeneration as Generation
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderInstance as Instance
from bisheng.knowledge.domain.models.provider_control import KnowledgeProviderMapping as Mapping
from bisheng.knowledge.domain.repositories.provider_retrieval_repository import ProviderRetrievalRepository
from bisheng.knowledge.domain.services.knowledge_file_visibility_service import KnowledgeFileVisibilityService
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.knowledge.domain.services.retrieval_engine import RetrievalEngine


@pytest.fixture
def _native_route_without_provider_db():
    """Use real SQL routing; a SQL failure must never count as Native here."""

    def sqlite_only(dialect, *_):
        if dialect.name != "sqlite":
            pytest.fail(f"unexpected {dialect.name} connection in isolated route test")

    event.listen(Engine, "do_connect", sqlite_only)
    try:
        yield
    finally:
        event.remove(Engine, "do_connect", sqlite_only)


@pytest.fixture
async def route_client(monkeypatch, async_db_engine):
    async with async_db_engine.begin() as conn:
        for model in (Instance, Generation, Mapping):
            await conn.run_sync(model.__table__.create)
        for stmt in (
            "insert into knowledge_provider_binding (tenant_id,space_id,provider_key,active_generation,state) values (1,7,'weknora',3,'ready')",
            "insert into knowledgefile (id,knowledge_id,file_name) values (11,7,'manual.pdf'),(12,7,'other.pdf')",
            "insert into knowledge_document (id,knowledge_id,primary_version_id) values (21,7,31),(22,7,32)",
            "insert into knowledge_document_version (id,document_id,knowledge_file_id,version_no,is_primary) values (31,21,11,1,1),(32,22,12,1,1)",
        ):
            await conn.execute(text(stmt))
    sessions = partial(AsyncSession, async_db_engine)
    async with sessions() as session:
        session.add(
            Instance(
                id=4,
                tenant_id=1,
                provider_key="weknora",
                endpoint="unused",
                credential_ref="unused",
                remote_scope_id="scope",
                state="ready",
                capability_revision=1,
            )
        )
        session.add(
            Generation(
                tenant_id=1,
                space_id=7,
                generation=3,
                provider_instance_id=4,
                remote_scope_id="scope",
                remote_kb_id="kb",
                state="ready",
            )
        )
        for i in (1, 2):
            session.add(
                Mapping(
                    tenant_id=1,
                    space_id=7,
                    generation=3,
                    resource_type="file",
                    local_resource_id=10 + i,
                    logical_document_id=20 + i,
                    version_id=30 + i,
                    remote_object_id=f"R{i}",
                    lifecycle_state="active",
                    ready_revision=0,
                )
            )
        await session.commit()
    monkeypatch.setattr(
        provider_retrieval, "ProviderRetrievalRepository", partial(ProviderRetrievalRepository, sessions)
    )
    user = SimpleNamespace(user_id=27, tenant_id=1)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[deps.UserPayload.get_login_user] = lambda: user
    version_repo = object()
    app.dependency_overrides[deps.get_knowledge_document_version_repository] = lambda: version_repo
    monkeypatch.setattr(
        WorkCapabilitiesService,
        "_tools",
        AsyncMock(return_value={1: SimpleNamespace(tool_key="bisheng_knowledge_search")}),
    )
    monkeypatch.setattr(
        KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=lambda i: SimpleNamespace(id=i, type=3, tenant_id=1))
    )
    monkeypatch.setattr(KnowledgeFileDao, "aget_file_by_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(KnowledgeSpaceService, "_require_read_permission", AsyncMock())
    monkeypatch.setattr(KnowledgeSpaceService, "_require_action", AsyncMock())

    async def visible(self, space, ids):
        assert self.login_user is user and self.version_repo is version_repo
        assert space == 7 and set(ids) == {11, 12}
        return {11}

    monkeypatch.setattr(KnowledgeFileVisibilityService, "post_filter_visible_files", visible)
    calls = []

    def search(request):
        assert request.method == "POST" and request.url.path == "/knowledge-bases/kb/hybrid-search"
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {"knowledge_id": f"R{i}", "content": f"external-{i}", "id": f"chunk-{i}", "chunk_index": 0}
                    for i in (2, 1)
                ],
            },
        )

    @asynccontextmanager
    async def transport(route):
        assert (route.tenant_id, route.space_id, route.generation) == (1, 7, 3)
        async with httpx.AsyncClient(base_url="https://provider.test", transport=httpx.MockTransport(search)) as client:
            yield client

    monkeypatch.setattr(provider_v1_runtime, "instance_client", transport)

    async def native(self, *, space, sort_by_source_and_index, **kwargs):
        assert self.login_user is user and sort_by_source_and_index is False
        return [Document(page_content=f"native-{space.id}-{i}") for i in (2, 1)]

    monkeypatch.setattr(RetrievalEngine, "retrieve_and_filter", native)
    with tenant_execution_scope(1):
        async with httpx.AsyncClient(base_url="http://work.test", transport=httpx.ASGITransport(app)) as client:
            yield client, calls


async def test_work_dispatches_unmarked_bound_space(route_client):
    client, calls = route_client
    response = await client.post("/knowledge/space/retrieve", json={"space_ids": [7], "query": "q"})
    response.raise_for_status()
    assert calls == [{"query_text": "q", "knowledge_ids": ["R1"], "skip_context_enrichment": True}]
    assert response.json()["data"]["chunks"] == [
        {"content": "external-1", "space_id": 7, "document_id": 11, "document_name": "manual.pdf", "chunk_index": 0}
    ]


async def test_work_native_order_stays_per_space_then_per_hit(route_client):
    client, calls = route_client
    response = await client.post("/knowledge/space/retrieve", json={"space_ids": [9, 8, 9], "query": "q"})
    response.raise_for_status()
    assert [c["content"] for c in response.json()["data"]["chunks"]] == [
        "native-9-2",
        "native-9-1",
        "native-8-2",
        "native-8-1",
    ]
    assert not calls


async def test_work_checks_space_visibility_before_external_recall(route_client, monkeypatch):
    client, calls = route_client
    gate = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr(KnowledgeSpaceService, "_require_action", gate)
    response = await client.post("/knowledge/space/retrieve", json={"space_ids": [7], "query": "q"})
    assert response.status_code == 403
    gate.assert_awaited_once_with("knowledge_space", 7, "visible")
    assert not calls
