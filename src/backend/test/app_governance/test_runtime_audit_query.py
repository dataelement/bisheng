"""Read actual source tables. 覆盖 AC: AC-47, AC-48, AC-49, AC-50, AC-51, AC-52, AC-53, AC-54, AC-58, AC-61."""

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.core.context.tenant import tenant_execution_scope

AUDIT_USER = UserPayload(user_id=7, user_name="admin", tenant_id=1, user_role=[])


@pytest.fixture
def audit_tenant():
    with tenant_execution_scope(1):
        yield


@pytest.fixture
async def audit_env(monkeypatch, audit_tenant):
    from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditExport, RuntimeAuditQuerySnapshot
    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.schemas.runtime_audit import AuthorizedRuntimeAuditScope
    from bisheng.app_governance.domain.services.runtime_audit_query_service import RuntimeAuditQueryService
    from bisheng.app_publish.domain.models.capability_call_record import AppCapabilityCallRecord
    from bisheng.common.services.config_service import settings
    from bisheng.database.models.app_access_log import AppAccessLog
    from bisheng.open_api.domain.models.api_credential import ApiCredential
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
    from bisheng.user.domain.models.user import User
    from test.app_publish.conftest import _sqlite_ddl_quirks

    monkeypatch.setattr(settings.app_runtime, "enabled", True)
    monkeypatch.setattr(settings.app_runtime, "runtime_audit_source_timezone", "UTC")
    engine = create_async_engine("sqlite+aiosqlite://")
    models = [
        RuntimeAuditQuerySnapshot,
        RuntimeAuditExport,
        ModelCallRecord,
        AppCapabilityCallRecord,
        AppAccessLog,
        User,
        ApiCredential,
    ]
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

    async def resolve(user, tenant_id=None, *, app_id=None):
        assert user == AUDIT_USER
        if tenant_id not in (None, 1):
            from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError

            raise RuntimeAuditAccessDeniedError()
        return scope

    service = RuntimeAuditQueryService(repo, scope_resolver=resolve)
    now = datetime.utcnow()
    async with sessions() as s:
        s.add(User(user_id=9, user_name="Current visitor", password="test"))
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
                credential_id=10,
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


@pytest.mark.parametrize("credential_tenant", [1, 2])
async def test_display_labels_keep_ids_and_do_not_expand_history(audit_env, credential_tenant):
    """AC-26/29/31/34: names decorate the authorized facts without replacing IDs."""
    service, _, sessions, _ = audit_env
    from bisheng.open_api.domain.models.api_credential import ApiCredential

    async with sessions() as s:
        s.add(
            ApiCredential(
                id=10,
                tenant_id=credential_tenant,
                subject_kind="hosted_app",
                subject_id=8,
                name="PRIVATE_KEY_NAME",
                key_prefix="bs-app-",
                last4="ABCD",
                token_hash="x" * 64,
            )
        )
        await s.commit()
    capability = (await service.list(AUDIT_USER, "capability", {"time_range": "all"}))["items"][0]
    assert capability["subject_name"] == "Current visitor"
    assert capability["subject_user_id"] == 9
    assert capability.get("credential_mask") == ("bs-app-********ABCD" if credential_tenant == 1 else None)
    assert set(capability).isdisjoint({"name", "token_hash", "_credential_prefix", "_credential_last4"})
    assert "PRIVATE_KEY_NAME" not in str(capability)
    access = (await service.list(AUDIT_USER, "access", {"time_range": "all"}))["items"][0]
    assert access["user_name"] == "Historical visitor"
    assert access["user_id"] == 9
    candidates = await service.candidates(AUDIT_USER, "capability", "visitor", {"time_range": "all"})
    assert candidates["items"][0]["label"] == "Current visitor"


async def test_model_subject_names_require_a_real_typed_identity(audit_env):
    """AC-26/34: app-self never borrows the resource owner's user identity."""
    service, _, sessions, _ = audit_env
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

    async with sessions() as s:
        for record_id, kind, subject in [(10, "user", 9), (11, "app_self", None), (12, "user", 999)]:
            s.add(
                ModelCallRecord(
                    id=record_id,
                    tenant_id=1,
                    credential_id=10,
                    actor_kind="hosted_app",
                    actor_id=9,
                    actor_name="Historical application",
                    subject_kind=kind,
                    subject_id=subject,
                    resource_owner_user_id=9,
                    requested_model="model-a",
                    result="success",
                    create_time=datetime.utcnow(),
                )
            )
        s.add(
            ModelCallRecord(
                id=13,
                tenant_id=1,
                credential_id=10,
                actor_kind="service_account",
                actor_id=8,
                actor_name="Recorded SDK account",
                subject_kind="service_account",
                subject_id=8,
                requested_model="model-a",
                result="success",
                create_time=datetime.utcnow(),
            )
        )
        s.add(
            ModelCallRecord(
                id=14,
                tenant_id=1,
                credential_id=10,
                actor_kind="natural_person",
                actor_id=9,
                actor_name="Recorded direct user",
                subject_kind="user",
                subject_id=9,
                requested_model="model-a",
                result="success",
                create_time=datetime.utcnow(),
            )
        )
        await s.commit()
    rows = {r["id"]: r for r in (await service.list(AUDIT_USER, "model", {"time_range": "all"}))["items"]}
    assert rows[10]["subject_name"] == "Current visitor"
    assert rows[11]["subject_id"] is None and rows[11]["subject_name"] is None
    assert rows[12]["subject_name"] is None and rows[12]["subject_id"] == 999
    assert rows[10]["actor_name"] == "Historical application"
    assert rows[13]["subject_name"] == "Recorded SDK account"
    assert rows[14]["subject_name"] == "Recorded direct user"


@pytest.mark.parametrize("kind", ["model", "capability"])
async def test_export_preserves_source_nulls_and_zero_without_display_enrichment(audit_env, kind):
    """AC-26/32/34: CSV blanks match SQL NULL; real zero values remain zero."""
    import csv
    import io

    from bisheng.app_governance.domain.schemas.runtime_audit import FIELDS, normalize
    from bisheng.app_governance.domain.services.runtime_audit_export_service import csv_bytes
    from bisheng.app_publish.domain.models.capability_call_record import AppCapabilityCallRecord
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

    _, repo, sessions, scope = audit_env
    async with sessions() as s:
        if kind == "model":
            s.add(
                ModelCallRecord(
                    id=10,
                    tenant_id=1,
                    credential_id=10,
                    actor_kind="hosted_app",
                    actor_name="Application",
                    subject_kind="app_self",
                    requested_model="model-a",
                    result="success",
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    create_time=datetime.utcnow(),
                )
            )
            columns = (
                "subject_id",
                "ttft_ms",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "error_code",
                "http_status",
            )
        else:
            s.add(
                AppCapabilityCallRecord(
                    id=10,
                    tenant_id=1,
                    app_id="app-a",
                    subject_user_id=9,
                    capability="knowledge",
                    result="success",
                    chunk_count=0,
                    create_time=datetime.utcnow(),
                )
            )
            columns = ("chunk_count", "error_code")
        await s.commit()
    _, filters = normalize(kind, {"time_range": "all"})
    watermark = await repo.watermark(scope, kind, filters)
    records = [row async for batch in repo.stream_export(scope, kind, filters, watermark) for row in batch]
    exported = list(csv.DictReader(io.StringIO(csv_bytes(FIELDS[kind], records, header=True).decode("utf-8-sig"))))
    assert len(exported) == len(records)
    assert all("subject_name" not in row for row in records)
    for record, row in zip(records, exported, strict=True):
        for field in columns:
            assert row[field] == ("" if record[field] is None else str(record[field]))
    zero = next(row for row in exported if row["id"] == "10")
    assert zero["total_tokens" if kind == "model" else "chunk_count"] == "0"


async def test_service_account_rows_and_null_tokens_survive_stable_pages(audit_env):
    service, _, _, _ = audit_env
    first = await service.list(AUDIT_USER, "model", {"time_range": "all"}, limit=2)
    second = await service.list(AUDIT_USER, "model", {"time_range": "all"}, limit=2, cursor=first["next_cursor"])
    assert [i["id"] for i in first["items"] + second["items"]] == [4, 3, 2, 1]
    assert second["next_cursor"] is None
    assert first["items"][0]["app_id"] is None
    assert first["items"][0]["total_tokens"] is None
    assert set(first["items"][0]).isdisjoint({"token_hash", "prompt", "targets", "metadata"})


async def test_cursor_refuses_changed_filter_and_tampering(audit_env):
    from bisheng.common.errcode.app_governance import RuntimeAuditCursorInvalidError

    service, _, _, _ = audit_env
    page = await service.list(AUDIT_USER, "model", {"time_range": "all"}, limit=1)
    for cursor, filters in [
        (page["next_cursor"] + "x", {"time_range": "all"}),
        (page["next_cursor"], {"time_range": "recent7d"}),
    ]:
        with pytest.raises(RuntimeAuditCursorInvalidError):
            await service.list(AUDIT_USER, "model", filters, cursor=cursor)


async def test_frozen_watermark_excludes_later_insert(audit_env):
    from bisheng.open_api.domain.models.model_call_record import ModelCallRecord

    service, _, sessions, _ = audit_env
    page = await service.list(AUDIT_USER, "model", {"time_range": "all"}, limit=1)
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
    rest = await service.list(AUDIT_USER, "model", {"time_range": "all"}, limit=100, cursor=page["next_cursor"])
    assert [i["id"] for i in rest["items"]] == [3, 2, 1]


async def test_capability_and_access_snapshots_without_live_joins(audit_env):
    service, _, _, _ = audit_env
    cap = await service.list(AUDIT_USER, "capability", {"time_range": "all"})
    access = await service.list(AUDIT_USER, "access", {"time_range": "all"})
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
        await service.list(AUDIT_USER, "access", filters)


async def test_historical_candidates_scope_and_disabled(audit_env, monkeypatch):
    from bisheng.common.errcode.app_factory import AppFactoryNotEnabledError
    from bisheng.common.services.config_service import settings

    service, _, _, _ = audit_env
    options = await service.candidates(AUDIT_USER, "capability", "app", {"time_range": "all"})
    assert options["items"][0]["label"] == "Deleted app"
    monkeypatch.setattr(settings.app_runtime, "enabled", False)
    with pytest.raises(AppFactoryNotEnabledError):
        await service.list(AUDIT_USER, "model", {})


async def test_scope_rejects_non_session_and_fresh_non_admin(monkeypatch):
    """AC-52/53 + F114: a typed session still needs current audit-entry qualification."""
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
        return SimpleNamespace(is_global_super=False, user_id=7, tenant_id=1)

    async def own(*args, **kwargs):
        return SimpleNamespace(tenant_id=1)

    async def editable(*args):
        return ("app-a",)

    async def no_menu(*args):
        raise RuntimeAuditAccessDeniedError()

    async def denied(*args):
        return False

    monkeypatch.setattr(RuntimeAuditRepository, "current_user", account)
    monkeypatch.setattr(UserPayload, "init_login_user", fresh)
    monkeypatch.setattr(UserPayload, "assert_effective_web_menu_contains", no_menu)
    monkeypatch.setattr(module, "resolve_management_scope", own)
    monkeypatch.setattr(module, "editable_app_ids", editable)
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


async def test_global_super_uses_one_current_tenant_without_http_middleware(monkeypatch):
    """AC-52/56 + F114: use one concrete tenant, with own-tenant fallback."""
    from types import SimpleNamespace

    from bisheng.app_governance.domain.repositories.runtime_audit_repository import RuntimeAuditRepository
    from bisheng.app_governance.domain.services import runtime_audit_scope as module
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.errcode.app_governance import RuntimeAuditAccessDeniedError
    from bisheng.core.context.tenant import tenant_execution_scope

    async def account(*args):
        return SimpleNamespace(token_version=0)

    async def fresh(**kwargs):
        return SimpleNamespace(is_global_super=True, user_id=7, tenant_id=1)

    async def own(*args, **kwargs):
        return SimpleNamespace(tenant_id=1)

    async def editable(user, tenant):
        return (f"tenant-{tenant}-app",)

    monkeypatch.setattr(RuntimeAuditRepository, "current_user", account)
    monkeypatch.setattr(UserPayload, "init_login_user", fresh)
    monkeypatch.setattr(module, "resolve_management_scope", own)
    monkeypatch.setattr(module, "editable_app_ids", editable)
    user = UserPayload(user_id=7, user_name="super", tenant_id=1, user_role=[])
    with tenant_execution_scope(1):
        assert (await module.resolve_scope(user)).tenant_id == 1
    with tenant_execution_scope(2):
        scope = await module.resolve_scope(user)
        assert scope.tenant_id == 2 and scope.authorized_app_ids == ("tenant-2-app",)
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
        AUDIT_USER,
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
    app.dependency_overrides[UserPayload.get_login_user] = lambda: AUDIT_USER

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
