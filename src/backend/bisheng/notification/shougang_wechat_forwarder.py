"""Hook: create WeChat push outbox records from in-app notifications."""

import logging

from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.message.domain.models.inbox_message import InboxMessage
from bisheng.message.domain.models.message_push_outbox import MessagePushOutbox
from bisheng.message.domain.repositories.implementations.message_push_outbox_repository_impl import (
    MessagePushOutboxRepositoryImpl,
)
from bisheng.notification.external.shougang_wechat_payload import (
    PUSHABLE_ACTION_CODES,
    render_body,
    resolve_action_code,
)
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)


async def _resolve_wechat_user_ids(user_ids: list[int]) -> list[str]:
    """Resolve BiSheng user IDs to enterprise WeChat user IDs."""
    if not user_ids:
        return []
    users = await UserDao.aget_user_by_ids(user_ids) or []
    wechat_ids = []
    for user in users:
        wid = getattr(user, "wechat_user_id", None)
        if wid:
            wechat_ids.append(wid)
    return wechat_ids


async def maybe_push_shougang_wechat_message(message: InboxMessage) -> None:
    """Create a message_push_outbox record for eligible QA expert notifications.

    Called from ``MessageService.send_message`` after the inbox message is saved.
    This function never raises; errors are logged and swallowed.
    """
    message_id = getattr(message, "id", None)
    try:
        conf = settings.get_shougang_wechat_message_push_conf()
        if not conf.enabled:
            logger.info(
                "wechat_push.skipped message_id=%s reason=feature_disabled",
                message_id,
            )
            return

        action_code = resolve_action_code(message)
        if action_code not in PUSHABLE_ACTION_CODES:
            logger.info(
                "wechat_push.skipped message_id=%s action_code=%s reason=not_pushable",
                message_id,
                action_code,
            )
            return

        receiver_user_ids = list(getattr(message, "receiver", None) or [])
        wechat_user_ids = await _resolve_wechat_user_ids(receiver_user_ids)
        if not wechat_user_ids:
            logger.info(
                "wechat_push.skipped message_id=%s action_code=%s reason=no_wechat_user_ids",
                message_id,
                action_code,
            )
            return

        body = render_body(
            action_code=action_code,
            content=getattr(message, "content", None) or [],
            conf=conf,
        )

        outbox = MessagePushOutbox(
            inbox_message_id=getattr(message, "id", None),
            action_code=action_code,
            receiver_user_ids=receiver_user_ids,
            wechat_user_ids=wechat_user_ids,
            body=body,
            max_retries=conf.max_retries,
        )

        async with get_async_db_session() as session:
            repo = MessagePushOutboxRepositoryImpl(session)
            saved = await repo.save(outbox)
            logger.info(
                "wechat_push.outbox_created message_id=%s outbox_id=%s action_code=%s users=%s",
                message_id,
                saved.id,
                action_code,
                ",".join(wechat_user_ids),
            )
    except Exception as exc:
        logger.warning(
            "wechat_push.outbox_failed message_id=%s reason=%s",
            message_id,
            exc,
            exc_info=True,
        )
