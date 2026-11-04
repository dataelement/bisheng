"""Delete personal skill objects that no skill row still points at.

Beat sends one child task per tenant. The child receives ``tenant_id`` in its
arguments and in the Celery header; ``worker/tenant_context.py`` restores
``current_tenant_id`` before the body runs. The body does not switch tenants.
A failure is logged and does not change a delete the user already received.
"""

from __future__ import annotations

import re

from loguru import logger

from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
from bisheng.worker._asyncio_utils import run_async_task
from bisheng.worker.main import bisheng_celery

PERSONAL_PREFIX = "linsight/personal-skills"
_HASH_ZIP = re.compile(r"^[0-9a-f]{64}\.zip$")


def tenant_personal_prefix(tenant_id: int) -> str:
    return f"{PERSONAL_PREFIX}/{tenant_id}/"


def content_hash_of(object_name: str, tenant_id: int) -> str | None:
    """Hash of one personal bundle under this tenant, or None when it is not one."""
    prefix = tenant_personal_prefix(tenant_id)
    if not object_name.startswith(prefix):
        return None
    filename = object_name.rsplit("/", 1)[-1]
    if _HASH_ZIP.fullmatch(filename) is None:
        return None
    return filename[:-4]


def orphan_object_keys(object_names, tenant_id: int, live_hashes: set[str]) -> list[str]:
    """Personal objects of this tenant whose hash no skill row points at.

    ``linsight/skills/`` and every other tenant's prefix are left out even when
    they appear in ``object_names``.
    """
    doomed = []
    for name in object_names:
        digest = content_hash_of(name, tenant_id)
        if digest is None or digest in live_hashes:
            continue
        doomed.append(name)
    return doomed


def publish_tenant_sweeps(tenant_ids, publish) -> None:
    """Publish one child per tenant, then put the caller tenant back."""
    for tenant_id in tenant_ids:
        token = set_current_tenant_id(tenant_id)
        try:
            publish(tenant_id)
        finally:
            current_tenant_id.reset(token)


async def run_sweep(tenant_id: int, *, list_objects=None, live_hashes=None, remove=None) -> list[str]:
    """Delete this tenant's orphan bundles. Returns the keys that were removed."""
    if get_current_tenant_id() != tenant_id:
        logger.error("personal skill sweep tenant mismatch arg={} context={}", tenant_id, get_current_tenant_id())
        return []
    list_objects = list_objects or _list_objects
    live_hashes = live_hashes or _live_hashes
    remove = remove or _remove
    try:
        names = list_objects(tenant_id)
        hashes = live_hashes()
        if hasattr(hashes, "__await__"):
            hashes = await hashes
    except Exception:
        logger.exception("personal skill orphan sweep failed tenant_id={}", tenant_id)
        return []
    removed = []
    for key in orphan_object_keys(names, tenant_id, set(hashes)):
        try:
            remove(key)
        except Exception:
            logger.exception("personal skill orphan delete failed key={}", key)
            continue
        removed.append(key)
    return removed


def _list_objects(tenant_id: int) -> list[str]:
    from bisheng.linsight.domain.services.skill_store import SkillStore

    store = SkillStore()
    prefix = tenant_personal_prefix(tenant_id)
    return [
        obj.object_name
        for obj in store.minio.minio_client_sync.list_objects(store._bucket(), prefix=prefix, recursive=True)
    ]


def _remove(object_name: str) -> None:
    from bisheng.linsight.domain.services.skill_store import SkillStore

    store = SkillStore()
    store.minio.remove_object_sync(bucket_name=store._bucket(), object_name=object_name)


async def _live_hashes() -> set[str]:
    """Content hashes of the current tenant's skill rows. No other tenant is read."""
    from sqlmodel import select

    from bisheng.core.context.tenant import strict_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.linsight.domain.models.linsight_skill import LinsightSkill

    with strict_tenant_filter():
        async with get_async_db_session() as session:
            rows = (await session.exec(select(LinsightSkill.content_hash))).all()
    return {row for row in rows if row}


async def _active_tenant_ids() -> list[int]:
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import DEFAULT_TENANT_ID

    if not settings.multi_tenant.enabled:
        return [DEFAULT_TENANT_ID]
    from bisheng.database.models.tenant import TenantDao

    return sorted(await TenantDao.aget_active_ids())


def _publish_one(tenant_id: int) -> None:
    sweep_personal_skill_orphans.apply_async(args=[tenant_id], headers={"tenant_id": tenant_id})


async def _dispatch() -> None:
    publish_tenant_sweeps(await _active_tenant_ids(), _publish_one)


@bisheng_celery.task(name="bisheng.worker.linsight.personal_skill_sweep.dispatch_personal_skill_orphan_sweep")
def dispatch_personal_skill_orphan_sweep() -> None:
    try:
        run_async_task(_dispatch)
    except Exception:
        logger.exception("personal skill orphan dispatch failed")


@bisheng_celery.task(name="bisheng.worker.linsight.personal_skill_sweep.sweep_personal_skill_orphans")
def sweep_personal_skill_orphans(tenant_id: int) -> list[str]:
    try:
        return run_async_task(lambda: run_sweep(tenant_id))
    except Exception:
        logger.exception("personal skill orphan sweep failed tenant_id={}", tenant_id)
        return []
