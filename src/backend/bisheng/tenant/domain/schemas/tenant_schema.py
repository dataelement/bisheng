"""Pydantic DTOs for Tenant management API.

Part of F010-tenant-management-ui.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    tenant_name: str = Field(..., min_length=2, max_length=128)
    tenant_code: str = Field(..., pattern=r'^[a-zA-Z][a-zA-Z0-9_-]{1,63}$')
    logo: Optional[str] = None
    contact_name: Optional[str] = Field(None, max_length=64)
    contact_phone: Optional[str] = Field(None, max_length=32)
    contact_email: Optional[str] = Field(None, max_length=128)
    quota_config: Optional[dict] = None
    admin_user_ids: List[int] = Field(..., min_length=1)


class TenantUpdate(BaseModel):
    tenant_name: Optional[str] = Field(None, min_length=2, max_length=128)
    logo: Optional[str] = None
    contact_name: Optional[str] = Field(None, max_length=64)
    contact_phone: Optional[str] = Field(None, max_length=32)
    contact_email: Optional[str] = Field(None, max_length=128)


class TenantStatusUpdate(BaseModel):
    status: Literal['active', 'disabled', 'archived']


class TenantQuotaUpdate(BaseModel):
    quota_config: dict


class TenantUserAdd(BaseModel):
    user_ids: List[int] = Field(..., min_length=1)
    is_admin: bool = False


class SwitchTenantRequest(BaseModel):
    tenant_id: int


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------

class TenantListItem(BaseModel):
    id: int
    tenant_name: str
    tenant_code: str
    logo: Optional[str] = None
    status: str
    user_count: int = 0
    storage_used_gb: Optional[float] = None
    storage_quota_gb: Optional[float] = None
    create_time: Optional[datetime] = None


class TenantDetail(TenantListItem):
    root_dept_id: Optional[int] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    quota_config: Optional[dict] = None
    storage_config: Optional[dict] = None
    admin_users: List[Dict] = []


class TenantQuotaResponse(BaseModel):
    quota_config: Optional[dict] = None
    usage: dict = {}


class UserTenantItem(BaseModel):
    tenant_id: int
    tenant_name: str
    tenant_code: str
    logo: Optional[str] = None
    status: str
    last_access_time: Optional[datetime] = None
    is_default: int = 0
