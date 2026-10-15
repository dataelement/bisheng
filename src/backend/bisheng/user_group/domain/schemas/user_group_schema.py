"""Pydantic DTOs for user group API endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserGroupCreate(BaseModel):
    group_name: str = Field(..., min_length=1, max_length=128)
    visibility: str = Field(default="public", pattern="^(public|private)$")
    remark: str | None = None
    admin_user_ids: list[int] | None = None


class UserGroupUpdate(BaseModel):
    group_name: str | None = Field(default=None, min_length=1, max_length=128)
    visibility: str | None = Field(default=None, pattern="^(public|private)$")
    remark: str | None = None


class UserGroupMemberAdd(BaseModel):
    user_ids: list[int] = Field(..., min_length=1)


class UserGroupMemberSync(BaseModel):
    """全量同步普通成员（is_group_admin=0）；不在列表中的将从组内移除。"""

    user_ids: list[int] = Field(default_factory=list)


class UserGroupAdminSet(BaseModel):
    user_ids: list[int]


class UserGroupListItem(BaseModel):
    id: int
    group_name: str
    visibility: str
    remark: str | None = None
    member_count: int = 0
    create_user: int | None = None
    create_user_name: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    group_admins: list[dict] = []


class UserGroupMemberInfo(BaseModel):
    user_id: int
    user_name: str
    external_id: str | None = None
    is_group_admin: bool
    create_time: datetime | None = None
