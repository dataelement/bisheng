from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from bisheng.common.models.space_channel_member import ChannelRelationEnum
from bisheng.permission.domain.schemas.permission_schema import (
    AuthorizationItemResult,
    AuthorizationResult,
)


class ChannelGrantItem(BaseModel):
    subject_type: str = Field(..., description="user | department | user_group")
    subject_id: int
    relation: ChannelRelationEnum = Field(..., description="owner | manager | editor | viewer")
    include_children: bool = True
    model_id: str | None = None


class ChannelRevokeItem(BaseModel):
    subject_type: str = Field(..., description="user | department | user_group")
    subject_id: int
    relation: ChannelRelationEnum = Field(..., description="owner | manager | editor | viewer")
    include_children: bool = True
    model_id: str | None = None


class ChannelAuthorizeRequest(BaseModel):
    grants: list[ChannelGrantItem] = Field(default_factory=list)
    revokes: list[ChannelRevokeItem] = Field(default_factory=list)


ChannelAuthorizationItemResult = AuthorizationItemResult


class ChannelAuthorizeResponse(AuthorizationResult):
    synced_user_count: int = 0
    affected_member_count: int = 0


class ChannelPermissionEntry(BaseModel):
    subject_type: str
    subject_id: int
    subject_name: str | None = None
    subject_group_names: list[str] | None = None
    subject_member_names: list[str] | None = None
    relation: ChannelRelationEnum
    include_children: bool | None = None
    model_id: str | None = None
    model_name: str | None = None
    # True for the channel creator's entry: their permission level is permanent
    # and must not be editable in the UI.
    is_creator: bool = False
    authorization_status: Literal["active", "pending"] = "active"
    approval_instance_id: int | None = None


class ChannelRelationModelItem(BaseModel):
    id: str
    name: str
    relation: ChannelRelationEnum
    permissions: list[str] = Field(default_factory=list)
    permissions_explicit: bool = False
    is_system: bool = False
    grant_tier: str = "usage"
