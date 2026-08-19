from __future__ import annotations

from collections.abc import Callable

from bisheng.approval.domain.ports.scenario_policy import ApprovalSubmissionPort
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService
from bisheng.approval.domain.services.approval_status_read_service import ApprovalStatusReadService

_submission_port_factory: Callable[[], ApprovalSubmissionPort] | None = None


def configure_approval_submission_port_factory(factory: Callable[[], ApprovalSubmissionPort]) -> None:
    global _submission_port_factory
    _submission_port_factory = factory


def get_approval_submission_port() -> ApprovalSubmissionPort:
    if _submission_port_factory is None:
        raise RuntimeError("approval submission port is not configured")
    return _submission_port_factory()


def get_approval_decision_application_service() -> ApprovalCenterService:
    """Compose the public decision application service inside Approval."""

    from bisheng.bootstrap.approval_scenarios import get_approval_scenario_registry

    return ApprovalCenterService(
        instance_repository=ApprovalInstanceRepository,
        registry=get_approval_scenario_registry(),
    )


def get_approval_status_read_port() -> ApprovalStatusReadService:
    """Return the Approval-owned minimal status reader."""

    return ApprovalStatusReadService()


__all__ = [
    "configure_approval_submission_port_factory",
    "get_approval_decision_application_service",
    "get_approval_status_read_port",
    "get_approval_submission_port",
]
