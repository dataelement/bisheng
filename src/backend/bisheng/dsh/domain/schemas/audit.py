"""Read-only, allowlisted administrative audit projections."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from bisheng.common.schemas.api import PageInfiniteCursorData

AuditAction = Literal[
    "REVOKE",
    "REASSIGN",
    "UPDATE_POLICY",
    "UPDATE_DEPARTMENT_POLICY",
    "UPDATE_ROLE_POLICY",
    "SYNC_PROFILE",
    "RECONCILE_USAGE",
]
AuditStatus = Literal["PENDING", "PROCESSING", "SUCCEEDED", "FAILED"]


class AuditRecord(BaseModel):
    id: str
    created_at: datetime
    action: AuditAction
    status: AuditStatus
    actor_id: int | None
    actor_name: str | None
    target_type: Literal["USER", "DEPARTMENT", "ROLE"]
    target_id: int
    target_name: str | None
    model_id: int | None
    model_name: str | None
    before_values: dict
    after_values: dict
    requested_values: dict
    result_code: str | None


class AuditPage(PageInfiniteCursorData[AuditRecord]):
    pass
