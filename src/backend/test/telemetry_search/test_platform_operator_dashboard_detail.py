"""AT-30: 运营岗看板详情/组件查询在无 ReBAC tuple 时仍可读."""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME


def _ops_user(*, user_id: int = 88004001) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="ops-dashboard",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
        async_access_check=AsyncMock(return_value=False),
    )


@pytest.mark.asyncio
async def test_ops_dashboard_detail_without_rebac_read(monkeypatch):
    from bisheng.telemetry_search.domain.models.dashboard import (
        Dashboard,
        DashboardComponent,
        DashboardStatus,
        DashboardType,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    dashboard = Dashboard(
        id=10,
        title="统计看板",
        status=DashboardStatus.PUBLISHED.value,
        dashboard_type=DashboardType.PRESET_OSS.value,
        user_id=1,
    )
    component = DashboardComponent(
        id="comp-1",
        dashboard_id=10,
        type="chart",
        dataset_code="mid_knowledge_space_content_stat",
    )
    monkeypatch.setattr(module.DashboardDao, "get_one", AsyncMock(return_value=dashboard))
    monkeypatch.setattr(module.DashboardDao, "get_components", AsyncMock(return_value=[component]))
    monkeypatch.setattr(module.DashboardDao, "get_default_dashboard", AsyncMock(return_value=None))
    monkeypatch.setattr(
        module.UserService,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(user_name="admin")),
    )

    service = module.DashboardService.model_construct(login_user=_ops_user())
    detail = await service.get_dashboard_detail(10, from_share=False)

    assert detail.id == 10
    assert detail.write is True
    assert detail.components[0].id == "comp-1"


@pytest.mark.asyncio
async def test_ops_query_component_data_without_rebac_read(monkeypatch):
    from bisheng.telemetry_search.domain.models.dashboard import (
        Dashboard,
        DashboardComponent,
        DashboardStatus,
        DashboardType,
    )
    from bisheng.telemetry_search.domain.services import dashboard as module

    dashboard = Dashboard(
        id=10,
        title="统计看板",
        status=DashboardStatus.PUBLISHED.value,
        dashboard_type=DashboardType.PRESET_OSS.value,
        user_id=1,
    )
    component = DashboardComponent(
        id="comp-1",
        dashboard_id=10,
        type="chart",
        dataset_code="mid_knowledge_space_content_stat",
        data_config={"metrics": [], "dimensions": []},
    )
    monkeypatch.setattr(module.DashboardDao, "get_one", AsyncMock(return_value=dashboard))
    monkeypatch.setattr(module.DashboardDao, "get_one_component", AsyncMock(return_value=component))
    monkeypatch.setattr(module.DashboardDao, "get_components", AsyncMock(return_value=[component]))
    monkeypatch.setattr(
        module.DataQueryService,
        "query_telemetry_data",
        AsyncMock(return_value={"rows": []}),
    )

    service = module.DashboardService.model_construct(login_user=_ops_user())
    result = await service.query_component_data(10, component_id="comp-1")

    assert result == {"rows": []}


def _mysql_async_url() -> str:
    override = os.environ.get("PLATFORM_OPERATOR_FLOW_DATABASE_URL")
    if override:
        return override.replace("pymysql", "aiomysql")
    from bisheng.core.config.settings import decrypt_token

    cfg_name = os.environ.get("config", "config.yaml")
    cfg_path = Path(__file__).resolve().parents[2] / "bisheng" / Path(cfg_name).name
    loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    url = loaded["database_url"]
    if not isinstance(url, str):
        raise RuntimeError("config.yaml database_url 不是字符串")
    match = re.search(r"(?<=:)[^:]+(?=@)", url)
    if match:
        url = re.sub(r"(?<=:)[^:]+(?=@)", decrypt_token(match.group(0)), url)
    if "171" not in url and not override:
        raise RuntimeError("流转测试默认打 192.168.106.171, 请确认 config.yaml")
    return url.replace("pymysql", "aiomysql")


@pytest.fixture
async def mysql_engine():
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping

    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_ops_dashboard_detail_api_flow_mysql(mysql_engine, monkeypatch):
    """U-ops GET 看板详情 200; 响应与 dashboard 表一致."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import text
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.telemetry_search.api.endpoints.dashboard import router as dashboard_router

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    set_current_tenant_id(1)

    login_user = UserPayload(
        user_id=838,
        user_name="ht056-ops",
        user_role=[2, 9],
        role_names=["普通用户", PLATFORM_OPERATOR_ROLE_NAME],
        tenant_id=1,
        is_global_super=False,
    )

    @asynccontextmanager
    async def patched_async_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.telemetry_search.domain.models.dashboard_dao.get_async_db_session",
        patched_async_session,
    )
    monkeypatch.setattr(
        "bisheng.user.domain.services.user.UserService.get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(user_name="admin")),
    )

    async with AsyncSession(bind=engine, expire_on_commit=False) as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, title FROM dashboard "
                    "WHERE dashboard_type = 'preset_oss' ORDER BY id ASC LIMIT 1"
                )
            )
        ).first()
    assert row is not None, "171 上应至少有一个 preset_oss 看板"
    dashboard_id, db_title = row[0], row[1]

    app = FastAPI()
    app.include_router(dashboard_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: login_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/dashboard/{dashboard_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status_code"] == 200
        assert body["data"]["id"] == dashboard_id
        assert body["data"]["title"] == db_title

        again = await client.get(f"/api/v1/dashboard/{dashboard_id}")
        assert again.status_code == 200
        assert again.json()["data"]["id"] == dashboard_id
