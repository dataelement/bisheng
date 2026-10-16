"""按部门授予的管理员上传文档时, 违规删除免扣; 没有 manager 关系时仍扣.

直连管理员名单不含上传者. 免扣只依赖一次 OpenFGA manager 检查.
本用例打 171 MySQL, 断言删除落库, 以及 user_point_log 有没有新行.
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


async def _violation_delete_for_computed_manager(monkeypatch, *, has_manager: bool):
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.core.database.tenant_filter import register_tenant_filter_events

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
        "bisheng.points.domain.services.points_pending_deduct_service.get_async_db_session",
    ):
        monkeypatch.setattr(target, session_scope)

    token = uuid.uuid4().hex[:8]
    operator_id = uploader_id = space_id = document_id = file_id = 0
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for name in (f"vd-cm-up-{token}", f"vd-cm-op-{token}"):
                await session.execute(
                    text("INSERT INTO user (user_name, password, `delete`) VALUES (:n, 'x', 0)"),
                    {"n": name},
                )
            await session.commit()
            rows = (
                await session.execute(
                    text("SELECT user_id, user_name FROM user WHERE user_name LIKE :p"),
                    {"p": f"vd-cm-%-{token}"},
                )
            ).all()
            ids = {name: int(user_id) for user_id, name in rows}
            uploader_id = ids[f"vd-cm-up-{token}"]
            operator_id = ids[f"vd-cm-op-{token}"]
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge (user_id, name, type, tenant_id, is_released, is_favorite, auth_type)
                    VALUES (1, :name, :type, 1, 0, 0, 'PRIVATE')
                    """
                ),
                {"name": f"vd-cm-space-{token}", "type": KnowledgeTypeEnum.SPACE.value},
            )
            await session.commit()
            space_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledge WHERE name = :n"),
                        {"n": f"vd-cm-space-{token}"},
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
                      (:uid, :uid, :kid, :name, 1, 1, 'vd-cm', :doc, 'manager', 'active', 2)
                    """
                ),
                {"uid": uploader_id, "kid": space_id, "name": f"vd-cm-{token}.pdf", "doc": document_id},
            )
            await session.commit()
            file_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledgefile WHERE file_name = :n"),
                        {"n": f"vd-cm-{token}.pdf"},
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

        async def roles(raw_space_id: int):
            if int(raw_space_id) == space_id:
                return set(), {operator_id}
            return set(), set()

        async def relation(raw_space_id: int, raw_user_id: int) -> bool:
            return has_manager and int(raw_space_id) == space_id and int(raw_user_id) == uploader_id

        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_violation_delete_service.read_space_owner_manager_ids",
            roles,
        )
        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_violation_delete_service.user_has_space_manager_relation",
            relation,
        )

        app = _app(_user(operator_id, f"vd-cm-op-{token}"))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})
            assert first.status_code == 200
            body = first.json()
            assert body["status_code"] == 200, body
            assert body["data"]["deleted"] is True
            again = await client.post(f"{PREFIX}/{file_id}/violation-delete", json={"rule_code": "R4"})
            assert again.json()["status_code"] == 200

        async with AsyncSession(engine, expire_on_commit=False) as session:
            document = (
                await session.execute(
                    text("SELECT lifecycle_status FROM knowledge_document WHERE id = :id"),
                    {"id": document_id},
                )
            ).one()
            logs = (
                await session.execute(
                    text(
                        """
                        SELECT delta FROM user_point_log
                        WHERE user_id = :uid AND biz_type = 'knowledge_document' AND biz_id = :bid
                        """
                    ),
                    {"uid": uploader_id, "bid": str(document_id)},
                )
            ).all()
            pending = (
                await session.execute(
                    text("SELECT COUNT(*) FROM point_pending_deduct WHERE biz_id = :bid"),
                    {"bid": str(document_id)},
                )
            ).scalar_one()
        assert document.lifecycle_status == "deleting"
        assert int(pending) == 0
        if has_manager:
            assert body["data"]["deducted"] is False
            assert body["data"]["reason"] == "monthly_award_exempt"
            assert logs == []
            assert again.json()["data"]["reason"] == "monthly_award_exempt"
        else:
            assert body["data"]["deducted"] is True
            assert [int(row.delta) for row in logs] == [-2]
            assert again.json()["data"]["deducted"] is True
            async with AsyncSession(engine, expire_on_commit=False) as session:
                replay_logs = (
                    await session.execute(
                        text(
                            """
                            SELECT delta FROM user_point_log
                            WHERE user_id = :uid AND biz_type = 'knowledge_document' AND biz_id = :bid
                            """
                        ),
                        {"uid": uploader_id, "bid": str(document_id)},
                    )
                ).all()
            assert [int(row.delta) for row in replay_logs] == [-2]
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
                await session.execute(
                    text("DELETE FROM user_point_log WHERE biz_id = :bid"),
                    {"bid": str(document_id)},
                )
            if uploader_id:
                await session.execute(
                    text("DELETE FROM user_point_account WHERE user_id = :id"),
                    {"id": uploader_id},
                )
            if file_id:
                await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
            if space_id:
                await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": space_id})
                await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": space_id})
            for user_id in (uploader_id, operator_id):
                if user_id:
                    await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
            await session.commit()
        await engine.dispose()


async def test_department_grant_manager_uploader_is_exempt(monkeypatch):
    """上传者只有计算出来的 manager 关系时, 删除成功且不写扣分流水."""
    await _violation_delete_for_computed_manager(monkeypatch, has_manager=True)


async def test_uploader_without_manager_relation_is_still_deducted(monkeypatch):
    """没有 manager 关系时仍扣部门库档 2 分, 再确认一次不重复扣."""
    await _violation_delete_for_computed_manager(monkeypatch, has_manager=False)
