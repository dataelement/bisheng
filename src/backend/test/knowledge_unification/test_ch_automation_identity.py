"""Automation resolves real active users/members/roles, not a synthetic JWT.

覆盖 AC: AC-35, AC-87, AC-89, AC-91. Identity tables and the existing resolver
are real; only the global-super permission transport is stubbed.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.channel.application import automation_identity as identity_module
from bisheng.channel.application.automation_identity import resolve_channel_automation_identity
from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.database.models.tenant import Tenant, UserTenant
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.domain.services.permission_action_service import PermissionActor
from bisheng.resource_reference.application import read_identity
from bisheng.user.domain.models import user_role as role_module
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole
from bisheng.user.domain.repositories import runtime_identity as person_repository
from bisheng.utils import http_middleware
from test.knowledge_unification import test_ch_repository as fixtures

store = fixtures.store
tenant = fixtures.tenant


@pytest.fixture
async def people(store, monkeypatch):
    metadata = sa.MetaData()
    for model in (User, Tenant, UserTenant, UserRole):
        sa.Table(
            model.__tablename__,
            metadata,
            *[
                sa.Column(
                    c.name,
                    c.type.copy(),
                    primary_key=c.primary_key,
                    nullable=c.nullable,
                    server_default=sa.text("CURRENT_TIMESTAMP")
                    if c.name in {"create_time", "update_time", "password_update_time"}
                    else c.server_default,
                )
                for c in model.__table__.columns
            ],
        )
    async with store.begin() as connection:
        await connection.run_sync(metadata.create_all)

    @asynccontextmanager
    async def sessions():
        async with AsyncSession(store, expire_on_commit=False) as session:
            yield session

    async with sessions() as session, session.begin():
        session.add(User(user_id=7, user_name="actual", password="not-a-credential", token_version=12))
        session.add(Tenant(id=101, tenant_code="t101", tenant_name="actual", status="active"))
        session.add(Tenant(id=202, tenant_code="t202", tenant_name="other", status="active"))
        session.add(UserTenant(user_id=7, tenant_id=101, is_active=1, status="active"))
        session.add_all([UserRole(id=value, user_id=7, role_id=value) for value in (4, 6)])
    monkeypatch.setattr(person_repository, "get_async_db_session", sessions)
    monkeypatch.setattr(role_module, "get_async_db_session", sessions)
    monkeypatch.setattr(http_middleware, "_check_is_global_super", AsyncMock(return_value=False))
    monkeypatch.setattr(
        read_identity,
        "resolve_permission_actor",
        AsyncMock(
            side_effect=lambda user: (
                get_current_permission_actor() or PermissionActor(tenant_id=101, user_id=user.user_id)
            )
        ),
    )
    return sessions


async def test_automation_proof_requires_original_restored_object_source_and_full_environment(people):
    async with people() as session:
        identity = await resolve_channel_automation_identity(session, "own", "own", tenant_id=101)
        await identity_module.assert_channel_automation_identity(identity, "own", "own", tenant_id=101)
        with pytest.raises(PermissionDeniedError):
            await identity_module.assert_channel_automation_identity(identity.model_copy(), "own", "own", tenant_id=101)
        with pytest.raises(PermissionDeniedError):
            await identity_module.assert_channel_automation_identity(identity, "own", "foreign", tenant_id=101)
        identity.user_role.append(999)
        with pytest.raises(PermissionDeniedError):
            await identity_module.assert_channel_automation_identity(identity, "own", "own", tenant_id=101)


async def test_ambient_actor_cannot_inflate_restored_person_privileges(people):
    token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=7, super_admin=True))
    try:
        async with people() as session:
            with pytest.raises(PermissionDeniedError):
                await resolve_channel_automation_identity(session, "own", "own", tenant_id=101)
    finally:
        reset_current_permission_actor(token)


async def test_actual_identity_restores_full_roles_without_fabricating_web_credential(people):
    async with people() as session:
        identity = await resolve_channel_automation_identity(session, "own", "own", tenant_id=101)
        assert (identity.user_id, identity.tenant_id, identity.token_version) == (7, 101, 12)
        assert identity.user_name == "actual" and set(identity.user_role) == {4, 6}
        assert identity._runtime_credential_reference is None
        assert get_current_tenant_id() == 101


@pytest.mark.parametrize(
    "bad",
    [
        "disabled_user",
        "inactive_member",
        "disabled_member",
        "disabled_tenant",
        "no_member",
        "ambiguous",
        "moved_tenant",
    ],
)
async def test_current_user_membership_and_tenant_are_not_assumed_from_old_config(people, bad):
    async with people() as session, session.begin():
        if bad == "disabled_user":
            await session.execute(sa.update(User).where(User.user_id == 7).values(delete=1))
        elif bad == "disabled_tenant":
            await session.execute(sa.update(Tenant).where(Tenant.id == 101).values(status="disabled"))
        elif bad == "no_member":
            await session.execute(sa.delete(UserTenant).where(UserTenant.user_id == 7))
        elif bad == "ambiguous":
            session.add(UserTenant(user_id=7, tenant_id=202, is_active=1, status="active"))
        else:
            values = (
                {"is_active": None}
                if bad == "inactive_member"
                else {"status": "disabled"}
                if bad == "disabled_member"
                else {"tenant_id": 202}
            )
            await session.execute(sa.update(UserTenant).where(UserTenant.user_id == 7).values(**values))
    async with people() as session:
        with pytest.raises(PermissionDeniedError):
            await resolve_channel_automation_identity(session, "own", "own", tenant_id=101)
    assert get_current_tenant_id() == 101


@pytest.mark.parametrize(
    "bad", ["config_missing", "wrong_parent", "wrong_tenant", "missing_context", "actor", "open", "public"]
)
async def test_internal_adapter_rejects_unbound_inputs_and_ambient_identity_without_clearing_it(
    people, monkeypatch, bad
):
    channel, config, tenant_id = "own", "own", 101
    actor_token = tenant_token = None
    if bad == "config_missing":
        config = "missing"
    elif bad == "wrong_parent":
        config = "foreign"
    elif bad == "wrong_tenant":
        tenant_id = 202
    elif bad == "missing_context":
        tenant_token = set_current_tenant_id(None)
    elif bad == "actor":
        actor_token = set_current_permission_actor(PermissionActor(tenant_id=101, user_id=99))
    else:
        method = "get_current_open_api_principal" if bad == "open" else "get_current_public_api_principal"
        monkeypatch.setattr(identity_module, method, lambda: object())
    try:
        async with people() as session:
            with pytest.raises(PermissionDeniedError):
                await resolve_channel_automation_identity(session, channel, config, tenant_id=tenant_id)
    finally:
        if actor_token is not None:
            reset_current_permission_actor(actor_token)
        if tenant_token is not None:
            current_tenant_id.reset(tenant_token)
