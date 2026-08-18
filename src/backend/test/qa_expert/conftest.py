# ruff: noqa: RUF002
"""qa_expert 流转夹具：真实 MySQL（config.yaml / 171），每次新连接。"""

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
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.api.endpoints.approval_user import router as approval_user_router
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database.connection import _patch_aiomysql_pre_ping
from bisheng.database.models.qa_expert import Expert
from bisheng.qa_expert.api.router import router
from bisheng.qa_expert.domain.publish_service import PublishService
from bisheng.qa_expert.domain.services import AnswerService, CommentService, ExpertService, QuestionService

FLOW_PREFIX = "df-flow-"
_USER_ID_BASE = 88_000_000


def _mysql_async_url() -> str:
    """从 config.yaml 解密 database_url，转为 aiomysql；可用环境变量覆盖。不打印口令。"""
    override = os.environ.get("QA_EXPERT_FLOW_DATABASE_URL")
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
    if "171" not in url and not os.environ.get("QA_EXPERT_FLOW_DATABASE_URL"):
        # 本 Feature 验收库约定 171；覆盖 URL 时跳过该检查
        raise RuntimeError("流转测试默认打 192.168.106.171，请确认 config.yaml 或设置 QA_EXPERT_FLOW_DATABASE_URL")
    return url.replace("pymysql", "aiomysql")


def make_user(
    user_id: int,
    *,
    admin: bool = False,
    super_admin: bool = False,
    role: str | None = None,
    name: str | None = None,
):
    """构造接口依赖用的登录身份（不写 user 表）。"""
    return SimpleNamespace(
        user_id=user_id,
        user_name=name or f"u{user_id}",
        tenant_id=1,
        is_admin=lambda: admin,
        role=role,
        is_global_super=super_admin,
    )


def _flow_app(auth: dict):
    """挂 qa_expert 路由；身份从 auth['user'] 读取。"""
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    app.include_router(router, prefix="/api/v1")
    app.include_router(approval_user_router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: auth["user"]
    return app


async def _cleanup_prefix(engine, prefix: str) -> None:
    """按标题/专家名前缀删除本夹具写入的 qa_* 行。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        q_rows = (
            await session.execute(text("SELECT id FROM qa_question WHERE title LIKE :p"), {"p": f"{prefix}%"})
        ).fetchall()
        qids = [int(row[0]) for row in q_rows]
        if qids:
            ids = ",".join(str(i) for i in qids)
            for stmt in (
                f"DELETE FROM qa_publish_approver WHERE request_id IN (SELECT id FROM qa_publish_request WHERE question_id IN ({ids}))",
                f"DELETE FROM qa_publish_request WHERE question_id IN ({ids})",
                f"DELETE FROM qa_answer_eligibility WHERE question_id IN ({ids})",
                f"DELETE FROM qa_anonymous_alias WHERE question_id IN ({ids})",
                f"DELETE FROM qa_answer_adopt WHERE question_id IN ({ids})",
                f"DELETE FROM qa_comment WHERE question_id IN ({ids})",
                f"DELETE FROM qa_answer WHERE question_id IN ({ids})",
                f"DELETE FROM qa_question_invite WHERE question_id IN ({ids})",
                f"DELETE FROM qa_question WHERE id IN ({ids})",
            ):
                await session.execute(text(stmt))
        await session.execute(
            text(
                "DELETE FROM approval_action_log WHERE instance_id IN "
                "(SELECT id FROM approval_instance WHERE scenario_code = 'qa_question_publish' AND business_name LIKE :p)"
            ),
            {"p": f"{prefix}%"},
        )
        await session.execute(
            text(
                "DELETE FROM approval_task WHERE instance_id IN "
                "(SELECT id FROM approval_instance WHERE scenario_code = 'qa_question_publish' AND business_name LIKE :p)"
            ),
            {"p": f"{prefix}%"},
        )
        await session.execute(
            text("DELETE FROM approval_instance WHERE scenario_code = 'qa_question_publish' AND business_name LIKE :p"),
            {"p": f"{prefix}%"},
        )
        await session.execute(text("DELETE FROM qa_expert WHERE expert_name LIKE :p"), {"p": f"{prefix}%"})
        await session.execute(
            text(
                "DELETE FROM inbox_message_read WHERE message_id IN "
                "(SELECT id FROM (SELECT id FROM inbox_message WHERE CAST(content AS CHAR) LIKE :p) t)"
            ),
            {"p": f"%{prefix}%"},
        )
        await session.execute(
            text("DELETE FROM inbox_message WHERE CAST(content AS CHAR) LIKE :p"),
            {"p": f"%{prefix}%"},
        )
        await session.commit()


def _flow_engine():
    _patch_aiomysql_pre_ping()
    return create_async_engine(
        _mysql_async_url(),
        pool_pre_ping=True,
        pool_size=8,
        max_overflow=4,
        pool_recycle=3600,
    )


@pytest.fixture
async def flow_env(monkeypatch):
    """
    真实 MySQL：每次仓储调用新 session，才能验 FOR UPDATE / 行锁。
    通知/积分/遥测静音。数据前缀 df-flow-<uuid>- 。
    """
    set_current_tenant_id(1)
    prefix = f"{FLOW_PREFIX}{uuid.uuid4().hex[:8]}-"
    uid_start = _USER_ID_BASE + (uuid.uuid4().int % 40_000) * 20
    uid_cursor = {"n": uid_start}
    uid_map: dict[int, int] = {}

    def next_uid() -> int:
        uid_cursor["n"] += 1
        return uid_cursor["n"]

    def uid(logical: int) -> int:
        if logical not in uid_map:
            uid_map[logical] = next_uid()
        return uid_map[logical]

    engine = _flow_engine()
    await _cleanup_prefix(engine, FLOW_PREFIX)
    await _cleanup_prefix(engine, prefix)

    @asynccontextmanager
    async def patched_session():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    monkeypatch.setattr("bisheng.qa_expert.domain.repositories.get_async_db_session", patched_session)
    monkeypatch.setattr("bisheng.qa_expert.domain.services.get_async_db_session", patched_session)
    monkeypatch.setattr("bisheng.core.database.get_async_db_session", patched_session)
    monkeypatch.setattr("bisheng.core.database.manager.get_async_db_session", patched_session)
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session",
        patched_session,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_center_service.UserDao.aget_user_by_ids",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(QuestionService, "_send_expert_invitation_inbox_notice", AsyncMock())
    monkeypatch.setattr(QuestionService, "_send_adoption_notification", AsyncMock())
    monkeypatch.setattr(AnswerService, "_send_answer_notification", AsyncMock())
    monkeypatch.setattr(CommentService, "_send_comment_notification", AsyncMock())
    monkeypatch.setattr(PublishService, "_notify", AsyncMock())
    monkeypatch.setattr("bisheng.qa_expert.domain.services.RealtimeQaQuestionFact.record_success", AsyncMock())
    monkeypatch.setattr("bisheng.qa_expert.api.endpoints.check_question_content", lambda *a, **k: None)
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_award_hooks.notify_answer_adopted",
        AsyncMock(),
    )

    async def _related_access(_user, _space_id, _file_id):
        return False

    monkeypatch.setattr(
        "bisheng.qa_expert.domain.related_docs_access.check_related_doc_access",
        _related_access,
    )

    def mapped_user(logical_id: int, **kwargs):
        real_id = logical_id if logical_id >= _USER_ID_BASE else uid(logical_id)
        return make_user(real_id, **kwargs)

    asker = mapped_user(101, name="asker")
    auth = {"user": asker}
    app = _flow_app(auth)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def seed_expert(*, user_id: int, name: str, status: int = 1) -> Expert:
        repo = ExpertService().repository
        return await repo.create(
            Expert(user_id=uid(user_id), expert_name=f"{prefix}{name}", status=status, tenant_id=1)
        )

    async def reload_row(model, **eq):
        table = model.__table__
        stmt = select(table)
        for key, value in eq.items():
            stmt = stmt.where(table.c[key] == value)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            mapping = (await session.execute(stmt)).mappings().first()
            return SimpleNamespace(**dict(mapping)) if mapping else None

    async def reload_all(model, **eq):
        table = model.__table__
        stmt = select(table)
        for key, value in eq.items():
            stmt = stmt.where(table.c[key] == value)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            mappings = (await session.execute(stmt)).mappings().all()
            return [SimpleNamespace(**dict(item)) for item in mappings]

    env = SimpleNamespace(
        client=client,
        engine=engine,
        prefix=prefix,
        uid=uid,
        auth=auth,
        as_user=lambda user: auth.__setitem__("user", user),
        user=mapped_user,
        seed_expert=seed_expert,
        reload_row=reload_row,
        reload_all=reload_all,
        asker=asker,
        stranger=mapped_user(301, name="stranger"),
        portal_admin=mapped_user(401, name="portal-admin", admin=True, role="管理员"),
        t=lambda title: title if title.startswith(prefix) else prefix + title,
    )
    try:
        yield env
    finally:
        await client.aclose()
        await _cleanup_prefix(engine, prefix)
        await engine.dispose()
