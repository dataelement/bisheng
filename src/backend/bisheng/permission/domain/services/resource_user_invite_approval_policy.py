from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bisheng.approval.domain.ports.decision_subscriber import ApprovalDecisionPermanentError
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    APPROVAL_SUBMISSION_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalDecisionContext,
    ApprovalSubmissionCommand,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.domain.models.resource_user_invite_request import (
    RESOURCE_USER_INVITE_REQUEST_TYPE,
    RESOURCE_USER_INVITE_SCENARIO_CODE,
    ResourceUserInviteRequest,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ResourceUserInviteApprovalPolicy:
    """Enforce invitee-only submission and terminal decision authority."""

    scenario_code = RESOURCE_USER_INVITE_SCENARIO_CODE
    protocol_version = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE
    node_mode = "or"

    def __init__(self, *, session_factory: SessionFactory = get_async_db_session) -> None:
        self.session_factory = session_factory

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        self._require_tenant(command.tenant_id)
        if command.protocol_version != APPROVAL_SUBMISSION_PROTOCOL_VERSION:
            raise ApprovalDecisionPermanentError("resource user invite submission protocol mismatch")
        if command.completion_mode != self.completion_mode:
            raise ApprovalDecisionPermanentError("resource user invite completion mode mismatch")
        if command.scenario_code != self.scenario_code:
            raise ApprovalDecisionPermanentError("resource user invite scenario binding mismatch")
        if command.business_request_type != RESOURCE_USER_INVITE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("resource user invite business type mismatch")
        self._parse_request_id(command.business_request_id)
        if not command.request_fingerprint:
            raise ApprovalDecisionPermanentError("resource user invite request fingerprint is required")

        try:
            target_user_id = int(command.detail_snapshot["target_user_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("resource user invite target user is invalid") from error
        if target_user_id <= 0 or tuple(command.initial_approver_user_ids) != (target_user_id,):
            raise ApprovalDecisionPermanentError("resource user invite requires the invitee as the only OR approver")

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        tenant_id = self._require_tenant(context.tenant_id)
        if context.business_request_type != RESOURCE_USER_INVITE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("resource user invite business type mismatch")
        request_id = self._parse_request_id(context.business_request_id)
        if context.decision not in {"approved", "rejected", "withdrawn", "cancelled"}:
            raise ApprovalDecisionPermanentError("resource user invite decision is invalid")

        async with self.session_factory() as session, session.begin():
            row = await self._load_for_update(
                session,
                tenant_id=tenant_id,
                request_id=request_id,
            )
            self._validate_binding(
                row,
                approval_instance_id=context.approval_instance_id,
                request_fingerprint=context.request_fingerprint,
            )
            if int(context.operator_user_id) != int(row.target_user_id):
                raise ApprovalDecisionPermanentError("only the invitee can decide a resource user invite")

    @staticmethod
    async def _load_for_update(
        session: AsyncSession,
        *,
        tenant_id: int,
        request_id: int,
    ) -> ResourceUserInviteRequest:
        statement = (
            select(ResourceUserInviteRequest)
            .where(
                ResourceUserInviteRequest.id == request_id,
                ResourceUserInviteRequest.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        result = await session.execute(statement)
        row = result.scalars().first()
        if row is None:
            raise ApprovalDecisionPermanentError("resource user invite business request does not exist")
        return row

    @staticmethod
    def _validate_binding(
        row: ResourceUserInviteRequest,
        *,
        approval_instance_id: int,
        request_fingerprint: str,
    ) -> None:
        if row.approval_instance_id is None or int(row.approval_instance_id) != int(approval_instance_id):
            raise ApprovalDecisionPermanentError("resource user invite approval instance mismatch")
        if row.request_fingerprint != request_fingerprint:
            raise ApprovalDecisionPermanentError("resource user invite request fingerprint mismatch")

    @staticmethod
    def _parse_request_id(value: str) -> int:
        try:
            request_id = int(value)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("resource user invite business request id is invalid") from error
        if request_id <= 0 or str(request_id) != str(value):
            raise ApprovalDecisionPermanentError("resource user invite business request id is invalid")
        return request_id

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        try:
            normalized_tenant_id = int(tenant_id)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("resource user invite tenant is invalid") from error
        current_tenant_id = get_current_tenant_id()
        if normalized_tenant_id <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized_tenant_id:
            raise ApprovalDecisionPermanentError("resource user invite requires the matching tenant context")
        return normalized_tenant_id


__all__ = [
    "RESOURCE_USER_INVITE_REQUEST_TYPE",
    "RESOURCE_USER_INVITE_SCENARIO_CODE",
    "ResourceUserInviteApprovalPolicy",
]
