"""Lightweight inbox-notification helper used by tenant-tree handlers.

Both F011 ``DepartmentDeletionHandler`` and F012 ``UserTenantSyncService``
need to send best-effort station-internal notifications without an active
FastAPI request scope (called from Celery, SSO and reconcile contexts).
This module centralises the MessageService construction + lazy imports so
the two callers share one code path.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)


async def send_inbox_notice(
    title: str, body: str, recipients: List[int],
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
        from bisheng.message.domain.repositories.implementations.inbox_message_read_repository_impl import (  # noqa: E501
            InboxMessageReadRepositoryImpl,
        )
        from bisheng.message.domain.repositories.implementations.inbox_message_repository_impl import (  # noqa: E501
            InboxMessageRepositoryImpl,
        )
        from bisheng.message.domain.services.message_service import MessageService
    except ImportError as exc:
        logger.warning(
            'MessageService unavailable (%s); inbox notice skipped (title=%s)',
            exc, title,
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
            'Inbox delivery failed for %d recipients (title=%s): %s',
            len(recipients), title, exc,
        )


async def list_global_super_admin_ids() -> List[int]:
    """Return user ids carrying ``system:global#super_admin``.

    Returns ``[]`` on any FGA failure so callers degrade gracefully.
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
