"""AT-01/02/04/90: 保留名「平台管理员」租户内唯一、禁改名删除、剥离管理端菜单."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.role import RoleBuiltinProtectedError, RoleNameDuplicateError
from bisheng.role.domain.schemas.role_schema import RoleCreateRequest, RoleUpdateRequest
from bisheng.role.domain.services.role_service import RoleService
from bisheng.user.domain.services.platform_operator import (
    PLATFORM_OPERATOR_ROLE_NAME,
    strip_platform_operator_admin_menus,
)


def _admin_user():
    user = MagicMock()
    user.user_id = 1
    user.tenant_id = 1
    user.is_admin.return_value = True
    return user


def _make_role(role_id, role_name=PLATFORM_OPERATOR_ROLE_NAME, role_type="global", department_id=None):
    role = MagicMock()
    role.id = role_id
    role.role_name = role_name
    role.role_type = role_type
    role.department_id = department_id
    role.tenant_id = 1
    role.remark = None
    return role


def test_strip_admin_menus_drops_board_and_sys_for_operator() -> None:
    kept = strip_platform_operator_admin_menus(
        PLATFORM_OPERATOR_ROLE_NAME,
        ["board", "sys", "workstation", "board", "frontend"],
    )
    assert "board" not in kept
    assert "sys" not in kept
    assert "workstation" in kept
    assert "frontend" in kept


def test_strip_admin_menus_keeps_board_for_other_roles() -> None:
    kept = strip_platform_operator_admin_menus("普通用户", ["board", "workstation"])
    assert "board" in kept
    assert "workstation" in kept


def test_normalize_menu_ids_strips_operator_admin_keys() -> None:
    out = RoleService._normalize_menu_ids(
        ["board", "sys", "workstation", "system_config"],
        role_name=PLATFORM_OPERATOR_ROLE_NAME,
    )
    assert "board" not in out
    assert "sys" not in out
    assert "system_config" not in out
    assert "workstation" in out


@pytest.mark.asyncio
async def test_create_reserved_name_unique_across_department() -> None:
    """同租户任意 department 再创建保留名 → 24002."""
    admin = _admin_user()
    first = RoleCreateRequest(role_name=PLATFORM_OPERATOR_ROLE_NAME)
    second = RoleCreateRequest(role_name=PLATFORM_OPERATOR_ROLE_NAME, department_id=99)
    created = _make_role(41)

    with (
        patch.object(RoleService, "_check_role_permission", new=AsyncMock()),
        patch.object(RoleService, "_ensure_create_scope", new=AsyncMock()),
        patch.object(RoleService, "_validate_department", new=AsyncMock()),
        patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
        patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
        patch("bisheng.role.domain.services.role_service.QuotaService"),
    ):
        mock_role_cls.return_value = created
        mock_dao.aget_role_by_name = AsyncMock(return_value=None)
        mock_dao.ainsert_role = AsyncMock(return_value=created)
        mock_dao.aget_role_by_exact_name_in_tenant = AsyncMock(side_effect=[None, created])

        result = await RoleService.create_role(first, admin)
        assert result.id == 41

        with pytest.raises(RoleNameDuplicateError) as exc:
            await RoleService.create_role(second, admin)
        assert exc.value.Code == 24002


@pytest.mark.asyncio
async def test_create_operator_can_coexist_with_portal_admin_name() -> None:
    admin = _admin_user()
    req = RoleCreateRequest(role_name=PLATFORM_OPERATOR_ROLE_NAME)
    created = _make_role(42)

    with (
        patch.object(RoleService, "_check_role_permission", new=AsyncMock()),
        patch.object(RoleService, "_ensure_create_scope", new=AsyncMock()),
        patch("bisheng.role.domain.services.role_service.Role") as mock_role_cls,
        patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
        patch("bisheng.role.domain.services.role_service.QuotaService"),
    ):
        mock_role_cls.return_value = created
        mock_dao.aget_role_by_name = AsyncMock(return_value=None)
        mock_dao.ainsert_role = AsyncMock(return_value=created)
        mock_dao.aget_role_by_exact_name_in_tenant = AsyncMock(return_value=None)

        result = await RoleService.create_role(req, admin)

    assert result.role_name == PLATFORM_OPERATOR_ROLE_NAME
    mock_dao.aget_role_by_name.assert_called()


@pytest.mark.asyncio
async def test_update_reserved_name_is_protected() -> None:
    admin = _admin_user()
    role = _make_role(50)
    req = RoleUpdateRequest(role_name="运营改名")

    with (
        patch.object(RoleService, "_check_role_permission", new=AsyncMock()),
        patch.object(RoleService, "_ensure_role_mutation_access", new=AsyncMock()),
        patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
        patch("bisheng.role.domain.services.role_service.QuotaService"),
    ):
        mock_dao.aget_role_by_id = AsyncMock(return_value=role)
        with pytest.raises(RoleBuiltinProtectedError) as exc:
            await RoleService.update_role(50, req, admin)
        assert exc.value.Code == 24004
        mock_dao.update_role.assert_not_called()


@pytest.mark.asyncio
async def test_delete_reserved_name_is_protected() -> None:
    admin = _admin_user()
    role = _make_role(50)

    with (
        patch.object(RoleService, "_check_role_permission", new=AsyncMock()),
        patch.object(RoleService, "_ensure_role_mutation_access", new=AsyncMock()),
        patch("bisheng.role.domain.services.role_service.RoleDao") as mock_dao,
    ):
        mock_dao.aget_role_by_id = AsyncMock(return_value=role)
        with pytest.raises(RoleBuiltinProtectedError) as exc:
            await RoleService.delete_role(50, admin)
        assert exc.value.Code == 24004
        mock_dao.adelete_role.assert_not_called()


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get("PLATFORM_OPERATOR_FLOW_DATABASE_URL")
    if override:
        return override.replace("pymysql", "aiomysql")
    from bisheng.core.config.settings import decrypt_token

    cfg_name = os.environ.get("config", "config.yaml")
    cfg_path = Path(__file__).resolve().parents[2] / "bisheng" / Path(cfg_name).name
    loaded = __import__("yaml").safe_load(cfg_path.read_text(encoding="utf-8"))
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
async def test_reserved_name_flow_mysql(mysql_engine, monkeypatch):
    """171: 创建保留名落库, 跨 scope 24002, 改名/删除 24004, WEB_MENU 无 board/sys."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from httpx import ASGITransport, AsyncClient

    from bisheng.common.errcode.base import BaseErrorCode
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.role.api.endpoints.role import router as role_router
    from bisheng.role.api.endpoints.role_access import router as menu_router
    from bisheng.user.domain.services.auth import LoginUser

    _patch_aiomysql_pre_ping()
    engine = mysql_engine
    suffix = uuid.uuid4().hex[:8]
    remark = f"ops-role-flow-{suffix}"
    created_ids: list[int] = []

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    async def sql_insert(role):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text(
                    "INSERT INTO role (role_name, role_type, department_id, remark, create_user, tenant_id) "
                    "VALUES (:n, :t, :d, :r, :u, :tid)"
                ),
                {
                    "n": role.role_name,
                    "t": getattr(role, "role_type", "global"),
                    "d": getattr(role, "department_id", None),
                    "r": getattr(role, "remark", None),
                    "u": getattr(role, "create_user", 1),
                    "tid": getattr(role, "tenant_id", 1),
                },
            )
            await session.commit()
            role_id = (await session.execute(text("SELECT LAST_INSERT_ID()"))).scalar_one()
        ns = SimpleNamespace(
            id=int(role_id),
            role_name=role.role_name,
            role_type=getattr(role, "role_type", "global"),
            department_id=getattr(role, "department_id", None),
            quota_config=getattr(role, "quota_config", None),
            remark=getattr(role, "remark", None),
            create_user=getattr(role, "create_user", 1),
            tenant_id=getattr(role, "tenant_id", 1),
            create_time=None,
            update_time=None,
        )
        created_ids.append(ns.id)
        return ns

    async def sql_get_by_id(role_id: int):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = (
                await session.execute(
                    text("SELECT id, role_name, role_type, department_id, remark, tenant_id FROM role WHERE id = :id"),
                    {"id": role_id},
                )
            ).first()
        if not row:
            return None
        return SimpleNamespace(
            id=int(row[0]),
            role_name=row[1],
            role_type=row[2],
            department_id=row[3],
            remark=row[4],
            tenant_id=row[5],
            quota_config=None,
        )

    async def sql_get_by_name(tenant_id, role_type, role_name, department_id):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if department_id is None:
                row = (
                    await session.execute(
                        text(
                            "SELECT id, role_name FROM role "
                            "WHERE tenant_id = :t AND role_type = :rt AND role_name = :n "
                            "AND department_id IS NULL LIMIT 1"
                        ),
                        {"t": tenant_id, "rt": role_type, "n": role_name},
                    )
                ).first()
            else:
                row = (
                    await session.execute(
                        text(
                            "SELECT id, role_name FROM role "
                            "WHERE tenant_id = :t AND role_type = :rt AND role_name = :n "
                            "AND department_id = :d LIMIT 1"
                        ),
                        {"t": tenant_id, "rt": role_type, "n": role_name, "d": department_id},
                    )
                ).first()
        if not row:
            return None
        return SimpleNamespace(id=int(row[0]), role_name=row[1])

    async def sql_get_exact_in_tenant(tenant_id, role_name, exclude_id=None):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT id, role_name, department_id FROM role WHERE tenant_id = :t AND role_name = :n LIMIT 1"
                    ),
                    {"t": tenant_id, "n": role_name},
                )
            ).first()
        if not row:
            return None
        if exclude_id is not None and int(row[0]) == int(exclude_id):
            return None
        return SimpleNamespace(id=int(row[0]), role_name=row[1], department_id=row[2])

    async def sql_replace_menus(_session, role_id: int, menu_ids: list[str]) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM roleaccess WHERE role_id = :rid AND type = 99"),
                {"rid": role_id},
            )
            for menu_id in menu_ids:
                await session.execute(
                    text("INSERT INTO roleaccess (role_id, third_id, type, tenant_id) VALUES (:rid, :tid, 99, 1)"),
                    {"rid": role_id, "tid": menu_id},
                )
            await session.commit()

    def role_factory(**kwargs):
        return SimpleNamespace(id=None, **kwargs)

    dao = MagicMock()
    dao.aget_role_by_name = sql_get_by_name
    dao.ainsert_role = sql_insert
    dao.aget_role_by_id = sql_get_by_id
    dao.aget_role_by_exact_name_in_tenant = sql_get_exact_in_tenant
    dao.update_role = AsyncMock(side_effect=lambda role: role)
    dao.adelete_role = AsyncMock()

    monkeypatch.setattr("bisheng.role.domain.services.role_service.RoleDao", dao)
    monkeypatch.setattr("bisheng.role.domain.services.role_service.Role", role_factory)
    monkeypatch.setattr(
        "bisheng.role.domain.services.role_service.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        RoleService,
        "_replace_menu_access_in_session",
        sql_replace_menus,
    )
    async def update_menu_sql(cls, role_id, menu_ids, login_user):
        # premock 下 Role 不能进 select(); 菜单剥离仍走 _normalize_menu_ids, 落库走 SQL.
        role = await sql_get_by_id(role_id)
        if not role:
            from bisheng.common.errcode.role import RoleNotFoundError

            raise RoleNotFoundError()
        normalized = cls._normalize_menu_ids(menu_ids, role_name=role.role_name)
        await sql_replace_menus(None, role_id, normalized)

    async def get_menu_sql(cls, role_id, login_user):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            rows = (
                await session.execute(
                    text("SELECT third_id FROM roleaccess WHERE role_id = :id AND type = 99"),
                    {"id": role_id},
                )
            ).all()
        return [row[0] for row in rows]

    monkeypatch.setattr(RoleService, "update_menu", classmethod(update_menu_sql))
    monkeypatch.setattr(RoleService, "get_menu", classmethod(get_menu_sql))
    monkeypatch.setattr(RoleService, "_validate_department", AsyncMock())
    monkeypatch.setattr(
        "bisheng.role.api.endpoints.role._audit_log_service",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "bisheng.permission.domain.services.legacy_rbac_sync_service.LegacyRBACSyncService.sync_role_deleted",
        AsyncMock(),
    )

    admin = SimpleNamespace(
        user_id=1,
        user_name="ops-role-flow-admin",
        tenant_id=1,
        is_admin=lambda: True,
        is_global_super=True,
    )

    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.include_router(role_router, prefix="/api/v1")
    app.include_router(menu_router, prefix="/api/v1")
    app.dependency_overrides[LoginUser.get_login_user] = lambda: admin

    dept_id = None
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(
            text(
                "DELETE FROM roleaccess WHERE role_id IN "
                "(SELECT id FROM role WHERE remark LIKE 'ops-role-flow-%')"
            )
        )
        await session.execute(text("DELETE FROM role WHERE remark LIKE 'ops-role-flow-%'"))
        await session.commit()
        dept_id = (
            await session.execute(
                text("SELECT id FROM department WHERE tenant_id = 1 AND status = 'active' LIMIT 1")
            )
        ).scalar()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(
                "/api/v1/roles",
                json={"role_name": PLATFORM_OPERATOR_ROLE_NAME, "remark": remark},
            )
            body1 = r1.json()
            assert r1.status_code == 200
            assert body1["status_code"] == 200, body1
            assert body1["data"]["role_name"] == PLATFORM_OPERATOR_ROLE_NAME
            role_id = int(body1["data"]["id"])

            async with AsyncSession(engine, expire_on_commit=False) as session:
                count1 = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM role WHERE tenant_id = 1 AND role_name = :n"),
                        {"n": PLATFORM_OPERATOR_ROLE_NAME},
                    )
                ).scalar_one()
            assert int(count1) == 1

            dup_payload = {"role_name": PLATFORM_OPERATOR_ROLE_NAME, "remark": f"{remark}-dup"}
            if dept_id is not None:
                dup_payload["department_id"] = int(dept_id)
            r2 = await client.post("/api/v1/roles", json=dup_payload)
            body2 = r2.json()
            assert r2.status_code == 200
            assert body2["status_code"] == 24002

            async with AsyncSession(engine, expire_on_commit=False) as session:
                count2 = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM role WHERE tenant_id = 1 AND role_name = :n"),
                        {"n": PLATFORM_OPERATOR_ROLE_NAME},
                    )
                ).scalar_one()
            assert int(count2) == 1

            r3 = await client.put(
                f"/api/v1/roles/{role_id}",
                json={"role_name": "不该改名"},
            )
            body3 = r3.json()
            assert r3.status_code == 200
            assert body3["status_code"] == 24004

            r4 = await client.delete(f"/api/v1/roles/{role_id}")
            body4 = r4.json()
            assert r4.status_code == 200
            assert body4["status_code"] == 24004

            async with AsyncSession(engine, expire_on_commit=False) as session:
                still = (
                    await session.execute(
                        text("SELECT role_name FROM role WHERE id = :id"),
                        {"id": role_id},
                    )
                ).scalar_one()
            assert still == PLATFORM_OPERATOR_ROLE_NAME

            r5 = await client.post(
                f"/api/v1/roles/{role_id}/menu",
                json={"menu_ids": ["board", "sys", "workstation"]},
            )
            assert r5.status_code == 200
            assert r5.json()["status_code"] == 200

            async with AsyncSession(engine, expire_on_commit=False) as session:
                menus = [
                    row[0]
                    for row in (
                        await session.execute(
                            text("SELECT third_id FROM roleaccess WHERE role_id = :id AND type = 99"),
                            {"id": role_id},
                        )
                    ).all()
                ]
            assert "board" not in menus
            assert "sys" not in menus
            assert "workstation" in menus

            r6 = await client.get(f"/api/v1/roles/{role_id}/menu")
            assert r6.status_code == 200
            assert "board" not in (r6.json().get("data") or [])
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            ids = list({*created_ids})
            if ids:
                id_list = ",".join(str(i) for i in ids)
                await session.execute(text(f"DELETE FROM roleaccess WHERE role_id IN ({id_list})"))
            await session.execute(
                text(
                    "DELETE FROM roleaccess WHERE role_id IN "
                    "(SELECT id FROM role WHERE remark LIKE 'ops-role-flow-%')"
                )
            )
            await session.execute(text("DELETE FROM role WHERE remark LIKE 'ops-role-flow-%'"))
            await session.commit()
