"""Caller-owned SQL rollback, ready activation and exact preview isolation (AC-50/AC-69)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
from bisheng.common.errcode.app_publish import AppPreviewForbiddenError


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for model in (AppPreviewSession, HostedAppSubject):
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    yield factory
    await engine.dispose()


def values(**kw):
    return {
        "id": "session",
        "tenant_id": 3,
        "app_id": "app",
        "version_id": "version",
        "approver_user_id": 42,
        "purpose": "management",
        "status": "starting",
        "expires_at": datetime.utcnow() + timedelta(hours=1),
        **kw,
    }


async def test_registration_is_not_committed_by_public_port(db):
    from bisheng.app_publish.application import preview_runtime as port

    async with db() as session:
        await port.register(session, values())
        await port.bind_identity(session, "session", operation_id="op", credential_id=7)
        await session.rollback()
    async with db() as session:
        assert (await session.exec(select(AppPreviewSession))).all() == []


async def test_reuse_key_separates_purpose_and_task(db):
    from bisheng.app_publish.application import preview_runtime as port

    async with db() as session:
        await port.register(session, values())
        key = {
            "tenant_id": 3,
            "app_id": "app",
            "version_id": "version",
            "viewer_user_id": 42,
            "purpose": "management",
            "task_id": None,
        }
        assert (await port.find_reusable(session, **key)).session_id == "session"
        assert await port.find_reusable(session, **{**key, "purpose": "approval", "task_id": 9}) is None
        assert await port.find_reusable(session, **{**key, "viewer_user_id": 43}) is None


async def test_ready_and_reclaim_bind_exact_operation_and_one_credential(db, monkeypatch):
    from bisheng.app_publish.application import preview_runtime as port
    from bisheng.open_api.application import runtime_credentials as credentials

    revoke = AsyncMock()
    monkeypatch.setattr(credentials, "revoke_preview_credential", revoke)
    op = SimpleNamespace(id="op", tenant_id=3, app_id="app", version_id="version", payload={"session_id": "session"})
    async with db() as session:
        session.add(HostedAppSubject(id=5, app_id="app"))
        await port.register(session, values())
        with pytest.raises(AppPreviewForbiddenError):
            await port.activate(session, op)
        await port.bind_identity(session, "session", operation_id="op", credential_id=7)
        assert (await port.activate(session, op)).status == "running"
        with pytest.raises(AppPreviewForbiddenError):
            await port.activate(session, SimpleNamespace(**{**vars(op), "id": "other"}))
        await port.close(session, op, reason="manual")
        await port.close(session, op, reason="expired")
        assert revoke.await_count == 1
        assert revoke.call_args.kwargs["credential_id"] == 7
        assert (await session.get(AppPreviewSession, "session")).status == "reclaimed"


async def test_registration_rollback_covers_operation_capacity_identity_and_sealed_environment(monkeypatch):
    from sqlalchemy import event

    from bisheng.app_publish.application import preview_runtime, runtime_delivery
    from bisheng.app_publish.domain.repositories.preview_runtime_repository import PreviewRuntimeRepository
    from bisheng.app_publish.domain.services.preview_access_service import PreviewQualification
    from bisheng.app_runtime.application import preview_operations as api
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation, RuntimeOperation
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeDeliveryRepository
    from bisheng.app_runtime.domain.services.runtime_authorization_service import RuntimeAuthorizationService
    from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
    from bisheng.database.models.app_version import AppVersion
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.domain.models.api_credential import ApiCredential

    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def connect(connection, _):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async with engine.begin() as conn:
        for model in (AppPreviewSession, RuntimeOperation, RuntimeCapacityReservation, ApiCredential, AuditLog):
            await conn.run_sync(model.__table__.create)
    repo = RuntimeDeliveryRepository(factory)
    c = RuntimeDeliveryCoordinator(repository=repo)
    q = PreviewQualification(3, "app", "version", 42, "management")
    app = SimpleNamespace(id="app", tenant_id=3, owner_user_id=81, slug="app", state="draft")
    version = SimpleNamespace(id="version", app_id="app", tenant_id=3, version_no=1, manifest={}, capabilities={})
    monkeypatch.setattr(PreviewRuntimeRepository, "lock_version", AsyncMock())
    monkeypatch.setattr(api, "qualify", AsyncMock(return_value=q))
    monkeypatch.setattr(repo, "get_application", AsyncMock(return_value=app))
    original_get = repo.get

    async def get(model, ident, **kw):
        return version if model is AppVersion else await original_get(model, ident, **kw)

    monkeypatch.setattr(repo, "get", get)
    monkeypatch.setattr(
        RuntimeAuthorizationService, "capture_user", AsyncMock(return_value={"purpose": "management_preview"})
    )
    monkeypatch.setattr(runtime_delivery, "preview_migration_plan", AsyncMock(return_value=[]))
    monkeypatch.setattr(runtime_delivery, "declared_scopes", AsyncMock(return_value=[]))
    monkeypatch.setattr(c, "delivery", AsyncMock(return_value=SimpleNamespace(content={"mode": "image"})))

    async def submit(*args, **kw):
        op = RuntimeOperation(
            id="op",
            tenant_id=3,
            app_id="app",
            scope_key="3/app",
            version_id="version",
            kind="preview",
            node_id="node",
            generation=1,
            owner_epoch=1,
            idempotency_key=kw["key"],
            request_digest="a" * 64,
            deadline=datetime.utcnow() + timedelta(minutes=5),
            payload=kw["payload"],
        )
        await repo.save(op)
        await repo.save(
            RuntimeCapacityReservation(
                tenant_id=3,
                app_id="app",
                operation_id="op",
                node_id="node",
                memory_mb=64,
                cpu_millicores=100,
                purpose="preview",
                state="held",
            )
        )
        return op

    monkeypatch.setattr(c, "submit", submit)

    async def issue(session, **kw):
        session.add(
            ApiCredential(
                id=7,
                tenant_id=3,
                subject_kind="hosted_app",
                subject_id=1,
                name="preview",
                key_prefix="bs-app-",
                last4="test",
                token_hash="test",
                scopes=[],
            )
        )
        session.add(
            AuditLog(
                id=7,
                tenant_id=3,
                operator_id=0,
                operator_name="system",
                operator_tenant_id=3,
                action="open_api.api_key.issue",
                target_type="api_credential",
                target_id="7",
            )
        )
        await preview_runtime.bind_identity(session, kw["session_id"], operation_id="op", credential_id=7)
        return "test-only-token"

    monkeypatch.setattr(preview_runtime, "issue_identity", issue)
    monkeypatch.setattr(c, "inject_environment", AsyncMock(side_effect=ValueError("seal failed")))
    wake = AsyncMock()
    monkeypatch.setattr(c, "wake", wake)

    async def payload(*args):
        return {
            "base_path": "/apps/preview/s",
            "port": 8080,
            "health": {},
            "tier": {"mem": 64, "cpu": 0.1},
            "egress_domains": [],
        }

    from bisheng.core.context.tenant import tenant_execution_scope

    with tenant_execution_scope(3), pytest.raises(ValueError, match="seal failed"):
        await api.start_preview(q, actor=object(), payload_factory=payload, coordinator=c)
    wake.assert_not_awaited()
    async with factory() as session:
        for model in (AppPreviewSession, RuntimeOperation, RuntimeCapacityReservation, ApiCredential, AuditLog):
            assert (await session.exec(select(model))).all() == []
    await engine.dispose()


async def test_preview_payload_expiry_is_utc_on_non_utc_hosts(monkeypatch):
    """AC-50、AC-69: the stamped UTC preview lifetime is independent of host local timezone."""

    from bisheng.app_publish.domain.services.preview_instance_service import PreviewInstanceService

    monkeypatch.setattr(PreviewInstanceService, "_tier_payload", AsyncMock(return_value={"cpu": 0.1, "mem": 64}))
    expiry = datetime(2030, 1, 2, 3, 4, 5)
    app = SimpleNamespace(id="app", slug="app")
    version = SimpleNamespace(id="version", version_no=1, image_ref="image", tier_id="tier", manifest={}, injections={})
    row = SimpleNamespace(session_id="session", expires_at=expiry)
    result = await PreviewInstanceService._start_payload(app, version, row)
    assert result["expires_at"] == int(expiry.replace(tzinfo=UTC).timestamp())


async def test_legacy_null_sessions_are_not_adopted_or_starve_new_expiry_sweep(db, monkeypatch):
    """AC-50、AC-69、AC-71: legacy preview cleanup is a pre-upgrade gate, never an implicit adoption."""
    from bisheng.app_publish.domain.repositories import preview_runtime_repository as mod

    monkeypatch.setattr(mod, "get_async_db_session", db)
    async with db() as session:
        session.add(
            AppPreviewSession(**values(id="legacy", purpose=None, expires_at=datetime.utcnow() - timedelta(days=1)))
        )
        session.add(AppPreviewSession(**values(id="current", expires_at=datetime.utcnow() - timedelta(seconds=1))))
        await session.commit()
    rows = await mod.PreviewRuntimeRepository.sweep_candidates(expired=True)
    assert [row.session_id for row in rows] == ["current"]
    async with db() as session:
        legacy = await session.get(AppPreviewSession, "legacy")
        assert legacy.purpose is None and legacy.credential_id is None and legacy.operation_id is None
