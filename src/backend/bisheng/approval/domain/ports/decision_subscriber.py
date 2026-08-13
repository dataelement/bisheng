from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from bisheng.approval.domain.ports.scenario_policy import (
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalCompletionMode,
    ApprovalTerminalDecision,
)

APPROVAL_DECISION_EVENT_VERSION = 1
APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION = 1


class ApprovalDecisionPermanentError(RuntimeError):
    """The event cannot be accepted without an explicit operator replay."""


class ApprovalDecisionRetryableError(RuntimeError):
    """The event is valid but delivery failed because of a temporary condition."""


@dataclass(frozen=True, slots=True)
class ApprovalDecisionEvent:
    """A terminal approval fact delivered to a business-owned subscriber."""

    event_id: int
    event_version: int
    decision_version: int
    tenant_id: int
    scenario_code: str
    approval_instance_id: int
    business_request_type: str
    business_request_id: str
    business_key: str
    request_fingerprint: str
    decision: ApprovalTerminalDecision
    decided_at: datetime
    operator_user_id: int | None = None


@runtime_checkable
class ApprovalDecisionSubscriber(Protocol):
    """Idempotently accept one versioned approval decision event."""

    scenario_code: str
    subscriber_key: str
    protocol_version: int
    event_version: int
    completion_mode: ApprovalCompletionMode

    async def accept(self, event: ApprovalDecisionEvent) -> None: ...


__all__ = [
    "APPROVAL_DECISION_EVENT_VERSION",
    "APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION",
    "DECISION_DELIVERY_COMPLETION_MODE",
    "ApprovalDecisionEvent",
    "ApprovalDecisionPermanentError",
    "ApprovalDecisionRetryableError",
    "ApprovalDecisionSubscriber",
]
