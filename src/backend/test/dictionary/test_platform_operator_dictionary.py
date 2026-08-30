"""AT-29: 运营岗可创建系统字典, 普通用户 19102 且无脏行."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dictionary import DictionaryPermissionDeniedError
from bisheng.dictionary.domain.services.dictionary_service import DictionaryService
from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME


def _ops_user(*, user_id: int = 88003001) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="ops-dict-admin",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
    )


def _plain_user(*, user_id: int = 88003002) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="plain-dict-user",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=["普通用户"],
    )


def test_ensure_admin_allows_operator() -> None:
    DictionaryService._ensure_admin(_ops_user())


def test_ensure_admin_rejects_ordinary() -> None:
    with pytest.raises(DictionaryPermissionDeniedError) as exc:
        DictionaryService._ensure_admin(_plain_user())
    assert exc.value.Code == 19102


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
async def test_ops_create_dictionary_flow_mysql(mysql_engine):
    """U-ops POST /dictoption/create 落 system_dictionary; 再按 type GET; U-user 19102."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.core_deps import get_db_session
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.dictionary.api.endpoints.dictionary_endpoint import router as dict_router

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    suffix = uuid.uuid4().hex[:8]
    ops = _ops_user(user_id=88_003_000 + (int(suffix[:6], 16) % 90_000))
    plain = _plain_user(user_id=ops.user_id + 1)
    auth: dict = {"user": ops}
    dict_type = "expert_major"
    dict_key = f"opsdict{suffix}"
    dict_value = f"ops-dict-flow-{suffix}"

    async def patched_db():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.include_router(dict_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: auth["user"]
    app.dependency_overrides[get_db_session] = patched_db

    async def _count(session, key: str = dict_key) -> int:
        return int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM system_dictionary WHERE dict_key = :k"),
                    {"k": key},
                )
            ).scalar_one()
        )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/v1/dictoption/create",
                json={
                    "type": dict_type,
                    "dict_key": dict_key,
                    "dict_value": dict_value,
                    "sort_order": 0,
                    "is_enabled": True,
                },
            )
            body_created = created.json()
            assert created.status_code == 200
            assert body_created["status_code"] == 200, body_created
            assert body_created["data"]["dict_key"] == dict_key
            row_id = int(body_created["data"]["id"])

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT id, dict_value, is_enabled, tenant_id FROM system_dictionary "
                            "WHERE dict_key = :k ORDER BY id DESC LIMIT 1"
                        ),
                        {"k": dict_key},
                    )
                ).first()
                count1 = await _count(session)
            assert row is not None, body_created
            assert int(row[0]) == row_id
            assert str(row[1]) == dict_value
            assert int(row[2]) == 1
            assert int(row[3] or 0) in {0, 1}
            assert count1 == 1

            listed = await client.get(
                f"/api/v1/dictoption/type/{dict_type}",
                params={"page": 1, "page_size": 500},
            )
            body_listed = listed.json()
            assert listed.status_code == 200
            assert body_listed["status_code"] == 200, body_listed
            keys = {item["dict_key"] for item in body_listed["data"]}
            assert dict_key in keys

            again = await client.get(f"/api/v1/dictoption/query/{row_id}")
            body_again = again.json()
            assert again.status_code == 200
            assert body_again["status_code"] == 200, body_again
            assert body_again["data"]["dict_key"] == dict_key

            auth["user"] = plain
            denied = await client.post(
                "/api/v1/dictoption/create",
                json={
                    "type": dict_type,
                    "dict_key": f"{dict_key}x",
                    "dict_value": dict_value,
                    "sort_order": 0,
                    "is_enabled": True,
                },
            )
            body_denied = denied.json()
            assert denied.status_code == 200
            assert body_denied["status_code"] == 19102
            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert await _count(session) == 1
                extra = await _count(session, f"{dict_key}x")
            assert int(extra) == 0
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM system_dictionary WHERE dict_key IN (:k, :kx)"),
                {"k": dict_key, "kx": f"{dict_key}x"},
            )
            await session.commit()
