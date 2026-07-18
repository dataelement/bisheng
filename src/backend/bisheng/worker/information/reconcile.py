"""F031 — daily reconcile of information-source subscriptions across tenants.

Thin Celery Beat wrapper (spec §7.1). It enumerates active tenants and runs the per-tenant
reconcile business logic (``ChannelService.reconcile_information_subscriptions``) under each
tenant's context. No business logic lives here — that is owned by the domain service, so the
``worker → service → repo`` layering holds and the logic stays unit-testable without Celery.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from loguru import logger

from bisheng.core.context.tenant import DEFAULT_TENANT_ID, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery


@bisheng_celery.task
def reconcile_all_tenants():
    """Beat entrypoint: reconcile information-source subscriptions for every active tenant."""
    run_async_task(_reconcile_all_tenants_async)


async def _active_tenant_ids() -> list[int]:
    """Active tenant ids to reconcile.

    Falls back to the default tenant when multi-tenancy is disabled (single-tenant
    deployments behave as tenant_id=1).
    """
    from bisheng.common.services.config_service import settings

    if not settings.multi_tenant.enabled:
        return [DEFAULT_TENANT_ID]

    from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao

    child_ids = await TenantDao.aget_children_ids_active()
    return [ROOT_TENANT_ID, *child_ids]


@asynccontextmanager
async def _channel_service_session():
    """Open an async DB session and build a ChannelService for reconcile use.

    Only the channel / channel_info_source repositories are needed by the reconcile
    method, so the other collaborators are left unset.
    """
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
    from bisheng.channel.domain.services.channel_service import ChannelService
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        yield ChannelService(
            channel_repository=ChannelRepositoryImpl(session),
            space_channel_member_repository=None,
            channel_info_source_repository=ChannelInfoSourceRepositoryImpl(session),
        )


async def _reconcile_one_tenant(tenant_id: int) -> None:
    set_current_tenant_id(tenant_id)
    async with _channel_service_session() as service:
        stats = await service.reconcile_information_subscriptions()
        logger.info("information subscription reconcile tenant=%s stats=%s", tenant_id, stats)


async def _reconcile_all_tenants_async() -> None:
    tenant_ids = await _active_tenant_ids()
    for tenant_id in tenant_ids:
        try:
            await _reconcile_one_tenant(tenant_id)
        except Exception:
            # Isolate per-tenant failures so one bad tenant never blocks the rest.
            logger.exception("information subscription reconcile failed for tenant=%s", tenant_id)
