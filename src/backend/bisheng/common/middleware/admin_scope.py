"""Bind a concrete browser management view; execution identities remain independent."""

from __future__ import annotations

import re
from collections.abc import Iterable

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from bisheng.common.errcode.admin_scope import AdminScopeUnavailableError
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import ServiceAccountManagementScopeChangedError
from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_manager import get_redis_client
from bisheng.core.context.tenant import (
    management_tenant_scope,
    set_admin_scope_tenant_id,
    set_is_management_api,
    set_management_all_tenants,
)
from bisheng.utils.http_middleware import (
    _check_is_global_super,
    _decode_jwt_subject,
    _extract_http_access_token,
)

MANAGEMENT_API_PREFIXES: tuple[str, ...] = (
    "/api/v1/llm",
    "/api/v1/workstation",
    "/api/v1/linsight",
    "/api/v1/tool",
    "/api/v1/knowledge",
    "/api/v1/chat/online",
    "/api/v1/admin",
    "/api/v1/service-accounts",
    "/api/v1/personal-tokens",
    "/api/v1/workflow/list",
    "/api/v1/workflow/get_one_flow",
    "/api/v1/workflow/create",
    "/api/v1/workflow/update",
    "/api/v1/workflow/versions",
    "/api/v1/workflow/change_version",
    "/api/v1/workflow/status",
    "/api/v1/workflow/write/auth",
    "/api/v1/flows",
    "/api/v1/assistant",
    "/api/v1/apps",
    "/api/v1/approval/admin",
    "/api/v1/audit",
    "/api/v1/app-runtime-audit",
    "/api/v1/permissions",
    "/api/v1/roles",
    "/api/v1/user-groups",
    "/api/v1/tag",
    "/api/v1/evaluation",
)


# Explicit mutating management routes only: shared reads and calls need no new header.
_EXPECTED_SCOPE_WRITES = (
    (frozenset({"PATCH", "DELETE"}), r"/api/v1/apps/[^/]+"),
    (frozenset({"POST"}), r"/api/v1/apps/[^/]+/actions/[^/]+"),
    (frozenset({"PUT", "DELETE", "POST"}), r"/api/v1/apps/[^/]+/secrets/[^/]+"),
    (frozenset({"PATCH"}), r"/api/v1/apps/[^/]+/data/tables/[^/]+/rows(?:/[^/]+)?"),
    (
        frozenset({"POST", "PATCH"}),
        r"/api/v1/apps/[^/]+/runtime/(?:materials(?:/[^/]+)?|restore|operations/[^/]+/cancel)",
    ),
    (frozenset({"POST"}), r"/api/v1/apps/[^/]+/(?:withdraw|publish/manual-publish)"),
    (frozenset({"POST", "DELETE"}), r"/api/v1/apps/[^/]+/versions/[^/]+/preview(?:/[^/]+)?"),
    (frozenset({"POST", "PUT", "PATCH", "DELETE"}), r"/api/v1/(?:roles|user-groups)(?:/[^/]+)?"),
    (frozenset({"POST"}), r"/api/v1/workflow/(?:create|versions|change_version)"),
    (frozenset({"PATCH"}), r"/api/v1/workflow/(?:update/[^/]+|status)"),
    (frozenset({"PUT", "DELETE"}), r"/api/v1/workflow/versions/[^/]+"),
    (frozenset({"DELETE"}), r"/api/v1/flows/[^/]+"),
    (frozenset({"POST", "PUT"}), r"/api/v1/assistant"),
    (frozenset({"POST"}), r"/api/v1/assistant/(?:delete|status|flow|tool)"),
    (frozenset({"POST"}), r"/api/v1/knowledge/(?:create|copy|qa/copy|upload(?:/[^/]+)?|tags|file/tags(?:/batch)?)"),
)


def _is_management_api_path(path: str, prefixes: Iterable[str] = MANAGEMENT_API_PREFIXES) -> bool:
    return any(path == value or path.startswith(value + "/") for value in prefixes)


def requires_expected_management_tenant(method: str, path: str) -> bool:
    return any(
        method in methods and re.fullmatch(pattern, path.rstrip("/")) for methods, pattern in _EXPECTED_SCOPE_WRITES
    )


def _scope_error(exc: BaseErrorCode, tenant_id: int | None = None):
    status = 503 if isinstance(exc, AdminScopeUnavailableError) else 409
    if exc.code == 19703:
        status = 400
    response = JSONResponse(exc.return_resp_instance().model_dump(), status_code=status)
    if tenant_id is not None:
        response.headers["X-Management-Tenant"] = str(tenant_id)
    return response


class AdminScopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from bisheng.admin.application.tenant_scope import (
            require_expected_management_tenant,
            resolve_management_scope,
        )

        path = request.url.path
        personal_preview = (
            bool(re.fullmatch(r"/api/v1/apps/[^/]+/versions/[^/]+/preview(?:/[^/]+)?", path))
            and request.query_params.get("purpose") == "approval"
        )
        is_mgmt = _is_management_api_path(path) and not personal_preview
        set_is_management_api(is_mgmt)
        set_admin_scope_tenant_id(None)
        set_management_all_tenants(False)
        if not is_mgmt:
            return await call_next(request)
        token = _extract_http_access_token(request)
        subject = _decode_jwt_subject(token) if token else None
        if not subject or not subject.get("user_id"):
            return await call_next(request)
        user_id = int(subject["user_id"])
        writing = requires_expected_management_tenant(request.method, path)
        scope = None
        try:
            is_super = await _check_is_global_super(user_id)
            scope = await resolve_management_scope(user_id, is_super=is_super, for_write=writing)
            if writing:
                require_expected_management_tenant(request.headers.get("X-Management-Tenant"), scope)
            old_header = request.headers.get("X-Service-Account-Tenant")
            new_header = request.headers.get("X-Management-Tenant")
            if path.startswith("/api/v1/service-accounts") and new_header is not None:
                if (old_header is not None and new_header != old_header) or new_header != str(scope.tenant_id):
                    raise ServiceAccountManagementScopeChangedError()
        except BaseErrorCode as exc:
            return _scope_error(exc, scope.tenant_id if scope else None)
        except Exception:
            logger.opt(exception=True).warning("Management scope admission failed")
            return _scope_error(AdminScopeUnavailableError())
        request.state.management_tenant_id = scope.tenant_id
        with management_tenant_scope(scope.tenant_id):
            response = await call_next(request)
        response.headers["X-Management-Tenant"] = str(scope.tenant_id)
        response.headers["X-Management-Tenant-Source"] = scope.source
        if scope.source == "selected":
            try:
                redis = await get_redis_client()
                await redis.aexpire_key(f"admin_scope:{user_id}", settings.multi_tenant.admin_scope_ttl_seconds)
            except Exception:
                # Refresh is optional; the next request revalidates an expired selection.
                logger.opt(exception=True).warning("Management scope TTL refresh failed")
        return response
