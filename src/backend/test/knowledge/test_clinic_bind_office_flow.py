"""科室库绑定下拉与创建拒绝：171 MySQL 接口+落库（无 DDL）。"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.knowledge_space import SpaceCreateDepartmentDeniedError
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.domain.services.clinic_department_bind import CLINIC_BIND_DENIED_MSG
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


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
        user_name="clinic-bind-flow-admin",
        tenant_id=1,
        is_admin=lambda: True,
        is_global_super=True,
        role="admin",
    )


def _collect_ids(nodes: list) -> set[int]:
    ids: set[int] = set()
    for node in nodes:
        ids.add(int(node["id"]))
        ids |= _collect_ids(node.get("children") or [])
    return ids


@pytest.fixture
async def flow_env(monkeypatch):
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping

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

    monkeypatch.setattr("bisheng.core.database.get_async_db_session", patched_session)
    monkeypatch.setattr("bisheng.database.models.department.get_async_db_session", patched_session)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.models.department_knowledge_space.get_async_db_session",
        patched_session,
    )
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_clinic_bind_office_tree_and_reject_non_office_flow_mysql(flow_env, monkeypatch):
    """下拉裁到 office；用部门节点创建科室库被拒绝且 department_knowledge_space 无脏行。"""
    from fastapi.responses import JSONResponse

    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, int] = {}

    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(
            text(
                """
                INSERT INTO department
                  (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                VALUES
                  (:d, :n, NULL, 1, :p, 'active', 'local', 'company', 0)
                """
            ),
            {"d": f"cb-co-{suffix}", "n": f"cb公司-{suffix}", "p": f"/tmp-{suffix}/"},
        )
        await session.commit()
        ids["company"] = int(
            (
                await session.execute(
                    text("SELECT id FROM department WHERE dept_id = :d"),
                    {"d": f"cb-co-{suffix}"},
                )
            ).scalar_one()
        )
        await session.execute(
            text("UPDATE department SET path = :p WHERE id = :id"),
            {"p": f"/{ids['company']}/", "id": ids["company"]},
        )
        await session.execute(
            text(
                """
                INSERT INTO department
                  (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                VALUES
                  (:d, :n, :pid, 1, :p, 'active', 'local', 'dept', 0)
                """
            ),
            {
                "d": f"cb-dept-{suffix}",
                "n": f"cb部门-{suffix}",
                "pid": ids["company"],
                "p": f"/{ids['company']}/tmp/",
            },
        )
        await session.commit()
        ids["dept"] = int(
            (
                await session.execute(
                    text("SELECT id FROM department WHERE dept_id = :d"),
                    {"d": f"cb-dept-{suffix}"},
                )
            ).scalar_one()
        )
        await session.execute(
            text("UPDATE department SET path = :p WHERE id = :id"),
            {"p": f"/{ids['company']}/{ids['dept']}/", "id": ids["dept"]},
        )
        await session.execute(
            text(
                """
                INSERT INTO department
                  (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                VALUES
                  (:do, :no, :poid, 1, :po, 'active', 'local', 'office', 0),
                  (:du, :nu, :puid, 1, :pu, 'active', 'local', NULL, 0)
                """
            ),
            {
                "do": f"cb-off-{suffix}",
                "no": f"cb科室-{suffix}",
                "poid": ids["dept"],
                "po": f"/{ids['company']}/{ids['dept']}/tmp-off/",
                "du": f"cb-unl-{suffix}",
                "nu": f"cb未标-{suffix}",
                "puid": ids["dept"],
                "pu": f"/{ids['company']}/{ids['dept']}/tmp-unl/",
            },
        )
        await session.commit()
        ids["office"] = int(
            (
                await session.execute(
                    text("SELECT id FROM department WHERE dept_id = :d"),
                    {"d": f"cb-off-{suffix}"},
                )
            ).scalar_one()
        )
        ids["unlabeled"] = int(
            (
                await session.execute(
                    text("SELECT id FROM department WHERE dept_id = :d"),
                    {"d": f"cb-unl-{suffix}"},
                )
            ).scalar_one()
        )
        await session.execute(
            text("UPDATE department SET path = :p WHERE id = :id"),
            {"p": f"/{ids['company']}/{ids['dept']}/{ids['office']}/", "id": ids["office"]},
        )
        await session.execute(
            text("UPDATE department SET path = :p WHERE id = :id"),
            {"p": f"/{ids['company']}/{ids['dept']}/{ids['unlabeled']}/", "id": ids["unlabeled"]},
        )
        await session.execute(
            text(
                """
                INSERT INTO department
                  (dept_id, name, parent_id, tenant_id, path, status, source, org_level, is_deleted)
                VALUES
                  (:d, :n, :pid, 1, :p, 'active', 'local', 'squad', 0)
                """
            ),
            {
                "d": f"cb-sq-{suffix}",
                "n": f"cb班组-{suffix}",
                "pid": ids["office"],
                "p": f"/{ids['company']}/{ids['dept']}/{ids['office']}/tmp-sq/",
            },
        )
        await session.commit()
        ids["squad"] = int(
            (
                await session.execute(
                    text("SELECT id FROM department WHERE dept_id = :d"),
                    {"d": f"cb-sq-{suffix}"},
                )
            ).scalar_one()
        )
        await session.execute(
            text("UPDATE department SET path = :p WHERE id = :id"),
            {
                "p": f"/{ids['company']}/{ids['dept']}/{ids['office']}/{ids['squad']}/",
                "id": ids["squad"],
            },
        )
        await session.commit()
        dks_before = int((await session.execute(text("SELECT COUNT(*) FROM department_knowledge_space"))).scalar_one())

    async def _noop_freeze(_tenant_id: int) -> None:
        return None

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service._require_not_write_frozen",
        _noop_freeze,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.LLMService.get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(embedding_model=SimpleNamespace(id="embedding-flow"))),
    )

    admin = _admin_user()
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    @app.get("/api/v1/knowledge/space/create-options/my-department-tree")
    async def tree():
        svc = KnowledgeSpaceService(request=None, login_user=admin)
        return resp_200(await svc.get_my_department_tree_for_create())

    @app.post("/api/v1/knowledge/space")
    async def create():
        svc = KnowledgeSpaceService(request=None, login_user=admin)
        await svc.create_knowledge_space(
            name=f"cb-clinic-{suffix}",
            space_level="department",
            department_id=ids["dept"],
            is_clinic=True,
            auto_tag_library_ids=[1],
        )
        return resp_200({"ok": True})

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/v1/knowledge/space/create-options/my-department-tree")
            assert listed.status_code == 200
            body = listed.json()
            assert body["status_code"] == 200
            tree_ids = _collect_ids(body["data"]["data"])
            assert ids["company"] in tree_ids
            assert ids["dept"] in tree_ids
            assert ids["office"] in tree_ids
            assert ids["squad"] not in tree_ids
            assert ids["unlabeled"] not in tree_ids

            created = await client.post("/api/v1/knowledge/space")
            assert created.status_code == 200
            created_body = created.json()
            assert created_body["status_code"] == SpaceCreateDepartmentDeniedError.Code
            assert CLINIC_BIND_DENIED_MSG in created_body["status_message"]

        async with AsyncSession(engine, expire_on_commit=False) as session:
            dks_after = int(
                (await session.execute(text("SELECT COUNT(*) FROM department_knowledge_space"))).scalar_one()
            )
        assert dks_after == dks_before

        created_again = None
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created_again = await client.post("/api/v1/knowledge/space")
        assert created_again.json()["status_code"] == SpaceCreateDepartmentDeniedError.Code
        async with AsyncSession(engine, expire_on_commit=False) as session:
            dks_again = int(
                (await session.execute(text("SELECT COUNT(*) FROM department_knowledge_space"))).scalar_one()
            )
        assert dks_again == dks_before
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for dept_id in (
                f"cb-sq-{suffix}",
                f"cb-off-{suffix}",
                f"cb-unl-{suffix}",
                f"cb-dept-{suffix}",
                f"cb-co-{suffix}",
            ):
                await session.execute(text("DELETE FROM department WHERE dept_id = :d"), {"d": dept_id})
            await session.commit()
