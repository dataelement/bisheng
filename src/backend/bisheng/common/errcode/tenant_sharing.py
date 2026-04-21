"""Tenant sharing module error codes, module code: 195 (F017).

Declared in CLAUDE.md + release-contract.md; this file is the authoritative registry.
Inherits BaseErrorCode -> HTTP 200 + UnifiedResponseModel.status_code (per project convention).
"""
from .base import BaseErrorCode


class RootOnlyShareError(BaseErrorCode):
    """Non-Root resource cannot be shared to Child Tenants (AC-01 derivative).

    Raised by PATCH /api/v1/resources/{type}/{id}/share when the target resource
    has tenant_id != 1 (Root).
    """
    Code: int = 19501
    Msg: str = 'Only Root Tenant can share resources'


class ResourceTypeNotShareableError(BaseErrorCode):
    """Resource type is not in the supported sharing list.

    Supported: knowledge_space / workflow / assistant / channel / tool.
    """
    Code: int = 19502
    Msg: str = 'Resource type does not support sharing'


class StorageSharingFallbackError(BaseErrorCode):
    """Cross-tenant MinIO/Milvus fallback to Root prefix/collection failed (AC-06).

    Raised when Child user attempts to read a Root-shared file/vector but the
    Root prefix lookup also fails (genuine missing object, not just leaf miss).
    """
    Code: int = 19503
    Msg: str = 'Cross-tenant storage fallback failed'


class TenantContextMissingError(BaseErrorCode):
    """get_current_tenant_id() returned None when writing derived data (AC-11).

    Raised by ChatMessageService / MessageSessionService / LLMTokenTracker /
    ModelCallLogger to prevent INV-T13 pollution. The middleware layer
    (F012) must always set the tenant context on HTTP / WS / Celery paths;
    a None value indicates a framework-level bug.
    """
    Code: int = 19504
    Msg: str = 'Tenant context missing; cannot write derived data'
