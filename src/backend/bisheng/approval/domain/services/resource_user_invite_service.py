from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any

from loguru import logger
from sqlmodel import select

from bisheng.approval.domain.models.approval_scenario import ApprovalScenario
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.repositories.approval_scenario_repository import ApprovalScenarioRepository
from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateRequest
from bisheng.approval.domain.services.approval_business_lock import approval_invite_business_lock
from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
from bisheng.core.database import get_async_db_session

RESOURCE_USER_INVITE_SCENARIO_CODE = "resource_user_invite_confirmation"
RESOURCE_USER_INVITE_SCENARIO_NAME = "知识空间用户邀请确认"
RESOURCE_USER_INVITE_DISABLED_MESSAGE = "个人用户邀请确认场景未启用，无法新增个人用户权限"  # noqa: RUF001


class ResourceUserInviteService:
    """Create one self-confirmation approval instance for a resource user."""

    def __init__(
        self,
        *,
        scenario_repository=ApprovalScenarioRepository,
        instance_repository=ApprovalInstanceRepository,
        gate=None,
        lock_factory=approval_invite_business_lock,
    ) -> None:
        self.scenario_repository = scenario_repository
        self.instance_repository = instance_repository
        self._gate = gate
        self.lock_factory = lock_factory

    @classmethod
    async def ensure_scenario_available(cls, *, tenant_id: int) -> None:
        service = cls()
        await service._ensure_scenario_available(tenant_id=tenant_id)

    async def _ensure_scenario_available(self, *, tenant_id: int) -> None:
        scenario = await self.scenario_repository.get_scenario_by_code(
            tenant_id,
            RESOURCE_USER_INVITE_SCENARIO_CODE,
        )
        if scenario is None or not scenario.enabled:
            raise ApprovalScenarioDisabledError(msg=RESOURCE_USER_INVITE_DISABLED_MESSAGE)

    @asynccontextmanager
    async def scenario_guard(self, *, tenant_id: int):
        """Keep scenario disable/delete updates outside one authorization operation."""
        statement = (
            select(ApprovalScenario)
            .where(
                ApprovalScenario.tenant_id == int(tenant_id),
                ApprovalScenario.scenario_code == RESOURCE_USER_INVITE_SCENARIO_CODE,
            )
            .with_for_update()
        )
        async with get_async_db_session() as session:
            scenario = (await session.exec(statement)).first()
            if scenario is None or not scenario.enabled:
                raise ApprovalScenarioDisabledError(msg=RESOURCE_USER_INVITE_DISABLED_MESSAGE)
            yield

    @staticmethod
    def build_business_key(*, resource_type: str, resource_id: str | int, target_user_id: int) -> str:
        return f"resource-user-invite:{resource_type}:{resource_id}:user:{target_user_id}"

    @staticmethod
    def normalize_role_snapshot(role_snapshot: dict[str, Any]) -> tuple[dict[str, Any], str]:
        normalized_json = json.dumps(role_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return json.loads(normalized_json), hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()

    async def request_invite(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | int,
        resource_name: str,
        inviter_user_id: int,
        inviter_user_name: str,
        target_user_id: int,
        target_user_name: str,
        relation: str,
        model_id: str | None,
        role_snapshot: dict[str, Any],
        include_children: bool = False,
        applicant_department_id: int | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> dict[str, Any]:
        await self._ensure_scenario_available(tenant_id=tenant_id)
        business_key = self.build_business_key(
            resource_type=resource_type,
            resource_id=resource_id,
            target_user_id=target_user_id,
        )
        lock_key = f"approval:resource-user-invite:{tenant_id}:{resource_type}:{resource_id}:{target_user_id}"
        async with self.lock_factory(lock_key) as lock:
            lock.ensure_owned()
            existing = await self.instance_repository.find_blocking_invite(
                tenant_id=tenant_id,
                business_key=business_key,
            )
            if existing is not None:
                logger.bind(
                    tenant_id=tenant_id,
                    scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
                    business_key=business_key,
                    instance_id=existing.id,
                    outcome="invite_existing",
                ).info("resource user invite request resolved")
                return self._result_from_instance(existing, outcome="invite_existing")

            normalized_role, role_fingerprint = self.normalize_role_snapshot(role_snapshot)
            payload = {
                "schema_version": 1,
                "tenant_id": tenant_id,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "resource_name": resource_name,
                "inviter_user_id": inviter_user_id,
                "inviter_user_name": inviter_user_name,
                "target_user_id": target_user_id,
                "target_user_name": target_user_name,
                "relation": relation,
                "model_id": model_id,
                "include_children": include_children,
                "role_snapshot": normalized_role,
                "role_fingerprint": role_fingerprint,
            }
            gate = self._gate or await self._build_gate()
            gate_result = await gate.request_or_pass(
                ApprovalGateRequest(
                    tenant_id=tenant_id,
                    scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
                    business_key=business_key,
                    business_resource_type=resource_type,
                    business_resource_id=str(resource_id),
                    business_name=resource_name,
                    applicant_user_id=inviter_user_id,
                    applicant_user_name=inviter_user_name,
                    applicant_department_id=applicant_department_id,
                    reason=reason,
                    payload_snapshot=payload,
                    ip_address=ip_address,
                )
            )
            lock.ensure_owned()

        result = {
            "outcome": "invite_created",
            "subject_type": "user",
            "subject_id": target_user_id,
            "relation": relation,
            "model_id": model_id,
            "approval_instance_id": gate_result.instance_id,
        }
        logger.bind(
            tenant_id=tenant_id,
            scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
            business_key=business_key,
            instance_id=gate_result.instance_id,
            outcome="invite_created",
        ).info("resource user invite request resolved")
        if gate_result.task_ids:
            from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

            try:
                await ApprovalNotificationService.notify_user(
                    sender=inviter_user_id,
                    receiver_user_id=target_user_id,
                    action_code="resource_user_invite_pending",
                    business_name=resource_name,
                    instance_id=gate_result.instance_id,
                    scenario_code=RESOURCE_USER_INVITE_SCENARIO_CODE,
                    task_id=gate_result.task_ids[0],
                )
            except Exception:
                # The ApprovalInstance/Task is the fact source; reminders are best effort.
                logger.exception(
                    "failed to send resource user invite reminder: instance_id={}",
                    gate_result.instance_id,
                )
        return result

    async def list_pending_invites(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str | int,
    ):
        return await self.instance_repository.list_resource_invites(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
        )

    @staticmethod
    def _result_from_instance(instance, *, outcome: str) -> dict[str, Any]:
        payload = instance.payload_snapshot or {}
        return {
            "outcome": outcome,
            "subject_type": "user",
            "subject_id": int(payload["target_user_id"]),
            "relation": payload.get("relation"),
            "model_id": payload.get("model_id"),
            "approval_instance_id": instance.id,
        }

    @staticmethod
    async def _build_gate():
        from bisheng.approval.domain.services.approval_gate import ApprovalGate
        from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
        from bisheng.approval.domain.services.resource_user_invite_scenario_handler import (
            ResourceUserInviteScenarioHandler,
        )

        registry = ApprovalRegistry.with_default_presets()
        registry.register_handler(RESOURCE_USER_INVITE_SCENARIO_CODE, ResourceUserInviteScenarioHandler())
        return ApprovalGate(registry=registry)
