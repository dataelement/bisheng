# ruff: noqa: RUF002
"""通过真实登录接口验证标准登录记录，以及组织同步和失败登录的排除边界。"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def login_records(monkeypatch):
    from bisheng.api.services.audit_log import AuditLogDao, AuditLogService, UserGroupDao
    from bisheng.common.services import telemetry_service
    from bisheng.core.context.tenant import get_current_tenant_id
    from bisheng.sso_sync.api.endpoints import login_sync as endpoint
    from bisheng.sso_sync.domain.schemas.payloads import LoginSyncResponse
    from bisheng.sso_sync.domain.services import login_sync_service as service
    from bisheng.telemetry.domain.mid_table.daily_participation import DailyParticipationFact

    @asynccontextmanager
    async def acquired(*args, **kwargs):
        yield True

    monkeypatch.setattr(service, "_acquire_user_lock", acquired)
    locked = AsyncMock(return_value=LoginSyncResponse(user_id=7, leaf_tenant_id=15, token="test-token"))
    monkeypatch.setattr(service.LoginSyncService, "_execute_locked", locked)
    monkeypatch.setattr(service.UserDao, "aget_user", AsyncMock(return_value=SimpleNamespace(user_name="测试用户")))

    async def init_user(user_id, user_name, tenant_id):
        return SimpleNamespace(user_id=user_id, user_name=user_name, tenant_id=tenant_id)

    monkeypatch.setattr(service.LoginUser, "init_login_user", init_user)
    monkeypatch.setattr(UserGroupDao, "get_user_group", lambda user_id: [])
    audit, events, participation = [], [], []

    def insert(rows):
        audit.extend((row, get_current_tenant_id()) for row in rows)

    async def log_event(**kwargs):
        events.append((kwargs, get_current_tenant_id()))

    async def record_login(**kwargs):
        participation.append((kwargs, get_current_tenant_id()))

    monkeypatch.setattr(AuditLogDao, "insert_audit_logs", insert)
    monkeypatch.setattr(telemetry_service, "log_event", log_event)
    monkeypatch.setattr(DailyParticipationFact, "record_login", record_login)
    monkeypatch.setattr(endpoint, "flush_log", AsyncMock())
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[endpoint.verify_hmac] = lambda: None
    return SimpleNamespace(
        app=app,
        service=service,
        locked=locked,
        audit=audit,
        events=events,
        participation=participation,
        audit_service=AuditLogService,
        telemetry=telemetry_service,
        fact=DailyParticipationFact,
    )


async def request_login(records):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=records.app), base_url="http://test") as client:
        return await client.post(
            "/api/v1/internal/sso/login-sync",
            json={
                "source": "sso",
                "external_user_id": "account-7",
                "ts": 1,
            },
        )


async def test_successful_portal_login_records_standard_login_in_leaf_tenant(login_records):
    from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id

    token = set_current_tenant_id(1)
    try:
        response = await request_login(login_records)
        assert response.status_code == 200
        assert response.json()["data"]["token"] == "test-token"
        assert len(login_records.audit) == len(login_records.events) == len(login_records.participation) == 1
        row, tenant = login_records.audit[0]
        assert (row.operator_id, row.event_type, tenant) == (7, "user_login", 15)
        event, tenant = login_records.events[0]
        assert (event["user_id"], event["event_type"], tenant) == (7, "user_login", 15)
        assert event["event_data"].method == "sso"
        fact, tenant = login_records.participation[0]
        assert (fact["user_id"], fact["tenant_id"], tenant) == (7, 15, 15)
        assert fact["user_name"] == "测试用户"
        assert get_current_tenant_id() == 1
    finally:
        current_tenant_id.reset(token)


@pytest.mark.parametrize("mode", ["disabled", "rejected", "batch"])
async def test_non_login_paths_do_not_record_login(login_records, mode):
    from bisheng.common.errcode.user import UserMultiLoginConflictError
    from bisheng.sso_sync.domain.schemas.payloads import LoginSyncRequest, LoginSyncResponse

    if mode == "batch":
        await login_records.service.LoginSyncService.execute(
            LoginSyncRequest(external_user_id="account-7", ts=1, skip_org_sync_log=True),
            row_source="wecom",
        )
    else:
        if mode == "disabled":
            login_records.locked.return_value = LoginSyncResponse(user_id=7, leaf_tenant_id=15, token="")
        else:
            login_records.locked.side_effect = UserMultiLoginConflictError()
        response = await request_login(login_records)
        assert response.status_code == 200
    assert not login_records.audit and not login_records.events and not login_records.participation


@pytest.mark.parametrize("failed_sink", ["audit", "es", "participation"])
async def test_recording_failure_does_not_block_login_or_other_sinks(login_records, monkeypatch, failed_sink):
    from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id

    def fail(*args, **kwargs):
        raise RuntimeError("模拟记录服务不可用")

    if failed_sink == "audit":
        monkeypatch.setattr(login_records.audit_service, "user_login", fail)
    elif failed_sink == "es":
        monkeypatch.setattr(login_records.telemetry, "log_event", AsyncMock(side_effect=fail))
    else:
        monkeypatch.setattr(login_records.fact, "record_login", AsyncMock(side_effect=fail))
    token = set_current_tenant_id(1)
    try:
        response = await request_login(login_records)
        assert response.json()["data"]["token"] == "test-token"
        for sink, records in [
            ("audit", login_records.audit),
            ("es", login_records.events),
            ("participation", login_records.participation),
        ]:
            assert len(records) == (0 if sink == failed_sink else 1)
        assert get_current_tenant_id() == 1
    finally:
        current_tenant_id.reset(token)
