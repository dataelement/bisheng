from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalTaskStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.resource_user_invite_service import (
    RESOURCE_USER_INVITE_DISABLED_MESSAGE,
    RESOURCE_USER_INVITE_SCENARIO_CODE,
    ResourceUserInviteService,
)
from bisheng.common.errcode.approval import ApprovalRequestAlreadyProcessedError
from bisheng.core.lock.token_safe_redis_lock import RedisLockBusyError, RedisLockLostError


class ApprovalInviteRetryableExecutionError(RuntimeError):
    """The invite effect is uncertain and must remain owned by outbox retry."""


class ResourceUserInviteScenarioHandler:
    scenario_code = RESOURCE_USER_INVITE_SCENARIO_CODE
    requires_self_confirmation = True
    dedupe_scope = "business_key"
    duplicate_statuses = (
        ApprovalInstanceStatus.PENDING,
        ApprovalInstanceStatus.APPROVED,
        ApprovalInstanceStatus.EXECUTING,
    )
    scenario_disabled_message = RESOURCE_USER_INVITE_DISABLED_MESSAGE

    def __init__(
        self,
        *,
        instance_repository=ApprovalInstanceRepository,
        knowledge_grant: Callable[..., Awaitable[Any]] | None = None,
        channel_grant: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.instance_repository = instance_repository
        self._knowledge_grant = knowledge_grant
        self._channel_grant = channel_grant

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return f"{req.business_name}个人用户邀请确认"

    async def build_detail(self, req) -> dict:
        payload = req.payload_snapshot or {}
        return {
            "resource_type": payload.get("resource_type"),
            "resource_id": payload.get("resource_id"),
            "resource_name": payload.get("resource_name") or req.business_name,
            "target_user_id": payload.get("target_user_id"),
            "target_user_name": payload.get("target_user_name"),
            "relation": payload.get("relation"),
            "model_id": payload.get("model_id"),
            "role_name": (payload.get("role_snapshot") or {}).get("name"),
            "reason": req.reason,
        }

    async def build_business_link(self, req) -> dict:
        payload = req.payload_snapshot or {}
        return {
            "resource_type": payload.get("resource_type"),
            "resource_id": payload.get("resource_id"),
        }

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        sources = node_config.get("sources") or []
        if len(sources) != 1 or sources[0].get("type") != "invited_user":
            return []
        target_user_id = (req.payload_snapshot or {}).get("target_user_id")
        try:
            return [int(target_user_id)]
        except (TypeError, ValueError):
            return []

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        execution_logger = logger.bind(
            instance_id=instance_id,
            resource_type=payload_snapshot.get("resource_type"),
            resource_id=payload_snapshot.get("resource_id"),
            target_user_id=payload_snapshot.get("target_user_id"),
        )
        execution_logger.bind(validation_stage="instance_and_task").info("resource user invite execution started")
        instance = await self.instance_repository.get_instance(instance_id)
        if instance is None or instance.status not in (
            ApprovalInstanceStatus.APPROVED,
            ApprovalInstanceStatus.EXECUTING,
        ):
            raise ApprovalRequestAlreadyProcessedError()
        target_user_id = int(payload_snapshot["target_user_id"])
        tasks = await self.instance_repository.list_tasks(instance_id)
        if (
            len(tasks) != 1
            or tasks[0].approver_user_id != target_user_id
            or tasks[0].status != ApprovalTaskStatus.APPROVED
        ):
            raise ApprovalRequestAlreadyProcessedError()

        role_snapshot, role_fingerprint = ResourceUserInviteService.normalize_role_snapshot(
            payload_snapshot.get("role_snapshot") or {}
        )
        if role_fingerprint != payload_snapshot.get("role_fingerprint"):
            raise ValueError("resource invite role fingerprint does not match snapshot")

        newer = await self.instance_repository.find_blocking_invite(
            tenant_id=int(payload_snapshot["tenant_id"]),
            business_key=instance.business_key,
            exclude_instance_id=instance_id,
        )
        if newer is not None:
            raise ApprovalRequestAlreadyProcessedError()

        command = await self._resolve_grant_command(str(payload_snapshot["resource_type"]))
        try:
            await command(
                tenant_id=int(payload_snapshot["tenant_id"]),
                resource_id=str(payload_snapshot["resource_id"]),
                inviter_user_id=int(payload_snapshot["inviter_user_id"]),
                target_user_id=target_user_id,
                relation=str(payload_snapshot["relation"]),
                model_id=payload_snapshot.get("model_id"),
                role_snapshot=role_snapshot,
                role_fingerprint=role_fingerprint,
                include_children=bool(payload_snapshot.get("include_children", False)),
                approval_instance_id=instance_id,
            )
        except (RedisLockBusyError, RedisLockLostError) as error:
            raise ApprovalInviteRetryableExecutionError("resource authorization lock is unavailable") from error
        execution_logger.bind(
            validation_stage="grant_applied",
            compensation_result="not_required",
        ).info("resource user invite execution succeeded")
        return {"status": "applied", "approval_instance_id": instance_id}

    async def _resolve_grant_command(self, resource_type: str):
        if resource_type == "knowledge_space":
            if self._knowledge_grant is not None:
                return self._knowledge_grant
            from bisheng.permission.domain.services.resource_authorization_service import (
                ResourceAuthorizationService,
            )

            return ResourceAuthorizationService().apply_confirmed_personal_user_grant
        if resource_type == "channel":
            if self._channel_grant is not None:
                return self._channel_grant
            return self._apply_channel_grant
        raise ValueError(f"unsupported resource invite type: {resource_type}")

    @staticmethod
    async def _apply_channel_grant(**kwargs):
        from bisheng.channel.domain.repositories.implementations.channel_repository_impl import (
            ChannelRepositoryImpl,
        )
        from bisheng.channel.domain.services.channel_authorization_service import ChannelAuthorizationService
        from bisheng.common.repositories.implementations.space_channel_member_repository_impl import (
            SpaceChannelMemberRepositoryImpl,
        )
        from bisheng.core.database import get_async_db_session

        async with get_async_db_session() as session:
            service = ChannelAuthorizationService(
                channel_repository=ChannelRepositoryImpl(session),
                space_channel_member_repository=SpaceChannelMemberRepositoryImpl(session),
            )
            await service.apply_confirmed_personal_user_grant(**kwargs)

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None
