"""Lightweight inbox-notification helper used by tenant-tree handlers.

Both F011 ``DepartmentDeletionHandler`` and F012 ``UserTenantSyncService``
need to send best-effort station-internal notifications without an active
FastAPI request scope (called from Celery, SSO and reconcile contexts).
This module centralises the MessageService construction + lazy imports so
the two callers share one code path.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def send_inbox_notice(
    title: str,
    body: str,
    recipients: list[int],
) -> None:
    """Send one ``NOTIFY`` inbox message to the given recipients.

    Best-effort: import / DB / MessageService failures are logged and
    swallowed because the authoritative trace lives in ``audit_log``.
    """
    if not recipients:
        return
    try:
        from bisheng.core.database import get_async_db_session
        from bisheng.message.domain.models.inbox_message import (
            MessageStatusEnum,
            MessageTypeEnum,
        )
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import (
            InboxMessageReadRepositoryImpl,
        )
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import (
            InboxMessageRepositoryImpl,
        )
        from bisheng.message.domain.services.message_service import MessageService
    except ImportError as exc:
        logger.warning(
            "MessageService unavailable (%s); inbox notice skipped (title=%s)",
            exc,
            title,
        )
        return

    content = [{"type": "text", "title": title, "body": body}]
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
    except Exception as exc:
        logger.warning(
            "Inbox delivery failed for %d recipients (title=%s): %s",
            len(recipients),
            title,
            exc,
        )


async def list_global_super_admin_ids() -> list[int]:
    """Return user IDs carrying the global super-admin permission.

    Returns ``[]`` on any permission-service failure so callers degrade gracefully.
    """
    try:
        from bisheng.permission.application import PermissionObject, get_permission_relation_api

        permissions = await get_permission_relation_api()
        raw = await permissions.list_subject_ids(
            resource=PermissionObject("system", "global"),
            relation="super_admin",
            subject_type="user",
        )
        return [int(user_id) for user_id in raw if user_id.isdigit()]
    except Exception as exc:
        logger.warning("Permission super-admin lookup failed: %s", exc)
        return []
