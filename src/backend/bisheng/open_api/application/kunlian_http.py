"""昆联 Workflow 入口统一用户依赖; 不接受普通 v2 身份头。"""

from fastapi import Query, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger

from bisheng.common.errcode.flow import (
    WorkflowRegistrationConflict,
    WorkflowRegistrationDenied,
    WorkflowRegistrationError,
    WorkflowRegistrationUnavailable,
)
from bisheng.common.errcode.open_api import OpenApiCredentialInvalidError, OpenApiKunlianRateLimitedError
from bisheng.common.errcode.sso_sync import (
    KunlianBindingConflictError,
    KunlianDependencyUnavailableError,
    KunlianError,
    KunlianIdentityUnavailableError,
    KunlianLoginInvalidError,
)
from bisheng.common.schemas.api import resp_500
from bisheng.open_api.application.kunlian_access import KunlianAccessService
from bisheng.open_api.application.kunlian_limits import check_request
from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError, KunlianCredentialService
from bisheng.workflow.application.kunlian_workflow_authorization import AuthorizationError
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError


def kunlian_capability(capability):
    def decorate(endpoint):
        endpoint.kunlian_capability = capability
        return endpoint

    return decorate


class KunlianApiRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                response = await handler(request)
            except OpenApiKunlianRateLimitedError as error:
                response = JSONResponse(
                    resp_500(code=error.code, message=error.message).model_dump(),
                    status_code=error.http_status,
                    headers={"Retry-After": str(getattr(request.state, "kunlian_request_window_seconds", 60))},
                )
            except KunlianAccessError as error:
                owner = {
                    "UNAUTHENTICATED": OpenApiCredentialInvalidError,
                    "FORBIDDEN": KunlianIdentityUnavailableError,
                    "INVALID_INPUT": KunlianLoginInvalidError,
                    "CONFLICT": KunlianBindingConflictError,
                    "UNAVAILABLE": KunlianDependencyUnavailableError,
                    "NOT_FOUND": KunlianIdentityUnavailableError,
                }[error.code]()
                response = JSONResponse(
                    resp_500(code=owner.code, message=owner.message).model_dump(),
                    status_code=error.http_status,
                )
            except (RunError, AuthorizationError) as error:
                category = str(error)
                if category == "UNAUTHENTICATED":
                    status, owner = 401, OpenApiCredentialInvalidError()
                elif category in {"SESSION_NOT_FOUND", "NOT_FOUND"}:
                    status, owner = 404, WorkflowRegistrationDenied()
                elif category == "FORBIDDEN":
                    status, owner = 403, WorkflowRegistrationDenied()
                elif category == "UNAVAILABLE":
                    status, owner = 503, WorkflowRegistrationUnavailable()
                elif category == "INVALID_INPUT":
                    status, owner = 422, KunlianLoginInvalidError()
                else:
                    status, owner = 409, WorkflowRegistrationConflict()
                response = JSONResponse(
                    resp_500(code=owner.code, message=category).model_dump(),
                    status_code=status,
                )
            except WorkflowRegistrationError as error:
                # Dedicated entry only: do not change ordinary v2 Owner mapping.
                response = JSONResponse(
                    resp_500(code=error.code, message=error.message).model_dump(),
                    status_code=error.http_status,
                )
            except KunlianError as error:
                response = error.to_response()
            response.headers["Cache-Control"] = "no-store"
            audit_id = getattr(request.state, "kunlian_audit_id", None)
            if audit_id:
                await request.state.kunlian_audit_service.finish(audit_id, response.status_code)
            return response

        return guarded


def _read_optional_external_tenant_header(request: Request) -> str | None:
    values = request.headers.getlist("x-kunlian-tenant-id")
    if not values:
        return None
    if len(values) != 1:
        raise KunlianAccessError("INVALID_INPUT")
    tenant_id = values[0]
    if not tenant_id or not tenant_id.strip() or tenant_id != tenant_id.strip() or len(tenant_id) > 64:
        raise KunlianAccessError("INVALID_INPUT")
    return tenant_id


async def get_kunlian_request_user(
    request: Request,
    user_account: str = Query(..., min_length=1, max_length=128),
):
    if any(name in request.headers for name in ("cookie", "x-on-behalf-of", "x-end-user", "x-user-id", "x-tenant-id")):
        raise KunlianAccessError("INVALID_INPUT")
    if len(request.query_params.getlist("user_account")) != 1 or any(
        name in request.query_params for name in ("external_tenant_id", "external_user_id")
    ):
        raise KunlianAccessError("INVALID_INPUT")
    preferred_external_tenant_id = _read_optional_external_tenant_header(request)
    capability = getattr(request.scope.get("endpoint"), "kunlian_capability", None)
    if capability is None:
        raise KunlianAccessError("FORBIDDEN")
    service = getattr(request.app.state, "kunlian_access_service", None)
    if service is None:
        from bisheng.sso_sync.application.kunlian_identity import get_kunlian_identity_application

        async def identity_factory():
            return await get_kunlian_identity_application(request.app)

        from bisheng.user.application.kunlian_account import get_kunlian_account_application

        async def account_factory():
            return await get_kunlian_account_application(request.app)

        service = KunlianAccessService(KunlianCredentialService(), identity_factory, account_resolver=account_factory)
    preferred_local_tenant_id = None
    user_kwargs = {}
    if isinstance(service, KunlianAccessService):
        if preferred_external_tenant_id is not None:
            user_kwargs["preferred_external_tenant_id"] = preferred_external_tenant_id
        else:
            workflow_id = request.path_params.get("workflow_id")
            if isinstance(workflow_id, str) and workflow_id.strip():
                resolver = getattr(request.app.state, "kunlian_workflow_tenant_resolver", None)
                if resolver is None:
                    from bisheng.workflow.application.kunlian_workflow_api import resolve_kunlian_workflow_tenant_id

                    resolver = resolve_kunlian_workflow_tenant_id
                preferred_local_tenant_id = await resolver(workflow_id)
                if preferred_local_tenant_id is not None:
                    user_kwargs["preferred_local_tenant_id"] = preferred_local_tenant_id
    try:
        async with service.use_user(
            request.headers.get("Authorization"),
            user_account,
            capability=capability,
            **user_kwargs,
        ) as access:
            from bisheng.core.logger import trace_id_var
            from bisheng.open_api.application.kunlian_audit import KunlianAuditService

            limiter = getattr(request.app.state, "kunlian_request_limiter", None)
            if limiter is None:
                from bisheng.common.services.config_service import settings

                policy = settings.get_workflow_conf().kunlian_api
                request.state.kunlian_request_window_seconds = policy.request_window_seconds
                await check_request(access, limit=policy.request_limit, window_seconds=policy.request_window_seconds)
            else:
                await limiter(access)
            request.state.kunlian_access = access
            audit = getattr(request.app.state, "kunlian_audit_service", None) or KunlianAuditService()
            request.state.kunlian_audit_service = audit
            route = getattr(request.scope.get("route"), "path", None)
            target = request.path_params.get("workflow_id") or request.path_params.get("session_id")
            request.state.kunlian_audit_id = await audit.begin(
                access,
                request.method,
                route,
                target,
                str(trace_id_var.get() or "") or None,
            )
            yield access
    except KunlianAccessError:
        raise
    except Exception:
        logger.exception("Kunlian request user resolution or business operation failed")
        raise
