"""文档纠错两段正文: 调接口, 查表, 再读待办详情."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.permission.domain.services.permission_service import PermissionService
from test.knowledge.test_file_correction_flow import (
    _allowed_files,
    _app,
    _body,
    _cleanup,
    _insert_file,
    _insert_space,
    _insert_user,
    _mysql_async_url,
    _user,
)


@pytest.fixture
async def flow_env(monkeypatch):
    """复用纠错流转测试的 171 MySQL 会话补丁, 不跑巨石文件里的其它用例."""
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

    monkeypatch.setattr(ApprovalCenterService, "_send_approval_notify", classmethod(_noop_notify))
    monkeypatch.setattr(ApprovalCenterService, "get_instance_detail", classmethod(_detail))
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_two_part_submit_persists_and_rereads(flow_env):
    """两段都填写时落库两列, 详情接口按两段返回; 缺一段拒绝且不写行."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            applicant = await _insert_user(session, f"fc2-reader-{suffix}")
            uploader = await _insert_user(session, f"fc2-up-{suffix}")
            user_ids.extend([applicant, uploader])
            space_id = await _insert_space(session, name=f"fc2-dept-{suffix}", level="department")
            space_ids.append(space_id)
            file_id = await _insert_file(
                session,
                space_id=space_id,
                name=f"fc2-doc-{suffix}.txt",
                user_id=uploader,
                object_name=f"obj2-{suffix}",
            )
            file_ids.append(file_id)

        async with AsyncClient(
            transport=ASGITransport(app=_app(_user(applicant, name="reader"))),
            base_url="http://test",
        ) as client:
            empty = _body(
                await client.post(
                    f"/api/v1/knowledge/files/{file_id}/corrections",
                    json={"original_error": "原文日期不对", "corrected_content": "  "},
                )
            )
            assert empty["status_code"] == 18400
            too_long = _body(
                await client.post(
                    f"/api/v1/knowledge/files/{file_id}/corrections",
                    json={"original_error": "错" * 501, "corrected_content": "改正"},
                )
            )
            assert too_long["status_code"] == 18401

            async with AsyncSession(engine, expire_on_commit=False) as session:
                before = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id"),
                        {"id": file_id},
                    )
                ).scalar_one()
            assert int(before) == 0

            created = _body(
                await client.post(
                    f"/api/v1/knowledge/files/{file_id}/corrections",
                    json={
                        "original_error": "原文写错了日期",
                        "corrected_content": "应为 2026-10-13",
                    },
                )
            )
            assert created["status_code"] == 200, created
            correction_id = created["data"]["correction_id"]

            visible = _body(await client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
            assert visible["status_code"] == 200
            assert visible["data"]["original_error"] == "原文写错了日期"
            assert visible["data"]["corrected_content"] == "应为 2026-10-13"
            assert visible["data"]["content"] == "原文写错了日期"

        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT original_error, corrected_content, content
                        FROM knowledge_file_correction
                        WHERE id = :id
                        """
                    ),
                    {"id": correction_id},
                )
            ).one()
            assert row[0] == "原文写错了日期"
            assert row[1] == "应为 2026-10-13"
            assert row[2] == "原文写错了日期"
            again = (
                await session.execute(
                    text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id"),
                    {"id": file_id},
                )
            ).scalar_one()
            assert int(again) == 1
    finally:
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)
