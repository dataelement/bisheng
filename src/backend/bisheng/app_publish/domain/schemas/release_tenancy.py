"""Internal provenance of one accepted approval-execution phase; never an HTTP input."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApprovedReleaseSource:
    approval_instance_id: int
    deployment_id: str
    app_id: str
    version_id: str
    tenant_id: int
    owner_user_id: int
    audit_source: str = "approval_outbox"
    authorization_context: dict | None = None
