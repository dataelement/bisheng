"""按部门授予的空间管理员可以违规删除, 普通成员不行.

直连 user 元组为空时, 鉴权改走知识空间 can_manage. 本用例打 171 MySQL,
用接口写删除状态, 再查 knowledge_document 与 knowledgefile.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

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
from test.knowledge.test_knowledge_violation_delete_flow import _mysql_async_url

PREFIX = "/api/v1/knowledge/space/files"


def _user(user_id: int, name: str):
    return SimpleNamespace(
        user_id=user_id,
        user_name=name,
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=False,
        role="user",
    )


def _app(user) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.dependency_overrides[UserPayload.get_login_user] = lambda: user
    app.include_router(violation_router, prefix="/api/v1")
    return app


async def test_department_manager_can_violation_delete_without_direct_user_tuple(monkeypatch):
    """部门管理员没有 user 直连元组时, 预览和确认都能删, 非管理员仍是 18052."""
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.core.database.tenant_filter import register_tenant_filter_events
    from bisheng.permission.domain.services.permission_service import PermissionService

    set_current_tenant_id(1)
    _patch_aiomysql_pre_ping()
    register_tenant_filter_events()
    engine = create_async_engine(_mysql_async_url(), pool_pre_ping=True)

    @asynccontextmanager
    async def session_scope():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    for target in (
        "bisheng.knowledge.domain.services.knowledge_violation_delete_service.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_space_scope.get_async_db_session",
    ):
        monkeypatch.setattr(target, session_scope)

    async def empty_roles(_space_id: int):
        return set(), set()

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_violation_delete_service.read_space_owner_manager_ids",
        empty_roles,
    )

    token = uuid.uuid4().hex[:8]
    operator_id = 0
    stranger_id = 0
    uploader_id = 0
    space_id = 0
    document_id = 0
    file_id = 0
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for name in (f"vd-dept-up-{token}", f"vd-dept-op-{token}", f"vd-dept-st-{token}"):
                await session.execute(
                    text("INSERT INTO user (user_name, password, `delete`) VALUES (:n, 'x', 0)"),
                    {"n": name},
                )
            await session.commit()
            rows = (
                await session.execute(
                    text("SELECT user_id, user_name FROM user WHERE user_name LIKE :p"),
                    {"p": f"vd-dept-%-{token}"},
                )
            ).all()
            ids = {name: int(user_id) for user_id, name in rows}
            uploader_id = ids[f"vd-dept-up-{token}"]
            operator_id = ids[f"vd-dept-op-{token}"]
            stranger_id = ids[f"vd-dept-st-{token}"]
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge (user_id, name, type, tenant_id, is_released, is_favorite, auth_type)
                    VALUES (1, :name, :type, 1, 0, 0, 'PRIVATE')
                    """
                ),
                {"name": f"vd-dept-space-{token}", "type": KnowledgeTypeEnum.SPACE.value},
            )
            await session.commit()
            space_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledge WHERE name = :n"),
                        {"n": f"vd-dept-space-{token}"},
                    )
                ).scalar_one()
            )
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_space_scope
                      (tenant_id, space_id, level, owner_type, owner_id, created_by)
                    VALUES (1, :sid, 'department', 'department', 1, 1)
                    """
                ),
                {"sid": space_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_document
                      (tenant_id, knowledge_id, content_generation, lifecycle_status)
                    VALUES (1, :kid, 1, 'active')
                    """
                ),
                {"kid": space_id},
            )
            await session.commit()
            document_id = int(
                (
                    await session.execute(
                        text(
                            "SELECT id FROM knowledge_document WHERE knowledge_id = :kid ORDER BY id DESC LIMIT 1"
                        ),
                        {"kid": space_id},
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
                      (:uid, :uid, :kid, :name, 1, 1, 'vd-dept', :doc, 'publish', 'active', 2)
                    """
                ),
                {
                    "uid": uploader_id,
                    "kid": space_id,
                    "name": f"vd-dept-{token}.pdf",
                    "doc": document_id,
                },
            )
            await session.commit()
            file_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                        {"n": f"vd-dept-{token}.pdf"},
                    )
                ).scalar_one()
            )
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_document_version
                      (document_id, knowledge_file_id, version_no, is_primary)
                    VALUES (:doc, :file, 1, 1)
                    """
                ),
                {"doc": document_id, "file": file_id},
            )
            version_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledge_document_version WHERE document_id = :doc"),
                        {"doc": document_id},
                    )
                ).scalar_one()
            )
            await session.execute(
                text("UPDATE knowledge_document SET primary_version_id = :vid WHERE id = :doc"),
                {"vid": version_id, "doc": document_id},
            )
            await session.commit()

        async def check(user_id, relation, object_type, object_id, login_user=None):
            return (
                int(user_id) == operator_id
                and relation == "can_manage"
                and object_type == "knowledge_space"
                and int(object_id) == space_id
            )

        monkeypatch.setattr(PermissionService, "check", check)

        stranger = _app(_user(stranger_id, f"vd-dept-st-{token}"))
        async with AsyncClient(transport=ASGITransport(app=stranger), base_url="http://test") as client:
            denied = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={})
        assert denied.status_code == 200
        assert denied.json()["status_code"] == 18052
        async with AsyncSession(engine, expire_on_commit=False) as session:
            before = (
                await session.execute(
                    text(
                        """
                        SELECT d.lifecycle_status, f.entry_status, f.deleted_at
                        FROM knowledge_document d
                        JOIN knowledgefile f ON f.reference_document_id = d.id
                        WHERE d.id = :doc AND f.id = :file
                        """
                    ),
                    {"doc": document_id, "file": file_id},
                )
            ).one()
        assert before.lifecycle_status == "active"
        assert before.entry_status == "active"
        assert before.deleted_at is None

        operator = _app(_user(operator_id, f"vd-dept-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=operator), base_url="http://test") as client:
            preview = await client.post(f"{PREFIX}/{file_id}/violation-delete/preview", json={})
            assert preview.status_code == 200
            assert preview.json()["status_code"] == 200
            committed = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={})
            assert committed.status_code == 200
            body = committed.json()
            assert body["status_code"] == 200
            assert body["data"]["deleted"] is True
            assert body["data"]["deducted"] is False
            again = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={})
            assert again.json()["status_code"] == 200
            assert again.json()["data"]["deleted"] is True

        async with AsyncSession(engine, expire_on_commit=False) as session:
            after = (
                await session.execute(
                    text(
                        """
                        SELECT d.lifecycle_status, f.entry_status, f.deleted_at
                        FROM knowledge_document d
                        JOIN knowledgefile f ON f.id = :file
                        WHERE d.id = :doc
                        """
                    ),
                    {"doc": document_id, "file": file_id},
                )
            ).one()
            pending = (
                await session.execute(
                    text("SELECT COUNT(*) FROM point_pending_deduct WHERE biz_id = :bid"),
                    {"bid": str(document_id)},
                )
            ).scalar_one()
        assert after.lifecycle_status == "deleting"
        assert after.entry_status == "deleting"
        assert after.deleted_at is not None
        assert int(pending) == 0
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if document_id:
                await session.execute(
                    text("DELETE FROM knowledge_document_version WHERE document_id = :id"),
                    {"id": document_id},
                )
                await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": document_id})
                await session.execute(
                    text("DELETE FROM point_pending_deduct WHERE biz_id = :bid"),
                    {"bid": str(document_id)},
                )
            if file_id:
                await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            if space_id:
                await session.execute(
                    text("DELETE FROM knowledge_space_scope WHERE space_id = :id"),
                    {"id": space_id},
                )
                await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": space_id})
            for user_id in (uploader_id, operator_id, stranger_id):
                if user_id:
                    await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            await session.commit()
        await engine.dispose()
