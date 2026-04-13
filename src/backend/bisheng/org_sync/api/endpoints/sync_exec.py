"""Org sync execution endpoints (4): test, execute, logs, remote-tree.

Part of F009-org-sync. Spec §6.6–6.9.
"""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.org_sync import (
    OrgSyncAlreadyRunningError,
    OrgSyncConfigDisabledError,
    OrgSyncConfigNotFoundError,
)
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.org_sync.domain.models.org_sync import (
    OrgSyncConfigDao,
    OrgSyncLogDao,
    decrypt_auth_config,
)
from bisheng.org_sync.domain.providers.base import get_provider
from bisheng.org_sync.domain.schemas.org_sync_schema import OrgSyncLogRead, RemoteTreeNode
from bisheng.org_sync.api.endpoints.sync_config import _get_config_or_404

router = APIRouter()


@router.post('/configs/{config_id}/test')
async def test_connection(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Test provider connectivity (spec §6.6, AC-09, AC-10)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        auth_config = decrypt_auth_config(config.auth_config)
        provider = get_provider(config.provider, auth_config)
        result = await provider.test_connection()
        return resp_200(result)
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.post('/configs/{config_id}/execute')
async def execute_sync(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Manually trigger sync execution (spec §6.7, AC-13, AC-14, AC-15)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        if config.status == 'disabled':
            return OrgSyncConfigDisabledError.return_resp()

        if config.sync_status == 'running':
            return OrgSyncAlreadyRunningError.return_resp()

        # Dispatch Celery task — log entry created inside OrgSyncService.execute_sync
        from bisheng.worker.org_sync.tasks import execute_org_sync
        execute_org_sync.apply_async(
            args=[config_id, 'manual', login_user.user_id],
            queue='knowledge_celery',
        )

        return resp_200({
            'config_id': config_id,
            'message': 'Sync task dispatched',
        })
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/configs/{config_id}/logs')
async def get_sync_logs(
    config_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Get sync history logs with pagination (spec §6.8, AC-29, AC-30)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        logs, total = await OrgSyncLogDao.aget_by_config(config_id, page, limit)
        log_reads = [
            OrgSyncLogRead.model_validate(log).model_dump(mode='json')
            for log in logs
        ]
        return resp_200(PageData(data=log_reads, total=total).model_dump())
    except BaseErrorCode as e:
        return e.return_resp_instance()


@router.get('/configs/{config_id}/remote-tree')
async def get_remote_tree(
    config_id: int,
    login_user: UserPayload = Depends(UserPayload.get_admin_user),
):
    """Preview remote org tree from provider (spec §6.9, AC-11, AC-12)."""
    try:
        config = await _get_config_or_404(config_id, login_user)
        if not config:
            return OrgSyncConfigNotFoundError.return_resp()

        auth_config = decrypt_auth_config(config.auth_config)
        provider = get_provider(config.provider, auth_config)
        await provider.authenticate()

        scope = config.sync_scope
        root_dept_ids = scope.get('root_dept_ids') if scope else None
        remote_depts = await provider.fetch_departments(root_dept_ids)

        tree = _build_tree(remote_depts)
        return resp_200([node.model_dump() for node in tree])
    except BaseErrorCode as e:
        return e.return_resp_instance()


def _build_tree(depts) -> list[RemoteTreeNode]:
    """Convert flat department list to nested tree."""
    nodes: dict[str, RemoteTreeNode] = {}
    for d in depts:
        nodes[d.external_id] = RemoteTreeNode(
            external_id=d.external_id,
            name=d.name,
        )

    roots: list[RemoteTreeNode] = []
    for d in depts:
        node = nodes[d.external_id]
        if d.parent_external_id and d.parent_external_id in nodes:
            nodes[d.parent_external_id].children.append(node)
        else:
            roots.append(node)

    return roots
