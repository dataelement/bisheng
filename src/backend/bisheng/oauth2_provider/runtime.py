"""Lazy runtime wiring for the OAuth 2.0 / OIDC Provider module."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import Request

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_sync_db_session
from bisheng.oauth2_provider.domain.services.auth_service import OAuth2AuthService, OAuth2UserIdentity
from bisheng.oauth2_provider.domain.services.client_service import OAuth2ClientService
from bisheng.oauth2_provider.domain.services.exchange_service import OAuth2ExchangeService
from bisheng.oauth2_provider.domain.services.platform_exchange_service import OAuth2PlatformExchangeService
from bisheng.oauth2_provider.infrastructure.code_store import OAuth2CodeStore
from bisheng.oauth2_provider.infrastructure.key_service import OAuth2KeyService
from bisheng.user.application.oauth_exchange import validate_platform_exchange_reference


@contextmanager
def oauth2_db_session():
    with get_sync_db_session() as db, db.begin():
        yield db


async def lookup_user_identity(tenant_id: int, user_id: int) -> OAuth2UserIdentity | None:
    def _query() -> OAuth2UserIdentity | None:
        from sqlmodel import select

        from bisheng.database.models.tenant import Tenant, UserTenant
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            with oauth2_db_session() as db:
                user = db.exec(select(User).where(User.user_id == user_id)).first()
                if user is None:
                    return None
                # User rows are natural people; service accounts have a separate table.
                # Visibility of Root/shared resources does not imply tenant membership.
                membership = db.exec(
                    select(UserTenant).where(
                        UserTenant.user_id == user_id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.is_active == 1,
                        UserTenant.status == "active",
                    )
                ).first()
                if membership is None:
                    return None
                tenant = db.exec(select(Tenant).where(Tenant.id == tenant_id)).first()
                user_active = int(getattr(user, "delete", 0) or 0) == 0
                tenant_active = tenant is not None and getattr(tenant, "status", "active") == "active"
                username = getattr(user, "user_name", "") or ""
                display_name = (getattr(user, "nickname", None) or "").strip() or username
                email = getattr(user, "email", None)
                tenant_name = (getattr(tenant, "tenant_name", None) or "").strip() if tenant else f"Tenant {tenant_id}"
                return OAuth2UserIdentity(
                    user_id=int(user.user_id),
                    tenant_id=int(tenant_id),
                    username=username,
                    display_name=display_name,
                    email=email,
                    tenant_name=tenant_name or f"Tenant {tenant_id}",
                    active=bool(user_active and tenant_active and username.strip()),
                )

    return await asyncio.to_thread(_query)


@dataclass
class OAuth2ProviderRuntime:
    clients: OAuth2ClientService
    auth: OAuth2AuthService
    keys: OAuth2KeyService
    exchange: OAuth2ExchangeService | None = None
    platform_exchange: OAuth2PlatformExchangeService | None = None


async def build_oauth2_runtime() -> OAuth2ProviderRuntime:
    from bisheng.core.cache.redis_manager import get_redis_client

    redis = (await get_redis_client()).async_connection
    keys = OAuth2KeyService()
    clients = OAuth2ClientService(oauth2_db_session)
    code_store = OAuth2CodeStore(redis)
    auth = OAuth2AuthService(
        clients=clients,
        code_store=code_store,
        keys=keys,
        session_factory=oauth2_db_session,
        identity_lookup=lookup_user_identity,
    )
    exchange = OAuth2ExchangeService(
        clients=clients, keys=keys, session_factory=oauth2_db_session, identity_lookup=lookup_user_identity
    )
    platform_exchange = OAuth2PlatformExchangeService(
        keys=keys,
        session_factory=oauth2_db_session,
        identity_lookup=lookup_user_identity,
        platform_validator=validate_platform_exchange_reference,
    )
    exchange._platform_validator = platform_exchange.validate_claims
    auth._exchange_validator = exchange.validate_exchange_claims
    auth._consent_recorder = platform_exchange.record_consent
    return OAuth2ProviderRuntime(
        clients=clients, auth=auth, keys=keys, exchange=exchange, platform_exchange=platform_exchange
    )


async def get_oauth2_runtime(request: Request) -> OAuth2ProviderRuntime:
    runtime = getattr(request.app.state, "oauth2_provider_runtime", None)
    if runtime is not None:
        return runtime
    if not hasattr(request.app.state, "oauth2_provider_init_lock"):
        request.app.state.oauth2_provider_init_lock = asyncio.Lock()
    async with request.app.state.oauth2_provider_init_lock:
        runtime = getattr(request.app.state, "oauth2_provider_runtime", None)
        if runtime is not None:
            return runtime
        runtime = await build_oauth2_runtime()
        request.app.state.oauth2_provider_runtime = runtime
        return runtime
