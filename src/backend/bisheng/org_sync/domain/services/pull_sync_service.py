"""Console-triggered pull sync for a stored ``org_sync_config`` row.

Fetches departments + members through the configured provider and applies them
through ``apply_wecom_org_snapshot`` — the same implementation the HMAC Gateway
push uses. State, member reconciliation and the ``org_sync_log`` row are
therefore identical whichever trigger fired; only the log's ``trigger_type``
(``manual``) and config id differ.

Runs in a Celery worker, so it owns its tenant context: the config row is read
with the tenant filter bypassed, then the tenant is pinned for the writes.
"""

from __future__ import annotations

import time

from loguru import logger

from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigDisabledError,
    OrgSyncConfigNotFoundError,
    OrgSyncInvalidConfigError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id
from bisheng.org_sync.domain.models.org_sync import OrgSyncConfigDao, decrypt_auth_config
from bisheng.org_sync.domain.providers.base import get_provider
from bisheng.org_sync.domain.services.sync_enqueue_lock import release_enqueue_lock
from bisheng.org_sync.domain.services.wecom_payload import (
    build_department_items,
    build_member_items,
    build_request,
)
from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.sso_sync.domain.services.wecom_org_sync_service import (
    apply_wecom_org_snapshot,
)

# The snapshot endpoint is WeCom-shaped today; other providers need their own
# absent-reconcile semantics before they can be exposed here.
SUPPORTED_PROVIDERS = frozenset({WECOM_SOURCE})


def ensure_runnable(config) -> None:
    """Reject a config that cannot be synced right now.

    Shared by the API (fail fast before queueing) and the task (defence in
    depth) so the rules cannot drift apart; raises the 220xx business errors.
    """
    if config is None or config.status == "deleted":
        raise OrgSyncConfigNotFoundError()
    if config.provider not in SUPPORTED_PROVIDERS:
        raise OrgSyncInvalidConfigError(
            msg=f"Manual sync supports {sorted(SUPPORTED_PROVIDERS)}; config provider is {config.provider}"
        )
    if config.status != "active":
        raise OrgSyncConfigDisabledError()


async def run_pull_sync(
    config_id: int,
    *,
    trigger_user: int | None = None,
    request_ip: str = "",
    enqueue_token: str | None = None,
) -> dict:
    """Fetch one config's upstream org and apply it. Returns a summary dict.

    Raises ``OrgSync*Error`` (220xx) for not-found / disabled / unsupported /
    already-running, so the caller can surface the business code.

    ``enqueue_token`` is the Redis lock token taken by the API before queueing;
    it is released in ``finally`` so the button unlocks as soon as the run ends
    (the TTL only covers a crashed worker).
    """
    with bypass_tenant_filter():
        config = await OrgSyncConfigDao.aget_by_id(config_id)
    ensure_runnable(config)
    # CAS guard: two clicks / a cron run landing together must not interleave.
    if not await OrgSyncConfigDao.aset_sync_status(config.id, "idle", "running"):
        raise OrgSyncAlreadyRunningError()

    token = current_tenant_id.set(int(config.tenant_id or 1))
    try:
        auth_config = decrypt_auth_config(config.auth_config)
        auth_config["_config_id"] = config.id
        provider = get_provider(config.provider, auth_config)
        departments = await provider.fetch_departments()
        members = await provider.fetch_members()
        logger.info(
            "org sync (manual): config_id={} fetched departments={} members={}",
            config.id,
            len(departments),
            len(members),
        )

        ts = int(time.time())
        payload = build_request(
            build_department_items(departments),
            build_member_items(members, ts),
            ts,
            full_snapshot=True,
        )
        result = await apply_wecom_org_snapshot(
            payload,
            request_ip=request_ip,
            trigger_type="manual",
            config_id=config.id,
            trigger_user=trigger_user,
        )
        dept = result.department_result
        summary = {
            "config_id": config.id,
            "departments": len(departments),
            "members": len(members),
            "dept_updated": dept.applied_upsert,
            "dept_archived": dept.applied_remove,
            "member_ok": result.member_sync_ok,
            "member_fail": result.member_sync_fail,
            "absent_disabled": result.absent_wecom_users_disabled,
        }
        logger.info("org sync (manual): config_id={} result={}", config.id, summary)
        return summary
    finally:
        current_tenant_id.reset(token)
        # Release the queue gate first: the operator should be able to retry
        # even if the DB flag update below fails.
        await release_enqueue_lock(config.id, enqueue_token)
        # Best effort: a failed reset would leave the config locked as running.
        try:
            await OrgSyncConfigDao.aset_sync_status(config.id, "running", "idle")
        except Exception:
            logger.exception("org sync (manual): failed to clear running flag for config_id={}", config.id)
