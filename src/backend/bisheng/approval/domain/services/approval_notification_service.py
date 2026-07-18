from __future__ import annotations

import logging

from bisheng.core.database import get_async_db_session
from bisheng.message.domain.services.notification_content import build_notify_content

logger = logging.getLogger(__name__)


class ApprovalNotificationService:
    """Station-message helpers for approval-center events."""

    @staticmethod
    async def notify_user(
        *,
        sender: int,
        receiver_user_id: int,
        action_code: str,
        business_name: str,
        instance_id: int,
        scenario_code: str | None = None,
        reason: str | None = None,
        task_id: int | None = None,
    ) -> None:
        await ApprovalNotificationService.notify_users(
            sender=sender,
            receiver_user_ids=[receiver_user_id],
            action_code=action_code,
            business_name=business_name,
            instance_id=instance_id,
            scenario_code=scenario_code,
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
        scenario_code: str | None = None,
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
                if scenario_code:
                    data = dict(metadata.get("data") or {})
                    data.setdefault("scenario_code", scenario_code)
                    metadata["data"] = data
                    metadata["scenario_code"] = scenario_code
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
                        scenario_code=scenario_code,
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
        scenario_code: str | None = None,
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
            scenario_code=scenario_code,
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
