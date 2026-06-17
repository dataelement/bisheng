"""Pydantic DTOs for Role API requests and responses.

Part of F005-role-menu-quota.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RoleCreateRequest(BaseModel):
    role_name: str = Field(..., min_length=1, max_length=128)
    department_id: int | None = None
    quota_config: dict | None = None
    remark: str | None = Field(None, max_length=512)
    menu_ids: list[str] | None = None


class RoleUpdateRequest(BaseModel):
    role_name: str | None = Field(None, min_length=1, max_length=128)
    department_id: int | None = None
    quota_config: dict | None = None
    remark: str | None = Field(None, max_length=512)
    menu_ids: list[str] | None = None


class RoleListResponse(BaseModel):
    id: int
    role_name: str
    role_type: str  # 'global' | 'tenant'
    department_id: int | None = None
    department_name: str | None = None
    department_scope_path: str | None = Field(
        default=None,
        description="从组织根到作用域部门的完整路径（基于 Department.path），与前端树是否裁剪无关",
    )
    quota_config: dict | None = None
    remark: str | None = None
    user_count: int = 0
    creator_name: str | None = None
    is_readonly: bool = False
    create_time: datetime | None = None
    update_time: datetime | None = None


class EffectiveQuotaItem(BaseModel):
    resource_type: str
    # knowledge_space_file quota/usage is measured in GB and is fractional, so
    # every numeric field must accept float — int-only rejected GB values and
    # 500'd the whole /quota/effective response (pydantic int_from_float).
    role_quota: int | float  # multi-role max, -1=unlimited; GB may be one-decimal float
    tenant_quota: int | float  # tenant limit, -1=unlimited
    tenant_used: int | float  # tenant total usage
    user_used: int | float  # user's own usage
    effective: int | float  # min(tenant_remaining, role_quota), -1=unlimited


class MenuUpdateRequest(BaseModel):
    menu_ids: list[str]  # WebMenuResource values
