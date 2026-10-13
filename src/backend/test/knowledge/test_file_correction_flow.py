"""文档纠错: 171 MySQL 接口, 落库, 再打一枪."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
import contextvars
from types import SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.api.endpoints.knowledge_file_correction import router as correction_router
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.permission.domain.services.permission_service import PermissionService

_allowed_files: contextvars.ContextVar[set[int] | None] = contextvars.ContextVar(
    "fc_allowed_files",
    default=None,
)


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


def _user(user_id: int, *, admin: bool = False, name: str = "fc-user"):
    return SimpleNamespace(
        user_id=user_id,
        user_name=name,
        tenant_id=1,
        is_admin=lambda: admin,
        is_global_super=False,
        role="admin" if admin else "user",
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
            # 调用方显式 commit. 这里不额外提交.
        finally:
            await session.close()

    for target in (
        "bisheng.knowledge.domain.services.knowledge_file_correction_service.get_async_db_session",
        "bisheng.points.domain.services.points_award_hooks.get_async_db_session",
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        "bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session",
        "bisheng.approval.domain.repositories.user_menu_access_repository.get_async_db_session",
    ):
        monkeypatch.setattr(target, patched_session)
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_award_hooks._award_async_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_award_facade.PointsAwardFacade._is_enabled",
        lambda self: True,
    )

    async def _no_space_managers(*_space_ids: int) -> frozenset[int]:
        return frozenset()

    monkeypatch.setattr(
        "bisheng.points.domain.services.points_award_hooks.resolve_space_manager_ids",
        _no_space_managers,
    )

    async def _check(user_id, relation, object_type, object_id, login_user=None):
        allowed = _allowed_files.get()
        if allowed is None:
            return True
        return int(object_id) in allowed

    monkeypatch.setattr(PermissionService, "check", _check)

    async def _noop_notify(cls, **kwargs):
        return None

    async def _detail(cls, **kwargs):
        return {"status": "ok", "instance_id": kwargs.get("instance_id")}

    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    monkeypatch.setattr(ApprovalCenterService, "_send_approval_notify", classmethod(_noop_notify))
    monkeypatch.setattr(ApprovalCenterService, "get_instance_detail", classmethod(_detail))
    yield engine
    await engine.dispose()


def _app(user, allowed_files: set[int] | None = None) -> FastAPI:
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
    app.include_router(correction_router, prefix="/api/v1")

    from bisheng.approval.api.endpoints.approval_user import router as approval_router

    app.include_router(approval_router, prefix="/api/v1")
    _allowed_files.set(allowed_files)
    return app


async def _insert_user(session: AsyncSession, name: str, *, disabled: bool = False) -> int:
    await session.execute(
        text("INSERT INTO user (user_name, password, `delete`) VALUES (:n, 'x', :d)"),
        {"n": name, "d": 1 if disabled else 0},
    )
    await session.commit()
    return int((await session.execute(text("SELECT user_id FROM user WHERE user_name = :n"), {"n": name})).scalar_one())


async def _insert_space(session: AsyncSession, *, name: str, level: str, favorite: bool = False) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledge
              (user_id, name, type, tenant_id, is_released, is_favorite, auth_type)
            VALUES (1, :name, :type, 1, 0, :fav, 'PRIVATE')
            """
        ),
        {"name": name, "type": KnowledgeTypeEnum.SPACE.value, "fav": 1 if favorite else 0},
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


async def _insert_file(
    session: AsyncSession,
    *,
    space_id: int,
    name: str,
    user_id: int | None,
    tenant_id: int = 1,
    object_name: str = "obj-fc",
) -> int:
    await session.execute(
        text(
            """
            INSERT INTO knowledgefile
              (user_id, knowledge_id, file_name, file_type, tenant_id, object_name)
            VALUES (:uid, :kid, :name, 1, :tid, :obj)
            """
        ),
        {"uid": user_id, "kid": space_id, "name": name, "tid": tenant_id, "obj": object_name},
    )
    await session.commit()
    return int(
        (
            await session.execute(
                text("SELECT id FROM knowledgefile WHERE file_name = :n AND knowledge_id = :k"),
                {"n": name, "k": space_id},
            )
        ).scalar_one()
    )


async def _cleanup(engine, *, user_ids: list[int], space_ids: list[int], file_ids: list[int]) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        for file_id in file_ids:
            await session.execute(text("DELETE FROM knowledge_file_correction_open WHERE file_id = :id"), {"id": file_id})
            await session.execute(text("DELETE FROM knowledge_file_correction_award WHERE file_id = :id"), {"id": file_id})
            rows = (
                await session.execute(
                    text("SELECT approval_instance_id FROM knowledge_file_correction WHERE file_id = :id"),
                    {"id": file_id},
                )
            ).all()
            await session.execute(text("DELETE FROM knowledge_file_correction WHERE file_id = :id"), {"id": file_id})
            for row in rows:
                instance_id = row[0]
                if instance_id:
                    await session.execute(text("DELETE FROM approval_task WHERE instance_id = :id"), {"id": instance_id})
                    await session.execute(
                        text("DELETE FROM approval_action_log WHERE instance_id = :id"),
                        {"id": instance_id},
                    )
                    await session.execute(text("DELETE FROM approval_instance WHERE id = :id"), {"id": instance_id})
            await session.execute(text("DELETE FROM knowledgefile WHERE id = :id"), {"id": file_id})
        for space_id in space_ids:
            await session.execute(text("DELETE FROM knowledge_space_scope WHERE space_id = :id"), {"id": space_id})
            await session.execute(text("DELETE FROM knowledge WHERE id = :id"), {"id": space_id})
        for user_id in user_ids:
            await session.execute(
                text("DELETE FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                {"id": user_id},
            )
            await session.execute(text("DELETE FROM user_point_account WHERE user_id = :id"), {"id": user_id})
            await session.execute(text("DELETE FROM user WHERE user_id = :id"), {"id": user_id})
        await session.commit()


def _body(response) -> dict:
    return response.json()


async def _submit(client: AsyncClient, file_id: int, content: str = "这里有一个错字"):
    return await client.post(f"/api/v1/knowledge/files/{file_id}/corrections", json={"content": content})


@pytest.mark.asyncio
async def test_submit_approve_points_and_second_pass_mysql(flow_env):
    """FC-01/02/23/25: 提交后待办出现且不加分; 通过后入账; 再通过不加分; 正文不进快照."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            applicant = await _insert_user(session, f"fc-reader-{suffix}")
            uploader = await _insert_user(session, f"fc-up-{suffix}")
            user_ids.extend([applicant, uploader])
            space_id = await _insert_space(session, name=f"fc-dept-{suffix}", level="department")
            space_ids.append(space_id)
            file_id = await _insert_file(
                session,
                space_id=space_id,
                name=f"fc-doc-{suffix}.txt",
                user_id=uploader,
                object_name=f"obj-{suffix}",
            )
            file_ids.append(file_id)
        async with AsyncClient(transport=ASGITransport(app=_app(_user(applicant, name="reader"))), base_url="http://test") as client:
            created = _body(await _submit(client, file_id))
            assert created["status_code"] == 200, created
            correction_id = created["data"]["correction_id"]
            task_id = created["data"]["task_id"]
            again = _body(await _submit(client, file_id, "另一处错误"))
            assert again["status_code"] == 18406
            visible = _body(await client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
            assert visible["status_code"] == 200
            assert visible["data"]["content"] == "这里有一个错字"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            open_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_file_correction_open WHERE file_id = :id"),
                    {"id": file_id},
                )
            ).scalar_one()
            point_count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": applicant},
                )
            ).scalar_one()
            snapshot = (
                await session.execute(
                    text(
                        """
                        SELECT payload_snapshot FROM approval_instance
                        WHERE id = :id
                        """
                    ),
                    {"id": created["data"]["instance_id"]},
                )
            ).scalar_one()
            assert int(open_count) == 1
            assert int(point_count) == 0
            assert "这里有一个错字" not in str(snapshot)
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            tasks = _body(await up_client.get("/api/v1/approval/my-tasks"))
            assert tasks["status_code"] == 200
            assert any(item.get("id") == task_id or item.get("task_id") == task_id for item in tasks["data"]["data"])
            approved = _body(
                await up_client.post(f"/api/v1/approval/tasks/{task_id}/decision", json={"action": "approve"})
            )
            assert approved["status_code"] == 200, approved
            replay = _body(
                await up_client.post(f"/api/v1/approval/tasks/{task_id}/decision", json={"action": "approve"})
            )
            assert replay["status_code"] == 18102
        async with AsyncSession(engine, expire_on_commit=False) as session:
            status = (
                await session.execute(
                    text("SELECT status FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            instance_status = (
                await session.execute(
                    text("SELECT status FROM approval_instance WHERE id = :id"),
                    {"id": created["data"]["instance_id"]},
                )
            ).scalar_one()
            obj = (
                await session.execute(text("SELECT object_name FROM knowledgefile WHERE id = :id"), {"id": file_id})
            ).scalar_one()
            logs = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": applicant},
                )
            ).scalar_one()
            award = (
                await session.execute(
                    text(
                        """
                        SELECT award_state FROM knowledge_file_correction_award
                        WHERE correction_id = :id
                        """
                    ),
                    {"id": correction_id},
                )
            ).scalar_one()
            assert status == "approved"
            assert instance_status == "approved"
            assert obj == f"obj-{suffix}"
            assert int(logs) == 1
            assert award == "awarded"
        async with AsyncClient(transport=ASGITransport(app=_app(_user(applicant, name="reader"))), base_url="http://test") as client:
            second = _body(await _submit(client, file_id, "通过后再提一条"))
            assert second["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            approved2 = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{second['data']['task_id']}/decision",
                    json={"action": "approve"},
                )
            )
            assert approved2["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            logs = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": applicant},
                )
            ).scalar_one()
            assert int(logs) == 1
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_submit_rejections_mysql(flow_env):
    """FC-03/04/05/15/16: 本人, 停用上传人, 字数, 无权查看, 个人库和收藏库都拒绝且不留单."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-r2-{suffix}")
            owner = await _insert_user(session, f"fc-o2-{suffix}")
            disabled = await _insert_user(session, f"fc-dis-{suffix}", disabled=True)
            user_ids.extend([reader, owner, disabled])
            dept = await _insert_space(session, name=f"fc-d2-{suffix}", level="department")
            personal = await _insert_space(session, name=f"fc-p2-{suffix}", level="personal")
            favorite = await _insert_space(session, name=f"fc-f2-{suffix}", level="public", favorite=True)
            public = await _insert_space(session, name=f"fc-pub2-{suffix}", level="public")
            space_ids.extend([dept, personal, favorite, public])
            own = await _insert_file(session, space_id=dept, name=f"own-{suffix}", user_id=reader)
            gone = await _insert_file(session, space_id=dept, name=f"gone-{suffix}", user_id=disabled)
            ok = await _insert_file(session, space_id=dept, name=f"ok-{suffix}", user_id=owner)
            hidden = await _insert_file(session, space_id=dept, name=f"hid-{suffix}", user_id=owner)
            per = await _insert_file(session, space_id=personal, name=f"per-{suffix}", user_id=owner)
            fav = await _insert_file(session, space_id=favorite, name=f"fav-{suffix}", user_id=owner)
            pub = await _insert_file(session, space_id=public, name=f"pub-{suffix}", user_id=owner)
            file_ids.extend([own, gone, ok, hidden, per, fav, pub])
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(reader), allowed_files={own, gone, ok, per, fav})),
            base_url="http://test",
        ) as client:
            assert _body(await _submit(client, own))["status_code"] == 18402
            assert _body(await _submit(client, gone))["status_code"] == 18403
            assert _body(await _submit(client, ok, "  "))["status_code"] == 18400
            assert _body(await _submit(client, ok, "错" * 501))["status_code"] == 18401
            created = _body(await _submit(client, ok, "错" * 500))
            assert created["status_code"] == 200
            assert _body(await _submit(client, hidden))["status_code"] == 18405
            assert _body(await _submit(client, per))["status_code"] == 18404
            assert _body(await _submit(client, fav))["status_code"] == 18404
            # 公共库没有文件级 view_file 时, 登录读者仍可提交. pub 不在 allowed_files 里.
            opened = _body(await _submit(client, pub, "公共库也能纠"))
            assert opened["status_code"] == 200, opened
            stranger = _body(await client.get("/api/v1/knowledge/file-corrections/999999999"))
            assert stranger["status_code"] == 18407
        async with AsyncSession(engine, expire_on_commit=False) as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id"),
                    {"id": ok},
                )
            ).scalar_one()
            assert int(count) == 1
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_reject_withdraw_admin_and_levels_mysql(flow_env):
    """FC-07/09/10/22: 代批拒绝, 无原因不改状态, 拒绝后可再交, 撤回可再交, 三种库可提交."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-r3-{suffix}")
            uploader = await _insert_user(session, f"fc-u3-{suffix}")
            admin = await _insert_user(session, f"fc-a3-{suffix}")
            user_ids.extend([reader, uploader, admin])
            dept = await _insert_space(session, name=f"fc-d3-{suffix}", level="department")
            public = await _insert_space(session, name=f"fc-pub-{suffix}", level="public")
            team = await _insert_space(session, name=f"fc-team-{suffix}", level="team")
            clinic = await _insert_space(session, name=f"fc-ks-{suffix}", level="team_ks")
            space_ids.extend([dept, public, team, clinic])
            file_id = await _insert_file(session, space_id=dept, name=f"main-{suffix}", user_id=uploader)
            file_ids.append(file_id)
            for level_space, label in ((public, "pub"), (team, "team"), (clinic, "ks")):
                file_ids.append(
                    await _insert_file(session, space_id=level_space, name=f"{label}-{suffix}", user_id=uploader)
                )
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, file_id))
            assert created["status_code"] == 200
            for extra in file_ids[1:]:
                assert _body(await _submit(client, extra, f"层级{extra}"))["status_code"] == 200
        task_id = created["data"]["task_id"]
        instance_id = created["data"]["instance_id"]
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(admin, admin=True, name="admin"))),
            base_url="http://test",
        ) as admin_client:
            denied = _body(await admin_client.post(f"/api/v1/approval/tasks/{task_id}/decision", json={"action": "approve"}))
            assert denied["status_code"] == 18408
            outsider = _body(await admin_client.get(f"/api/v1/knowledge/file-corrections/{created['data']['correction_id']}"))
            assert outsider["status_code"] == 18407
            assert outsider["data"] is None or "content" not in (outsider["data"] or {})
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            missing = _body(await up_client.post(f"/api/v1/approval/tasks/{task_id}/decision", json={"action": "reject"}))
            assert missing["status_code"] == 18103
            rejected = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{task_id}/decision",
                    json={"action": "reject", "comment": "不成立"},
                )
            )
            assert rejected["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            points = (
                await session.execute(
                    text("SELECT COUNT(*) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": reader},
                )
            ).scalar_one()
            assert int(points) == 0
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            again = _body(await _submit(client, file_id, "拒绝后再提"))
            assert again["status_code"] == 200
            withdrawn = _body(await client.post(f"/api/v1/approval/instances/{again['data']['instance_id']}/withdraw", json={}))
            assert withdrawn["status_code"] == 200, withdrawn
            third = _body(await _submit(client, file_id, "撤回后再提"))
            assert third["status_code"] == 200
        assert instance_id
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_cap_super_admin_rule_disabled_and_cancel_mysql(flow_env, monkeypatch):
    """FC-11/12/18/19/21: 日满, 超管, 规则停用都通过但不入账; 删除取消待处理; 重放不加流水."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-r4-{suffix}")
            uploader = await _insert_user(session, f"fc-u4-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-d4-{suffix}", level="department")
            space_ids.append(space_id)
            capped = await _insert_file(session, space_id=space_id, name=f"cap-{suffix}", user_id=uploader)
            pending = await _insert_file(session, space_id=space_id, name=f"pend-{suffix}", user_id=uploader)
            file_ids.extend([capped, pending])
            await session.execute(
                text(
                    """
                    INSERT INTO user_point_log
                      (tenant_id, user_id, delta, balance_after, direction, rule_code, title, source,
                       idempotency_key, occurred_at, create_time)
                    VALUES
                      (1, :uid, 15, 15, 'earn', 'G8', 'seed', 'auto', :key, NOW(), NOW())
                    """
                ),
                {"uid": reader, "key": f"seed-g8-{suffix}"},
            )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, capped, "已满当日"))
            waiting = _body(await _submit(client, pending, "待删除"))
            assert created["status_code"] == 200
            assert waiting["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            approved = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{created['data']['task_id']}/decision",
                    json={"action": "approve"},
                )
            )
            assert approved["status_code"] == 200
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            second = _body(await _submit(client, capped, "同一天再采纳"))
            assert second["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            second_approved = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{second['data']['task_id']}/decision",
                    json={"action": "adopt"},
                )
            )
            assert second_approved["status_code"] == 200
        async with AsyncSession(engine, expire_on_commit=False) as session:
            state = (
                await session.execute(
                    text(
                        """
                        SELECT award_state FROM knowledge_file_correction_award
                        WHERE correction_id = :id
                        """
                    ),
                    {"id": second["data"]["correction_id"]},
                )
            ).scalar_one()
            logs = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(delta), 0) FROM user_point_log
                        WHERE user_id = :id AND rule_code = 'G8' AND idempotency_key <> :key
                        """
                    ),
                    {"id": reader, "key": f"seed-g8-{suffix}"},
                )
            ).scalar_one()
            assert state == "skipped"
            assert int(logs) == 1
        from bisheng.knowledge.domain.services.knowledge_file_correction_service import (
            cancel_pending_file_corrections,
        )

        await cancel_pending_file_corrections([pending])
        async with AsyncSession(engine, expire_on_commit=False) as session:
            status = (
                await session.execute(
                    text("SELECT status FROM knowledge_file_correction WHERE file_id = :id"),
                    {"id": pending},
                )
            ).scalar_one()
            assert status == "cancelled"

        async def _super(_user_id: int) -> bool:
            return int(_user_id) == reader

        monkeypatch.setattr(
            "bisheng.points.domain.services.points_award_hooks.is_platform_super_admin_user",
            _super,
        )
        super_file = None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                text("DELETE FROM user_point_log WHERE user_id = :id AND idempotency_key = :key"),
                {"id": reader, "key": f"seed-g8-{suffix}"},
            )
            await session.execute(
                text("DELETE FROM knowledge_file_correction_award WHERE applicant_user_id = :id"),
                {"id": reader},
            )
            super_file = await _insert_file(session, space_id=space_id, name=f"super-{suffix}", user_id=uploader)
            file_ids.append(super_file)
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            super_created = _body(await _submit(client, super_file, "超管反馈"))
            assert super_created["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            assert (
                _body(
                    await up_client.post(
                        f"/api/v1/approval/tasks/{super_created['data']['task_id']}/decision",
                        json={"action": "approve"},
                    )
                )["status_code"]
                == 200
            )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            state = (
                await session.execute(
                    text("SELECT award_state FROM knowledge_file_correction_award WHERE file_id = :f"),
                    {"f": super_file},
                )
            ).scalar_one()
            assert state == "skipped"
            await session.execute(text("UPDATE point_rule SET status = 'disabled' WHERE rule_code = 'G8' AND tenant_id = 1"))
            await session.execute(
                text("DELETE FROM knowledge_file_correction_award WHERE file_id = :f"),
                {"f": super_file},
            )
            await session.commit()
        async def _not_super(_user_id: int) -> bool:
            return False

        monkeypatch.setattr(
            "bisheng.points.domain.services.points_award_hooks.is_platform_super_admin_user",
            _not_super,
        )
        disabled_file = None
        async with AsyncSession(engine, expire_on_commit=False) as session:
            disabled_file = await _insert_file(session, space_id=space_id, name=f"off-{suffix}", user_id=uploader)
            file_ids.append(disabled_file)
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            off = _body(await _submit(client, disabled_file, "规则停用"))
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            assert (
                _body(
                    await up_client.post(
                        f"/api/v1/approval/tasks/{off['data']['task_id']}/decision",
                        json={"action": "approve"},
                    )
                )["status_code"]
                == 200
            )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            state = (
                await session.execute(
                    text("SELECT award_state FROM knowledge_file_correction_award WHERE file_id = :f"),
                    {"f": disabled_file},
                )
            ).scalar_one()
            assert state == "skipped"
            await session.execute(text("UPDATE point_rule SET status = 'enabled' WHERE rule_code = 'G8' AND tenant_id = 1"))
            await session.commit()
        from bisheng.points.domain.services.points_award_hooks import notify_file_correction_adopted

        await notify_file_correction_adopted(
            tenant_id=1,
            file_id=int(capped),
            applicant_user_id=int(reader),
            correction_id=int(created["data"]["correction_id"]),
            award_kind="adopt",
            delta=1,
        )
        await notify_file_correction_adopted(
            tenant_id=1,
            file_id=int(capped),
            applicant_user_id=int(reader),
            correction_id=int(created["data"]["correction_id"]),
            award_kind="adopt",
            delta=1,
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            logs = (
                await session.execute(
                    text("SELECT COUNT(*) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8' AND title <> 'seed'"),
                    {"id": reader},
                )
            ).scalar_one()
            assert int(logs) <= 1
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("UPDATE point_rule SET status = 'enabled' WHERE rule_code = 'G8' AND tenant_id = 1"))
            await session.commit()
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_concurrent_submit_mysql(flow_env):
    """FC-13: 同一人同时提交同一文档, 只有一条待处理."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-r5-{suffix}")
            uploader = await _insert_user(session, f"fc-u5-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-d5-{suffix}", level="department")
            space_ids.append(space_id)
            file_id = await _insert_file(session, space_id=space_id, name=f"race-{suffix}", user_id=uploader)
            file_ids.append(file_id)

        async def _one(text_value: str):
            async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
                return _body(await _submit(client, file_id, text_value))

        first, second = await asyncio.gather(_one("并发甲"), _one("并发乙"))
        codes = sorted([first["status_code"], second["status_code"]])
        assert codes == [200, 18406]
        async with AsyncSession(engine, expire_on_commit=False) as session:
            count = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id AND status = 'pending'"),
                    {"id": file_id},
                )
            ).scalar_one()
            assert int(count) == 1
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_adopt_update_pays_each_new_version_mysql(flow_env):
    """同一天同一文档两次采纳并更新, 各发 2 分, 新文件成为主版本."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-r6-{suffix}")
            uploader = await _insert_user(session, f"fc-u6-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-d6-{suffix}", level="department")
            space_ids.append(space_id)
            origin = await _insert_file(session, space_id=space_id, name=f"origin-{suffix}", user_id=uploader)
            newer = await _insert_file(session, space_id=space_id, name=f"new-{suffix}", user_id=uploader)
            newest = await _insert_file(session, space_id=space_id, name=f"newest-{suffix}", user_id=uploader)
            file_ids.extend([origin, newer, newest])
            await session.execute(
                text("UPDATE knowledgefile SET status = 2 WHERE id IN (:a, :b)"),
                {"a": newer, "b": newest},
            )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            first = _body(await _submit(client, origin, "第一处"))
            assert first["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            updated = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{first['data']['task_id']}/decision",
                    json={"action": "adopt_update", "new_file_id": newer},
                )
            )
            assert updated["status_code"] == 200, updated
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            second = _body(await _submit(client, origin, "第二处"))
            assert second["status_code"] == 200
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            updated2 = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{second['data']['task_id']}/decision",
                    json={"action": "adopt_update", "new_file_id": newest},
                )
            )
            assert updated2["status_code"] == 200, updated2
        async with AsyncSession(engine, expire_on_commit=False) as session:
            total = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": reader},
                )
            ).scalar_one()
            primary = (
                await session.execute(
                    text(
                        """
                        SELECT knowledge_file_id FROM knowledge_document_version
                        WHERE knowledge_file_id = :id AND is_primary = 1
                        """
                    ),
                    {"id": newest},
                )
            ).scalar_one()
            old_primary = (
                await session.execute(
                    text(
                        """
                        SELECT is_primary FROM knowledge_document_version
                        WHERE knowledge_file_id = :id
                        """
                    ),
                    {"id": origin},
                )
            ).scalar_one()
            awards = (
                await session.execute(
                    text(
                        """
                        SELECT award_kind, award_state FROM knowledge_file_correction_award
                        WHERE file_id = :id
                        ORDER BY id
                        """
                    ),
                    {"id": origin},
                )
            ).all()
            assert int(total) == 4
            assert int(primary) == newest
            assert int(old_primary) == 0
            assert [(str(kind), str(state)) for kind, state in awards] == [
                ("update", "awarded"),
                ("update", "awarded"),
            ]
            doc_ids = (
                await session.execute(
                    text(
                        """
                        SELECT document_id FROM knowledge_document_version
                        WHERE knowledge_file_id IN (:a, :b)
                        """
                    ),
                    {"a": origin, "b": newest},
                )
            ).all()
            await session.execute(
                text("DELETE FROM knowledge_document_version WHERE knowledge_file_id IN (:a, :b, :c)"),
                {"a": origin, "b": newer, "c": newest},
            )
            for row in {int(item[0]) for item in doc_ids}:
                await session.execute(text("DELETE FROM knowledge_document WHERE id = :id"), {"id": row})
            await session.commit()
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_g8_skips_library_owner_and_admin_mysql(flow_env, monkeypatch):
    """文档所在库的所有者或管理员作为反馈人时, 采纳成功但不发 G8."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-owner-{suffix}")
            uploader = await _insert_user(session, f"fc-up-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-own-{suffix}", level="public")
            space_ids.append(space_id)
            file_id = await _insert_file(session, space_id=space_id, name=f"ownlib-{suffix}", user_id=uploader)
            file_ids.append(file_id)

        async def _managers(*_space_ids: int) -> frozenset[int]:
            return frozenset({int(reader)})

        monkeypatch.setattr(
            "bisheng.points.domain.services.points_award_hooks.resolve_space_manager_ids",
            _managers,
        )
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, file_id, "库管反馈"))
            assert created["status_code"] == 200, created
        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
            base_url="http://test",
        ) as up_client:
            decided = _body(
                await up_client.post(
                    f"/api/v1/approval/tasks/{created['data']['task_id']}/decision",
                    json={"action": "adopt"},
                )
            )
            assert decided["status_code"] == 200, decided
        async with AsyncSession(engine, expire_on_commit=False) as session:
            state = (
                await session.execute(
                    text(
                        """
                        SELECT award_state FROM knowledge_file_correction_award
                        WHERE correction_id = :id
                        """
                    ),
                    {"id": created["data"]["correction_id"]},
                )
            ).scalar_one()
            total = (
                await session.execute(
                    text("SELECT COALESCE(SUM(delta), 0) FROM user_point_log WHERE user_id = :id AND rule_code = 'G8'"),
                    {"id": reader},
                )
            ).scalar_one()
            assert str(state) == "skipped"
            assert int(total) == 0
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_update_file_skips_ingest_points_and_copies_labels_mysql(flow_env, monkeypatch):
    """采纳并更新登记不记入库分, 并复制旧文件的分类、业务域和非自动标签. 同一路径并发只登记一次."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    calls: list[dict] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-ur-{suffix}")
            uploader = await _insert_user(session, f"fc-uu-{suffix}")
            user_ids.extend([reader, uploader])
            space_id = await _insert_space(session, name=f"fc-us-{suffix}", level="department")
            space_ids.append(space_id)
            origin = await _insert_file(session, space_id=space_id, name=f"old-{suffix}", user_id=uploader)
            file_ids.append(origin)
            await session.execute(
                text(
                    """
                    UPDATE knowledgefile
                    SET split_rule = :rule, file_subcategory_code = 'SUB', file_subcategory_source = 'manual'
                    WHERE id = :id
                    """
                ),
                {"id": origin, "rule": '{"file_category_code": "STD", "business_domain_code": "SC"}'},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO tag (name, business_type, business_id, user_id, tenant_id, resource_type)
                    VALUES ('手工标签', 'tag_library', '1', 1, 1, 'manual_tag'),
                           ('自动标签', 'tag_library', '1', 1, 1, 'ai_auto_tag')
                    """
                )
            )
            await session.commit()
            tag_rows = (
                await session.execute(
                    text("SELECT id FROM tag WHERE name IN ('手工标签', '自动标签')")
                )
            ).all()
            for tag_row in tag_rows:
                await session.execute(
                    text(
                        """
                        INSERT INTO taglink (tag_id, resource_id, resource_type, user_id, tenant_id)
                        VALUES (:tag, :file, 8, 1, 1)
                        """
                    ),
                    {"tag": int(tag_row[0]), "file": str(origin)},
                )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            created = _body(await _submit(client, origin, "带上分类"))
            assert created["status_code"] == 200, created
        correction_id = int(created["data"]["correction_id"])

        async def _fake_add(_request, _login_user, **kwargs):
            calls.append(kwargs)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                new_id = await _insert_file(
                    session,
                    space_id=space_id,
                    name=f"new-{suffix}-{uuid.uuid4().hex[:6]}",
                    user_id=uploader,
                )
            file_ids.append(new_id)
            return [SimpleNamespace(id=new_id, status=1, file_name=f"new-{suffix}")]

        monkeypatch.setattr(
            "bisheng.knowledge.domain.services.knowledge_file_correction_service._add_correction_file",
            _fake_add,
        )
        async def _once():
            async with AsyncClient(
                transport=ASGITransport(app=_app(_user(uploader, name="uploader"))),
                base_url="http://test",
            ) as client:
                return _body(
                    await client.post(
                        f"/api/v1/knowledge/file-corrections/{correction_id}/update-file",
                        json={"file_path": "tmp/same.pdf"},
                    )
                )

        first, second = await asyncio.gather(_once(), _once())
        bodies = [first, second]
        success = next(item for item in bodies if item["status_code"] == 200)
        rejected = next(item for item in bodies if item["status_code"] != 200)
        assert rejected["status_code"] == 18102, rejected
        assert len(calls) == 1
        assert calls[0]["award_points"] is False
        assert calls[0]["file_category_code"] == "STD"
        assert calls[0]["business_domain_code"] == "SC"
        assert calls[0]["file_subcategory_code"] == "SUB"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            copied = (
                await session.execute(
                    text(
                        """
                        SELECT t.resource_type
                        FROM taglink l JOIN tag t ON t.id = l.tag_id
                        WHERE l.resource_id = :id
                        """
                    ),
                    {"id": str(success["data"]["id"])},
                )
            ).all()
            kinds = {str(item[0]) for item in copied}
            assert "manual_tag" in kinds
            assert "ai_auto_tag" not in kinds
            pointer = (
                await session.execute(
                    text("SELECT pending_update_file_id FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            correction_status = (
                await session.execute(
                    text("SELECT status FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            awarded = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(delta), 0) FROM user_point_log
                        WHERE user_id = :id AND rule_code = 'G8'
                        """
                    ),
                    {"id": reader},
                )
            ).scalar_one()
            stored = (
                await session.execute(
                    text(
                        """
                        SELECT user_metadata, file_subcategory_source
                        FROM knowledgefile WHERE id = :id
                        """
                    ),
                    {"id": int(success["data"]["id"])},
                )
            ).one()
            metadata = stored[0]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            assert str(correction_status) == "approved"
            assert int(awarded) == 2
            assert int(pointer) == int(success["data"]["id"])
            assert (metadata or {}).get("correction_update_source") == "tmp/same.pdf"
            assert str(stored[1]) == "manual"
            primary_before = (
                await session.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM knowledge_document_version
                        WHERE knowledge_file_id = :id AND is_primary = 1
                        """
                    ),
                    {"id": int(success["data"]["id"])},
                )
            ).scalar_one()
            assert int(primary_before) == 0
            await session.execute(
                text("UPDATE knowledgefile SET status = 2 WHERE id = :id"),
                {"id": int(success["data"]["id"])},
            )
            await session.commit()
        from bisheng.knowledge.domain.services.knowledge_file_correction_service import (
            KnowledgeFileCorrectionService,
        )

        await KnowledgeFileCorrectionService.promote_parsed_update_file(int(success["data"]["id"]))
        async with AsyncSession(engine, expire_on_commit=False) as session:
            primary_after = (
                await session.execute(
                    text(
                        """
                        SELECT knowledge_file_id FROM knowledge_document_version
                        WHERE knowledge_file_id = :id AND is_primary = 1
                        """
                    ),
                    {"id": int(success["data"]["id"])},
                )
            ).scalar_one()
            cleared = (
                await session.execute(
                    text("SELECT pending_update_file_id FROM knowledge_file_correction WHERE id = :id"),
                    {"id": correction_id},
                )
            ).scalar_one()
            assert int(primary_after) == int(success["data"]["id"])
            assert cleared is None
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(text("DELETE FROM taglink WHERE resource_id = :id"), {"id": str(origin)})
            for created_id in file_ids:
                await session.execute(
                    text("DELETE FROM taglink WHERE resource_id = :id"),
                    {"id": str(created_id)},
                )
            await session.execute(text("DELETE FROM tag WHERE name IN ('手工标签', '自动标签')"))
            for created_id in file_ids:
                await session.execute(
                    text("DELETE FROM knowledge_document_version WHERE knowledge_file_id = :id"),
                    {"id": created_id},
                )
            await session.commit()
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)


@pytest.mark.asyncio
async def test_list_corrections_shows_body_and_status_mysql(flow_env):
    """能看文档的人能看到每条纠错的反馈人, 说明和状态."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    document_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            reader = await _insert_user(session, f"fc-lr-{suffix}")
            uploader = await _insert_user(session, f"fc-lu-{suffix}")
            stranger = await _insert_user(session, f"fc-ls-{suffix}")
            user_ids.extend([reader, uploader, stranger])
            space_id = await _insert_space(session, name=f"fc-ls-{suffix}", level="department")
            space_ids.append(space_id)
            file_id = await _insert_file(session, space_id=space_id, name=f"list-{suffix}", user_id=uploader)
            file_ids.append(file_id)
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader, name=f"fc-lr-{suffix}"))), base_url="http://test") as client:
            created = _body(await _submit(client, file_id, "列表里的说明"))
            assert created["status_code"] == 200, created
        async with AsyncClient(transport=ASGITransport(app=_app(_user(reader))), base_url="http://test") as client:
            listed = _body(await client.get(f"/api/v1/knowledge/files/{file_id}/corrections"))
        assert listed["status_code"] == 200, listed
        assert listed["data"][0]["status"] == "pending"
        assert listed["data"][0]["content"] == "列表里的说明"
        assert listed["data"][0]["file_name"] == f"list-{suffix}"
        async with AsyncClient(transport=ASGITransport(app=_app(_user(uploader))), base_url="http://test") as client:
            uploader_view = _body(await client.get(f"/api/v1/knowledge/files/{file_id}/corrections"))
        assert uploader_view["data"][0]["content"] == "列表里的说明"
        async with AsyncClient(transport=ASGITransport(app=_app(_user(stranger))), base_url="http://test") as client:
            hidden = _body(await client.get(f"/api/v1/knowledge/files/{file_id}/corrections"))
        assert hidden["status_code"] == 200, hidden
        assert hidden["data"][0]["status"] == "pending"
        assert hidden["data"][0]["content"] == "列表里的说明"
        assert hidden["data"][0]["applicant_user_name"]
        async with AsyncClient(transport=ASGITransport(app=_app(_user(stranger))), base_url="http://test") as client:
            again = _body(await client.get(f"/api/v1/knowledge/files/{file_id}/corrections"))
        assert again["data"][0]["content"] == "列表里的说明"
        assert again["data"][0]["status"] == "pending"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            newer = await _insert_file(session, space_id=space_id, name=f"newer-{suffix}", user_id=uploader)
            file_ids.append(newer)
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_document (tenant_id, knowledge_id, lifecycle_status)
                    VALUES (1, :space, 'active')
                    """
                ),
                {"space": space_id},
            )
            document_id = int(
                (
                    await session.execute(
                        text("SELECT id FROM knowledge_document WHERE knowledge_id = :space ORDER BY id DESC LIMIT 1"),
                        {"space": space_id},
                    )
                ).scalar_one()
            )
            document_ids.append(document_id)
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_document_version
                      (document_id, knowledge_file_id, version_no, is_primary)
                    VALUES (:doc, :old, 1, 0), (:doc, :new, 2, 1)
                    """
                ),
                {"doc": document_id, "old": file_id, "new": newer},
            )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=_app(_user(stranger))), base_url="http://test") as client:
            chained = _body(await client.get(f"/api/v1/knowledge/files/{newer}/corrections"))
        assert chained["status_code"] == 200, chained
        assert chained["data"][0]["content"] == "列表里的说明"
        assert chained["data"][0]["file_name"] == f"list-{suffix}"
        async with AsyncClient(transport=ASGITransport(app=_app(_user(stranger))), base_url="http://test") as client:
            chained_again = _body(await client.get(f"/api/v1/knowledge/files/{newer}/corrections"))
        assert len(chained_again["data"]) == 1
    finally:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            if file_ids:
                await session.execute(
                    text("DELETE FROM knowledge_document_version WHERE knowledge_file_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": file_ids},
                )
            if document_ids:
                await session.execute(
                    text("DELETE FROM knowledge_document WHERE id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": document_ids},
                )
            await session.commit()
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)
