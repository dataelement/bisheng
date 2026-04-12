"""Pydantic DTOs for permission module."""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

# Valid OpenFGA resource types
VALID_RESOURCE_TYPES = {
    'knowledge_space', 'folder', 'knowledge_file',
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


class PermissionCheckResponse(BaseModel):
    """Response data for permission check API."""
    allowed: bool


class AuthorizeGrantItem(BaseModel):
    """Single grant entry in authorize request."""
    subject_type: str = Field(description='user | department | user_group')
    subject_id: int
    relation: str = Field(description='owner | manager | editor | viewer')
    include_children: bool = Field(default=True, description='For department: include sub-departments')


class AuthorizeRevokeItem(BaseModel):
    """Single revoke entry in authorize request."""
    subject_type: str
    subject_id: int
    relation: str
    include_children: bool = Field(default=True)


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
