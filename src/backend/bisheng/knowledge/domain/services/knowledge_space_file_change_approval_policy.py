from __future__ import annotations

from collections.abc import Awaitable, Callable
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
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE,
    KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.services.knowledge_space_file_change_approver_resolver import (
    KnowledgeSpaceFileChangeApproverResolver,
)

ApproverResolver = Callable[..., Awaitable[list[int]]]
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class KnowledgeSpaceFileChangeApprovalPolicy:
    """Keep F046 approver authority inside the Knowledge domain."""

    scenario_code = KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE
    protocol_version = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode = DECISION_DELIVERY_COMPLETION_MODE
    node_mode = "or"
    _TERMINAL_DECISIONS = {"approved", "rejected", "withdrawn", "cancelled"}

    def __init__(
        self,
        *,
        approver_resolver: ApproverResolver | None = None,
        session_factory: SessionFactory = get_async_db_session,
    ) -> None:
        self.approver_resolver = approver_resolver or KnowledgeSpaceFileChangeApproverResolver.resolve_approver_user_ids
        self.session_factory = session_factory

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        tenant_id = self._require_tenant(command.tenant_id)
        if command.protocol_version != APPROVAL_SUBMISSION_PROTOCOL_VERSION:
            raise ApprovalDecisionPermanentError("file change submission protocol mismatch")
        if command.completion_mode != self.completion_mode:
            raise ApprovalDecisionPermanentError("file change completion mode mismatch")
        if command.scenario_code != self.scenario_code:
            raise ApprovalDecisionPermanentError("file change scenario binding mismatch")
        if command.business_request_type != KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("file change business type mismatch")
        self._parse_request_id(command.business_request_id)
        if not command.business_key:
            raise ApprovalDecisionPermanentError("file change business key is required")
        if not command.request_fingerprint:
            raise ApprovalDecisionPermanentError("file change request fingerprint is required")
        space_id = self._parse_positive_id(command.link_snapshot.get("space_id"), "space")
        expected = self._normalize_approvers(
            await self.approver_resolver(
                tenant_id=tenant_id,
                space_id=space_id,
                applicant_user_id=int(command.applicant.user_id),
            )
        )
        submitted = self._normalize_approvers(command.initial_approver_user_ids)
        if len(submitted) != len(command.initial_approver_user_ids) or submitted != expected:
            raise ApprovalDecisionPermanentError(
                "file change initial approvers must exactly match current owners and managers"
            )

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        tenant_id = self._require_tenant(context.tenant_id)
        if context.business_request_type != KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE:
            raise ApprovalDecisionPermanentError("file change business type mismatch")
        if context.decision not in self._TERMINAL_DECISIONS:
            raise ApprovalDecisionPermanentError("file change decision is invalid")
        request_id = self._parse_request_id(context.business_request_id)
        operator_user_id = self._parse_positive_id(context.operator_user_id, "operator user")

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
            approver_user_ids = await self.approver_resolver(
                tenant_id=tenant_id,
                space_id=int(row.space_id),
                applicant_user_id=None,
            )
            if operator_user_id not in self._normalize_approvers(approver_user_ids):
                raise ApprovalDecisionPermanentError(
                    "file change decision requires a current owner or manager approver"
                )

    @staticmethod
    async def _load_for_update(
        session: AsyncSession,
        *,
        tenant_id: int,
        request_id: int,
    ) -> KnowledgeSpaceFileChangeRequest:
        statement = (
            select(KnowledgeSpaceFileChangeRequest)
            .where(
                KnowledgeSpaceFileChangeRequest.id == request_id,
                KnowledgeSpaceFileChangeRequest.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        result = await session.execute(statement)
        row = result.scalars().first()
        if row is None:
            raise ApprovalDecisionPermanentError("file change business request does not exist")
        return row

    @staticmethod
    def _validate_binding(
        row: KnowledgeSpaceFileChangeRequest,
        *,
        approval_instance_id: int,
        request_fingerprint: str,
    ) -> None:
        if row.approval_instance_id is None or int(row.approval_instance_id) != int(approval_instance_id):
            raise ApprovalDecisionPermanentError("file change approval instance mismatch")
        if not row.request_fingerprint or row.request_fingerprint != request_fingerprint:
            raise ApprovalDecisionPermanentError("file change request fingerprint mismatch")

    @classmethod
    def _parse_request_id(cls, value: str) -> int:
        request_id = cls._parse_positive_id(value, "business request")
        if str(request_id) != str(value):
            raise ApprovalDecisionPermanentError("file change business request id is invalid")
        return request_id

    @staticmethod
    def _parse_positive_id(value: object, label: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError(f"file change {label} id is invalid") from error
        if normalized <= 0:
            raise ApprovalDecisionPermanentError(f"file change {label} id is invalid")
        return normalized

    @classmethod
    def _normalize_approvers(cls, values) -> tuple[int, ...]:
        return tuple(sorted({cls._parse_positive_id(value, "approver user") for value in values}))

    @staticmethod
    def _require_tenant(tenant_id: int) -> int:
        try:
            normalized = int(tenant_id)
        except (TypeError, ValueError) as error:
            raise ApprovalDecisionPermanentError("file change tenant is invalid") from error
        current_tenant_id = get_current_tenant_id()
        if normalized <= 0 or current_tenant_id is None or int(current_tenant_id) != normalized:
            raise ApprovalDecisionPermanentError("file change requires the matching tenant context")
        return normalized


__all__ = [
    "KNOWLEDGE_SPACE_FILE_CHANGE_REQUEST_TYPE",
    "KNOWLEDGE_SPACE_FILE_CHANGE_SCENARIO_CODE",
    "KnowledgeSpaceFileChangeApprovalPolicy",
]
