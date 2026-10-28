"""异常上传: 171 MySQL 接口, 核对 knowledgefile 与回收站, 再打一枪."""

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
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.api.endpoints.abnormal_upload import router as abnormal_router
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum

PREFIX = "/api/v1/knowledge/space/abnormal-uploads"


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


def _operator(user_id: int, *, name: str, role_names: list[str] | None = None, super_admin: bool = False):
    return SimpleNamespace(
        user_id=user_id,
        user_name=name,
        tenant_id=1,
        is_admin=lambda: False,
        is_global_super=super_admin,
        role="user",
        role_names=role_names or [],
    )


@pytest.fixture
async def flow_env(monkeypatch):
    from bisheng.core.context.tenant import set_current_tenant_id
    from bisheng.core.database.connection import _patch_aiomysql_pre_ping
    from bisheng.core.database.tenant_filter import register_tenant_filter_events
    from bisheng.knowledge.domain.services.knowledge_recycle_service import KnowledgeRecycleService
    from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

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
        "bisheng.knowledge.domain.models.knowledge_file.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge.get_async_db_session",
        "bisheng.knowledge.domain.services.knowledge_recycle_service.get_async_db_session",
        "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
        "bisheng.knowledge.domain.models.knowledge_space_shared_storage.get_async_db_session",
    ):
        monkeypatch.setattr(target, patched_session)

    async def _retention_days(*_args, **_kwargs) -> int:
        return 30

    async def _no_tags(*_args, **_kwargs):
        return {}

    async def _no_stat(*_args, **_kwargs):
        return None

    async def _no_cleanup(self, _file_ids):
        return None

    import importlib.util

    http_error_path = Path(__file__).resolve().parents[2] / "bisheng" / "common" / "errcode" / "http_error.py"
    spec = importlib.util.spec_from_file_location(
        "bisheng.common.errcode.http_error_real",
        http_error_path,
    )
    real_http_error = importlib.util.module_from_spec(spec)
    real_http_error.__package__ = "bisheng.common.errcode"
    spec.loader.exec_module(real_http_error)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.abnormal_upload_service.UnAuthorizedError",
        real_http_error.UnAuthorizedError,
    )
    monkeypatch.setattr(KnowledgeRecycleService, "get_retention_days", _retention_days)
    monkeypatch.setattr(KnowledgeRecycleService, "_snapshot_tags_by_file_ids", _no_tags)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_recycle_service.KnowledgeSpaceContentStat.enqueue_file_stat_async",
        _no_stat,
    )
    monkeypatch.setattr(KnowledgeSpaceService, "_cleanup_review_tags_for_deleted_files", _no_cleanup)
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.enqueue_favorite_change_events",
        lambda _events: None,
    )
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_service.cancel_pending_file_corrections",
        _no_stat,
    )
    yield engine
    await engine.dispose()


def _app(user, engine) -> FastAPI:
    app = FastAPI()

    @app.exception_handler(BaseErrorCode)
    async def _biz(_req, exc: BaseErrorCode):
        return JSONResponse(
            {"status_code": exc.code, "status_message": exc.message, "data": None},
            status_code=200,
        )

    async def _login():
        return user

    async def _db():
        session = AsyncSession(bind=engine, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[UserPayload.get_login_user] = _login
    app.dependency_overrides[get_db_session] = _db
    app.include_router(abnormal_router, prefix="/api/v1")
    return app


async def _select(engine, sql: str, params: dict | None = None) -> list[dict]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        rows = (await session.execute(text(sql), params or {})).mappings().all()
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


async def _set_update_time(session: AsyncSession, file_id: int, value: str) -> None:
    await session.execute(
        text("UPDATE knowledgefile SET update_time = :ts WHERE id = :id"),
        {"ts": value, "id": file_id},
    )
    await session.commit()


async def _insert_file(
    session: AsyncSession,
    *,
    user_id: int,
    user_name: str,
    space_id: int,
    file_name: str,
    status: int,
    entry_type: str | None = None,
    file_type: int = 1,
    remark: str = "",
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledgefile
              (user_id, user_name, knowledge_id, file_name, file_type, tenant_id,
               object_name, entry_type, status, remark)
            VALUES
              (:uid, :uname, :kid, :name, :ftype, 1, :obj, :entry, :status, :remark)
            """
        ),
        {
            "uid": user_id,
            "uname": user_name,
            "kid": space_id,
            "name": file_name,
            "ftype": file_type,
            "obj": f"obj-{file_name}",
            "entry": entry_type,
            "status": status,
            "remark": remark,
        },
    )
    await session.commit()
    return int(
        (
            await session.execute(text("SELECT id FROM knowledgefile WHERE file_name = :n"), {"n": file_name})
        ).scalar_one()
    )


def _id_list(values: list[int]) -> str:
    return ",".join(str(int(value)) for value in values)


async def _cleanup(engine, *, user_ids: list[int], space_ids: list[int], file_ids: list[int]) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if file_ids:
            ids = _id_list(file_ids)
            await session.execute(text(f"DELETE FROM knowledge_recycle_item WHERE file_id IN ({ids})"))
            await session.execute(text(f"DELETE FROM knowledgefile WHERE id IN ({ids})"))
        if space_ids:
            await session.execute(
                text(
                    "DELETE FROM knowledge_space_scope WHERE space_id IN ("
                    + ",".join(str(int(i)) for i in space_ids)
                    + ")"
                )
            )
            await session.execute(
                text("DELETE FROM knowledge WHERE id IN (" + ",".join(str(int(i)) for i in space_ids) + ")")
            )
        if user_ids:
            await session.execute(
                text("DELETE FROM user WHERE user_id IN (" + ",".join(str(int(i)) for i in user_ids) + ")")
            )
        await session.commit()


async def _point_counts(engine, user_id: int) -> tuple[int, int]:
    logs = await _select(
        engine,
        "SELECT COUNT(*) AS n FROM user_point_log WHERE user_id = :uid",
        {"uid": user_id},
    )
    pending = await _select(
        engine,
        "SELECT COUNT(*) AS n FROM point_pending_deduct WHERE user_id = :uid",
        {"uid": user_id},
    )
    return int(logs[0]["n"]), int(pending[0]["n"])


@pytest.mark.asyncio
async def test_list_keeps_only_abnormal_source_files_and_hides_names_from_strangers(flow_env):
    engine = flow_env
    token = uuid.uuid4().hex[:10]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-up-{token}")
        operator = await _insert_user(session, f"au-op-{token}")
        stranger = await _insert_user(session, f"au-st-{token}")
        space_id = await _insert_space(session, name=f"au-space-{token}", level="department")
        failed_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-up-{token}",
            space_id=space_id,
            file_name=f"au-failed-{token}.pdf",
            status=3,
            remark="parser blew up",
        )
        timeout_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-up-{token}",
            space_id=space_id,
            file_name=f"au-timeout-{token}.pdf",
            status=6,
            entry_type="manager",
        )
        hidden_share = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-up-{token}",
            space_id=space_id,
            file_name=f"au-share-{token}.pdf",
            status=3,
            entry_type="share",
        )
        hidden_ok = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-up-{token}",
            space_id=space_id,
            file_name=f"au-ok-{token}.pdf",
            status=2,
        )
    file_ids = [failed_id, timeout_id, hidden_share, hidden_ok]
    try:
        denied = _app(_operator(stranger, name=f"au-st-{token}", role_names=["管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=denied), base_url="http://test") as client:
            response = await client.get(PREFIX, params={"page": 1, "page_size": 100})
        assert response.status_code == 200
        body = response.json()
        assert body["status_code"] == 403
        assert f"au-failed-{token}.pdf" not in response.text

        allowed = _app(_operator(operator, name=f"au-op-{token}", role_names=["平台管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=allowed), base_url="http://test") as client:
            listed = await client.get(PREFIX, params={"page": 1, "page_size": 100})
            oversized = await client.get(PREFIX, params={"page": 1, "page_size": 101})
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["status_code"] == 200
        names = {item["file_name"] for item in payload["data"]["data"]}
        assert f"au-failed-{token}.pdf" in names
        assert f"au-timeout-{token}.pdf" in names
        assert f"au-share-{token}.pdf" not in names
        assert f"au-ok-{token}.pdf" not in names
        failed_row = next(item for item in payload["data"]["data"] if item["file_id"] == failed_id)
        assert failed_row["knowledge_name"] == f"au-space-{token}"
        assert failed_row["space_level"] == "department"
        assert failed_row["uploader_name"] == f"au-up-{token}"
        assert "object_name" not in failed_row
        assert oversized.json()["status_code"] == 422
    finally:
        await _cleanup(engine, user_ids=[uploader, operator, stranger], space_ids=[space_id], file_ids=file_ids)


@pytest.mark.asyncio
async def test_retry_moves_file_to_waiting_and_second_click_does_not_enqueue(flow_env, monkeypatch):
    engine = flow_env
    token = uuid.uuid4().hex[:10]
    calls: list[int] = []

    async def _dispatch(**kwargs):
        calls.append(int(kwargs["file_id"]))
        return "ticket"

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.abnormal_upload_service.dispatch_knowledge_parse_task",
        _dispatch,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-rup-{token}")
        operator = await _insert_user(session, f"au-rop-{token}")
        space_id = await _insert_space(session, name=f"au-rspace-{token}", level="personal")
        file_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-rup-{token}",
            space_id=space_id,
            file_name=f"au-retry-{token}.pdf",
            status=7,
            remark='{"reason":"sensitive_check","hits":[]}',
        )
    try:
        app = _app(_operator(operator, name=f"au-rop-{token}", super_admin=True), engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(f"{PREFIX}/{file_id}/retry")
            second = await client.post(f"{PREFIX}/{file_id}/retry")
        assert first.status_code == 200
        assert first.json()["status_code"] == 200
        assert first.json()["status_message"] == "已开始重新解析"
        rows = await _select(engine, "SELECT status, remark FROM knowledgefile WHERE id = :id", {"id": file_id})
        assert int(rows[0]["status"]) == 5
        assert rows[0]["remark"] in ("", None)
        assert calls == [file_id]
        assert second.json()["status_code"] == 18055
        assert calls == [file_id]
        rows = await _select(engine, "SELECT status FROM knowledgefile WHERE id = :id", {"id": file_id})
        assert int(rows[0]["status"]) == 5
    finally:
        await _cleanup(engine, user_ids=[uploader, operator], space_ids=[space_id], file_ids=[file_id])


@pytest.mark.asyncio
async def test_retry_failure_restores_previous_status(flow_env, monkeypatch):
    engine = flow_env
    token = uuid.uuid4().hex[:10]

    async def _dispatch(**_kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.abnormal_upload_service.dispatch_knowledge_parse_task",
        _dispatch,
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-fup-{token}")
        operator = await _insert_user(session, f"au-fop-{token}")
        space_id = await _insert_space(session, name=f"au-fspace-{token}", level="team_ks")
        file_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-fup-{token}",
            space_id=space_id,
            file_name=f"au-restore-{token}.pdf",
            status=3,
            remark="parser blew up",
        )
    try:
        app = _app(_operator(operator, name=f"au-fop-{token}", role_names=["平台管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"{PREFIX}/{file_id}/retry")
        assert response.json()["status_code"] == 18056
        rows = await _select(engine, "SELECT status, remark FROM knowledgefile WHERE id = :id", {"id": file_id})
        assert int(rows[0]["status"]) == 3
        assert rows[0]["remark"] == "parser blew up"
    finally:
        await _cleanup(engine, user_ids=[uploader, operator], space_ids=[space_id], file_ids=[file_id])


@pytest.mark.asyncio
async def test_delete_recycles_without_points_and_second_delete_is_gone(flow_env):
    engine = flow_env
    token = uuid.uuid4().hex[:10]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-dup-{token}")
        operator = await _insert_user(session, f"au-dop-{token}")
        space_id = await _insert_space(session, name=f"au-dspace-{token}", level="team")
        file_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-dup-{token}",
            space_id=space_id,
            file_name=f"au-delete-{token}.pdf",
            status=6,
        )
    before_logs, before_pending = await _point_counts(engine, uploader)
    try:
        app = _app(_operator(operator, name=f"au-dop-{token}", role_names=["平台管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post(f"{PREFIX}/{file_id}/delete")
            second = await client.post(f"{PREFIX}/{file_id}/delete")
        assert first.status_code == 200, first.text
        assert first.json()["status_code"] == 200, first.text
        assert first.json()["status_message"] == "已删除"
        rows = await _select(engine, "SELECT deleted_at, status FROM knowledgefile WHERE id = :id", {"id": file_id})
        assert rows[0]["deleted_at"] is not None
        recycle = await _select(
            engine,
            "SELECT id FROM knowledge_recycle_item WHERE file_id = :id",
            {"id": file_id},
        )
        assert len(recycle) == 1
        after_logs, after_pending = await _point_counts(engine, uploader)
        assert after_logs == before_logs
        assert after_pending == before_pending
        assert second.json()["status_code"] == 18020
        recycle_again = await _select(
            engine,
            "SELECT id FROM knowledge_recycle_item WHERE file_id = :id",
            {"id": file_id},
        )
        assert len(recycle_again) == 1
    finally:
        await _cleanup(engine, user_ids=[uploader, operator], space_ids=[space_id], file_ids=[file_id])


@pytest.mark.asyncio
async def test_list_filters_status_level_and_keyword(flow_env):
    engine = flow_env
    token = uuid.uuid4().hex[:10]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-fup-{token}")
        operator = await _insert_user(session, f"au-fop-{token}")
        dept_id = await _insert_space(session, name=f"au-dept-{token}", level="department")
        personal_id = await _insert_space(session, name=f"au-person-{token}", level="personal")
        apple_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-fup-{token}",
            space_id=dept_id,
            file_name=f"apple-{token}.pdf",
            status=3,
        )
        timeout_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-fup-{token}",
            space_id=dept_id,
            file_name=f"timeout-{token}.pdf",
            status=6,
        )
        banana_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-alt-{token}",
            space_id=personal_id,
            file_name=f"banana-{token}.pdf",
            status=3,
        )
        await _set_update_time(session, apple_id, "2019-03-01 12:00:00")
        await _set_update_time(session, timeout_id, "2019-03-02 08:00:00")
        await _set_update_time(session, banana_id, "2019-03-10 18:00:00")
    file_ids = [apple_id, timeout_id, banana_id]
    apple_name = f"apple-{token}.pdf"
    timeout_name = f"timeout-{token}.pdf"
    banana_name = f"banana-{token}.pdf"

    def names(response) -> set[str]:
        return {item["file_name"] for item in response.json()["data"]["data"]}

    try:
        app = _app(_operator(operator, name=f"au-fop-{token}", role_names=["平台管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            failed = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "status": 3, "knowledge_name": f"au-dept-{token}"},
            )
            failed_person = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "status": 3, "knowledge_name": f"au-person-{token}"},
            )
            personal = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "space_level": "personal", "keyword": banana_name},
            )
            personal_apple = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "space_level": "personal", "keyword": apple_name},
            )
            keyword = await client.get(PREFIX, params={"page": 1, "page_size": 100, "keyword": f"apple-{token}"})
            keyword_space = await client.get(
                PREFIX, params={"page": 1, "page_size": 100, "keyword": f"au-dept-{token}"}
            )
            keyword_uploader = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "keyword": f"au-fup-{token}"},
            )
            knowledge = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "knowledge_name": f"au-dept-{token}"},
            )
            uploader_filter = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 100, "uploader_name": f"au-alt-{token}"},
            )
            both = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 100,
                    "status": 3,
                    "space_level": "department",
                    "knowledge_name": f"au-dept-{token}",
                },
            )
            combined = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 100,
                    "keyword": f"timeout-{token}",
                    "knowledge_name": f"au-dept-{token}",
                },
            )
            date_range = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 100,
                    "knowledge_name": f"au-dept-{token}",
                    "update_time_from": "2019-03-01",
                    "update_time_to": "2019-03-02",
                },
            )
            date_from = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 100,
                    "knowledge_name": f"au-person-{token}",
                    "update_time_from": "2019-03-10",
                },
            )
            date_to = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 100,
                    "knowledge_name": f"au-dept-{token}",
                    "update_time_to": "2019-03-01",
                },
            )
            inverted = await client.get(
                PREFIX,
                params={
                    "page": 1,
                    "page_size": 20,
                    "update_time_from": "2019-03-10",
                    "update_time_to": "2019-03-01",
                },
            )
            bad_date = await client.get(
                PREFIX,
                params={"page": 1, "page_size": 20, "update_time_from": "2019/03/01"},
            )
            bad_status = await client.get(PREFIX, params={"page": 1, "page_size": 20, "status": 2})
            bad_level = await client.get(PREFIX, params={"page": 1, "page_size": 20, "space_level": "other"})
        assert names(failed) == {apple_name}
        assert names(failed_person) == {banana_name}
        assert names(personal) == {banana_name}
        assert names(personal_apple) == set()
        assert names(keyword) == {apple_name}
        assert apple_name not in names(keyword_space)
        assert timeout_name not in names(keyword_space)
        assert apple_name not in names(keyword_uploader)
        assert timeout_name not in names(keyword_uploader)
        assert names(knowledge) == {apple_name, timeout_name}
        assert names(uploader_filter) == {banana_name}
        assert names(both) == {apple_name}
        assert names(combined) == {timeout_name}
        assert names(date_range) == {apple_name, timeout_name}
        assert names(date_from) == {banana_name}
        assert names(date_to) == {apple_name}
        assert inverted.json()["status_code"] == 422
        assert bad_date.json()["status_code"] == 422
        assert bad_status.json()["status_code"] == 422
        assert bad_level.json()["status_code"] == 422
    finally:
        await _cleanup(
            engine,
            user_ids=[uploader, operator],
            space_ids=[dept_id, personal_id],
            file_ids=file_ids,
        )


@pytest.mark.asyncio
async def test_batch_delete_partial_success_does_not_deduct_or_repeat(flow_env):
    engine = flow_env
    token = uuid.uuid4().hex[:10]
    async with AsyncSession(engine, expire_on_commit=False) as session:
        uploader = await _insert_user(session, f"au-bup-{token}")
        operator = await _insert_user(session, f"au-bop-{token}")
        space_id = await _insert_space(session, name=f"au-bspace-{token}", level="public")
        first_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-bup-{token}",
            space_id=space_id,
            file_name=f"au-batch-a-{token}.pdf",
            status=3,
        )
        second_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-bup-{token}",
            space_id=space_id,
            file_name=f"au-batch-b-{token}.pdf",
            status=6,
        )
        third_id = await _insert_file(
            session,
            user_id=uploader,
            user_name=f"au-bup-{token}",
            space_id=space_id,
            file_name=f"au-batch-c-{token}.pdf",
            status=7,
        )
    before_logs, before_pending = await _point_counts(engine, uploader)
    try:
        app = _app(_operator(operator, name=f"au-bop-{token}", role_names=["平台管理员"]), engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            empty = await client.post(f"{PREFIX}/delete-batch", json={"file_ids": []})
            oversized = await client.post(
                f"{PREFIX}/delete-batch",
                json={"file_ids": list(range(1, 102))},
            )
            first = await client.post(f"{PREFIX}/delete-batch", json={"file_ids": [first_id, second_id]})
            partial = await client.post(f"{PREFIX}/delete-batch", json={"file_ids": [first_id, third_id]})
            again = await client.post(f"{PREFIX}/delete-batch", json={"file_ids": [first_id, second_id, third_id]})
        assert empty.json()["status_code"] == 422
        assert oversized.json()["status_code"] == 422
        assert first.json()["status_code"] == 200
        assert first.json()["status_message"] == "已删除 2 条"
        assert first.json()["data"] == {"deleted": 2, "failed": 0}
        assert partial.json()["status_message"] == "已删除 1 条，1 条未删除"  # noqa: RUF001
        assert partial.json()["data"] == {"deleted": 1, "failed": 1}
        assert again.json()["status_message"] == "已删除 0 条，3 条未删除"  # noqa: RUF001
        ids = _id_list([first_id, second_id, third_id])
        rows = await _select(
            engine,
            f"SELECT id, deleted_at FROM knowledgefile WHERE id IN ({ids})",
        )
        deleted_map = {int(row["id"]): row["deleted_at"] for row in rows}
        assert deleted_map[first_id] is not None
        assert deleted_map[second_id] is not None
        assert deleted_map[third_id] is not None
        recycle = await _select(
            engine,
            f"SELECT file_id FROM knowledge_recycle_item WHERE file_id IN ({ids})",
        )
        assert {int(row["file_id"]) for row in recycle} == {first_id, second_id, third_id}
        after_logs, after_pending = await _point_counts(engine, uploader)
        assert after_logs == before_logs
        assert after_pending == before_pending
    finally:
        await _cleanup(
            engine,
            user_ids=[uploader, operator],
            space_ids=[space_id],
            file_ids=[first_id, second_id, third_id],
        )
