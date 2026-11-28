"""Lazy native DSH composition without external identity or seat services."""

import asyncio
from dataclasses import dataclass

from fastapi import Depends, Request

from bisheng.common.errcode.dsh import DshDshDisabledError
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.repositories.local_session import DshSessionRepository
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh.domain.services.authorization import DshAuthorizationService
from bisheng.dsh.domain.services.identity import IdentityService
from bisheng.dsh.domain.services.local_session import DshLocalSessionService
from bisheng.dsh.domain.services.settings import DshSettingsService
from bisheng.dsh.infrastructure.token_keys import ISSUER, LocalTokenKeys


def get_settings() -> DshSettings:
    from bisheng.common.services.config_service import settings

    return settings.dsh


@dataclass
class DshRuntime:
    settings: DshSettings
    identity: IdentityService
    access: DshAccessService
    sessions: DshLocalSessionService
    authorizations: DshAuthorizationService
    platform_sessions: object | None = None

    async def close(self):
        models = getattr(self, "models", None)
        if models is not None:
            await models.close()


async def get_logout_runtime(request: Request, config: DshSettings = Depends(get_settings)) -> DshRuntime:
    runtime = getattr(request.app.state, "dsh_runtime", None)
    if runtime is not None:
        return runtime
    if not hasattr(request.app.state, "dsh_init_lock"):
        request.app.state.dsh_init_lock = asyncio.Lock()
    async with request.app.state.dsh_init_lock:
        runtime = getattr(request.app.state, "dsh_runtime", None)
        if runtime is not None:
            return runtime
        runtime = await build_runtime(config)
        injected = getattr(request.app.state, "platform_auth_service", None)
        if injected is not None:
            runtime.platform_sessions = injected
            runtime.access.platform_auth = injected
        request.app.state.dsh_runtime = runtime
        return runtime


async def get_runtime(request: Request, config: DshSettings = Depends(get_settings)) -> DshRuntime:
    if not config.enabled:
        raise DshDshDisabledError()
    await DshSettingsService().require_enabled()
    return await get_logout_runtime(request, config)


async def build_runtime(config: DshSettings) -> DshRuntime:
    """Compose the same session validator for HTTP requests and queued work."""
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.dsh.operations_runtime import repository_scope
    from bisheng.oauth2_provider.domain.services.client_service import OAuth2ClientService
    from bisheng.oauth2_provider.runtime import oauth2_db_session
    from bisheng.user.domain.services.dsh_avatar import read_dsh_avatar

    redis = (await get_redis_client()).async_connection
    authorizations = DshAuthorizationService(
        redis,
        config.platform_public_url,
        oauth2_clients=OAuth2ClientService(oauth2_db_session),
    )
    identity = IdentityService(
        TicketRepository(redis), CurrentIdentityRecords(), authorizations, avatar_reader=read_dsh_avatar
    )
    keys = LocalTokenKeys()
    sessions = DshLocalSessionService(
        lambda: repository_scope(DshSessionRepository),
        identity,
        keys,
        access_seconds=config.access_ttl_seconds,
        session_seconds=config.session_ttl_seconds,
        refresh_grace_seconds=config.refresh_reuse_grace_seconds,
        idle_seconds=config.session_idle_ttl_seconds,
        migrate_idle_sessions=config.session_idle_migrate_existing,
    )
    from bisheng.user.platform_auth_runtime import platform_auth_service

    platform_sessions = platform_auth_service()
    access = DshAccessService(ISSUER, keys, identity, sessions, platform_auth=platform_sessions)
    return DshRuntime(config, identity, access, sessions, authorizations, platform_sessions)
