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


# ---------------------------------------------------------------------------
# F016 Tenant Quota Tree DTOs (AC-06).
# ---------------------------------------------------------------------------

class TenantQuotaUsageItem(BaseModel):
    """Per-resource-type usage entry within a TenantQuotaTreeNode."""
    resource_type: str
    used: int
    limit: int  # -1 = unlimited
    utilization: float  # 0.0 ~ 1.0+ (>1.0 indicates over-quota)


class TenantQuotaTreeNode(BaseModel):
    tenant_id: int
    tenant_name: str
    parent_tenant_id: Optional[int] = None
    quota_config: dict = Field(default_factory=dict)
    usage: List[TenantQuotaUsageItem] = Field(default_factory=list)


class TenantQuotaTreeResponse(BaseModel):
    root: TenantQuotaTreeNode
    children: List[TenantQuotaTreeNode] = Field(default_factory=list)


class UserTenantItem(BaseModel):
    tenant_id: int
    tenant_name: str
    tenant_code: str
    logo: Optional[str] = None
    status: str
    last_access_time: Optional[datetime] = None
    is_default: int = 0


# ---------------------------------------------------------------------------
# F011 mount / unmount / migrate-from-root DTOs (v2.5.1)
# ---------------------------------------------------------------------------

class MountTenantRequest(BaseModel):
    tenant_code: str = Field(..., min_length=1, max_length=64)
    tenant_name: str = Field(..., min_length=1, max_length=128)


class UnmountTenantRequest(BaseModel):
    """Body kept for backwards compatibility; ignored.

    v2.5.1 收窄到唯一路径（资源迁回 Root + Child 归档）。旧客户端可能仍发
    ``{"policy": ...}``，本字段保留以避免 422，但任何值都走 migrate 行为。
    """
    policy: Optional[Literal['migrate', 'archive', 'manual']] = None


class MigrateFromRootRequest(BaseModel):
    resource_type: Literal[
        'knowledge', 'flow', 'assistant', 'channel', 't_gpts_tools',
    ]
    resource_ids: List[int] = Field(..., min_length=1, max_length=500)
    new_owner_user_id: Optional[int] = None


# ---------------------------------------------------------------------------
# F018 resource-owner-transfer DTOs (v2.5.1)
# ---------------------------------------------------------------------------

# Literal tuple mirrors ``resource_type_registry.SUPPORTED_TYPES`` — keeping
# them in sync is a release-contract invariant for spec §5 / PRD §5.6.4.1.
TransferResourceType = Literal[
    'knowledge_space', 'folder', 'knowledge_file',
    'workflow', 'assistant', 'tool', 'channel',
]


class TransferOwnerRequest(BaseModel):
    from_user_id: int = Field(..., gt=0)
    to_user_id: int = Field(..., gt=0)
    resource_types: List[TransferResourceType] = Field(..., min_length=1)
    # Mixed int / str so that Flow/Assistant/Channel UUIDs and integer ids
    # (knowledge_space, folder, knowledge_file, tool) travel in the same
    # list. The service silently drops entries whose type doesn't match
    # the target table's id_type.
    resource_ids: Optional[List[str]] = None
    reason: str = Field(default='', max_length=1000)


class TransferOwnerResponse(BaseModel):
    transferred_count: int
    transfer_log_id: Optional[str] = None


class PendingTransferItem(BaseModel):
    user_id: int
    resource_count: int
    current_leaf_tenant_id: int
