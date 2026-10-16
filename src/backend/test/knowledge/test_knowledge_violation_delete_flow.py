"""知识文档违规删除: 171 MySQL 接口, 回收与扣分落库, 再打一枪."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.api.endpoints.knowledge_violation_delete import router as violation_router
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.points.domain.services.points_pending_deduct_service import PointsPendingDeductService

PREFIX = "/api/v1/knowledge/space/files"


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
        raise RuntimeError("流转测试默认打 192.168.106.171, 请确认 config.yaml")
    return url.replace("pymysql", "aiomysql")


def _user(user_id: int, *, name: str):
    return SimpleNamespace(
        user_id=user_id,
        user_name=name,
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role="user",
    )


@pytest.fixture
async def flow_env(monkeypatch):
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    register_tenant_filter_events()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for target in (
        "bisheng.knowledge.domain.services.knowledge_violation_delete_service.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_space_scope.get_async_db_session",
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
    ):
        monkeypatch.setattr(target, patched_session)

    roles: dict[int, tuple[set[int], set[int]]] = {}

    async def _roles(space_id: int):
        return roles.get(int(space_id), (set(), set()))

    async def _no_notify(self, **_kwargs):
        return None

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_violation_delete_service.read_space_owner_manager_ids",
        _roles,
    )
    monkeypatch.setattr(PointsPendingDeductService, "_notify_admin_deduct", _no_notify)
    yield engine, roles
    await engine.dispose()


def _app(user) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    async def _login():
        return user

    app.dependency_overrides[UserPayload.get_login_user] = _login
    app.include_router(violation_router, prefix="/api/v1")
    return app


async def _select(engine, sql: str, params: dict) -> list[dict]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        rows = (await session.execute(text(sql), params)).mappings().all()
        return [dict(row) for row in rows]


async def _insert_user(session: AsyncSession, name: str) -> int:
    await session.execute(
        text("INSERT INTO user (user_name, password, `delete`) VALUES (:n, 'x', 0)"),
        {"n": name},
    )
    await session.commit()
    return int((await session.execute(text("SELECT user_id FROM user WHERE user_name = :n"), {"n": name})).scalar_one())


async def _insert_space(session: AsyncSession, *, name: str, level: str) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledge (user_id, name, type, tenant_id, is_released, is_favorite, auth_type)
            VALUES (1, :name, :type, 1, 0, 0, 'PRIVATE')
            """
        ),
        {"name": name, "type": KnowledgeTypeEnum.SPACE.value},
    )
    await session.commit()
    space_id = int((await session.execute(text("SELECT id FROM knowledge WHERE name = :n"), {"n": name})).scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO knowledge_space_scope
              (tenant_id, space_id, level, owner_type, owner_id, created_by)
            VALUES (1, :sid, :level, 'department', 1, 1)
            """
        ),
        {"sid": space_id, "level": level},
    )
    await session.commit()
    return space_id


async def _ensure_r4(session: AsyncSession, expr: dict) -> dict | None:
    row = (
        (
            await session.execute(
                text("SELECT id, score_expr, status FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R4'")
            )
        )
        .mappings()
        .first()
    )
    payload = json.dumps(expr)
    if row is None:
        await session.execute(
            text(
                """
                INSERT INTO point_rule
                  (tenant_id, rule_code, rule_type, name, display_name, score_expr, status, sort_order)
                VALUES
                  (1, 'R4', 'deduct', '知识文档色情低俗/暴力违法', '知识文档色情低俗/暴力违法',
                   CAST(:expr AS JSON), 'enabled', 24)
                """
            ),
            {"expr": payload},
        )
        await session.commit()
        return None
    previous = {"id": int(row["id"]), "score_expr": row["score_expr"], "status": row["status"]}
    await session.execute(
        text("UPDATE point_rule SET score_expr = CAST(:expr AS JSON), status = 'enabled' WHERE id = :id"),
        {"expr": payload, "id": previous["id"]},
    )
    await session.commit()
    return previous


async def test_violation_delete_removes_personal_original_and_deducts_public_score(flow_env):
    """公共库副本加个人库原件: 两处都标成删除中且不进回收站, 按公共库 3 分扣一次."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-up-{token}")
        operator = await _insert_user(session, f"vd-op-{token}")
        stranger = await _insert_user(session, f"vd-st-{token}")
        personal_id = await _insert_space(session, name=f"vd-personal-{token}", level="personal")
        public_id = await _insert_space(session, name=f"vd-public-{token}", level="public")
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document
                  (tenant_id, knowledge_id, content_generation, lifecycle_status)
                VALUES (1, :kid, 1, 'active')
                """
            ),
            {"kid": personal_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": personal_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES
                  (:uid, :uid, :personal, :manager_name, 1, 1, 'vd-manager', :doc, 'manager', 'active', 2)
                """
            ),
            {
                "uid": uploader,
                "personal": personal_id,
                "manager_name": f"vd-manager-{token}.pdf",
                "doc": document_id,
            },
        )
        await session.commit()
        manager_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-manager-{token}.pdf"},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES
                  (:uid, :uid, :public, :publish_name, 1, 1, 'vd-publish', :doc, 'publish', 'active', 2)
                """
            ),
            {
                "uid": uploader,
                "public": public_id,
                "publish_name": f"vd-publish-{token}.pdf",
                "doc": document_id,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document_version
                  (document_id, knowledge_file_id, version_no, is_primary)
                VALUES (:doc, :file, 1, 1)
                """
            ),
            {"doc": document_id, "file": manager_id},
        )
        await session.execute(
            text("UPDATE knowledge_document SET primary_version_id = :vid WHERE id = :doc"),
            {
                "doc": document_id,
                "vid": int(
                    (
                        await session.execute(
                            text(
                                "SELECT id FROM knowledge_document_version WHERE document_id = :doc AND version_no = 1"
                            ),
                            {"doc": document_id},
                        )
                    ).scalar_one()
                ),
            },
        )
        await session.commit()
        publish_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-publish-{token}.pdf"},
                )
            ).scalar_one()
        )
        previous_rule = await _ensure_r4(session, {"mode": "library_scope", "public": 3, "department": 2, "team": 1})
        roles[public_id] = ({operator}, set())
        roles[personal_id] = ({uploader}, set())
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, knowledge_id, file_name, file_type, tenant_id, object_name,
                   file_source, status)
                VALUES (:uid, :personal, :name, 1, 1, 'vd-fav', 'favorite_reference', 2)
                """
            ),
            {"uid": uploader, "personal": personal_id, "name": f"vd-fav-{token}.pdf"},
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledge_recycle_item
                  (tenant_id, file_id, knowledge_id, file_type, is_list_entry, display_name,
                   original_knowledge_id, original_path, deleted_by, deleted_at, expire_at,
                   recycle_batch_id, recycle_root_id, document_id)
                VALUES
                  (1, :file, :kid, 1, 1, 'vd-old', :kid, '/', :uid, NOW(), NOW(), :batch, :file, :doc)
                """
            ),
            {
                "file": manager_id,
                "kid": personal_id,
                "uid": uploader,
                "batch": f"vd-old-{token}",
                "doc": document_id,
            },
        )
        await session.commit()
        favorite_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-fav-{token}.pdf"},
                )
            ).scalar_one()
        )
        file_ids = [manager_id, publish_id, favorite_id]
    try:
        stranger_app = _app(_user(stranger, name=f"vd-st-{token}"))
        async with AsyncClient(transport=ASGITransport(app=stranger_app), base_url="http://test") as client:
            denied = await client.post(f"{PREFIX}/{publish_id}/violation-delete", json={"rule_code": "R4"})
        assert denied.status_code == 200
        assert denied.json()["status_code"] == 18052
        untouched = await _select(
            engine,
            "SELECT deleted_at FROM knowledgefile WHERE id = :id",
            {"id": publish_id},
        )
        assert untouched[0]["deleted_at"] is None

        personal_app = _app(_user(uploader, name=f"vd-up-{token}"))
        async with AsyncClient(transport=ASGITransport(app=personal_app), base_url="http://test") as client:
            personal_denied = await client.post(
                f"{PREFIX}/{manager_id}/violation-delete",
                json={"rule_code": "R4"},
            )
        assert personal_denied.json()["status_code"] == 18052

        operator_app = _app(_user(operator, name=f"vd-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=operator_app), base_url="http://test") as client:
            first = await client.post(f"{PREFIX}/{publish_id}/violation-delete", json={"rule_code": "R4"})
            body = first.json()
            assert body["status_code"] == 200, body
            assert body["data"]["deleted"] is True
            assert body["data"]["deducted"] is True
            assert body["data"]["score"] == 3
            assert body["data"]["scope_tier"] == "public"
            second = await client.post(f"{PREFIX}/{publish_id}/violation-delete", json={"rule_code": "R4"})
            assert second.json()["status_code"] == 200, second.json()

        files = await _select(
            engine,
            "SELECT id, deleted_at FROM knowledgefile WHERE id IN (:manager, :publish)",
            {"manager": manager_id, "publish": publish_id},
        )
        assert {row["id"] for row in files if row["deleted_at"] is not None} == {manager_id, publish_id}
        document = await _select(
            engine,
            "SELECT lifecycle_status FROM knowledge_document WHERE id = :id",
            {"id": document_id},
        )
        assert document[0]["lifecycle_status"] == "deleting"
        recycle = await _select(
            engine,
            "SELECT id FROM knowledge_recycle_item WHERE document_id = :id",
            {"id": document_id},
        )
        assert recycle == []
        statuses = await _select(
            engine,
            "SELECT entry_status FROM knowledgefile WHERE id IN (:manager, :publish)",
            {"manager": manager_id, "publish": publish_id},
        )
        assert {row["entry_status"] for row in statuses} == {"deleting"}
        favorite = await _select(
            engine,
            "SELECT deleted_at, reference_document_id FROM knowledgefile WHERE id = :id",
            {"id": favorite_id},
        )
        assert favorite[0]["deleted_at"] is None
        assert favorite[0]["reference_document_id"] is None
        logs = await _select(
            engine,
            """
            SELECT delta, rule_code, biz_type, biz_id
            FROM user_point_log
            WHERE user_id = :uid AND biz_type = 'knowledge_document' AND biz_id = :bid
            """,
            {"uid": uploader, "bid": str(document_id)},
        )
        assert len(logs) == 1
        assert logs[0]["delta"] == -3
        assert logs[0]["rule_code"] == "R4"
        account = await _select(
            engine,
            "SELECT balance FROM user_point_account WHERE user_id = :uid AND tenant_id = 1",
            {"uid": uploader},
        )
        assert account[0]["balance"] == -3
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"),
                {"id": document_id},
            )
            await session.execute(
                text("DELETE FROM knowledge_document_version WHERE document_id = :id"),
                {"id": document_id},
            )
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            for file_id in file_ids:
                await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            await session.execute(
                text("DELETE FROM knowledge_space_scope WHERE space_id IN (:a, :b)"), {"a": personal_id, "b": public_id}
            )
            await session.execute(
                text("DELETE FROM knowledge WHERE id IN (:a, :b)"), {"a": personal_id, "b": public_id}
            )
            await session.execute(
                text("DELETE FROM user_point_log WHERE user_id = :uid AND biz_id = :bid"),
                {"uid": uploader, "bid": str(document_id)},
            )
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(
                text("DELETE FROM point_pending_deduct WHERE user_id = :uid AND biz_id = :bid"),
                {"uid": uploader, "bid": str(document_id)},
            )
            for user_id in (uploader, operator, stranger):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            if previous_rule is None:
                await session.execute(
                    text(
                        "DELETE FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R4' AND name = '知识文档色情低俗/暴力违法'"
                    )
                )
            else:
                await session.execute(
                    text("UPDATE point_rule SET score_expr = :expr, status = :status WHERE id = :id"),
                    {
                        "expr": json.dumps(previous_rule["score_expr"])
                        if not isinstance(previous_rule["score_expr"], str)
                        else previous_rule["score_expr"],
                        "status": previous_rule["status"],
                        "id": previous_rule["id"],
                    },
                )
            await session.commit()


async def test_missing_document_identity_does_not_delete(flow_env):
    """没有 reference_document_id 时拒绝, 文件仍在."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        operator = await _insert_user(session, f"vd-miss-{token}")
        space_id = await _insert_space(session, name=f"vd-miss-space-{token}", level="public")
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, knowledge_id, file_name, file_type, tenant_id, object_name, status)
                VALUES (:uid, :kid, :name, 1, 1, 'vd-miss', 2)
                """
            ),
            {"uid": operator, "kid": space_id, "name": f"vd-miss-{token}.pdf"},
        )
        await session.commit()
        file_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-miss-{token}.pdf"},
                )
            ).scalar_one()
        )
    roles[space_id] = ({operator}, set())
    try:
        app = _app(_user(operator, name=f"vd-miss-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})
        assert resp.json()["status_code"] == 18053
        rows = await _select(engine, "SELECT deleted_at FROM knowledgefile WHERE id = :id", {"id": file_id})
        assert rows[0]["deleted_at"] is None
        logs = await _select(
            engine,
            "SELECT id FROM user_point_log WHERE user_id = :uid AND biz_type = 'knowledge_document'",
            {"uid": operator},
        )
        assert logs == []
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": space_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": space_id})
            await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": operator})
            await session.commit()


async def test_public_tier_score_wins_when_department_number_is_larger(flow_env):
    """公共库配成 1、部门库配成 5, 两边都可见时扣 1."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-hi-up-{token}")
        operator = await _insert_user(session, f"vd-hi-op-{token}")
        public_id = await _insert_space(session, name=f"vd-hi-public-{token}", level="public")
        department_id = await _insert_space(session, name=f"vd-hi-dept-{token}", level="department")
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status)
                VALUES (1, :kid, 1, 'active')
                """
            ),
            {"kid": department_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": department_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES
                  (:uid, :uid, :dept, :manager_name, 1, 1, 'vd-hi-m', :doc, 'manager', 'active', 2),
                  (:uid, :uid, :public, :publish_name, 1, 1, 'vd-hi-p', :doc, 'publish', 'active', 2)
                """
            ),
            {
                "uid": uploader,
                "dept": department_id,
                "public": public_id,
                "manager_name": f"vd-hi-m-{token}.pdf",
                "publish_name": f"vd-hi-p-{token}.pdf",
                "doc": document_id,
            },
        )
        await session.commit()
        manager_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-hi-m-{token}.pdf"},
                )
            ).scalar_one()
        )
        publish_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-hi-p-{token}.pdf"},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary)
                VALUES (:doc, :file, 1, 1)
                """
            ),
            {"doc": document_id, "file": manager_id},
        )
        await session.commit()
        previous_rule = await _ensure_r4(session, {"mode": "library_scope", "public": 1, "department": 5, "team": 9})
    roles[public_id] = ({operator}, set())
    try:
        app = _app(_user(operator, name=f"vd-hi-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/{publish_id}/violation-delete", json={"rule_code": "R4"})
        body = resp.json()
        assert body["status_code"] == 200, body
        assert body["data"]["score"] == 1
        assert body["data"]["deducted"] is True
        logs = await _select(
            engine,
            "SELECT delta FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert [row["delta"] for row in logs] == [-1]
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE reference_document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id IN (:a, :b)"), {"a": public_id, "b": department_id})
            await session.execute(text("DELETE FROM knowledge WHERE id IN (:a, :b)"), {"a": public_id, "b": department_id})
            await session.execute(text("DELETE FROM user_point_log WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            for user_id in (uploader, operator):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            if previous_rule is None:
                await session.execute(text("DELETE FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R4'"))
            else:
                expr = previous_rule["score_expr"]
                await session.execute(
                    text("UPDATE point_rule SET score_expr = CAST(:expr AS JSON), status = :status WHERE id = :id"),
                    {
                        "expr": expr if isinstance(expr, str) else json.dumps(expr),
                        "status": previous_rule["status"],
                        "id": previous_rule["id"],
                    },
                )
            await session.commit()


async def test_clinic_manager_upload_visible_in_clinic_is_not_deducted(flow_env):
    """上传者是可见科室库的管理者且月奖启用时, 删除成功但不写流水."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-ex-up-{token}")
        operator = await _insert_user(session, f"vd-ex-op-{token}")
        clinic_id = await _insert_space(session, name=f"vd-ex-clinic-{token}", level="team_ks")
        public_id = await _insert_space(session, name=f"vd-ex-public-{token}", level="public")
        m6 = (
            await session.execute(
                text("SELECT id, status FROM point_rule WHERE tenant_id = 1 AND rule_code = 'M6'")
            )
        ).mappings().first()
        if m6 is not None and m6["status"] != "enabled":
            await session.execute(text("UPDATE point_rule SET status = 'enabled' WHERE id = :id"), {"id": int(m6["id"])})
            await session.commit()
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status)
                VALUES (1, :kid, 1, 'active')
                """
            ),
            {"kid": clinic_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": clinic_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES
                  (:uid, :uid, :clinic, :manager_name, 1, 1, 'vd-ex-m', :doc, 'manager', 'active', 2),
                  (:uid, :uid, :public, :publish_name, 1, 1, 'vd-ex-p', :doc, 'publish', 'active', 2)
                """
            ),
            {
                "uid": uploader,
                "clinic": clinic_id,
                "public": public_id,
                "manager_name": f"vd-ex-m-{token}.pdf",
                "publish_name": f"vd-ex-p-{token}.pdf",
                "doc": document_id,
            },
        )
        await session.commit()
        manager_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-ex-m-{token}.pdf"},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary)
                VALUES (:doc, :file, 1, 1)
                """
            ),
            {"doc": document_id, "file": manager_id},
        )
        await session.commit()
        publish_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-ex-p-{token}.pdf"},
                )
            ).scalar_one()
        )
    roles[public_id] = ({operator}, set())
    roles[clinic_id] = (set(), {uploader})
    try:
        app = _app(_user(operator, name=f"vd-ex-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/{publish_id}/violation-delete", json={"rule_code": "R4"})
        body = resp.json()
        assert body["status_code"] == 200, body
        assert body["data"]["deducted"] is False
        assert body["data"]["reason"] == "monthly_award_exempt"
        logs = await _select(
            engine,
            "SELECT id FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert logs == []
        files = await _select(
            engine,
            "SELECT deleted_at FROM knowledgefile WHERE id IN (:a, :b)",
            {"a": manager_id, "b": publish_id},
        )
        assert all(row["deleted_at"] is not None for row in files)
        recycle = await _select(
            engine,
            "SELECT id FROM knowledge_recycle_item WHERE document_id = :id",
            {"id": document_id},
        )
        assert recycle == []
        document = await _select(
            engine,
            "SELECT lifecycle_status FROM knowledge_document WHERE id = :id",
            {"id": document_id},
        )
        assert document[0]["lifecycle_status"] == "deleting"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE reference_document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id IN (:a, :b)"), {"a": clinic_id, "b": public_id})
            await session.execute(text("DELETE FROM knowledge WHERE id IN (:a, :b)"), {"a": clinic_id, "b": public_id})
            await session.execute(text("DELETE FROM user_point_log WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            if m6 is not None:
                await session.execute(
                    text("UPDATE point_rule SET status = :status WHERE id = :id"),
                    {"status": m6["status"], "id": int(m6["id"])},
                )
            for user_id in (uploader, operator):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            await session.commit()


async def test_skip_deduct_then_later_deduct_writes_one_log(flow_env):
    """第一次只删不扣不占名额; 文档已在回收站后再次确认扣分, 只记一条."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-later-up-{token}")
        operator = await _insert_user(session, f"vd-later-op-{token}")
        public_id = await _insert_space(session, name=f"vd-later-public-{token}", level="public")
        await session.execute(
            text(
                """
                INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status)
                VALUES (1, :kid, 1, 'active')
                """
            ),
            {"kid": public_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": public_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES (:uid, :uid, :kid, :name, 1, 1, 'vd-later', :doc, 'manager', 'active', 2)
                """
            ),
            {"uid": uploader, "kid": public_id, "name": f"vd-later-{token}.pdf", "doc": document_id},
        )
        await session.commit()
        file_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-later-{token}.pdf"},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary) VALUES (:doc, :file, 1, 1)"
            ),
            {"doc": document_id, "file": file_id},
        )
        await session.commit()
        previous_rule = await _ensure_r4(session, {"mode": "library_scope", "public": 3, "department": 2, "team": 1})
    roles[public_id] = ({operator}, set())
    try:
        app = _app(_user(operator, name=f"vd-later-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={})
            assert first.json()["status_code"] == 200, first.json()
            assert first.json()["data"]["deducted"] is False
            second = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})
            assert second.json()["status_code"] == 200, second.json()
            assert second.json()["data"]["deducted"] is True
        logs = await _select(
            engine,
            "SELECT delta FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert [row["delta"] for row in logs] == [-3]
        recycle = await _select(
            engine,
            "SELECT id FROM knowledge_recycle_item WHERE document_id = :id",
            {"id": document_id},
        )
        assert recycle == []
        document = await _select(
            engine,
            "SELECT lifecycle_status FROM knowledge_document WHERE id = :id",
            {"id": document_id},
        )
        assert document[0]["lifecycle_status"] == "deleting"
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM user_point_log WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM point_pending_deduct WHERE biz_id = :bid"), {"bid": str(document_id)})
            for user_id in (uploader, operator):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            if previous_rule is None:
                await session.execute(text("DELETE FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R4'"))
            else:
                expr = previous_rule["score_expr"]
                await session.execute(
                    text("UPDATE point_rule SET score_expr = CAST(:expr AS JSON), status = :status WHERE id = :id"),
                    {
                        "expr": expr if isinstance(expr, str) else json.dumps(expr),
                        "status": previous_rule["status"],
                        "id": previous_rule["id"],
                    },
                )
            await session.commit()


async def test_preparing_publish_rejects_without_recycle_or_points(flow_env):
    """还有准备中的发布时整单拒绝, 原件仍在, 没有流水."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-busy-up-{token}")
        operator = await _insert_user(session, f"vd-busy-op-{token}")
        public_id = await _insert_space(session, name=f"vd-busy-public-{token}", level="public")
        await session.execute(
            text(
                "INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status) VALUES (1, :kid, 1, 'active')"
            ),
            {"kid": public_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": public_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES
                  (:uid, :uid, :kid, :manager_name, 1, 1, 'vd-busy-m', :doc, 'manager', 'active', 2),
                  (:uid, :uid, :kid, :prep_name, 1, 1, 'vd-busy-p', :doc, 'publish', 'preparing', 2)
                """
            ),
            {
                "uid": uploader,
                "kid": public_id,
                "manager_name": f"vd-busy-m-{token}.pdf",
                "prep_name": f"vd-busy-p-{token}.pdf",
                "doc": document_id,
            },
        )
        await session.commit()
        manager_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                    {"n": f"vd-busy-m-{token}.pdf"},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary) VALUES (:doc, :file, 1, 1)"
            ),
            {"doc": document_id, "file": manager_id},
        )
        await session.commit()
    roles[public_id] = ({operator}, set())
    try:
        app = _app(_user(operator, name=f"vd-busy-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/{manager_id}/violation-delete", json={"rule_code": "R4"})
        assert resp.json()["status_code"] == 18054
        rows = await _select(engine, "SELECT deleted_at FROM knowledgefile WHERE reference_document_id = :id", {"id": document_id})
        assert all(row["deleted_at"] is None for row in rows)
        recycle = await _select(engine, "SELECT id FROM knowledge_recycle_item WHERE document_id = :id", {"id": document_id})
        assert recycle == []
        logs = await _select(
            engine,
            "SELECT id FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert logs == []
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE reference_document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": public_id})
            for user_id in (uploader, operator):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            await session.commit()


async def test_pending_deduct_uses_score_snapshot_after_rule_edit(flow_env, monkeypatch):
    """记账失败入队后, 改大公共库分值, 补扣仍用确认时的 3 分."""
    from bisheng.points.domain.repositories.points_repository import PointsRepository
    from bisheng.points.domain.services.points_ledger_service import PointsLedgerService

    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    original_deduct = PointsLedgerService.deduct
    state = {"failed": False}

    async def _fail_once(self, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            raise RuntimeError("injected ledger failure")
        return await original_deduct(self, **kwargs)

    monkeypatch.setattr(PointsLedgerService, "deduct", _fail_once)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-snap-up-{token}")
        operator = await _insert_user(session, f"vd-snap-op-{token}")
        public_id = await _insert_space(session, name=f"vd-snap-public-{token}", level="public")
        await session.execute(
            text(
                "INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status) VALUES (1, :kid, 1, 'active')"
            ),
            {"kid": public_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": public_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES (:uid, :uid, :kid, :name, 1, 1, 'vd-snap', :doc, 'manager', 'active', 2)
                """
            ),
            {"uid": uploader, "kid": public_id, "name": f"vd-snap-{token}.pdf", "doc": document_id},
        )
        await session.commit()
        file_id = int(
            (await session.execute(text("SELECT id FROM knowledgefile WHERE file_name = :n"), {"n": f"vd-snap-{token}.pdf"})).scalar_one()
        )
        await session.execute(
            text("INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary) VALUES (:doc, :file, 1, 1)"),
            {"doc": document_id, "file": file_id},
        )
        await session.commit()
        previous_rule = await _ensure_r4(session, {"mode": "library_scope", "public": 3, "department": 2, "team": 1})
    roles[public_id] = ({operator}, set())
    try:
        app = _app(_user(operator, name=f"vd-snap-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})
        body = resp.json()
        assert body["status_code"] == 200, body
        assert body["data"]["pending_deduct"] is True
        pending = await _select(
            engine,
            "SELECT score_snapshot, scope_tier, idempotency_key FROM point_pending_deduct WHERE biz_id = :bid",
            {"bid": str(document_id)},
        )
        assert pending[0]["score_snapshot"] == 3
        assert pending[0]["scope_tier"] == "public"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("UPDATE point_rule SET score_expr = CAST(:expr AS JSON) WHERE tenant_id = 1 AND rule_code = 'R4'"),
                {"expr": json.dumps({"mode": "library_scope", "public": 9, "department": 5, "team": 1})},
            )
            await session.commit()
            repo = PointsRepository(session)
            row = await repo.get_pending_deduct_by_key(1, pending[0]["idempotency_key"])
            assert row is not None
            outcome = await PointsPendingDeductService()._process_one(repo, row)
            await session.commit()
        assert outcome == "done"
        logs = await _select(
            engine,
            "SELECT delta FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert [item["delta"] for item in logs] == [-3]
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM user_point_log WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM point_pending_deduct WHERE biz_id = :bid"), {"bid": str(document_id)})
            for user_id in (uploader, operator):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            if previous_rule is None:
                await session.execute(text("DELETE FROM point_rule WHERE tenant_id = 1 AND rule_code = 'R4'"))
            else:
                expr = previous_rule["score_expr"]
                await session.execute(
                    text("UPDATE point_rule SET score_expr = CAST(:expr AS JSON), status = :status WHERE id = :id"),
                    {
                        "expr": expr if isinstance(expr, str) else json.dumps(expr),
                        "status": previous_rule["status"],
                        "id": previous_rule["id"],
                    },
                )
            await session.commit()


async def test_two_operators_deduct_once(flow_env):
    """两名库所有者同时确认, 流水只有一条."""
    engine, roles = flow_env
    token = uuid.uuid4().hex[:8]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"vd-race-up-{token}")
        first_op = await _insert_user(session, f"vd-race-a-{token}")
        second_op = await _insert_user(session, f"vd-race-b-{token}")
        public_id = await _insert_space(session, name=f"vd-race-public-{token}", level="public")
        await session.execute(
            text(
                "INSERT INTO knowledge_document (tenant_id, knowledge_id, content_generation, lifecycle_status) VALUES (1, :kid, 1, 'active')"
            ),
            {"kid": public_id},
        )
        await session.commit()
        document_id = int(
            (
                await session.execute(
                    text("SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"),
                    {"kid": public_id},
                )
            ).scalar_one()
        )
        await session.execute(
            text(
                """
                INSERT INTO knowledgefile
                  (user_id, original_uploader_id, knowledge_id, file_name, file_type, tenant_id,
                   object_name, reference_document_id, entry_type, entry_status, status)
                VALUES (:uid, :uid, :kid, :name, 1, 1, 'vd-race', :doc, 'manager', 'active', 2)
                """
            ),
            {"uid": uploader, "kid": public_id, "name": f"vd-race-{token}.pdf", "doc": document_id},
        )
        await session.commit()
        file_id = int(
            (await session.execute(text("SELECT id FROM knowledgefile WHERE file_name = :n"), {"n": f"vd-race-{token}.pdf"})).scalar_one()
        )
        await session.execute(
            text("INSERT INTO knowledge_document_version (document_id, knowledge_file_id, version_no, is_primary) VALUES (:doc, :file, 1, 1)"),
            {"doc": document_id, "file": file_id},
        )
        await session.commit()
        await _ensure_r4(session, {"mode": "library_scope", "public": 3, "department": 2, "team": 1})
    roles[public_id] = ({first_op, second_op}, set())
    try:
        first_app = _app(_user(first_op, name=f"vd-race-a-{token}"))
        second_app = _app(_user(second_op, name=f"vd-race-b-{token}"))

        async def _confirm(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                return await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})

        left, right = await asyncio.gather(_confirm(first_app), _confirm(second_app))
        assert left.json()["status_code"] == 200, left.json()
        assert right.json()["status_code"] == 200, right.json()
        logs = await _select(
            engine,
            "SELECT delta FROM user_point_log WHERE user_id = :uid AND biz_id = :bid",
            {"uid": uploader, "bid": str(document_id)},
        )
        assert [row["delta"] for row in logs] == [-3]
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM knowledge_recycle_item WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document_version WHERE document_id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": public_id})
            await session.execute(text("DELETE FROM user_point_log WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :uid"), {"uid": uploader})
            await session.execute(text("DELETE FROM point_pending_deduct WHERE biz_id = :bid"), {"bid": str(document_id)})
            for user_id in (uploader, first_op, second_op):
                await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            await session.commit()


def test_ordinary_delete_file_does_not_call_violation_deduct():
    """普通删除函数本身不调用知识文档扣分."""
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

    source = inspect.getsource(KnowledgeSpaceService.delete_file)
    assert "PointsPendingDeduct" not in source
    assert "violation-delete" not in source
    assert "knowledge_violation_delete" not in source
