from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from bisheng.permission.domain.schemas.permission_schema import ResourcePermissionItem


class ResourceUserInvitePendingItem(ResourcePermissionItem):
    """Safe Permission-owned projection for a not-yet-effective user invite."""

    authorization_status: Literal["pending"] = "pending"
    business_request_id: int
    approval_status: str
    execution_state: Literal["awaiting_approval", "queued", "applying", "failed"]
    retryable: bool = False


class ResourceUserInviteRetryResult(BaseModel):
    """Dispatch acknowledgement; it is not evidence that authorization succeeded."""

    business_request_id: int
    approval_instance_id: int
    approval_status: Literal["approved"] = "approved"
    execution_state: Literal["failed"] = "failed"
    retry_dispatched: bool = True


__all__ = [
    "ResourceUserInvitePendingItem",
    "ResourceUserInviteRetryResult",
]
