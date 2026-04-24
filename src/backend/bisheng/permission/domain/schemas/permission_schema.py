"""Pydantic DTOs for permission module."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

# Valid OpenFGA resource types
VALID_RESOURCE_TYPES = {
    'knowledge_space', 'knowledge_library', 'folder', 'knowledge_file',
    'workflow', 'assistant', 'tool', 'channel', 'dashboard',
}

# Valid OpenFGA relations
VALID_RELATIONS = {
    'owner', 'manager', 'editor', 'viewer',
    'can_manage', 'can_edit', 'can_read', 'can_delete',
}

# Relations that must NOT be cached (security-sensitive, always query OpenFGA)
UNCACHEABLE_RELATIONS = {'can_manage', 'can_delete'}

# Valid subject types for authorization
VALID_SUBJECT_TYPES = {'user', 'department', 'user_group'}


class PermissionLevel(str, Enum):
    """Permission levels from highest to lowest."""
    owner = 'owner'
    can_manage = 'can_manage'
    can_edit = 'can_edit'
    can_read = 'can_read'


class PermissionCheckRequest(BaseModel):
    """Request body for permission check API."""
    object_type: str
    object_id: str
    relation: str
    permission_id: Optional[str] = None


class PermissionCheckResponse(BaseModel):
    """Response data for permission check API."""
    allowed: bool


class AuthorizeGrantItem(BaseModel):
    """Single grant entry in authorize request."""
    subject_type: str = Field(description='user | department | user_group')
    subject_id: int
    relation: str = Field(description='owner | manager | editor | viewer')
    include_children: bool = Field(default=True, description='For department: include sub-departments')
    model_id: Optional[str] = Field(default=None, description='Optional relation model id')


class AuthorizeRevokeItem(BaseModel):
    """Single revoke entry in authorize request."""
    subject_type: str
    subject_id: int
    relation: str
    include_children: bool = Field(default=True)
    model_id: Optional[str] = Field(default=None)


class AuthorizeRequest(BaseModel):
    """Request body for resource authorization API."""
    grants: List[AuthorizeGrantItem] = Field(default_factory=list)
    revokes: List[AuthorizeRevokeItem] = Field(default_factory=list)


class ResourcePermissionItem(BaseModel):
    """Single permission entry in resource permissions list."""
    subject_type: str
    subject_id: int
    subject_name: Optional[str] = None
    relation: str
    include_children: Optional[bool] = None
    model_id: Optional[str] = None
    model_name: Optional[str] = None


class RelationModelItem(BaseModel):
    id: str
    name: str
    relation: str = Field(description='owner | manager | editor | viewer')
    permissions: List[str] = Field(default_factory=list)
    permissions_explicit: bool = False
    is_system: bool = False
    # 授权级别：决定前台授权人需具备的资源权限档位（与 PRD 管理所有者/管理者/使用者对应）
    grant_tier: str = Field(
        default='usage',
        description='owner=所有者级 | manager=管理级 | usage=使用级',
    )


class RelationModelCreateRequest(BaseModel):
    name: str
    relation: str = Field(description='owner | manager | editor | viewer')
    permissions: List[str] = Field(default_factory=list)


class RelationModelUpdateRequest(BaseModel):
    name: Optional[str] = None
    permissions: Optional[List[str]] = None
