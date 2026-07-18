"""Pydantic DTOs for permission module."""

from enum import Enum

from pydantic import BaseModel, Field

# Valid OpenFGA resource types
VALID_RESOURCE_TYPES = {
    "knowledge_space",
    "knowledge_library",
    "folder",
    "knowledge_file",
    "workflow",
    "assistant",
    "tool",
    "channel",
    "dashboard",
}

# Valid OpenFGA relations
VALID_RELATIONS = {
    "owner",
    "manager",
    "editor",
    "viewer",
    "can_manage",
    "can_edit",
    "can_read",
    "can_delete",
}

# Relations that must NOT be cached (security-sensitive, always query OpenFGA)
UNCACHEABLE_RELATIONS = {"can_manage", "can_delete"}

# Valid subject types for authorization
VALID_SUBJECT_TYPES = {"user", "department", "user_group"}


class PermissionLevel(str, Enum):
    """Permission levels from highest to lowest."""

    owner = "owner"
    can_manage = "can_manage"
    can_edit = "can_edit"
    can_read = "can_read"


class PermissionCheckRequest(BaseModel):
    """Request body for permission check API."""

    object_type: str
    object_id: str
    relation: str
    permission_id: str | None = None


class PermissionCheckResponse(BaseModel):
    """Response data for permission check API."""

    allowed: bool


class AuthorizeGrantItem(BaseModel):
    """Single grant entry in authorize request."""

    subject_type: str = Field(description="user | department | user_group")
    subject_id: int
    relation: str = Field(description="owner | manager | editor | viewer")
    include_children: bool = Field(default=True, description="For department: include sub-departments")
    model_id: str | None = Field(default=None, description="Optional relation model id")


class AuthorizeRevokeItem(BaseModel):
    """Single revoke entry in authorize request."""

    subject_type: str
    subject_id: int
    relation: str
    include_children: bool = Field(default=True)
    model_id: str | None = Field(default=None)


class AuthorizeRequest(BaseModel):
    """Request body for resource authorization API."""

    grants: list[AuthorizeGrantItem] = Field(default_factory=list)
    revokes: list[AuthorizeRevokeItem] = Field(default_factory=list)


class ResourcePermissionItem(BaseModel):
    """Single permission entry in resource permissions list."""

    subject_type: str
    subject_id: int
    subject_name: str | None = None
    subject_group_names: list[str] | None = None
    subject_member_names: list[str] | None = None
    relation: str
    include_children: bool | None = None
    model_id: str | None = None
    model_name: str | None = None
    # knowledge_space creator: permanent, non-removable owner (backed by the
    # SpaceChannelMember CREATOR row + Knowledge.user_id, which the "我创建的" list
    # and file read/write/delete all honor). Lets the UI lock the row like the
    # channel creator. Other resource types leave it False (owner/creator decoupled).
    is_creator: bool = False


class RelationModelItem(BaseModel):
    id: str
    name: str
    relation: str = Field(description="owner | manager | editor | viewer")
    permissions: list[str] = Field(default_factory=list)
    permissions_explicit: bool = False
    is_system: bool = False
    # 授权级别：决定前台授权人需具备的资源权限档位（与 PRD 管理所有者/管理者/使用者对应）
    grant_tier: str = Field(
        default="usage",
        description="owner=所有者级 | manager=管理级 | usage=使用级",
    )


class RelationModelCreateRequest(BaseModel):
    name: str
    relation: str = Field(description="owner | manager | editor | viewer")
    permissions: list[str] = Field(default_factory=list)


class RelationModelUpdateRequest(BaseModel):
    name: str | None = None
    permissions: list[str] | None = None
