"""AT-30/47: 运营岗可看板/标签/敏感词; 审批超管 API 仍 403."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.tag import ReviewTagPermissionDeniedError
from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME


def _ops_user(*, user_id: int = 88004001) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="ops-tag-admin",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
        has_tenant_admin=AsyncMock(return_value=False),
        aget_user_access_resource_ids=AsyncMock(return_value=[]),
    )


def _plain_user(*, user_id: int = 88004002) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="plain-tag-user",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=["普通用户"],
        has_tenant_admin=AsyncMock(return_value=False),
        aget_user_access_resource_ids=AsyncMock(return_value=[]),
    )


@pytest.mark.asyncio
async def test_tag_console_allows_operator(monkeypatch):
    from bisheng.workstation.domain.services.tag_console_service import TagConsoleService

    monkeypatch.setattr(
        "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
        AsyncMock(return_value=[]),
    )
    svc = TagConsoleService(login_user=_ops_user(), repository=AsyncMock(), tags_service=AsyncMock())
    await svc._ensure_can_manage_tags()


@pytest.mark.asyncio
async def test_tag_console_rejects_ordinary(monkeypatch):
    from bisheng.workstation.domain.services.tag_console_service import TagConsoleService

    monkeypatch.setattr(
        "bisheng.database.models.department.DepartmentDao.aget_user_admin_departments",
        AsyncMock(return_value=[]),
    )
    svc = TagConsoleService(login_user=_plain_user(), repository=AsyncMock(), tags_service=AsyncMock())
    with pytest.raises(ReviewTagPermissionDeniedError) as exc:
        await svc._ensure_can_manage_tags()
    assert exc.value.Code == 10712


@pytest.mark.asyncio
async def test_ops_dashboard_list_uses_admin_scope(monkeypatch):
    from bisheng.telemetry_search.domain.models.dashboard_dao import DashboardDao
    from bisheng.telemetry_search.domain.services.dashboard import DashboardService

    captured: dict = {}

    async def fake_get_dashboards(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(DashboardDao, "get_dashboards", fake_get_dashboards)
    monkeypatch.setattr(DashboardDao, "get_default_dashboard", AsyncMock(return_value=None))
    svc = DashboardService.model_construct(login_user=_ops_user())
    result = await svc.get_dashboards()
    assert result == []
    assert "user_id" not in captured


@pytest.mark.asyncio
async def test_approval_admin_still_rejects_operator():
    from bisheng.approval.api.endpoints.approval_admin import _ensure_admin

    with pytest.raises(HTTPException) as exc:
        await _ensure_admin(_ops_user())
    assert exc.value.status_code == 403


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get(
        "PLATFORM_OPERATOR_FLOW_DATABASE_URL"
    )
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
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_ops_sensitive_word_policy_flow_mysql(mysql_engine, monkeypatch):
    """U-ops GET/PUT 敏感词; 落库一致再 GET; U-user 19801 且表不变."""
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.sensitive_word.api.endpoints.policies import router as policy_router

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    suffix = uuid.uuid4().hex[:8]
    ops = _ops_user()
    plain = _plain_user()
    auth: dict = {"user": ops}
    biz = "knowledge_space_file_parse"
    marker = f"ops-sw-{suffix}"

    @asynccontextmanager
    async def patched_async_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.sensitive_word.domain.models.sensitive_word_policy.get_async_db_session",
        patched_async_session,
    )

    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.include_router(policy_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: auth["user"]

    async def _load(session):
        return (
            await session.execute(
                text(
                    "SELECT enabled, auto_reply, custom_words, words_types FROM sensitive_word_policy "
                    "WHERE tenant_id = 1 AND business_type = :b AND logic_delete = 0 "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"b": biz},
            )
        ).first()

    original = None
    created_row = False
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            original = await _load(session)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            put = await client.put(
                f"/api/v1/sensitive-word-policies/{biz}",
                json={
                    "enabled": True,
                    "words_types": ["custom"],
                    "custom_words": marker,
                    "auto_reply": marker,
                    "extra_config": {},
                },
            )
            body_put = put.json()
            assert put.status_code == 200
            assert body_put["status_code"] == 200, body_put
            assert body_put["data"]["auto_reply"] == marker

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row = await _load(session)
            assert row is not None
            assert int(row[0]) == 1
            assert str(row[1]) == marker
            created_row = original is None

            got = await client.get(f"/api/v1/sensitive-word-policies/{biz}")
            body_got = got.json()
            assert got.status_code == 200
            assert body_got["status_code"] == 200, body_got
            assert body_got["data"]["auto_reply"] == marker
            assert body_got["data"]["custom_words"] == marker

            auth["user"] = plain
            denied = await client.put(
                f"/api/v1/sensitive-word-policies/{biz}",
                json={
                    "enabled": False,
                    "words_types": ["custom"],
                    "custom_words": f"{marker}-denied",
                    "auto_reply": f"{marker}-denied",
                    "extra_config": {},
                },
            )
            body_denied = denied.json()
            assert denied.status_code == 200
            assert body_denied["status_code"] == 19801
            async with AsyncSession(engine, expire_on_commit=False) as session:
                after = await _load(session)
            assert after is not None
            assert str(after[1]) == marker
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if created_row:
                await session.execute(
                    text(
                        "DELETE FROM sensitive_word_policy "
                        "WHERE tenant_id = 1 AND business_type = :b AND custom_words = :m"
                    ),
                    {"b": biz, "m": marker},
                )
            elif original is not None:
                await session.execute(
                    text(
                        "UPDATE sensitive_word_policy SET enabled = :e, auto_reply = :a, "
                        "custom_words = :c, words_types = :w "
                        "WHERE tenant_id = 1 AND business_type = :b AND logic_delete = 0"
                    ),
                    {
                        "e": int(original[0]),
                        "a": str(original[1]),
                        "c": str(original[2] or ""),
                        "w": original[3],
                        "b": biz,
                    },
                )
            await session.commit()
