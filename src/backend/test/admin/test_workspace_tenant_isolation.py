"""Browser admission isolates discovery and historical creator memberships."""

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.admin.application import request_admission
from bisheng.api.services.tag import TagService
from bisheng.api.v1.tag import router as tag_router
from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.services.channel_service import ChannelService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.channel import ChannelNotFoundError
from bisheng.common.errcode.tag import TagNotExistError
from bisheng.common.models import config as config_module
from bisheng.common.models.config import Config
from bisheng.common.models.space_channel_member import SpaceChannelMember
from bisheng.common.request_scope import RequestScope, inherit_scope, request_scope
from bisheng.common.schemas.api import resp_200
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models import tag as tag_module
from bisheng.database.models.group_resource import ResourceTypeEnum
from bisheng.database.models.tag import Tag, TagDao, TagLink
from bisheng.knowledge.domain.models import knowledge as knowledge_module
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.services import knowledge_space_service as space_module
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.llm.domain.models import llm_server as llm_module
from bisheng.llm.domain.models.llm_server import LLMDao, LLMServer
from bisheng.llm.domain.services.llm import LLMService
from bisheng.workstation.domain.models import tenant_workstation_config as workstation_module
from bisheng.workstation.domain.models.tenant_workstation_config import TenantWorkstationConfig
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter

OWNER = 849
TENANTS = (1, 60, 70)


@pytest.fixture
async def workspace(tmp_path, monkeypatch, isolated_tenant_filter):
    url = f"sqlite:///{tmp_path / 'workspace.db'}"
    sync_engine = create_engine(url, connect_args={"check_same_thread": False})
    async_engine = create_async_engine(url.replace("sqlite:", "sqlite+aiosqlite:"))
    for model in (Knowledge, SpaceChannelMember, Channel, Tag, TagLink, Config, LLMServer, TenantWorkstationConfig):
        model.__table__.create(sync_engine)
    now = datetime(2026, 11, 19)
    with bypass_tenant_filter(), Session(sync_engine) as session:
        for tenant in TENANTS:
            session.add(
                Knowledge(
                    id=tenant,
                    tenant_id=tenant,
                    user_id=OWNER,
                    name=f"space-{tenant}",
                    type=3,
                    is_released=True,
                    auth_type="public",
                    create_time=now,
                    update_time=now,
                )
            )
            # Old creator facts survive a user's tenant reassignment.
            session.add(
                SpaceChannelMember(
                    business_id=str(tenant), business_type="SPACE", user_id=OWNER, user_role="creator", status="ACTIVE"
                )
            )
            session.add(
                Channel(
                    id=f"channel-{tenant}",
                    tenant_id=tenant,
                    user_id=OWNER,
                    name=f"channel-{tenant}",
                    visibility="public",
                    is_released=True,
                    source_list=[],
                    filter_rules=[],
                    create_time=now,
                    update_time=now,
                )
            )
            session.add(
                Tag(
                    id=tenant,
                    tenant_id=tenant,
                    user_id=OWNER,
                    name=f"tag-{tenant}",
                    business_type="application",
                    business_id="application",
                )
            )
            session.add(LLMServer(id=tenant, tenant_id=tenant, user_id=OWNER, name=f"provider-{tenant}", type="openai"))
            session.add(
                TagLink(
                    id=tenant,
                    tag_id=tenant,
                    tenant_id=tenant,
                    user_id=OWNER,
                    resource_id=f"historical-{tenant}",
                    resource_type=ResourceTypeEnum.WORK_FLOW.value,
                )
            )
        session.add(Config(key="home_tags", value="[1, 60, 70]"))
        session.commit()

    @asynccontextmanager
    async def async_session():
        async with AsyncSession(async_engine, expire_on_commit=False) as session:
            yield session

    @contextmanager
    def sync_session():
        with Session(sync_engine) as session:
            yield session

    monkeypatch.setattr(knowledge_module, "get_async_db_session", async_session)
    from bisheng.common.models import space_channel_member as member_module

    monkeypatch.setattr(member_module, "get_async_db_session", async_session)
    monkeypatch.setattr(tag_module, "get_sync_db_session", sync_session)
    monkeypatch.setattr(tag_module, "get_async_db_session", async_session)
    monkeypatch.setattr(config_module, "get_sync_db_session", sync_session)
    monkeypatch.setattr(config_module, "get_async_db_session", async_session)
    monkeypatch.setattr(workstation_module, "get_async_db_session", async_session)
    monkeypatch.setattr(llm_module, "get_async_db_session", async_session)
    monkeypatch.setattr(
        space_module.DepartmentKnowledgeSpaceDao, "aget_department_ids_by_space_ids", AsyncMock(return_value={})
    )
    monkeypatch.setattr(space_module.KnowledgeSpaceUserPinDao, "list_pinned_space_ids", AsyncMock(return_value=set()))
    user = SimpleNamespace(user_id=OWNER, tenant_id=1, is_global_super=False)
    monkeypatch.setattr(request_admission, "authenticate_browser", AsyncMock(return_value=user))
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.dependency_overrides[UserPayload.get_admin_user] = lambda: user

    @app.exception_handler(BaseErrorCode)
    async def domain_error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    inherit_scope(tag_router, RequestScope.TENANT)
    app.include_router(tag_router, prefix="/api/v1")

    @app.get("/mine")
    @request_scope(RequestScope.TENANT)
    async def mine():
        return resp_200(await KnowledgeSpaceService(request=None, login_user=user).get_my_created_spaces())

    @app.get("/square")
    @request_scope(RequestScope.TENANT)
    async def square(page: int = 1, keyword: str | None = None):
        rows = await KnowledgeDao.async_get_public_spaces_paginated(OWNER, keyword=keyword, page=page, page_size=1)
        return resp_200(
            {"ids": [row[0].id for row in rows], "total": await KnowledgeDao.async_count_public_spaces(keyword=keyword)}
        )

    @app.get("/channels")
    @request_scope(RequestScope.TENANT)
    async def channels():
        async with async_session() as session:
            repository = ChannelRepositoryImpl(session)
            rows = await repository.find_square_channels(OWNER)
            recommendations = await repository.find_public_recommend_channels(OWNER)
            return resp_200(
                {
                    "ids": [row[0].id for row in rows],
                    "recommendations": [row[0].id for row in recommendations],
                    "total": await repository.count_square_channels(),
                }
            )

    @app.get("/channels/{channel_id}")
    @request_scope(RequestScope.TENANT)
    async def channel_detail(channel_id: str):
        async with async_session() as session:
            service = ChannelService(
                channel_repository=ChannelRepositoryImpl(session),
                space_channel_member_repository=None,
                channel_info_source_repository=None,
                article_es_service=None,
            )
            try:
                return resp_200(await service.get_channel_detail(channel_id, user))
            except ChannelNotFoundError as exc:
                return exc.return_resp_instance()

    request_admission.install_request_admission(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(client=client, user=user, async_session=async_session)
    await async_engine.dispose()
    sync_engine.dispose()


def success(response):
    assert response.status_code == 200
    body = response.json()
    assert body["status_code"] == 200, body
    assert "status_message" in body
    return body["data"]


async def test_creator_reassignment_never_carries_old_tenant_spaces(workspace):
    """The same creator sees Root, child A, then child B resources separately."""
    for tenant in TENANTS:
        workspace.user.tenant_id = tenant
        result = success(await workspace.client.get("/mine"))
        assert [row["id"] for row in result] == [tenant]
        assert {row["tenant_id"] for row in result} == {tenant}
    # Reads and reassignment never migrate the original business rows.
    with bypass_tenant_filter():
        rows = await KnowledgeDao.async_get_spaces_by_ids(list(TENANTS))
    assert {(row.id, row.tenant_id) for row in rows} == {(tenant, tenant) for tenant in TENANTS}


@pytest.mark.parametrize("tenant", TENANTS)
async def test_square_count_search_and_pagination_use_one_tenant(workspace, tenant):
    workspace.user.tenant_id = tenant
    assert success(await workspace.client.get("/square")) == {"ids": [tenant], "total": 1}
    assert success(await workspace.client.get("/square?page=2")) == {"ids": [], "total": 1}
    foreign = 60 if tenant == 1 else 1
    assert success(await workspace.client.get(f"/square?keyword=space-{foreign}")) == {"ids": [], "total": 0}


@pytest.mark.parametrize("tenant", TENANTS)
async def test_channel_square_recommendations_and_tags_cannot_include_root(workspace, tenant):
    workspace.user.tenant_id = tenant
    result = success(await workspace.client.get("/channels"))
    assert result == {"ids": [f"channel-{tenant}"], "recommendations": [f"channel-{tenant}"], "total": 1}
    assert [row["id"] for row in success(await workspace.client.get("/api/v1/tag/home"))] == [tenant]


@pytest.mark.parametrize("tenant,foreign", [(60, 1), (60, 70), (1, 60)])
async def test_foreign_public_channel_detail_is_absent_even_for_its_creator(workspace, tenant, foreign):
    workspace.user.tenant_id = tenant
    response = await workspace.client.get(f"/channels/channel-{foreign}")
    assert response.status_code == 200
    assert response.json()["status_code"] == ChannelNotFoundError.Code


@pytest.mark.parametrize("shared,expected", [([], {60}), ([1], {1, 60}), ([1, 70], {1, 60})])
async def test_explicit_root_model_sharing_still_works_in_an_isolated_request(workspace, monkeypatch, shared, expected):
    monkeypatch.setattr(LLMDao, "aget_shared_server_ids_for_leaf", AsyncMock(return_value=shared))
    admitted = request_admission.AdmittedRequest(OWNER, 60, 60, RequestScope.TENANT, False)
    with request_admission.bind_admitted_scope(admitted):
        servers = await LLMService.acollect_visible_servers(60)
    assert {server.id for server in servers} == expected


async def test_home_tag_updates_never_change_another_tenants_choices(workspace):
    workspace.user.tenant_id = 60
    success(await workspace.client.post("/api/v1/tag/home", json={"tag_ids": []}))
    assert success(await workspace.client.get("/api/v1/tag/home")) == []
    workspace.user.tenant_id = 1
    assert [row["id"] for row in success(await workspace.client.get("/api/v1/tag/home"))] == [1]
    workspace.user.tenant_id = 60
    success(await workspace.client.post("/api/v1/tag/home", json={"tag_ids": [60, 60]}))
    assert [row["id"] for row in success(await workspace.client.get("/api/v1/tag/home"))] == [60]
    rejected = await workspace.client.post("/api/v1/tag/home", json={"tag_ids": [1]})
    assert rejected.json()["status_code"] == TagNotExistError.Code
    assert [row["id"] for row in success(await workspace.client.get("/api/v1/tag/home"))] == [60]
    workspace.user.tenant_id = 70
    assert [row["id"] for row in success(await workspace.client.get("/api/v1/tag/home"))] == [70]


async def test_tag_deletion_and_tag_links_reject_foreign_tags(workspace, monkeypatch):
    workspace.user.tenant_id = 60
    # Isolate tag ownership from the separately tested resource action gate.
    monkeypatch.setattr(TagService, "check_tag_link_permission", lambda *args, **kwargs: True)
    rejected = await workspace.client.request("DELETE", "/api/v1/tag", json={"tag_id": 1})
    assert rejected.json()["status_code"] == TagNotExistError.Code
    payload = {"tag_id": 1, "resource_id": "editable-own-resource", "resource_type": ResourceTypeEnum.WORK_FLOW.value}
    rejected = await workspace.client.post("/api/v1/tag/link", json=payload)
    assert rejected.json()["status_code"] == TagNotExistError.Code
    payload["tag_id"] = 60
    assert success(await workspace.client.post("/api/v1/tag/link", json=payload))["tenant_id"] == 60
    success(await workspace.client.request("DELETE", "/api/v1/tag", json={"tag_id": 60}))
    with bypass_tenant_filter():
        assert {row.id for row in TagDao.get_tags_by_ids(list(TENANTS))} == {1, 70}
        assert TagDao.get_tag_link(1) is not None
        assert TagDao.get_tag_link(60) is None


async def test_bulk_tag_deletes_cannot_cross_tenants_without_service_guards(workspace):
    admitted = request_admission.AdmittedRequest(OWNER, 60, 60, RequestScope.TENANT, False)
    with request_admission.bind_admitted_scope(admitted):
        TagDao.delete_tag(1)
        TagDao.delete_tag_link(70)
        TagDao.delete_resource_tag(1, "historical-1", ResourceTypeEnum.WORK_FLOW)
    with bypass_tenant_filter():
        assert {row.id for row in TagDao.get_tags_by_ids(list(TENANTS))} == set(TENANTS)
        assert TagDao.get_tag_link(1) is not None
        assert TagDao.get_tag_link(70) is not None
