"""Core logic for scanning and pushing wechat message outbox records."""

import logging
from datetime import datetime, timedelta

from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.message.domain.models.message_push_outbox import (
    MessagePushOutboxStatus,
)
from bisheng.message.domain.repositories.implementations.message_push_outbox_repository_impl import (
    MessagePushOutboxRepositoryImpl,
)
from bisheng.notification.external.shougang_madp_client import ShougangMADPClient

logger = logging.getLogger(__name__)


class WeChatOutboxProcessor:
    """Scan pending outbox records and push them via Shougang MADC API."""

    async def scan_and_dispatch(self) -> int:
        """Scan pending-ready records and dispatch push tasks.

        Returns the number of records dispatched.
        """
        conf = settings.get_shougang_wechat_message_push_conf()
        if not conf.enabled:
            logger.debug("wechat_push.scan skipped: feature disabled")
            return 0

        async with get_async_db_session() as session:
            repo = MessagePushOutboxRepositoryImpl(session)
            now = datetime.now()
            with bypass_tenant_filter():
                records = await repo.find_pending_ready(
                    before=now,
                    limit=conf.batch_size,
                )

        if not records:
            return 0

        from bisheng.worker.message.tasks import push_single_wechat_message

        dispatched = 0
        for record in records:
            push_single_wechat_message.delay(record.id)
            dispatched += 1

        logger.info("wechat_push.scan dispatched=%s", dispatched)
        return dispatched

    async def push_one(self, outbox_id: int) -> bool:
        """Push a single outbox record and update its status.

        Returns True if the record reached a terminal state (sent or failed).
        """
        conf = settings.get_shougang_wechat_message_push_conf()
        if not conf.enabled:
            logger.debug("wechat_push.push_one skipped: feature disabled outbox_id=%s", outbox_id)
            return False

        async with get_async_db_session() as session:
            repo = MessagePushOutboxRepositoryImpl(session)
            with bypass_tenant_filter():
                record = await repo.find_by_id(outbox_id)

            if record is None:
                logger.warning("wechat_push.push_one not_found outbox_id=%s", outbox_id)
                return False

            if record.status != MessagePushOutboxStatus.PENDING:
                logger.debug(
                    "wechat_push.push_one skipped status=%s outbox_id=%s",
                    record.status,
                    outbox_id,
                )
                return False

            client = ShougangMADPClient()
            success, error = await client.push_text_message(
                outbox_id=outbox_id,
                user_ids=list(record.wechat_user_ids),
                body=record.body,
            )

            if success:
                with bypass_tenant_filter():
                    await repo.mark_sent(outbox_id=outbox_id, sent_at=datetime.now())
                logger.info("wechat_push.push_one sent outbox_id=%s", outbox_id)
                return True

            new_retry_count = record.retry_count + 1
            if new_retry_count >= record.max_retries:
                with bypass_tenant_filter():
                    await repo.mark_failed(
                        outbox_id=outbox_id,
                        retry_count=new_retry_count,
                        failure_reason=error or "unknown",
                    )
                logger.warning(
                    "wechat_push.push_one failed outbox_id=%s retry_count=%s reason=%s",
                    outbox_id,
                    new_retry_count,
                    error,
                )
                return True

            backoff = min(
                conf.retry_base_seconds * (2**record.retry_count),
                conf.retry_max_seconds,
            )
            next_retry_at = datetime.now() + timedelta(seconds=backoff)
            with bypass_tenant_filter():
                await repo.mark_pending_retry(
                    outbox_id=outbox_id,
                    retry_count=new_retry_count,
                    next_retry_at=next_retry_at,
                    failure_reason=error or "unknown",
                )
            logger.info(
                "wechat_push.push_one retry outbox_id=%s retry_count=%s next_retry_at=%s reason=%s",
                outbox_id,
                new_retry_count,
                next_retry_at,
                error,
            )
            return False
