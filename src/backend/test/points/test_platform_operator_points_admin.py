"""AT-21/48/80: 运营岗可积分调账, 不是超管, 解绑失效, 不能专家问答违规删."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.points import PointsPermissionDeniedError
from bisheng.points.domain.services.points_auth import is_platform_super_admin, require_platform_admin
from bisheng.qa_expert.domain.moderate_delete_service import ModerateDeleteService
from bisheng.user.domain.services.platform_operator import PLATFORM_OPERATOR_ROLE_NAME


def _ops_user(*, user_id: int = 88001001) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="ops-points-admin",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=[PLATFORM_OPERATOR_ROLE_NAME],
    )


def _plain_user(*, user_id: int = 88001002) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=user_id,
        user_name="plain-points-user",
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role_names=["普通用户"],
    )


def test_is_platform_super_admin_rejects_operator() -> None:
    ops = _ops_user()
    assert is_platform_super_admin(ops) is False
    assert ops.is_admin() is False


def test_require_platform_admin_allows_operator() -> None:
    require_platform_admin(_ops_user())


def test_require_platform_admin_still_rejects_ordinary() -> None:
    with pytest.raises(PointsPermissionDeniedError) as exc:
        require_platform_admin(_plain_user())
    assert exc.value.Code == 18201


@pytest.mark.asyncio
async def test_moderate_delete_rejects_operator() -> None:
    """AT-48: 扩积分闸门后, 专家问答违规删仍只认超管."""
    svc = ModerateDeleteService()
    svc.question_repo = AsyncMock()
    with pytest.raises(PointsPermissionDeniedError) as exc:
        await svc.moderate_delete(operator=_ops_user(), target_type="question", target_id=1)
    assert exc.value.Code == 18201
    svc.question_repo.get_by_id.assert_not_called()


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get("PLATFORM_OPERATOR_FLOW_DATABASE_URL")
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
async def test_ops_adjust_flow_mysql(mysql_engine, monkeypatch):
    """U-ops 调账落库; U-user 18201 无脏行; 清空 role_names 后再调 18201."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.dependencies.core_deps import get_db_session
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.points.api.endpoints.admin import router as points_admin_router

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    suffix = uuid.uuid4().hex[:8]
    target_uid = 88_001_000 + (int(suffix[:6], 16) % 90_000)
    remark = f"ops-pts-flow-{suffix}-adjust"
    delta = 7
    auth: dict = {"user": _ops_user(user_id=target_uid + 1)}

    async def patched_db():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_notify_service.PointsNotifyService.notify",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_query_service.PointsQueryService._leaderboard_display_maps",
        AsyncMock(return_value=({target_uid: "target"}, {})),
    )

    async def _fake_user_types(_ids):
        return {int(i): "普通用户" for i in _ids}

    monkeypatch.setattr(
        "bisheng.points.domain.constants.admin_user_type.resolve_user_types_for_admin_list",
        _fake_user_types,
    )

    app = FastAPI()
    app.include_router(points_admin_router, prefix="/api/v1/points")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: auth["user"]
    app.dependency_overrides[get_db_session] = patched_db

    async def _log_count(session) -> int:
        return int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM user_point_log WHERE tenant_id = 1 AND user_id = :uid AND remark = :r"),
                    {"uid": target_uid, "r": remark},
                )
            ).scalar_one()
        )

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/api/v1/points/admin/adjust",
                json={"user_id": target_uid, "delta": delta, "remark": remark},
            )
            body1 = r1.json()
            assert r1.status_code == 200
            assert body1["status_code"] == 200, body1
            assert body1["data"]["delta"] == delta

            async with AsyncSession(engine, expire_on_commit=False) as session:
                log_row = (
                    await session.execute(
                        text(
                            "SELECT delta, balance_after, operator_id FROM user_point_log "
                            "WHERE tenant_id = 1 AND user_id = :uid AND remark = :r "
                            "ORDER BY id DESC LIMIT 1"
                        ),
                        {"uid": target_uid, "r": remark},
                    )
                ).first()
                bal = (
                    await session.execute(
                        text("SELECT balance FROM user_point_account WHERE tenant_id = 1 AND user_id = :uid"),
                        {"uid": target_uid},
                    )
                ).scalar_one()
                count1 = await _log_count(session)
            assert log_row is not None
            assert int(log_row[0]) == delta
            assert int(log_row[1]) == int(bal)
            assert int(log_row[2]) == auth["user"].user_id
            assert count1 == 1

            r2 = await client.get(f"/api/v1/points/admin/users/{target_uid}/detail")
            body2 = r2.json()
            assert r2.status_code == 200
            assert body2["status_code"] == 200, body2
            assert int(body2["data"]["balance"]) == int(bal)

            auth["user"] = _plain_user(user_id=target_uid + 2)
            r3 = await client.post(
                "/api/v1/points/admin/adjust",
                json={"user_id": target_uid, "delta": delta, "remark": remark},
            )
            body3 = r3.json()
            assert r3.status_code == 200
            assert body3["status_code"] == 18201
            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert await _log_count(session) == count1

            unbound = _ops_user(user_id=target_uid + 1)
            unbound.role_names = []
            auth["user"] = unbound
            r4 = await client.post(
                "/api/v1/points/admin/adjust",
                json={"user_id": target_uid, "delta": delta, "remark": remark},
            )
            body4 = r4.json()
            assert r4.status_code == 200
            assert body4["status_code"] == 18201
            async with AsyncSession(engine, expire_on_commit=False) as session:
                assert await _log_count(session) == count1
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text(
                    "DELETE FROM point_sync_outbox WHERE log_id IN "
                    "(SELECT id FROM user_point_log WHERE tenant_id = 1 AND user_id = :uid)"
                ),
                {"uid": target_uid},
            )
            await session.execute(
                text("DELETE FROM user_point_log WHERE tenant_id = 1 AND user_id = :uid"),
                {"uid": target_uid},
            )
            await session.execute(
                text("DELETE FROM user_point_account WHERE tenant_id = 1 AND user_id = :uid"),
                {"uid": target_uid},
            )
            await session.commit()
