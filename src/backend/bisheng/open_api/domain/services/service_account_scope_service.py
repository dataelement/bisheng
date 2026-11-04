"""Authoritative management admission and a fixed, request-local tenant snapshot."""

from contextlib import asynccontextmanager
from contextvars import ContextVar

from loguru import logger

from bisheng.admin.application.tenant_scope import (
    current_admin_scope,
    ensure_service_account_tenant_available,
    read_service_account_scope,
    set_service_account_scope,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.open_api import (
    OpenApiAuthDependencyUnavailableError,
    ServiceAccountManagementScopeChangedError,
    ServiceAccountOperationForbiddenError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import DEFAULT_TENANT_ID, management_tenant_scope, tenant_execution_scope

_admitted_tenant: ContextVar[int | None] = ContextVar("service_account_admitted_tenant", default=None)


def _expected_tenant(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        expected = int(value)
        if expected <= 0:
            raise ValueError("Expected tenant must be positive")
        return expected
    except (ValueError, TypeError) as exc:
        raise ServiceAccountManagementScopeChangedError() from exc


class ServiceAccountScopeService:
    @staticmethod
    def admitted_tenant() -> int | None:
        return _admitted_tenant.get()

    @classmethod
    @asynccontextmanager
    async def bind_request(cls, operator, *, expected_tenant: str | None, writing: bool):
        expected = _expected_tenant(expected_tenant)
        try:
            if not settings.multi_tenant.enabled:
                tenant_id = DEFAULT_TENANT_ID
            elif operator.is_global_super:
                selected = await current_admin_scope(operator.user_id)
                if writing and (selected is None or expected is None):
                    raise ServiceAccountManagementScopeChangedError()
                if expected is not None and expected != selected:
                    raise ServiceAccountManagementScopeChangedError()
                # Legacy reads without a header retain the authenticated tenant when no scope exists.
                tenant_id = selected if selected is not None else operator.tenant_id
            else:
                tenant_id = operator.tenant_id
            if expected is not None and expected != tenant_id:
                raise ServiceAccountManagementScopeChangedError()
            if settings.multi_tenant.enabled:
                await ensure_service_account_tenant_available(tenant_id)
        except BaseErrorCode:
            raise
        except Exception as exc:
            logger.opt(exception=True).warning("open_api management scope lookup failed")
            raise OpenApiAuthDependencyUnavailableError() from exc

        # Clear stale middleware overrides as well as pinning current/visible tenant ids.
        with tenant_execution_scope(tenant_id), management_tenant_scope(tenant_id):
            token = _admitted_tenant.set(tenant_id)
            try:
                yield tenant_id
            finally:
                _admitted_tenant.reset(token)

    @staticmethod
    def _require_super(operator):
        if not operator.is_global_super:
            raise ServiceAccountOperationForbiddenError()

    @classmethod
    async def get_scope(cls, operator) -> dict:
        cls._require_super(operator)
        if not settings.multi_tenant.enabled:
            return {"scope_tenant_id": DEFAULT_TENANT_ID, "expires_at": None}
        try:
            value = await read_service_account_scope(operator.user_id)
            if value["scope_tenant_id"] is not None:
                await ensure_service_account_tenant_available(value["scope_tenant_id"])
            return value
        except BaseErrorCode:
            raise
        except Exception as exc:
            logger.opt(exception=True).warning("open_api management scope read failed")
            raise OpenApiAuthDependencyUnavailableError() from exc

    @classmethod
    async def set_scope(cls, operator, tenant_id: int, request_context: dict | None = None) -> dict:
        cls._require_super(operator)
        if not settings.multi_tenant.enabled:
            raise ServiceAccountOperationForbiddenError()
        try:
            return await set_service_account_scope(operator.user_id, tenant_id, request_context)
        except BaseErrorCode:
            raise
        except Exception as exc:
            logger.opt(exception=True).warning("open_api management scope switch failed")
            raise OpenApiAuthDependencyUnavailableError() from exc
