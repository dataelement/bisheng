"""F011 DepartmentDeletionHandler — central orphaning entry point (spec §5.4.1).

Any caller that removes a department (F014 SSO sync, F015 Celery reconcile,
manual admin action) funnels through ``on_deleted(dept_id, deletion_source)``.
If the department is a Child Tenant mount point, the linked tenant flips to
``orphaned`` and global super admins are notified. Centralising here keeps
"orphaned" semantics consistent across the three trigger paths.
"""

from __future__ import annotations

import logging
from typing import List

from bisheng.database.models.audit_log import AuditLogDao
from bisheng.database.models.department import DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao
from bisheng.tenant.domain.constants import DeletionSource, TenantAuditAction

logger = logging.getLogger(__name__)


class DepartmentDeletionHandler:
    """Stateless service: one entry point, idempotent."""

    @classmethod
    async def on_deleted(
        cls, dept_id: int, deletion_source: DeletionSource | str,
    ) -> None:
        """Propagate a department deletion to the tenant layer.

        No-op when the department does not exist or is not a Tenant mount point.
        """
        dept = await DepartmentDao.aget_by_id(dept_id)
        if dept is None:
            return
        mounted = getattr(dept, 'mounted_tenant_id', None)
        if not mounted:
            return
        source_value = (
            deletion_source.value if isinstance(deletion_source, DeletionSource)
            else deletion_source
        )

        try:
            await TenantDao.aupdate_tenant(mounted, status='orphaned')
        except Exception as exc:  # noqa: BLE001
            # Audit + notify still attempted — operator visibility wins here.
            logger.error('Failed to mark tenant %s as orphaned: %s', mounted, exc)

        try:
            await AuditLogDao.ainsert_v2(
                tenant_id=mounted,
                operator_id=0,
                operator_tenant_id=ROOT_TENANT_ID,
                action=TenantAuditAction.ORPHANED.value,
                target_type='tenant',
                target_id=str(mounted),
                metadata={
                    'deletion_source': source_value,
                    'dept_id': dept_id,
                    'dept_name': getattr(dept, 'name', None),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'audit_log insert failed for tenant.orphaned(%s): %s',
                mounted, exc,
            )

        try:
            title = '子公司挂载点被删除 (tenant orphaned)'
            body = (
                f'Child Tenant {mounted} 因部门 '
                f'"{getattr(dept, "name", dept_id)}" 被 {source_value} '
                f'删除而进入 orphaned 状态，请尽快处理。'
            )
            await _notify_super_admins(title, body, tenant_id=mounted)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                'Super-admin notification failed for tenant %s: %s',
                mounted, exc,
            )


async def _notify_super_admins(title: str, body: str, tenant_id: int) -> None:
    """Fan out the orphan notice to every global super admin in one inbox call.

    MessageService is constructed on demand (not a DI-managed singleton here)
    because DepartmentDeletionHandler is called from Celery + SSO contexts
    without an active FastAPI request scope. Delivery is best-effort: the
    authoritative record is the ``audit_log`` row written by the caller.
    """
    try:
        recipients = await _list_global_super_admin_ids()
    except Exception as exc:  # noqa: BLE001
        logger.error('Cannot enumerate super admins: %s', exc)
        return
    if not recipients:
        logger.warning(
            'No global super admins found; skipping orphan notification '
            '(tenant_id=%s, title=%s)',
            tenant_id, title,
        )
        return
    await _send_inbox_notice(title, body, recipients)


async def _send_inbox_notice(
    title: str, body: str, recipients: List[int],
) -> None:
    """Build a one-shot ``NOTIFY`` message with ``receiver=recipients``.

    ``MessageService.send_message`` already accepts a receiver list, so a
    single call fans out to every admin without a per-user await loop.
    Import is lazy to avoid pulling the message DI chain on every import of
    this handler (and to keep Celery boot fast).
    """
    try:
        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import (
            MessageStatusEnum,
            MessageTypeEnum,
        )
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import (  # noqa: E501
            InboxMessageReadRepositoryImpl,
        )
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import (  # noqa: E501
            InboxMessageRepositoryImpl,
        )
        from bisheng.message.domain.services.message_service import MessageService
    except ImportError as exc:
        logger.warning(
            'MessageService unavailable (%s); orphan notice only in audit_log',
            exc,
        )
        return

    content = [{'type': 'text', 'title': title, 'body': body}]
    try:
        async with get_async_db_session() as session:
            service = MessageService(
                message_repository=InboxMessageRepositoryImpl(session),
                message_read_repository=InboxMessageReadRepositoryImpl(session),
            )
            await service.send_message(
                content=content,
                sender=0,
                message_type=MessageTypeEnum.NOTIFY,
                receiver=recipients,
                status=MessageStatusEnum.APPROVED,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            'Inbox delivery failed for %d recipients: %s',
            len(recipients), exc,
        )


async def _list_global_super_admin_ids() -> List[int]:
    """Resolve the set of user ids carrying ``system:global#super_admin``.

    Returns ``[]`` on any FGA failure so the handler degrades gracefully
    (the ``audit_log`` entry is the authoritative trace).
    """
    try:
        from bisheng.core.openfga.manager import aget_fga_client
        fga = await aget_fga_client()
        if fga is None:
            return []
        raw = await fga.list_users(
            object='system:global', relation='super_admin',
            user_type='user',
        )
        return [int(u.split(':', 1)[1]) for u in raw if ':' in u]
    except Exception as exc:  # noqa: BLE001
        logger.warning('FGA super-admin lookup failed: %s', exc)
        return []
