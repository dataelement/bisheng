import random

from loguru import logger

from bisheng.channel.domain.services.information_subscription_reconcile_service import (
    DesiredSubscriptionSnapshot,
    InformationSubscriptionReconcileService,
)
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.information.redis_lock import InformationRedisLock
from bisheng.worker.main import bisheng_celery


def _jitter_seconds() -> int:
    from bisheng.common.services.config_service import settings

    return settings.get_intelligence_center_conf().information_sync_jitter_seconds


@bisheng_celery.task
def dispatch_information_subscription_reconcile() -> None:
    reconcile_information_subscriptions.apply_async(countdown=random.randint(0, _jitter_seconds()))


@bisheng_celery.task
def reconcile_information_subscriptions() -> None:
    lock = _new_platform_lock()
    if not lock.acquire():
        logger.warning(
            "information subscription reconcile skipped lock_unavailable redis_available={}",
            lock.redis_available,
        )
        return
    try:
        run_async_task(lambda: _reconcile_information_subscriptions_async(lock))
    finally:
        lock.release()


def _new_platform_lock() -> InformationRedisLock:
    from bisheng.core.cache.redis_manager import get_redis_client_sync

    return InformationRedisLock(
        get_redis_client_sync().connection,
        "information:subscription-reconcile",
        ttl_seconds=7200,
    )


async def _active_tenant_ids() -> list[int]:
    from bisheng.common.services.config_service import settings

    if not settings.multi_tenant.enabled:
        return [DEFAULT_TENANT_ID]
    from bisheng.database.models.tenant import TenantDao

    return sorted(await TenantDao.aget_active_ids())


async def _read_tenant_source_ids(tenant_id: int) -> set[str]:
    from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
    from bisheng.core.database import get_async_db_session

    async with get_async_db_session() as session:
        return await ChannelRepositoryImpl(session).find_all_referenced_source_ids()


async def _collect_desired_snapshot() -> DesiredSubscriptionSnapshot:
    try:
        tenant_ids = await _active_tenant_ids()
    except Exception:
        logger.exception("information subscription active tenant enumeration failed")
        return DesiredSubscriptionSnapshot(ids=frozenset(), complete=False)
    desired: set[str] = set()
    failed_tenants: list[int] = []
    for tenant_id in tenant_ids:
        token = set_current_tenant_id(tenant_id)
        try:
            desired.update(await _read_tenant_source_ids(tenant_id))
        except Exception:
            failed_tenants.append(tenant_id)
            logger.exception("information subscription desired read failed tenant_id={}", tenant_id)
        finally:
            current_tenant_id.reset(token)
    return DesiredSubscriptionSnapshot(
        ids=frozenset(desired),
        complete=not failed_tenants,
        failed_tenants=tuple(failed_tenants),
    )


async def _reconcile_information_subscriptions_async(lock_guard=None) -> dict:
    from bisheng.channel.domain.repositories.implementations.channel_info_source_repository_impl import (
        ChannelInfoSourceRepositoryImpl,
    )
    from bisheng.core.database import get_async_db_session
    from bisheng.core.external.bisheng_information_client.bisheng_information_manager import (
        get_bisheng_information_client,
    )

    desired = await _collect_desired_snapshot()
    client = await get_bisheng_information_client()
    async with get_async_db_session() as session:
        service = InformationSubscriptionReconcileService(
            client,
            ChannelInfoSourceRepositoryImpl(session),
        )
        return await service.reconcile(desired, _collect_desired_snapshot, lock_guard=lock_guard)
