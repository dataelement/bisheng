"""Read-only current decoration, separate from immutable approval snapshots."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ApprovalVisibilityRead:
    instance_id: int
    tenant_id: int
    app_id: str
    viewer_user_id: int
    management: bool = False
    payload_app_id: str | None = None


def visibility_state(state, *, reason=None, owner=None, subjects=None, owner_only=None):
    return {
        "state": state,
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "owner_only": owner_only,
        "owner": owner,
        "subjects": subjects or [],
        "admin_implicit_access": True,
        "reason": reason,
    }
