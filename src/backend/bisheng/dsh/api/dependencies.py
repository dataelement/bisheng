"""Lazy application-owned DSH dependencies; the deployment-disabled probe performs no IO."""

import asyncio
from dataclasses import dataclass

import httpx
from fastapi import Depends, Request

from bisheng.common.errcode.dsh import DshDshDisabledError
from bisheng.dsh.config import DshSettings
from bisheng.dsh.domain.repositories.identities import CurrentIdentityRecords
from bisheng.dsh.domain.repositories.tickets import TicketRepository
from bisheng.dsh.domain.services.access import DshAccessService
from bisheng.dsh.domain.services.identity import IdentityService
from bisheng.dsh.domain.services.settings import DshSettingsService
from bisheng.dsh.infrastructure.gateway_client import GatewayClient
from bisheng.dsh.infrastructure.service_auth import RedisNonceStore, ServiceAuth, ServiceKey
from bisheng.dsh.infrastructure.shared_trust import (
    ACCESS_KEY_ID,
    INBOUND_KEY_ID,
    OUTBOUND_KEY_ID,
    GatewayKeys,
    access_issuer,
    configured_key,
)


def get_settings() -> DshSettings:
    from bisheng.common.services.config_service import settings

    return settings.dsh


@dataclass
class DshRuntime:
    settings: DshSettings
    http: httpx.AsyncClient
    identity: IdentityService
    access: DshAccessService
    gateway: GatewayClient
    inbound_auth: ServiceAuth

    async def close(self):
        models = getattr(self, "models", None)
        if models is not None:
            await models.close()
        await self.http.aclose()


async def get_runtime(request: Request, config: DshSettings = Depends(get_settings)) -> DshRuntime:
    if not config.enabled:
        raise DshDshDisabledError()
    # Check every new request, including requests reusing the initialized runtime.
    # Background projection/settlement does not use this admission dependency.
    await DshSettingsService().require_enabled()
    runtime = getattr(request.app.state, "dsh_runtime", None)
    if runtime is not None:
        return runtime
    if not hasattr(request.app.state, "dsh_init_lock"):
        request.app.state.dsh_init_lock = asyncio.Lock()
    async with request.app.state.dsh_init_lock:
        runtime = getattr(request.app.state, "dsh_runtime", None)
        if runtime is not None:
            return runtime
        from bisheng.core.cache.redis_manager import get_redis_client

        redis = (await get_redis_client()).async_connection
        nonces = RedisNonceStore(redis)
        outbound = ServiceAuth(
            ServiceKey(
                config.installation_id,
                OUTBOUND_KEY_ID,
                configured_key(config.installation_id, OUTBOUND_KEY_ID).hex().encode(),
            ),
            nonces,
        )
        inbound = ServiceAuth(
            ServiceKey(
                config.installation_id,
                INBOUND_KEY_ID,
                configured_key(config.installation_id, INBOUND_KEY_ID).hex().encode(),
            ),
            nonces,
        )
        http = httpx.AsyncClient(verify=True, follow_redirects=False)
        gateway = GatewayClient(config.gateway_internal_url, outbound, http, config.introspection_timeout_seconds)
        identity = IdentityService(
            config.installation_id, TicketRepository(redis, config.installation_id), CurrentIdentityRecords(), gateway
        )
        access = DshAccessService(
            config.installation_id,
            access_issuer(config.installation_id),
            GatewayKeys(configured_key(config.installation_id, ACCESS_KEY_ID)),
            identity,
            gateway,
        )
        runtime = DshRuntime(config, http, identity, access, gateway, inbound)
        request.app.state.dsh_runtime = runtime
        return runtime
