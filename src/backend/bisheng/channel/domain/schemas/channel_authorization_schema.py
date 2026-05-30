from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from bisheng.common.models.space_channel_member import ChannelRelationEnum


class ChannelGrantItem(BaseModel):
    subject_type: str = Field(..., description='user | department | user_group')
    subject_id: int
    relation: ChannelRelationEnum = Field(..., description='owner | manager | editor | viewer')
    include_children: bool = True
    model_id: Optional[str] = None


class ChannelRevokeItem(BaseModel):
    subject_type: str = Field(..., description='user | department | user_group')
    subject_id: int
    relation: ChannelRelationEnum = Field(..., description='owner | manager | editor | viewer')
    include_children: bool = True
    model_id: Optional[str] = None


class ChannelAuthorizeRequest(BaseModel):
    grants: List[ChannelGrantItem] = Field(default_factory=list)
    revokes: List[ChannelRevokeItem] = Field(default_factory=list)


class ChannelAuthorizeResponse(BaseModel):
    synced_user_count: int = 0
    affected_member_count: int = 0


class ChannelPermissionEntry(BaseModel):
    subject_type: str
    subject_id: int
    subject_name: Optional[str] = None
    subject_group_names: Optional[List[str]] = None
    subject_member_names: Optional[List[str]] = None
    relation: ChannelRelationEnum
    include_children: Optional[bool] = None
    model_id: Optional[str] = None
    model_name: Optional[str] = None


class ChannelRelationModelItem(BaseModel):
    id: str
    name: str
    relation: ChannelRelationEnum
    permissions: List[str] = Field(default_factory=list)
    permissions_explicit: bool = False
    is_system: bool = False
    grant_tier: str = 'usage'
