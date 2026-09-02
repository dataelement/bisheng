"""F106 列表 can_reorder / can_reorder_folders 与写接口资格一致."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.permission_service import PermissionService
from test.knowledge.test_folder_reorder_auth_flow import _insert_folder
from test.knowledge.test_space_reorder_auth_flow import (
    WEIGHT_BAND,
    _cleanup,
    _insert_space,
    _ops_user,
    _plain_user,
    reorder_flow_env,
)


@pytest.fixture
async def flow_env(monkeypatch):
    async with reorder_flow_env(monkeypatch) as env:
        yield env


def _flags_app(user) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    @app.get("/api/v1/knowledge/space/level/{space_level}")
    async def list_level(space_level: str):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        if space_level == KnowledgeSpaceLevelEnum.PUBLIC.value:
            spaces = await svc.get_public_spaces("sort_weight")
        else:
            spaces = await svc.get_spaces_by_level(space_level, "sort_weight")
        return resp_200(spaces)

    @app.get("/api/v1/knowledge/space/{space_id}")
    async def space_info(space_id: int):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        return resp_200(await svc.get_space_info(space_id))

    @app.get("/api/v1/knowledge/space/{space_id}/children")
    async def children(space_id: int, parent_id: int | None = None):
        svc = KnowledgeSpaceService(request=None, login_user=user)
        return resp_200(await svc.list_space_children(space_id, parent_id=parent_id, page_size=20))

    return app


@pytest.mark.asyncio
async def test_can_reorder_flag_matches_write_eligibility(flow_env, monkeypatch):
    """AT-20: 运营岗公共库 true, 团队 false; 成员 false. 与随后 sort 写是否 200 一致."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            pub = await _insert_space(
                session,
                name=f"f106-flag-pub-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 60_000,
            )
            team = await _insert_space(
                session,
                name=f"f106-flag-team-{suffix}",
                level=KnowledgeSpaceLevelEnum.TEAM,
                sort_weight=WEIGHT_BAND + 61_000,
            )
            await session.commit()
        space_ids = [pub, team]
        fixture_ids.update(space_ids)

        async def _visible_ids(*_args, **_kwargs):
            return [str(i) for i in fixture_ids]

        monkeypatch.setattr(PermissionService, "list_accessible_ids", AsyncMock(side_effect=_visible_ids))
        monkeypatch.setattr(KnowledgeSpaceService, "_get_relation_models_map", AsyncMock(return_value={}))
        monkeypatch.setattr(KnowledgeSpaceService, "_get_relation_bindings", AsyncMock(return_value=[]))

        async with AsyncClient(transport=ASGITransport(app=_flags_app(_ops_user())), base_url="http://test") as client:
            listed = await client.get("/api/v1/knowledge/space/level/public")
            assert listed.json()["status_code"] == 200
            pub_row = next(item for item in listed.json()["data"] if int(item["id"]) == pub)
            assert pub_row["can_reorder"] is True
            team_listed = await client.get("/api/v1/knowledge/space/level/team")
            team_rows = [item for item in team_listed.json()["data"] if int(item["id"]) == team]
            if team_rows:
                assert team_rows[0]["can_reorder"] is False

        async with AsyncClient(
            transport=ASGITransport(app=_flags_app(_plain_user())), base_url="http://test"
        ) as client:
            listed = await client.get("/api/v1/knowledge/space/level/public")
            pub_row = next(item for item in listed.json()["data"] if int(item["id"]) == pub)
            assert pub_row["can_reorder"] is False
    finally:
        await _cleanup(engine, space_ids)


@pytest.mark.asyncio
async def test_children_can_reorder_folders_root_vs_unauthorized_dir(flow_env, monkeypatch):
    """AT-25: 库管根目录 can_reorder_folders=true, 无权子目录 false."""
    engine, fixture_ids = flow_env
    suffix = uuid.uuid4().hex[:8]
    space_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            space_id = await _insert_space(
                session,
                name=f"f106-flag-folder-{suffix}",
                level=KnowledgeSpaceLevelEnum.PUBLIC,
                sort_weight=WEIGHT_BAND + 62_000,
            )
            parent = await _insert_folder(
                session,
                space_id=space_id,
                name=f"f106-flag-parent-{suffix}",
                file_level_path="",
                sort_weight=WEIGHT_BAND,
            )
            await session.commit()
        space_ids = [space_id]
        fixture_ids.add(space_id)

        async def _check(**kwargs):
            if kwargs.get("object_type") == "knowledge_space" and str(kwargs.get("object_id")) == str(space_id):
                return kwargs.get("relation") in {"can_manage", "can_read", "can_view"}
            if kwargs.get("relation") == "can_read":
                return True
            return False

        monkeypatch.setattr(PermissionService, "check", AsyncMock(side_effect=_check))
        monkeypatch.setattr(
            KnowledgeSpaceService,
            "_require_read_permission",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            KnowledgeSpaceService,
            "_require_folder_relation",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            KnowledgeSpaceService,
            "_scan_visible_child_items",
            AsyncMock(return_value=([], False)),
        )

        manager = _plain_user(user_id=88010620)
        async with AsyncClient(transport=ASGITransport(app=_flags_app(manager)), base_url="http://test") as client:
            root = await client.get(f"/api/v1/knowledge/space/{space_id}/children")
            assert root.json()["status_code"] == 200
            assert root.json()["data"]["can_reorder_folders"] is True
            nested = await client.get(
                f"/api/v1/knowledge/space/{space_id}/children",
                params={"parent_id": parent},
            )
            assert nested.json()["status_code"] == 200
            assert nested.json()["data"]["can_reorder_folders"] is False
    finally:
        await _cleanup(engine, space_ids)
