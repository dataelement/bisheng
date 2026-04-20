"""Org sync configuration CRUD endpoints (5).

Part of F009-org-sync. Spec §6.1–6.5.
"""

from typing import Optional

from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.org_sync import (
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

router = APIRouter()


def _config_to_read(config: OrgSyncConfig) -> dict:
    """Convert ORM model to response dict with masked auth_config."""
    try:
        auth_dict = decrypt_auth_config(config.auth_config)
    except Exception:
        auth_dict = {}
    data = config.model_dump()
    data['auth_config'] = mask_sensitive_fields(auth_dict)
    return OrgSyncConfigRead.model_validate(data).model_dump(mode='json')


async def _get_config_or_404(
    config_id: int, login_user: UserPayload,
) -> Optional[OrgSyncConfig]:
    """Load config with tenant + deleted check. Returns None if not found."""
    config = await OrgSyncConfigDao.aget_by_id(config_id)
    if not config or config.tenant_id != login_user.tenant_id:
        return None
    if config.status == 'deleted':
        return None
    return config


@router.post('/configs')
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
        if 'Duplicate entry' in str(e) or 'uk_tenant_provider_name' in str(e):
            from bisheng.common.errcode.org_sync import OrgSyncConfigDuplicateError
            return OrgSyncConfigDuplicateError.return_resp()
        return OrgSyncInvalidConfigError.return_resp()


@router.get('/configs')
async def list_configs(
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """List org sync configs for current tenant (spec §6.2, AC-03)."""
    try:
        configs = await OrgSyncConfigDao.aget_list(login_user.tenant_id)
        return resp_200([_config_to_read(c) for c in configs])
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/configs/{config_id}')
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


@router.put('/configs/{config_id}')
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
            # F021: drop provider-internal keys if they leaked in from client
            incoming.pop('_config_id', None)
            # F021: '****' sentinel on secret fields means "keep stored value"
            for key, val in list(incoming.items()):
                if val == '****':
                    lower = key.lower()
                    if 'secret' in lower or 'password' in lower or 'token' in lower:
                        incoming.pop(key)
            existing_auth.update(incoming)
            # Never persist internal keys (defensive — _config_id is read-only
            # at runtime via OrgSyncService / endpoints)
            existing_auth.pop('_config_id', None)
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


@router.delete('/configs/{config_id}')
async def delete_config(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Soft-delete org sync config (spec §6.5, AC-07)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        if config.sync_status == 'running':
            from bisheng.common.errcode.org_sync import OrgSyncAlreadyRunningError
            return OrgSyncAlreadyRunningError.return_resp()

        config.status = 'deleted'
        await OrgSyncConfigDao.aupdate(config)
        return resp_200(None)
    except BaseErrorCode as e:
        return e.return_resp_instance()
