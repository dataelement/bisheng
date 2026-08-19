from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Literal, Protocol, TypeVar, runtime_checkable

APPROVAL_SUBMISSION_PROTOCOL_VERSION = 1
APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION = 1
DECISION_DELIVERY_COMPLETION_MODE = "decision_delivery"

ApprovalCompletionMode = Literal["decision_delivery"]
ApprovalTerminalDecision = Literal["approved", "rejected", "withdrawn", "cancelled"]
ApprovalPostCommitCallback = Callable[[], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class ApprovalApplicant:
    """Applicant identity captured as part of the approval fact."""

    user_id: int
    user_name: str
    department_id: int | None = None


@dataclass(frozen=True, slots=True)
class ApprovalSubmissionCommand:
    """Versioned, business-neutral command for an atomic approval submission."""

    tenant_id: int
    scenario_code: str
    business_request_type: str
    business_request_id: str
    business_key: str
    request_fingerprint: str
    title: str
    applicant: ApprovalApplicant
    initial_approver_user_ids: tuple[int, ...]
    detail_snapshot: Mapping[str, object] = field(default_factory=dict)
    link_snapshot: Mapping[str, object] = field(default_factory=dict)
    completion_mode: ApprovalCompletionMode = DECISION_DELIVERY_COMPLETION_MODE
    protocol_version: int = APPROVAL_SUBMISSION_PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class ApprovalSubmissionResult:
    """Approval binding and effects returned without committing the caller session."""

    instance_id: int
    task_ids: tuple[int, ...] = ()
    post_commit_effects: tuple[ApprovalPostCommitCallback, ...] = field(
        default_factory=tuple,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class ApprovalDecisionContext:
    """Candidate decision facts available before any terminal event is created."""

    tenant_id: int
    approval_instance_id: int
    business_request_type: str
    business_request_id: str
    request_fingerprint: str
    operator_user_id: int
    decision: ApprovalTerminalDecision


@runtime_checkable
class ApprovalScenarioPolicy(Protocol):
    """Business-owned rules consumed by the generic approval engine."""

    scenario_code: str
    protocol_version: int
    completion_mode: ApprovalCompletionMode

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None: ...

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None: ...


SessionT = TypeVar("SessionT", contravariant=True)


@runtime_checkable
class ApprovalSubmissionPort(Protocol[SessionT]):
    """Submit an approval bundle inside a caller-owned transaction."""

    async def submit_in_uow(
        self,
        *,
        session: SessionT,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResult: ...

    def scenario_guard(
        self,
        *,
        tenant_id: int,
        scenario_code: str,
    ) -> AbstractAsyncContextManager[None]: ...
