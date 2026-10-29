"""Read actual source tables. 覆盖 AC: AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-58, AC-61."""

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def audit_env(monkeypatch):
    from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditExport, RuntimeAuditQuerySnapshot
    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
    from bisheng.app_governance.domain.services.runtime_audit_query_service import RuntimeAuditQueryService
    from bisheng.app_publish.domain.models.capability_call_record import AppCapabilityCallRecord
    from bisheng.common.services.config_service import settings
    from bisheng.database.models.app_access_log import AppAccessLog
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
    from test.app_publish.conftest import _sqlite_ddl_quirks

    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    monkeypatch.setattr(settings.app_runtime, "runtime_audit_source_timezone", "UTC")
    engine = create_async_engine("sqlite+aiosqlite://")
    models = [RuntimeAuditQuerySnapshot, RuntimeAuditExport, ModelCallRecord, AppCapabilityCallRecord, AppAccessLog]
    with _sqlite_ddl_quirks([m.__table__ for m in models]):
        async with engine.begin() as c:
            for m in models:
                await c.run_sync(m.__table__.create)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(engine, expire_on_commit=False) as s:
            yield s

    repo = RuntimeAuditRepository(sessions)
    scope = AuthorizedRuntimeAuditScope(creator_user_id=7, owner_tenant_id=1, tenant_id=1)

    async def resolve(user, tenant_id=None):
        assert user == "admin"
        if tenant_id not in (None, 1):
            from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError

            raise RuntimeAuditAccessDeniedError()
        return scope

    service = RuntimeAuditQueryService(repo, scope_resolver=resolve)
    now = datetime.utcnow()
    async with sessions() as s:
        for i in range(1, 6):
            s.add(
                ModelCallRecord(
                    id=i,
                    tenant_id=1 if i < 5 else 2,
                    credential_id=10,
                    actor_kind="service_account",
                    actor_id=8,
                    actor_name="=unsafe",
                    requested_model="model-a",
                    result="success",
                    create_time=now,
                )
            )
        s.add(
            AppCapabilityCallRecord(
                id=1,
                tenant_id=1,
                app_id="app-a",
                app_name="Deleted app",
                subject_user_id=9,
                capability="knowledge",
                result="success",
                targets={"private": "must not escape"},
                create_time=now,
            )
        )
        s.add(
            AppAccessLog(
                id=1,
                tenant_id=1,
                app_id="app-a",
                user_id=9,
                user_name="Historical visitor",
                app_name_snapshot="Old app",
                entry_time=now,
            )
        )
        await s.commit()
    yield service, repo, sessions, scope
    await engine.dispose()


async def test_service_account_rows_and_null_tokens_survive_stable_pages(audit_env):
    service, _, _, _ = audit_env
    first = await service.list("admin", "model", {"time_range": "all"}, limit=2)
    second = await service.list("admin", "model", {"time_range": "all"}, limit=2, cursor=first["next_cursor"])
    assert [i["id"] for i in first["items"] + second["items"]] == [4, 3, 2, 1]
    assert second["next_cursor"] is None
    assert first["items"][0]["app_id"] is None
    assert first["items"][0]["total_tokens"] is None
    assert set(first["items"][0]).isdisjoint({"token_hash", "prompt", "targets", "metadata"})


async def test_cursor_refuses_changed_filter_and_tampering(audit_env):
    from bisheng.common.errcode.app_governance import RuntimeAuditCursorInvalidError

    service, _, _, _ = audit_env
    page = await service.list("admin", "model", {"time_range": "all"}, limit=1)
    for cursor, filters in [
        (page["next_cursor"] + "x", {"time_range": "all"}),
        (page["next_cursor"], {"time_range": "recent7d"}),
    ]:
        with pytest.raises(RuntimeAuditCursorInvalidError):
            await service.list("admin", "model", filters, cursor=cursor)


async def test_frozen_watermark_excludes_later_insert(audit_env):
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

    service, _, sessions, _ = audit_env
    page = await service.list("admin", "model", {"time_range": "all"}, limit=1)
    async with sessions() as s:
        s.add(
            ModelCallRecord(
                id=8,
                tenant_id=1,
                credential_id=10,
                actor_kind="service_account",
                requested_model="model-a",
                result="success",
            )
        )
        await s.commit()
    rest = await service.list("admin", "model", {"time_range": "all"}, limit=100, cursor=page["next_cursor"])
    assert [i["id"] for i in rest["items"]] == [3, 2, 1]


async def test_capability_and_access_snapshots_without_live_joins(audit_env):
    service, _, _, _ = audit_env
    cap = await service.list("admin", "capability", {"time_range": "all"})
    access = await service.list("admin", "access", {"time_range": "all"})
    assert cap["items"][0]["app_name"] == "Deleted app"
    assert "targets" not in cap["items"][0]
    assert access["items"][0]["app_name_snapshot"] == "Old app"


@pytest.mark.parametrize(
    "filters",
    [{"time_range": "custom"}, {"time_range": "all", "credential_id": 10}, {"time_range": "all", "app_id": "foreign"}],
)
async def test_invalid_inapplicable_and_foreign_filters_refused(audit_env, filters):
    from bisheng.common.errcode.app_governance import RuntimeAuditFilterInvalidError

    service, _, _, _ = audit_env
    with pytest.raises(RuntimeAuditFilterInvalidError):
        await service.list("admin", "access", filters)


async def test_historical_candidates_scope_and_disabled(audit_env, monkeypatch):
    from bisheng.common.errcode.app_factory import AppFactoryNotEnabledError
    from bisheng.common.services.config_service import settings

    service, _, _, _ = audit_env
    options = await service.candidates("admin", "capability", "app", {"time_range": "all"})
    assert options["items"][0]["label"] == "Deleted app"
    monkeypatch.setattr(settings.app_runtime, "enabled", False)
    with pytest.raises(AppFactoryNotEnabledError):
        await service.list("admin", "model", {})


async def test_scope_rejects_non_session_and_fresh_non_admin(monkeypatch):
    """覆盖 AC: AC-52, AC-53. JWT/menu/owner roles cannot authorize the new read surface."""
    from types import SimpleNamespace

    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.services import runtime_audit_scope as module
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError
    from bisheng.core.context.tenant import tenant_execution_scope

    with pytest.raises(RuntimeAuditAccessDeniedError):
        await module.resolve_scope(SimpleNamespace(user_id=7, is_global_super=True))

    async def account(*args):
        return SimpleNamespace(token_version=0)

    async def fresh(**kwargs):
        return SimpleNamespace(is_global_super=False)

    async def denied(*args):
        return False

    monkeypatch.setattr(RuntimeAuditRepository, "current_user", account)
    monkeypatch.setattr(UserPayload, "init_login_user", fresh)
    monkeypatch.setattr(module, "is_tenant_admin", denied)
    user = UserPayload(user_id=7, user_name="owner", tenant_id=1, user_role=[])
    with tenant_execution_scope(1):
        with pytest.raises(RuntimeAuditAccessDeniedError):
            await module.resolve_scope(user)

        async def allowed(*args):
            return True

        monkeypatch.setattr(module, "is_tenant_admin", allowed)
        assert (await module.resolve_scope(user)).tenant_id == 1
        with pytest.raises(RuntimeAuditAccessDeniedError):
            await module.resolve_scope(user, 2)


async def test_global_super_current_narrowing_is_rechecked_without_http_middleware(monkeypatch):
    """覆盖 AC: AC-52, AC-56. Worker/download cannot bypass a new admin scope."""
    from types import SimpleNamespace

    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.services import runtime_audit_scope as module
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError
    from bisheng.core.context.tenant import tenant_execution_scope

    async def account(*args):
        return SimpleNamespace(token_version=0)

    async def fresh(**kwargs):
        return SimpleNamespace(is_global_super=True)

    narrowed = None

    async def persisted(*args):
        return narrowed

    monkeypatch.setattr(RuntimeAuditRepository, "current_user", account)
    monkeypatch.setattr(UserPayload, "init_login_user", fresh)
    monkeypatch.setattr(module, "current_admin_scope", persisted)
    user = UserPayload(user_id=7, user_name="super", tenant_id=1, user_role=[])
    with tenant_execution_scope(1):
        assert (await module.resolve_scope(user)).tenant_id is None
        narrowed = 2
        assert (await module.resolve_scope(user)).tenant_id == 2
        with pytest.raises(RuntimeAuditAccessDeniedError):
            await module.resolve_scope(user, 3)


async def test_source_naive_time_converts_from_deployment_zone(audit_env, monkeypatch):
    """覆盖 AC: AC-47, AC-51. Container TZ dates must not disappear behind a UTC upper bound."""
    from datetime import timedelta

    from bisheng.common.services.config_service import settings
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

    service, _, sessions, _ = audit_env
    instant = datetime.utcnow().replace(microsecond=0) - timedelta(seconds=10)
    async with sessions() as session:
        row = await session.get(ModelCallRecord, 1)
        row.create_time = instant + timedelta(hours=8)
        session.add(row)
        await session.commit()
    monkeypatch.setattr(settings.app_runtime, "runtime_audit_source_timezone", "Asia/Shanghai")
    page = await service.list(
        "admin",
        "model",
        {
            "time_range": "custom",
            "start_time": (instant - timedelta(seconds=1)).isoformat() + "Z",
            "end_time": (instant + timedelta(seconds=1)).isoformat() + "Z",
        },
    )
    assert [r["id"] for r in page["items"]] == [1]
    assert page["items"][0]["create_time"].isoformat() == instant.isoformat() + "+00:00"


async def test_actual_read_router_envelope_and_invalid_filter(audit_env, monkeypatch):
    """覆盖 AC: AC-46, AC-47, AC-57. Real endpoint-to-service-to-source wiring."""
    import importlib

    import httpx
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.base import BaseErrorCode

    module = importlib.import_module("bisheng.app_governance.api.router")
    service, _, _, _ = audit_env
    monkeypatch.setattr(module, "RuntimeAuditQueryService", lambda: service)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/v1")
    app.dependency_overrides[UserPayload.get_login_user] = lambda: "admin"

    @app.exception_handler(BaseErrorCode)
    async def error(request, exc):
        return JSONResponse(exc.return_resp_instance().model_dump())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/app-runtime-audit/records/model?time_range=all")
        assert response.json()["status_code"] == 200
        assert len(response.json()["data"]["items"]) == 4
        candidates = await client.get("/api/v1/app-runtime-audit/candidates/app?kind=capability&time_range=all")
        assert candidates.json()["status_code"] == 200
        assert candidates.json()["data"]["items"][0]["label"] == "Deleted app"
        invalid = await client.get("/api/v1/app-runtime-audit/records/model?ignored_filter=1")
        assert invalid.json()["status_code"] == 16302
