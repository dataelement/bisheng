"""Read-only, allowlisted browser projection (not an execution/repair contract)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProviderOperationDiagnostic(BaseModel):
    operation_id: str
    space_id: int
    version_ids: list[int]
    remote_target: str
    generation: int
    kind: str
    phase: str
    state: str
    error_code: Literal["not_received", "manual_review_required", "unknown"] | None
    attempt: int
    create_time: datetime
    capability_revision: int
    # A recorded revision is not an action-specific proof for a live provider.
    capability_state: Literal["unknown"] = "unknown"
    manual_release_allowed: Literal[False] = False
