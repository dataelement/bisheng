from __future__ import annotations

import logging
from collections.abc import Callable

from bisheng.approval.domain.models.approval_notification_outbox import (
    ApprovalNotificationEventType,
    ApprovalNotificationOutbox,
    ApprovalNotificationOutboxStatus,
)
from bisheng.approval.domain.repositories.approval_instance_repository import (
    ApprovalInstanceRepository,
)
from bisheng.approval.domain.repositories.approval_notification_outbox_repository import (
    ApprovalNotificationOutboxRepository,
)
from bisheng.core.database import get_async_db_session
from bisheng.message.domain.services.notification_content import build_notify_content

logger = logging.getLogger(__name__)


class ApprovalNotificationService:
    """Station-message helpers for approval-center events."""

    def __init__(
        self,
        *,
        outbox_repository=ApprovalNotificationOutboxRepository,
        instance_repository=ApprovalInstanceRepository,
        message_service=None,
        dispatcher: Callable[[int, int], None] | None = None,
    ) -> None:
        self.outbox_repository = outbox_repository
        self.instance_repository = instance_repository
        self.message_service = message_service
        self.dispatcher = dispatcher or self._dispatch_file_publish_notification

    async def enqueue_file_publish(
        self,
        *,
        tenant_id: int,
        instance_id: int,
        task_ids: list[int],
        applicant_user_id: int,
        applicant_user_name: str,
        business_name: str,
    ) -> ApprovalNotificationOutbox:
        action_code = "request_knowledge_space_file_publish"
        outbox = await self.outbox_repository.create_or_get(
            ApprovalNotificationOutbox(
                tenant_id=tenant_id,
                instance_id=instance_id,
                event_type=ApprovalNotificationEventType.FILE_PUBLISH_SUBMITTED,
                payload_snapshot={
                    "task_ids": task_ids,
                    "applicant_user_id": applicant_user_id,
                    "applicant_user_name": applicant_user_name,
                    "action_code": action_code,
                    "business_type": "approval_instance_id",
                    "business_id": str(instance_id),
                    "business_name": business_name,
                    "button_action_code": action_code,
                },
            )
        )
        if outbox.status == ApprovalNotificationOutboxStatus.SUCCESS:
            return outbox
        try:
            self.dispatcher(int(outbox.id), int(outbox.tenant_id))
        except Exception as exc:  # Broker failure is recoverable from the persisted outbox.
            logger.exception(
                "approval notification dispatch failed: outbox_id=%s",
                outbox.id,
            )
            try:
                await self.outbox_repository.mark_failed(int(outbox.id), str(exc))
            except Exception:
                logger.exception(
                    "failed to record approval notification dispatch failure: outbox_id=%s",
                    outbox.id,
                )
        return outbox

    async def consume(self, outbox_id: int) -> bool:
        outbox = await self.outbox_repository.get(outbox_id)
        if outbox is None:
            raise ValueError(f"approval notification outbox not found: {outbox_id}")
        if outbox.status == ApprovalNotificationOutboxStatus.SUCCESS:
            return True
        if outbox.retry_count >= outbox.max_retries:
            return False

        try:
            task_ids = [int(task_id) for task_id in outbox.payload_snapshot.get("task_ids", [])]
            tasks = await self.instance_repository.get_tasks_by_ids(task_ids)
            receiver_user_ids = list(dict.fromkeys(int(task.approver_user_id) for task in tasks))
            if not receiver_user_ids:
                raise ValueError(f"approval notification has no receivers: {outbox_id}")
            await self._send_file_publish_message(
                payload=outbox.payload_snapshot,
                receiver_user_ids=receiver_user_ids,
            )
            await self.outbox_repository.mark_success(outbox_id)
            return True
        except Exception as exc:
            try:
                await self.outbox_repository.mark_failed(outbox_id, str(exc))
            except Exception:
                logger.exception(
                    "failed to record approval notification consume failure: outbox_id=%s",
                    outbox_id,
                )
            raise

    async def _send_file_publish_message(
        self,
        *,
        payload: dict,
        receiver_user_ids: list[int],
    ) -> None:
        message_service = self.message_service
        if message_service is not None:
            await message_service.send_generic_approval(
                applicant_user_id=payload["applicant_user_id"],
                applicant_user_name=payload["applicant_user_name"],
                action_code=payload["action_code"],
                business_type=payload["business_type"],
                business_id=payload["business_id"],
                business_name=payload["business_name"],
                button_action_code=payload["button_action_code"],
                receiver_user_ids=receiver_user_ids,
            )
            return

        from bisheng.message.api.dependencies import get_message_service as _get_message_service

        async with get_async_db_session() as session:
            message_service = await _get_message_service(session)
            await message_service.send_generic_approval(
                applicant_user_id=payload["applicant_user_id"],
                applicant_user_name=payload["applicant_user_name"],
                action_code=payload["action_code"],
                business_type=payload["business_type"],
                business_id=payload["business_id"],
                business_name=payload["business_name"],
                button_action_code=payload["button_action_code"],
                receiver_user_ids=receiver_user_ids,
            )

    @staticmethod
    def _dispatch_file_publish_notification(outbox_id: int, tenant_id: int) -> None:
        from bisheng.worker.approval.notification_tasks import consume_approval_notification

        consume_approval_notification.delay(outbox_id, tenant_id)

    @staticmethod
    async def notify_user(
        *,
        sender: int,
        receiver_user_id: int,
        action_code: str,
        business_name: str,
        instance_id: int,
        reason: str | None = None,
        task_id: int | None = None,
    ) -> None:
        await ApprovalNotificationService.notify_users(
            sender=sender,
            receiver_user_ids=[receiver_user_id],
            action_code=action_code,
            business_name=business_name,
            instance_id=instance_id,
            reason=reason,
            task_id=task_id,
        )

    @staticmethod
    async def notify_users(
        *,
        sender: int,
        receiver_user_ids: list[int],
        action_code: str,
        business_name: str,
        instance_id: int,
        reason: str | None = None,
        task_id: int | None = None,
    ) -> None:
        if not receiver_user_ids:
            return
        try:
            from bisheng.message.api.dependencies import get_message_service as _get_message_service

            async with get_async_db_session() as session:
                message_service = await _get_message_service(session)
                metadata = {}
                if task_id is not None:
                    metadata = {"data": {"approval_task_id": str(task_id)}}
                actor_user_name = None
                try:
                    from bisheng.user.domain.models.user import UserDao

                    actor = await UserDao.aget_user(sender)
                    actor_user_name = actor.user_name if actor else None
                except Exception:
                    logger.warning(
                        "failed to load approval notification sender name: user_id=%s",
                        sender,
                        exc_info=True,
                    )
                await message_service.send_generic_notify(
                    sender=sender,
                    receiver_user_ids=receiver_user_ids,
                    content_item_list=build_notify_content(
                        action_code=action_code,
                        target_name=business_name,
                        business_type="approval_instance_id",
                        business_id=instance_id,
                        actor_user_id=sender,
                        actor_user_name=actor_user_name,
                        reason=reason,
                        metadata=metadata,
                    ),
                    action_code=action_code,
                )
        except Exception:
            logger.exception(
                "failed to send approval notification: action_code=%s instance_id=%s",
                action_code,
                instance_id,
            )

    @staticmethod
    async def notify_admins(
        *,
        tenant_id: int,
        applicant_user_id: int,
        action_code: str,
        business_name: str,
        instance_id: int,
    ) -> None:
        admin_ids = await ApprovalNotificationService._get_admin_recipient_ids(
            tenant_id=tenant_id,
            exclude_user_id=applicant_user_id,
        )
        await ApprovalNotificationService.notify_users(
            sender=applicant_user_id,
            receiver_user_ids=admin_ids,
            action_code=action_code,
            business_name=business_name,
            instance_id=instance_id,
        )

    @staticmethod
    async def _get_admin_recipient_ids(
        *,
        tenant_id: int,
        exclude_user_id: int | None = None,
    ) -> list[int]:
        recipient_ids: set[int] = set()
        try:
            from bisheng.database.constants import AdminRole
            from bisheng.user.domain.models.user_role import UserRoleDao

            admin_rows = await UserRoleDao.aget_roles_user([AdminRole])
            recipient_ids.update(int(row.user_id) for row in admin_rows if row.user_id)
        except Exception:
            logger.exception("failed to load system-admin notification recipients")

        try:
            from bisheng.permission.domain.services.tenant_admin_service import TenantAdminService

            recipient_ids.update(await TenantAdminService.list_tenant_admins(tenant_id))
        except Exception:
            logger.exception(
                "failed to load tenant-admin notification recipients: tenant_id=%s",
                tenant_id,
            )

        if exclude_user_id is not None:
            recipient_ids.discard(int(exclude_user_id))
        return sorted(recipient_ids)
