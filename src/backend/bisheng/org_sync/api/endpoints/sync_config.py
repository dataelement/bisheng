"""Org sync configuration endpoints: CRUD plus the manual run trigger.

Part of F009-org-sync. Spec §6.1–6.5.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigNotFoundError,
    OrgSyncInvalidConfigError,
)
from bisheng.common.schemas.api import resp_200
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncConfig,
    OrgSyncConfigDao,
    decrypt_auth_config,
    encrypt_auth_config,
)
from bisheng.org_sync.domain.schemas.org_sync_schema import (
    OrgSyncConfigCreate,
    OrgSyncConfigRead,
    OrgSyncConfigUpdate,
    mask_sensitive_fields,
)
from bisheng.org_sync.domain.services.pull_sync_service import ensure_runnable
from bisheng.org_sync.domain.services.sync_enqueue_lock import (
    acquire_enqueue_lock,
    is_enqueue_locked,
    release_enqueue_lock,
)

router = APIRouter()


class OrgSyncExecuteRequest(BaseModel):
    """Body for ``POST /org-sync/execute``.

    The route path deliberately avoids ``config``: customer WAFs block URLs
    containing it as a sensitive-file probe, so the id travels in the body.
    """

    config_id: int


def _config_to_read(config: OrgSyncConfig) -> dict:
    """Convert ORM model to response dict with masked auth_config."""
    try:
        auth_dict = decrypt_auth_config(config.auth_config)
    except Exception:
        auth_dict = {}
    data = config.model_dump()
    data["auth_config"] = mask_sensitive_fields(auth_dict)
    return OrgSyncConfigRead.model_validate(data).model_dump(mode="json")


async def _get_config_or_404(
    config_id: int,
    login_user: UserPayload,
) -> OrgSyncConfig | None:
    """Load config with tenant + deleted check. Returns None if not found."""
    config = await OrgSyncConfigDao.aget_by_id(config_id)
    if not config or config.tenant_id != login_user.tenant_id:
        return None
    if config.status == "deleted":
        return None
    return config


@router.post("/configs")
async def create_config(
    data: OrgSyncConfigCreate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Create a new org sync configuration (spec §6.1, AC-01, AC-02)."""
    try:
        config = OrgSyncConfig(
            tenant_id=login_user.tenant_id,
            provider=data.provider,
            config_name=data.config_name,
            auth_type=data.auth_type,
            auth_config=encrypt_auth_config(data.auth_config),
            sync_scope=data.sync_scope,
            schedule_type=data.schedule_type,
            cron_expression=data.cron_expression,
            create_user=login_user.user_id,
        )
        config = await OrgSyncConfigDao.acreate(config)
        return resp_200(_config_to_read(config))
    except BaseErrorCode as e:
        return e.return_resp_instance()
    except Exception as e:
        if "Duplicate entry" in str(e) or "uk_tenant_provider_name" in str(e):
            from bisheng.common.errcode.org_sync import OrgSyncConfigDuplicateError

            return OrgSyncConfigDuplicateError.return_resp()
        return OrgSyncInvalidConfigError.return_resp()


@router.get("/configs")
async def list_configs(
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """List org sync configs for current tenant (spec §6.2, AC-03)."""
    try:
        configs = await OrgSyncConfigDao.aget_list(login_user.tenant_id)
        return resp_200([_config_to_read(c) for c in configs])
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get("/configs/{config_id}")
async def get_config(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Get org sync config details (spec §6.3, AC-04, AC-08)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()
        return resp_200(_config_to_read(config))
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.put("/configs/{config_id}")
async def update_config(
    config_id: int,
    data: OrgSyncConfigUpdate,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Update org sync config (spec §6.4, AC-05, AC-06)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        # Merge auth_config (AC-06)
        if data.auth_config is not None:
            existing_auth = decrypt_auth_config(config.auth_config)
            incoming = dict(data.auth_config)
            # Provider-internal keys must never be persisted, even if a client
            # echoes one back from a read response.
            incoming.pop("_config_id", None)
            # '****' sentinel on a secret field means "keep stored value";
            # dropping the key lets existing_auth.update() preserve it.
            for key, val in list(incoming.items()):
                if val == "****":
                    lower = key.lower()
                    if "secret" in lower or "password" in lower or "token" in lower:
                        incoming.pop(key)
            existing_auth.update(incoming)
            existing_auth.pop("_config_id", None)
            config.auth_config = encrypt_auth_config(existing_auth)

        if data.auth_type is not None:
            config.auth_type = data.auth_type
        if data.sync_scope is not None:
            config.sync_scope = data.sync_scope
        if data.schedule_type is not None:
            config.schedule_type = data.schedule_type
        if data.cron_expression is not None:
            config.cron_expression = data.cron_expression
        if data.status is not None:
            config.status = data.status
        if data.config_name is not None:
            config.config_name = data.config_name

        config = await OrgSyncConfigDao.aupdate(config)
        return resp_200(_config_to_read(config))
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.delete("/configs/{config_id}")
async def delete_config(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Soft-delete org sync config (spec §6.5, AC-07)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        # A run that is queued but not yet picked up has sync_status=idle; the
        # queue gate is what tells the two apart here.
        if config.sync_status == "running" or await is_enqueue_locked(config.id):
            return OrgSyncAlreadyRunningError.return_resp()

        config.status = "deleted"
        await OrgSyncConfigDao.aupdate(config)
        return resp_200(None)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post("/execute")
async def execute_config(
    data: OrgSyncExecuteRequest,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Queue a manual sync for this config (admin console「立即同步」).

    Runs asynchronously on the default Celery queue
    (``bisheng.worker.org_sync.tasks.execute_org_sync``); progress lands in
    ``org_sync_log`` and shows up on the 组织同步 page. The task re-checks
    status and takes the ``sync_status`` CAS lock, so a double click cannot
    start two runs.
    """
    try:
        config = await _get_config_or_404(data.config_id, login_user)
        # Same rules the task applies — one definition, fail fast here.
        ensure_runnable(config)
        if config.sync_status == "running":
            return OrgSyncAlreadyRunningError.return_resp()

        # Queue gate: sync_status only flips to running once the worker picks
        # the task up, so without this a double click enqueues two tasks.
        lock = await acquire_enqueue_lock(config.id)
        if not lock.acquired:
            return OrgSyncAlreadyRunningError.return_resp()

        from bisheng.worker.org_sync.tasks import execute_org_sync

        try:
            async_result = execute_org_sync.apply_async(
                args=[config.id, login_user.user_id, lock.token],
                # Matches the worker entrypoint's `-Q celery`; do not rely on
                # the implicit default queue name.
                queue="celery",
            )
        except Exception:
            # Broker rejected the task: free the gate so the operator can retry.
            await release_enqueue_lock(config.id, lock.token)
            raise
        return resp_200({"config_id": config.id, "task_id": async_result.id})
    except BaseErrorCode as e:
        return e.return_resp_instance()
