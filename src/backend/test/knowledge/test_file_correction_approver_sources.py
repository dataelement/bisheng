"""文档纠错审批人来源: 171 MySQL 上改场景配置, 待办和审批跟着变."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.knowledge.api.endpoints.knowledge_file_correction import router as correction_router
from bisheng.permission.domain.services.permission_service import PermissionService
from test.knowledge.test_file_correction_flow import (
    _cleanup,
    _insert_file,
    _insert_space,
    _insert_user,
    _mysql_async_url,
    _submit,
    _user,
)

_roles: dict[int, tuple[list[int], list[int]]] = {}


def _body(response) -> dict:
    return response.json()


def _task_ids(payload: dict) -> set[int]:
    rows = (payload.get("data") or {}).get("data") or []
    return {int(item["task_id"]) for item in rows}


def _config_types(raw) -> list[str]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    sources = (raw or {}).get("sources") or []
    return [str(item.get("type")) for item in sources]


@pytest.fixture
async def flow_env(monkeypatch):
    """把纠错和审批查询接到 171, 库角色由测试替身返回."""
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
        "bisheng.knowledge.domain.services.knowledge_file_correction_approver_policy.get_async_db_session",
        "bisheng.approval.domain.repositories.approval_query_repository.get_async_db_session",
        "bisheng.approval.domain.repositories.approval_scenario_repository.get_async_db_session",
        "bisheng.approval.domain.repositories.approval_instance_repository.get_async_db_session",
        "bisheng.approval.domain.repositories.user_menu_access_repository.get_async_db_session",
        "bisheng.points.domain.services.points_award_hooks.get_async_db_session",
    ):
        monkeypatch.setattr(target, patched_session)
    monkeypatch.setattr(
        "bisheng.points.domain.services.points_award_hooks._award_async_enabled",
        lambda: False,
    )

    async def _check(_user_id, _relation, _object_type, object_id, login_user=None):
        return True

    monkeypatch.setattr(PermissionService, "check", _check)

    async def _noop_audit(**kwargs):
        return None

    monkeypatch.setattr("bisheng.database.models.audit_log.AuditLogDao.ainsert_v2", _noop_audit)

    async def _roles_for(space_id: int):
        return _roles.get(int(space_id), ([], []))

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_file_correction_approver_policy._space_roles",
        _roles_for,
    )
    yield engine
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
    app.include_router(correction_router, prefix="/api/v1")
    from bisheng.approval.api.router import router as approval_router

    app.include_router(approval_router, prefix="/api/v1")
    return app


def _client(user) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app(user)), base_url="http://test")


async def _active_sources(session: AsyncSession) -> tuple[int | None, list[str]]:
    row = (
        await session.execute(
            text(
                """
                SELECT v.id, n.approver_config
                FROM approval_node_definition n
                JOIN approval_flow_version v ON v.id = n.flow_version_id AND v.is_active = 1
                JOIN approval_flow_definition f ON f.id = v.flow_definition_id
                WHERE f.flow_code = 'knowledge_file_correction_flow'
                ORDER BY v.id DESC
                LIMIT 1
                """
            )
        )
    ).first()
    if row is None:
        return None, []
    return int(row[0]), _config_types(row[1])


async def _restore_default(engine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(
            text(
                """
                UPDATE approval_scenario
                SET enabled = 1
                WHERE scenario_code = 'knowledge_file_correction' AND tenant_id = 1
                """
            )
        )
        await session.execute(
            text(
                """
                UPDATE approval_node_definition n
                INNER JOIN approval_flow_version v ON v.id = n.flow_version_id AND v.is_active = 1
                INNER JOIN approval_flow_definition f ON f.id = v.flow_definition_id
                SET n.approver_config = CAST(:cfg AS JSON), n.node_mode = 'or'
                WHERE f.flow_code = 'knowledge_file_correction_flow'
                """
            ),
            {"cfg": '{"sources":[{"type":"file_uploader"}]}'},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_correction_approver_sources_follow_scenario_config_mysql(flow_env):
    """默认只有上传人; 加上库角色后现任成员能批; 拿掉或停用后立刻生效."""
    engine = flow_env
    suffix = uuid.uuid4().hex[:8]
    _roles.clear()
    user_ids: list[int] = []
    space_ids: list[int] = []
    file_ids: list[int] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            applicant_id = await _insert_user(session, f"fc-src-applicant-{suffix}")
            uploader_id = await _insert_user(session, f"fc-src-uploader-{suffix}")
            manager_id = await _insert_user(session, f"fc-src-manager-{suffix}")
            owner_id = await _insert_user(session, f"fc-src-owner-{suffix}")
            stranger_id = await _insert_user(session, f"fc-src-stranger-{suffix}")
            admin_id = await _insert_user(session, f"fc-src-admin-{suffix}")
            user_ids.extend([applicant_id, uploader_id, manager_id, owner_id, stranger_id, admin_id])
            space_id = await _insert_space(session, name=f"fc-src-space-{suffix}", level="department")
            space_ids.append(space_id)
            file_id = await _insert_file(
                session,
                space_id=space_id,
                name=f"fc-src-{suffix}.md",
                user_id=uploader_id,
            )
            file_ids.append(file_id)
        _roles[space_id] = ([owner_id], [manager_id, applicant_id])

        admin = _user(admin_id, admin=True, name="fc-admin")
        applicant = _user(applicant_id, name="fc-applicant")
        uploader = _user(uploader_id, name="fc-uploader")
        manager = _user(manager_id, name="fc-manager")
        owner = _user(owner_id, name="fc-owner")
        stranger = _user(stranger_id, name="fc-stranger")

        async with _client(admin) as admin_client:
            presets = _body(await admin_client.get("/api/v1/approval/admin/scenario-presets"))
            preset = next(item for item in presets["data"] if item["scenario_code"] == "knowledge_file_correction")
            assert preset["approver_source_types"] == [
                "file_uploader",
                "knowledge_space_owner",
                "knowledge_space_manager",
            ]
            listed = _body(await admin_client.get("/api/v1/approval/admin/scenarios"))
            scenario = next(item for item in listed["data"] if item["scenario_code"] == "knowledge_file_correction")
            assert scenario["scenario_name"] == "文档纠错"
            assert scenario["enabled"] is True
            assert scenario["system_managed"] is True
            assert scenario["structure_locked"] is True
            assert scenario["approver_sources_editable"] is True
            scenario_id = int(scenario["id"])
            flows = _body(await admin_client.get(f"/api/v1/approval/admin/scenarios/{scenario_id}/flows"))
            assert len(flows["data"]) == 1
            flow_id = int(flows["data"][0]["id"])
            created_flow = _body(
                await admin_client.post(
                    f"/api/v1/approval/admin/scenarios/{scenario_id}/flows",
                    json={"flow_name": "多余流程", "is_active": True},
                )
            )
            assert created_flow["status_code"] == 18118
            created_route = _body(
                await admin_client.post(
                    f"/api/v1/approval/admin/scenarios/{scenario_id}/routes",
                    json={"route_name": "多余分支", "route_type": "approval", "flow_definition_id": flow_id},
                )
            )
            assert created_route["status_code"] == 18118
            reset = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/flows/{flow_id}/nodes",
                    json={
                        "nodes": [
                            {
                                "node_code": "file_uploader",
                                "node_name": "上传人审批",
                                "node_order": 0,
                                "node_mode": "or",
                                "approver_config": {"sources": [{"type": "file_uploader"}]},
                            }
                        ]
                    },
                )
            )
            assert reset["status_code"] == 200, reset

            async with AsyncSession(engine, expire_on_commit=False) as session:
                version_before, sources_before = await _active_sources(session)
            assert sources_before == ["file_uploader"]
            assert version_before is not None

            removed = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/flows/{flow_id}/nodes",
                    json={
                        "nodes": [
                            {
                                "node_code": "file_uploader",
                                "node_name": "上传人审批",
                                "node_order": 0,
                                "node_mode": "or",
                                "approver_config": {"sources": [{"type": "knowledge_space_manager"}]},
                            }
                        ]
                    },
                )
            )
            assert removed["status_code"] == 18413
            extra_node = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/flows/{flow_id}/nodes",
                    json={
                        "nodes": [
                            {
                                "node_code": "file_uploader",
                                "node_name": "上传人审批",
                                "node_mode": "or",
                                "approver_config": {"sources": [{"type": "file_uploader"}]},
                            },
                            {
                                "node_code": "second",
                                "node_name": "第二级",
                                "node_mode": "or",
                                "approver_config": {"sources": [{"type": "file_uploader"}]},
                            },
                        ]
                    },
                )
            )
            assert extra_node["status_code"] == 18118
            async with AsyncSession(engine, expire_on_commit=False) as session:
                version_still, sources_still = await _active_sources(session)
                flow_count = (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM approval_flow_definition
                            WHERE scenario_id = :sid
                            """
                        ),
                        {"sid": scenario_id},
                    )
                ).scalar_one()
            assert version_still == version_before
            assert sources_still == ["file_uploader"]
            assert int(flow_count) == 1

            async with _client(applicant) as applicant_client:
                created = _body(await _submit(applicant_client, file_id, "原文有错"))
            assert created["status_code"] == 200, created
            correction_id = int(created["data"]["correction_id"])
            task_id = int(created["data"]["task_id"])

            async with _client(manager) as manager_client:
                hidden = _body(await manager_client.get("/api/v1/approval/my-tasks"))
                denied_read = _body(await manager_client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
                denied_decide = _body(
                    await manager_client.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
            assert task_id not in _task_ids(hidden)
            assert denied_read["status_code"] == 18407
            assert denied_decide["status_code"] == 18408

            saved = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/flows/{flow_id}/nodes",
                    json={
                        "nodes": [
                            {
                                "node_code": "file_uploader",
                                "node_name": "上传人审批",
                                "node_order": 0,
                                "node_mode": "or",
                                "approver_config": {
                                    "sources": [
                                        {"type": "file_uploader"},
                                        {"type": "knowledge_space_owner"},
                                        {"type": "knowledge_space_manager"},
                                    ]
                                },
                            }
                        ]
                    },
                )
            )
            assert saved["status_code"] == 200, saved
            async with AsyncSession(engine, expire_on_commit=False) as session:
                version_after, sources_after = await _active_sources(session)
                old_active = (
                    await session.execute(
                        text("SELECT is_active FROM approval_flow_version WHERE id = :id"),
                        {"id": version_before},
                    )
                ).scalar_one()
            assert version_after != version_before
            assert int(old_active) == 0
            assert sources_after == [
                "file_uploader",
                "knowledge_space_owner",
                "knowledge_space_manager",
            ]

            async with (
                _client(manager) as manager_client,
                _client(owner) as owner_client,
                _client(applicant) as applicant_client,
                _client(stranger) as stranger_client,
                _client(admin) as admin_decide,
                _client(uploader) as uploader_client,
            ):
                manager_tasks = _body(await manager_client.get("/api/v1/approval/my-tasks"))
                owner_tasks = _body(await owner_client.get("/api/v1/approval/my-tasks"))
                applicant_tasks = _body(await applicant_client.get("/api/v1/approval/my-tasks"))
                stranger_tasks = _body(await stranger_client.get("/api/v1/approval/my-tasks"))
                uploader_tasks = _body(await uploader_client.get("/api/v1/approval/my-tasks"))
                manager_read = _body(await manager_client.get(f"/api/v1/knowledge/file-corrections/{correction_id}"))
                applicant_decide = _body(
                    await applicant_client.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
                stranger_decide = _body(
                    await stranger_client.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
                admin_decide_body = _body(
                    await admin_decide.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
                adopted = _body(
                    await manager_client.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
                again = _body(
                    await manager_client.post(
                        f"/api/v1/approval/tasks/{task_id}/decision",
                        json={"action": "adopt"},
                    )
                )
            assert task_id in _task_ids(manager_tasks)
            assert task_id in _task_ids(owner_tasks)
            assert task_id not in _task_ids(applicant_tasks)
            assert task_id not in _task_ids(stranger_tasks)
            assert task_id in _task_ids(uploader_tasks)
            assert manager_read["status_code"] == 200
            assert manager_read["data"]["content"] == "原文有错"
            assert applicant_decide["status_code"] == 18408
            assert stranger_decide["status_code"] == 18408
            assert admin_decide_body["status_code"] == 18408
            assert adopted["status_code"] == 200, adopted
            assert again["status_code"] == 18102

            async with AsyncSession(engine, expire_on_commit=False) as session:
                correction = (
                    await session.execute(
                        text(
                            """
                            SELECT status FROM knowledge_file_correction WHERE id = :id
                            """
                        ),
                        {"id": correction_id},
                    )
                ).scalar_one()
                task_row = (
                    await session.execute(
                        text(
                            """
                            SELECT status, approver_user_id FROM approval_task WHERE id = :id
                            """
                        ),
                        {"id": task_id},
                    )
                ).one()
                instance_row = (
                    await session.execute(
                        text(
                            """
                            SELECT status, latest_approver_user_id
                            FROM approval_instance
                            WHERE id = :id
                            """
                        ),
                        {"id": int(created["data"]["instance_id"])},
                    )
                ).one()
                award_count = (
                    await session.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM knowledge_file_correction_award
                            WHERE correction_id = :id
                            """
                        ),
                        {"id": correction_id},
                    )
                ).scalar_one()
            assert correction == "approved"
            assert task_row[0] == "approved"
            assert int(task_row[1]) == uploader_id
            assert instance_row[0] == "approved"
            assert int(instance_row[1]) == manager_id
            assert int(award_count) == 1
            assert again["status_code"] == 18102

            only_uploader = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/flows/{flow_id}/nodes",
                    json={
                        "nodes": [
                            {
                                "node_code": "file_uploader",
                                "node_name": "上传人审批",
                                "node_order": 0,
                                "node_mode": "or",
                                "approver_config": {"sources": [{"type": "file_uploader"}]},
                            }
                        ]
                    },
                )
            )
            assert only_uploader["status_code"] == 200, only_uploader
            async with _client(applicant) as applicant_client:
                second = _body(await _submit(applicant_client, file_id, "还有一处错误"))
            assert second["status_code"] == 200, second
            second_task = int(second["data"]["task_id"])
            second_correction = int(second["data"]["correction_id"])
            async with _client(manager) as manager_client, _client(uploader) as uploader_client:
                manager_again = _body(await manager_client.get("/api/v1/approval/my-tasks"))
                manager_denied = _body(
                    await manager_client.post(
                        f"/api/v1/approval/tasks/{second_task}/decision",
                        json={"action": "reject", "comment": "不该我批"},
                    )
                )
                rejected = _body(
                    await uploader_client.post(
                        f"/api/v1/approval/tasks/{second_task}/decision",
                        json={"action": "reject", "comment": "不采纳"},
                    )
                )
                rejected_again = _body(
                    await uploader_client.post(
                        f"/api/v1/approval/tasks/{second_task}/decision",
                        json={"action": "reject", "comment": "再拒绝一次"},
                    )
                )
            assert second_task not in _task_ids(manager_again)
            assert manager_denied["status_code"] == 18408
            assert rejected["status_code"] == 200, rejected
            assert rejected_again["status_code"] == 18102
            async with AsyncSession(engine, expire_on_commit=False) as session:
                second_status = (
                    await session.execute(
                        text("SELECT status FROM knowledge_file_correction WHERE id = :id"),
                        {"id": second_correction},
                    )
                ).scalar_one()
                before_disabled = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id"),
                        {"id": file_id},
                    )
                ).scalar_one()
            assert second_status == "rejected"

            disabled = _body(
                await admin_client.put(
                    f"/api/v1/approval/admin/scenarios/{scenario_id}",
                    json={"enabled": False, "toggle_reason": "测试停用"},
                )
            )
            assert disabled["status_code"] == 200, disabled
            async with _client(applicant) as applicant_client:
                blocked = _body(await _submit(applicant_client, file_id, "停用后不该写入"))
            async with AsyncSession(engine, expire_on_commit=False) as session:
                after_disabled = (
                    await session.execute(
                        text("SELECT COUNT(*) FROM knowledge_file_correction WHERE file_id = :id"),
                        {"id": file_id},
                    )
                ).scalar_one()
            assert blocked["status_code"] == 18106
            assert int(after_disabled) == int(before_disabled)
    finally:
        _roles.clear()
        await _restore_default(engine)
        await _cleanup(engine, user_ids=user_ids, space_ids=space_ids, file_ids=file_ids)
