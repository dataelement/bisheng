from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.message.domain.services.notification_content import build_notify_content
from bisheng.permission.domain.services.permission_service import PermissionService

logger = logging.getLogger(__name__)

_SUPPORTED_RESOURCE_TYPES = {"channel", "knowledge_space"}
_ADMIN_RELATIONS = {"owner", "manager"}


@dataclass
class ResourcePermissionNotificationContext:
    resource_type: str
    resource_id: str
    grant_user_ids: set[int] = field(default_factory=set)
    revoke_user_ids: set[int] = field(default_factory=set)
    before_can_manage: dict[int, bool] = field(default_factory=dict)

    @property
    def has_events(self) -> bool:
        return bool(self.grant_user_ids or self.revoke_user_ids)


class ResourcePermissionNotificationService:
    """Station-message notifications for relation-model admin changes."""

    @classmethod
    async def build_context(
        cls,
        *,
        resource_type: str,
        resource_id: str | int,
        grants: Iterable,
        revokes: Iterable,
    ) -> ResourcePermissionNotificationContext | None:
        if resource_type not in _SUPPORTED_RESOURCE_TYPES:
            return None

        context = ResourcePermissionNotificationContext(
            resource_type=resource_type,
            resource_id=str(resource_id),
        )
        context.grant_user_ids = await cls._expand_admin_subjects(grants)
        context.revoke_user_ids = await cls._expand_admin_subjects(revokes)
        if not context.has_events:
            return None

        impacted_user_ids = context.grant_user_ids | context.revoke_user_ids
        context.before_can_manage = {
            user_id: await cls._can_manage(
                user_id=user_id,
                resource_type=resource_type,
                resource_id=str(resource_id),
            )
            for user_id in impacted_user_ids
        }
        return context

    @classmethod
    async def dispatch_after_authorize(
        cls,
        *,
        context: ResourcePermissionNotificationContext | None,
        operator_user_id: int,
        operator_user_name: str | None = None,
    ) -> None:
        if context is None or not context.has_events:
            return

        try:
            resource_name = await cls._get_resource_name(
                context.resource_type,
                context.resource_id,
            )
            after_can_manage = {
                user_id: await cls._can_manage(
                    user_id=user_id,
                    resource_type=context.resource_type,
                    resource_id=context.resource_id,
                )
                for user_id in (context.grant_user_ids | context.revoke_user_ids)
            }

            assigned_user_ids = [
                user_id for user_id in sorted(context.grant_user_ids)
                if not context.before_can_manage.get(user_id, False)
                and after_can_manage.get(user_id, False)
            ]
            revoked_user_ids = [
                user_id for user_id in sorted(context.revoke_user_ids)
                if context.before_can_manage.get(user_id, False)
                and not after_can_manage.get(user_id, False)
            ]

            await cls._send_admin_change_notifications(
                resource_type=context.resource_type,
                resource_id=context.resource_id,
                resource_name=resource_name,
                operator_user_id=operator_user_id,
                operator_user_name=operator_user_name,
                assigned_user_ids=assigned_user_ids,
                revoked_user_ids=revoked_user_ids,
            )
        except Exception:
            logger.exception(
                "failed to dispatch resource permission notifications: resource=%s:%s",
                context.resource_type,
                context.resource_id,
            )

    @staticmethod
    async def _expand_admin_subjects(items: Iterable) -> set[int]:
        user_ids: set[int] = set()
        for item in items or []:
            if getattr(item, "relation", None) not in _ADMIN_RELATIONS:
                continue
            user_ids.update(
                await PermissionService._affected_user_ids_for_subject(
                    getattr(item, "subject_type", ""),
                    int(getattr(item, "subject_id", 0) or 0),
                    bool(getattr(item, "include_children", True)),
                )
            )
        return user_ids

    @staticmethod
    async def _can_manage(*, user_id: int, resource_type: str, resource_id: str) -> bool:
        return await PermissionService.check(
            user_id=user_id,
            relation="can_manage",
            object_type=resource_type,
            object_id=resource_id,
        )

    @staticmethod
    async def _get_resource_name(resource_type: str, resource_id: str) -> str:
        try:
            async with get_async_db_session() as session:
                if resource_type == "channel":
                    from bisheng.channel.domain.models.channel import Channel

                    result = await session.exec(
                        select(Channel.name).where(Channel.id == str(resource_id))
                    )
                    name = result.first()
                    if name:
                        return str(name)
                if resource_type == "knowledge_space":
                    from bisheng.knowledge.domain.models.knowledge import Knowledge

                    result = await session.exec(
                        select(Knowledge.name).where(Knowledge.id == int(resource_id))
                    )
                    name = result.first()
                    if name:
                        return str(name)
        except Exception:
            logger.warning(
                "failed to load resource name for notification: resource=%s:%s",
                resource_type,
                resource_id,
                exc_info=True,
            )
        return str(resource_id)

    @classmethod
    async def _send_admin_change_notifications(
        cls,
        *,
        resource_type: str,
        resource_id: str,
        resource_name: str,
        operator_user_id: int,
        operator_user_name: str | None,
        assigned_user_ids: list[int],
        revoked_user_ids: list[int],
    ) -> None:
        if not assigned_user_ids and not revoked_user_ids:
            return

        action_codes = cls._action_codes(resource_type)
        business_type = cls._business_type(resource_type)
        from bisheng.message.api.dependencies import get_message_service

        async with get_async_db_session() as session:
            message_service = await get_message_service(session)
            if assigned_user_ids:
                await message_service.send_generic_notify(
                    sender=operator_user_id,
                    receiver_user_ids=assigned_user_ids,
                    content_item_list=build_notify_content(
                        action_code=action_codes["assigned"],
                        target_name=resource_name,
                        business_type=business_type,
                        business_id=resource_id,
                        actor_user_id=operator_user_id,
                        actor_user_name=operator_user_name,
                    ),
                    action_code=action_codes["assigned"],
                )
            if revoked_user_ids:
                await message_service.send_generic_notify(
                    sender=operator_user_id,
                    receiver_user_ids=revoked_user_ids,
                    content_item_list=build_notify_content(
                        action_code=action_codes["revoked"],
                        target_name=resource_name,
                        business_type=business_type,
                        business_id=resource_id,
                        actor_user_id=operator_user_id,
                        actor_user_name=operator_user_name,
                    ),
                    action_code=action_codes["revoked"],
                )

    @staticmethod
    def _action_codes(resource_type: str) -> dict[str, str]:
        if resource_type == "channel":
            return {
                "assigned": "assigned_channel_admin",
                "revoked": "revoked_channel_admin",
            }
        return {
            "assigned": "assigned_knowledge_space_admin",
            "revoked": "revoked_knowledge_space_admin",
        }

    @staticmethod
    def _business_type(resource_type: str) -> str:
        if resource_type == "channel":
            return "channel_id"
        return "knowledge_space_id"
