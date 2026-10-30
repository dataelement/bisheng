"""F114 preview credentials and signed visitors must form one current pair."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, OpenApiPrincipal


def principal(**kw):
    return OpenApiPrincipal(
        credential_id=7,
        actor_kind="hosted_app",
        actor_id=2,
        actor_name="app",
        subject_ref="app",
        tenant_id=3,
        resource_owner_user_id=81,
        scopes=frozenset(),
        mode="S",
        authorization_subject_type="user",
        authorization_subject_id=81,
        effective_user_id=None,
        **kw,
    )


@pytest.fixture
def binding(monkeypatch):
    from bisheng.open_api.domain.services import preview_context as mod

    context = SimpleNamespace(
        tenant_id=3,
        app_id="app",
        version_id="pending",
        viewer_user_id=42,
        capability_user_id=81,
        purpose="approval",
        session_id="preview",
        credential_id=7,
        operation_id="op",
    )
    port = SimpleNamespace(resolve=AsyncMock(return_value=context))
    monkeypatch.setattr(mod, "_provider", port)
    return mod, port, context


async def test_pair_projects_only_verified_preview_references(binding):
    mod, _port, _context = binding
    verified = SimpleNamespace(user_id=42, preview_session="preview", expires_at=9999999999)
    result = await mod.bind_preview_principal(principal(), verified)
    assert result.preview_version_id == "pending" and result.preview_viewer_user_id == 42
    assert result.preview_capability_user_id == 81
    snapshot = OpenApiExecutionSnapshot.from_principal(result, trace_id="trace")
    assert snapshot.preview_session_id == "preview" and snapshot.preview_obo_expires_at == 9999999999


@pytest.mark.parametrize(
    "verified",
    [
        None,
        SimpleNamespace(user_id=43, preview_session="preview", expires_at=9999999999),
        SimpleNamespace(user_id=42, preview_session="other", expires_at=9999999999),
        SimpleNamespace(user_id=42, preview_session=None, expires_at=9999999999),
    ],
)
async def test_preview_missing_or_mixed_visitor_refused(binding, verified):
    mod, _port, _context = binding
    with pytest.raises(OpenApiCredentialInvalidError):
        await mod.bind_preview_principal(principal(), verified)


async def test_formal_app_self_unchanged_and_preview_obo_cannot_cross(binding):
    mod, port, _context = binding
    port.resolve.return_value = None
    assert await mod.bind_preview_principal(principal(), None) == principal()
    with pytest.raises(OpenApiCredentialInvalidError):
        await mod.bind_preview_principal(
            principal(), SimpleNamespace(user_id=42, preview_session="preview", expires_at=9999999999)
        )


@pytest.fixture
async def credential_db(monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject
    from bisheng.database.models.app import App
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.domain.models.api_credential import ApiCredential
    from bisheng.open_api.domain.repositories import credential_repository

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        for model in (App, HostedAppSubject, ApiCredential, AuditLog):
            await conn.run_sync(model.__table__.create)

    @asynccontextmanager
    async def factory():
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(credential_repository, "get_async_db_session", factory)
    async with factory() as session:
        session.add(App(id="app", slug="app", name="App", tenant_id=3, owner_user_id=81, state="draft"))
        session.add(HostedAppSubject(id=1, app_id="app"))
        for ident in (7, 8):
            session.add(
                ApiCredential(
                    id=ident,
                    tenant_id=3,
                    subject_kind="hosted_app",
                    subject_id=1,
                    name="preview" if ident == 7 else "production",
                    key_prefix="bs-app-",
                    last4="test",
                    token_hash=str(ident),
                    scopes=[],
                )
            )
        await session.commit()
    yield factory, credential_repository.CredentialRepository
    await engine.dispose()


async def test_preview_revoke_is_exact_audited_and_rollbackable(credential_db):
    """AC-50、AC-53、AC-69: one preview key, no subject-wide revocation or independent commit."""
    from sqlmodel import select

    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.database.models.audit_log import AuditLog
    from bisheng.open_api.application.runtime_credentials import revoke_preview_credential
    from bisheng.open_api.domain.models.api_credential import ApiCredential

    factory, repo = credential_db
    kwargs = {"credential_id": 7, "tenant_id": 3, "subject_id": 1, "reason": "manual"}
    with tenant_execution_scope(3):
        async with factory() as session:
            assert await revoke_preview_credential(session, **kwargs)
            await session.rollback()
        assert await repo.preview_credential_is_live(7, 3, "app")
        async with factory() as session:
            assert (await session.exec(select(AuditLog))).all() == []
            assert await revoke_preview_credential(session, **kwargs)
            assert not await revoke_preview_credential(session, **kwargs)
            await session.commit()
        async with factory() as session:
            assert (await session.get(ApiCredential, 8)).revoked_at is None
            logs = (await session.exec(select(AuditLog))).all()
            assert len(logs) == 1 and logs[0].target_id == "7"
        assert not await repo.preview_credential_is_live(7, 3, "app")
        assert await repo.preview_credential_is_live(8, 3, "app")


@pytest.mark.parametrize("tenant,subject", [(4, 1), (3, 2)])
async def test_preview_revoke_mixed_identity_has_no_effect(credential_db, tenant, subject):
    """AC-50、AC-69: a cross-tenant or mixed subject reference never revokes a key."""
    from bisheng.core.context.tenant import tenant_execution_scope
    from bisheng.open_api.domain.models.api_credential import ApiCredential

    factory, repo = credential_db
    with tenant_execution_scope(3):
        async with factory() as session:
            with pytest.raises(ValueError, match="preview_credential_mismatch"):
                await repo.revoke_preview_credential(
                    session, credential_id=7, tenant_id=tenant, subject_id=subject, reason="manual"
                )
            assert (await session.get(ApiCredential, 7)).revoked_at is None
        assert not await repo.preview_credential_is_live(7, 4, "app")
        assert not await repo.preview_credential_is_live(7, 3, "other-app")
