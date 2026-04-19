"""Tenant quota module error codes, module code: 194 (F016).

Declared in CLAUDE.md + release-contract.md; this file is the authoritative registry.
Inherits BaseErrorCode -> HTTP 200 + UnifiedResponseModel.status_code (per project convention).
"""
from .base import BaseErrorCode


class TenantQuotaExceededError(BaseErrorCode):
    """Leaf Tenant or Root hard-cap quota exceeded (AC-01, AC-07, AC-08).

    When raised because Root usage reached Root limit (Child creation blocked
    by group-wide cap), the Msg variant should contain '集团总量已耗尽' for AC-08.
    """
    Code: int = 19401
    Msg: str = 'Tenant quota exceeded'


class TenantRoleQuotaExceededError(BaseErrorCode):
    """Role-level quota exceeded after Tenant chain check passed (AC-01)."""
    Code: int = 19402
    Msg: str = 'Role quota exceeded'


class TenantStorageQuotaExceededError(BaseErrorCode):
    """Storage quota (storage_gb / knowledge_space_file) exceeded (AC-04)."""
    Code: int = 19403
    Msg: str = 'Storage quota exceeded'
