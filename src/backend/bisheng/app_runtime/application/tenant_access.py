"""Public request-tenant policy; resource permission checks remain with the caller."""

from bisheng.app_runtime.domain.services.tenant_access import require_app_request_tenant

__all__ = ["require_app_request_tenant"]
