"""Pydantic DTOs for user group API endpoints."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class UserGroupCreate(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=128)
    visibility: str = Field(default='public', pattern='^(public|private)$')
    remark: Optional[str] = None
    admin_user_ids: Optional[List[int]] = None


class UserGroupUpdate(BaseModel):
    group_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    visibility: Optional[str] = Field(default=None, pattern='^(public|private)$')
    remark: Optional[str] = None


class UserGroupMemberAdd(BaseModel):
    user_ids: List[int] = Field(..., min_length=1)


class UserGroupAdminSet(BaseModel):
    user_ids: List[int]


class UserGroupListItem(BaseModel):
    id: int
    group_name: str
    visibility: str
    remark: Optional[str] = None
    member_count: int = 0
    create_user: Optional[int] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    group_admins: List[Dict] = []


class UserGroupMemberInfo(BaseModel):
    user_id: int
    user_name: str
    is_group_admin: bool
    create_time: Optional[datetime] = None
