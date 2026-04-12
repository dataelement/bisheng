"""Pydantic DTOs for Role API requests and responses.

Part of F005-role-menu-quota.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=128)
    department_id: Optional[int] = None
    quota_config: Optional[dict] = None
    remark: Optional[str] = Field(None, max_length=512)


class RoleUpdateRequest(BaseModel):
    role_name: Optional[str] = Field(None, min_length=1, max_length=128)
    department_id: Optional[int] = None
    quota_config: Optional[dict] = None
    remark: Optional[str] = Field(None, max_length=512)


class RoleListResponse(BaseModel):
    id: int
    role_name: str
    role_type: str  # 'global' | 'tenant'
    department_id: Optional[int] = None
    department_name: Optional[str] = None
    quota_config: Optional[dict] = None
    remark: Optional[str] = None
    user_count: int = 0
    is_readonly: bool = False
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None


class EffectiveQuotaItem(BaseModel):
    resource_type: str
    role_quota: int  # multi-role max, -1=unlimited
    tenant_quota: int  # tenant limit, -1=unlimited
    tenant_used: int  # tenant total usage
    user_used: int  # user's own usage
    effective: int  # min(tenant_remaining, role_quota), -1=unlimited


class MenuUpdateRequest(BaseModel):
    menu_ids: List[str]  # WebMenuResource values
