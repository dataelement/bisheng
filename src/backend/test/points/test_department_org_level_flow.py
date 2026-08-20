"""组织树唯一公司：171 MySQL 接口+落库流转（无 DDL）。"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database.connection import _patch_aiomysql_pre_ping
from bisheng.department.api.endpoints import department_org_level as org_level_ep


def _mysql_async_url() -> str:
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL") or os.environ.get("ORG_LEVEL_FLOW_DATABASE_URL")
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
        raise RuntimeError("流转测试默认打 192.168.106.171，请确认 config.yaml")
    return url.replace("pymysql", "aiomysql")


def _admin_user():
    return SimpleNamespace(
        user_id=1,
        user_name="org-level-flow-admin",
        tenant_id=1,
        is_admin=lambda: True,
        is_global_super=True,
        role="admin",
    )


@pytest.fixture
async def flow_env(monkeypatch):
    """真实 MySQL session 注入到 org_level 服务与 DepartmentDao。"""
    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(
        "bisheng.points.domain.services.department_org_level_service.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.database.models.department.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", patched_session)

    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_set_company_root_unique_flow_mysql(flow_env):
    """AC1/AC2/AC5：唯一公司拒绝与 clear 后再设；临时清空租户标签以免存量干扰。"""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    dept_a = f"flow-co-a-{suffix}"
    dept_b = f"flow-co-b-{suffix}"
    path_a = f"/flow-{suffix}-a/"
    path_b = f"/flow-{suffix}-b/"
    snapshot: list[tuple[int, str | None]] = []

    async with AsyncSession(engine, expire_on_commit=False) as session:
        # 快照租户内已有标签，测试期间清空，结束恢复（避免 171 存量公司挡住 AC1）。
        rows = (
            await session.execute(
                text(
                    "SELECT id, org_level FROM department "
                    "WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
                )
            )
        ).all()
        snapshot = [(int(r[0]), r[1]) for r in rows]
        if snapshot:
            await session.execute(
                text(
                    "UPDATE department SET org_level = NULL "
                    "WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
                )
            )
        await session.execute(
            text(
                """
                INSERT INTO department
                  (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                VALUES
                  (:da, :na, NULL, 1, :pa, 'active', 'local', NULL, 0),
                  (:db, :nb, NULL, 1, :pb, 'active', 'local', NULL, 0)
                """
            ),
            {
                "da": dept_a,
                "na": f"flow-co-A-{suffix}",
                "pa": path_a,
                "db": dept_b,
                "nb": f"flow-co-B-{suffix}",
                "pb": path_b,
            },
        )
        await session.commit()
        id_a = (await session.execute(text("SELECT id FROM department WHERE dept_id = :d"), {"d": dept_a})).scalar_one()
        id_b = (await session.execute(text("SELECT id FROM department WHERE dept_id = :d"), {"d": dept_b})).scalar_one()

    app = FastAPI()
    app.include_router(org_level_ep.router, prefix="/api/v1/departments")
    app.dependency_overrides[UserPayload.get_login_user] = _admin_user

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post(f"/api/v1/departments/{dept_a}/set-company-root", json={})
            assert r1.status_code == 200
            body1 = r1.json()
            assert body1["status_code"] == 200
            assert body1["data"]["company_id"] == id_a

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row_a = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_a},
                    )
                ).scalar_one()
                row_b = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_b},
                    )
                ).scalar_one()
            assert row_a == "company"
            assert row_b is None

            r2 = await client.post(f"/api/v1/departments/{dept_b}/set-company-root", json={})
            assert r2.status_code == 200
            assert r2.json()["status_code"] == 18208

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row_a2 = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_a},
                    )
                ).scalar_one()
                row_b2 = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_b},
                    )
                ).scalar_one()
            assert row_a2 == "company"
            assert row_b2 is None

            r3 = await client.post(f"/api/v1/departments/{dept_a}/clear-company-root")
            assert r3.status_code == 200
            assert r3.json()["status_code"] == 200

            r4 = await client.post(f"/api/v1/departments/{dept_b}/set-company-root", json={})
            assert r4.status_code == 200
            body4 = r4.json()
            assert body4["status_code"] == 200
            assert body4["data"]["company_id"] == id_b

            async with AsyncSession(engine, expire_on_commit=False) as session:
                row_a3 = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_a},
                    )
                ).scalar_one()
                row_b3 = (
                    await session.execute(
                        text("SELECT org_level FROM department WHERE dept_id = :d"),
                        {"d": dept_b},
                    )
                ).scalar_one()
            assert row_a3 is None
            assert row_b3 == "company"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM department WHERE dept_id = :a"),
                {"a": dept_a},
            )
            await session.execute(
                text("DELETE FROM department WHERE dept_id = :b"),
                {"b": dept_b},
            )
            # 清掉测试残留标签后恢复快照
            await session.execute(
                text(
                    "UPDATE department SET org_level = NULL "
                    "WHERE tenant_id = 1 AND status = 'active' AND org_level IS NOT NULL"
                )
            )
            for dept_pk, level in snapshot:
                await session.execute(
                    text("UPDATE department SET org_level = :lv WHERE id = :id"),
                    {"lv": level, "id": dept_pk},
                )
            await session.commit()
