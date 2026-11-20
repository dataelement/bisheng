"""昆联 Workflow 反向调用受信协议端点（kunlian-workflow-candidate-v1）。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bisheng.common.schemas.api import resp_200
from bisheng.common.services.config_service import settings
from bisheng.open_api.api.dependencies import open_api_access_context
from bisheng.open_endpoints.api.endpoints.workflow import invoke_workflow as legacy_invoke_workflow
from bisheng.open_endpoints.domain.schemas.workflow import OpenWorkflowInvokeRequest
from bisheng.sso_sync.application.kunlian import resolve_kunlian_client_credentials_material
from bisheng.workflow.application.kunlian_runtime import create_kunlian_runtime_service
from bisheng.workflow.domain.clients.kunlian_resources import (
    KunlianInvalidTokenError,
    KunlianNotConfiguredError,
    KunlianTimeoutError,
    WorkflowExecutionIntrospection,
    introspect_workflow_execution_token,
    sanitize_log_field,
)
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import RunError, RunRequest, RunSubject

router = APIRouter(prefix="/api/v2/workflow", tags=["Kunlian Workflow Candidate"])


class CandidateInvokeBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workflow_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    workflow_version_id: int | str | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] | None = None


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"status_code": status_code, "status_message": message, "error": code},
    )


def _map_run_error(exc: RunError) -> JSONResponse:
    code = str(exc)
    mapping = {
        "FORBIDDEN": (403, "Forbidden"),
        "SESSION_NOT_FOUND": (404, "Session not found"),
        "VERSION_UNAVAILABLE": (409, "Workflow version unavailable"),
        "IDEMPOTENCY_CONFLICT": (409, "Idempotency conflict"),
        "IDEMPOTENCY_EXPIRED": (409, "Idempotency expired"),
        "INVALID_INPUT": (422, "Invalid input"),
        "CONTROL_UNAVAILABLE": (409, "Control unavailable"),
        "UNAVAILABLE": (503, "Service unavailable"),
    }
    status_code, msg = mapping.get(code, (400, code))
    return _error_response(status_code, code, msg)


def _extract_bearer_token(request: Request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        raise KunlianInvalidTokenError()
    token = auth[7:].strip()
    if not token:
        raise KunlianInvalidTokenError()
    return token


async def _resolve_candidate_user(app, introspected: WorkflowExecutionIntrospection):
    config = settings.sso_sync.kunlian
    connection_id = config.connection_id or "kunlian"

    if introspected.external_tenant_id:
        from bisheng.sso_sync.application.kunlian_identity import get_kunlian_identity_application

        identity_app = await get_kunlian_identity_application(app)
        user = await identity_app.resolve(
            connection_id,
            introspected.external_tenant_id,
            introspected.external_user_id,
        )
        return user, connection_id

    if introspected.user_account:
        from bisheng.user.application.kunlian_account import get_kunlian_account_application

        account_app = await get_kunlian_account_application(app)
        user = await account_app.resolve_by_account(introspected.user_account)
        return user, connection_id

    raise KunlianInvalidTokenError()


async def _build_candidate_runtime_service(app):
    from bisheng.worker.workflow.kunlian_runtime import dispatch_run

    async def resolve(subject: RunSubject):
        from types import SimpleNamespace

        from bisheng.user.application.runtime_identity import read_current_person_facts

        facts = (await read_current_person_facts([subject.user_id])).get(subject.user_id, {})
        if facts.get("state") != "active" or facts.get("tenant_id") != subject.tenant_id:
            raise RunError("FORBIDDEN")
        return SimpleNamespace(user_id=subject.user_id, tenant_id=subject.tenant_id)

    return create_kunlian_runtime_service(resolve_user=resolve, dispatch=dispatch_run)


async def _authenticate_candidate(
    request: Request,
    *,
    expected_workflow_version_id: str | int | None = None,
) -> tuple[RunSubject, WorkflowExecutionIntrospection]:
    token = _extract_bearer_token(request)
    wf_conf = settings.get_workflow_conf()
    creds = await resolve_kunlian_client_credentials_material(
        oidc_token_url=wf_conf.platform_agent.oidc_token_url,
    )
    introspected = await introspect_workflow_execution_token(
        oidc_token_url=creds.oidc_token_url,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        token=token,
        expected_audience=wf_conf.platform_agent.resource_audience or creds.client_id,
        expected_workflow_version_id=expected_workflow_version_id,
        timeout_seconds=wf_conf.platform_agent.list_timeout_seconds,
    )
    user, connection_id = await _resolve_candidate_user(request.app, introspected)
    subject = RunSubject(
        tenant_id=int(user.tenant_id),
        connection_id=connection_id,
        user_id=int(user.user_id),
        identity_connection_id=connection_id,
        external_tenant_id=introspected.external_tenant_id,
        external_user_id=introspected.external_user_id,
    )
    return subject, introspected


def _format_session_payload(row) -> dict[str, Any]:
    material = row.material if isinstance(row.material, dict) else {}
    agent_runtime = material.get("agent_runtime") if isinstance(material.get("agent_runtime"), dict) else {}
    data: dict[str, Any] = {
        "session_id": row.session_id,
        "workflow_id": row.workflow_id,
        "workflow_version_id": str(row.workflow_version_id),
        "status": row.status.lower(),
    }
    if material.get("context_id"):
        data["context_id"] = material["context_id"]
    if row.status == "SUCCEEDED" and isinstance(row.output, dict):
        data["result"] = row.output.get("result") if "result" in row.output else row.output
        data["output"] = row.output
    elif row.status == "WAITING_INPUT":
        if agent_runtime.get("agent_run_id"):
            data["agent_run_id"] = agent_runtime["agent_run_id"]
        if agent_runtime.get("interaction_id") or material.get("interaction_id"):
            data["interaction_id"] = agent_runtime.get("interaction_id") or material.get("interaction_id")
    elif row.status == "FAILED":
        data["error"] = row.error or "EXECUTION_FAILED"
    return data


@router.get("/capabilities")
async def workflow_capabilities():
    return resp_200(
        {
            "protocol_version": "kunlian-workflow-candidate-v1",
            "fixed_workflow_version": True,
            "operation_lookup": True,
        }
    )


@router.post("/invoke")
async def candidate_or_legacy_invoke(request: Request, response: Response):
    try:
        raw_body = await request.json()
    except Exception:
        return _error_response(422, "INVALID_INPUT", "Invalid JSON payload")

    idem_key = (
        request.headers.get("X-Idempotency-Key")
        or request.headers.get("x-idempotency-key")
        or request.headers.get("Idempotency-Key")
        or ""
    ).strip()
    is_candidate = bool(idem_key) or (isinstance(raw_body, dict) and "workflow_version_id" in raw_body)

    if not is_candidate:
        request.scope["endpoint"] = legacy_invoke_workflow
        async with open_api_access_context(request):
            try:
                legacy_body = OpenWorkflowInvokeRequest.model_validate(raw_body)
            except ValidationError:
                return _error_response(422, "INVALID_INPUT", "Invalid workflow invoke request")
            return await legacy_invoke_workflow(legacy_body)

    try:
        candidate_body = CandidateInvokeBody.model_validate(raw_body)
        raw_inputs = candidate_body.inputs if candidate_body.inputs is not None else candidate_body.input
        str_inputs = {str(k): "" if v is None else str(v) for k, v in (raw_inputs or {}).items()}
        run_req = RunRequest(
            workflow_id=candidate_body.workflow_id,
            workflow_version_id=candidate_body.workflow_version_id,
            input=str_inputs,
        )
    except ValidationError:
        return _error_response(422, "INVALID_INPUT", "Invalid candidate workflow invoke request")

    try:
        subject, introspected = await _authenticate_candidate(
            request,
            expected_workflow_version_id=run_req.workflow_version_id,
        )
    except KunlianInvalidTokenError as exc:
        logger.warning("kunlian candidate invoke auth rejected err={}", type(exc).__name__)
        return _error_response(401, "INVALID_TOKEN", "Invalid execution token")
    except (KunlianNotConfiguredError, KunlianTimeoutError) as exc:
        logger.warning("kunlian candidate invoke dependency unavailable err={}", type(exc).__name__)
        return _error_response(503, "UNAVAILABLE", "OIDC introspection unavailable")
    except Exception as exc:
        logger.warning("kunlian candidate invoke auth failed err={}", type(exc).__name__)
        return _error_response(403, "FORBIDDEN", "Execution subject resolution failed")

    operation_key = idem_key or uuid4().hex
    try:
        service = await _build_candidate_runtime_service(request.app)
        row, created = await service.submit(
            subject,
            operation_key,
            run_req,
            allow_platform_agent=True,
            extra_material={
                "context_id": introspected.context_id,
                "operation_key": operation_key,
            },
        )
    except RunError as exc:
        return _map_run_error(exc)

    response.status_code = 202 if created else 200
    payload = _format_session_payload(row)
    payload["operation_key"] = operation_key
    logger.info(
        "kunlian candidate workflow invoked session_id={} version_id={} replay={} context_id={}",
        sanitize_log_field(row.session_id),
        row.workflow_version_id,
        not created,
        sanitize_log_field(introspected.context_id),
    )
    return resp_200(payload)


@router.get("/invocations/{operation_key}")
async def lookup_invocation(request: Request, operation_key: str):
    try:
        subject, _ = await _authenticate_candidate(request)
    except KunlianInvalidTokenError:
        return _error_response(401, "INVALID_TOKEN", "Invalid execution token")
    except (KunlianNotConfiguredError, KunlianTimeoutError):
        return _error_response(503, "UNAVAILABLE", "OIDC introspection unavailable")
    except Exception:
        return _error_response(403, "FORBIDDEN", "Execution subject resolution failed")

    try:
        service = await _build_candidate_runtime_service(request.app)
        row = await service.lookup_operation(subject, operation_key)
    except RunError as exc:
        return _map_run_error(exc)

    payload = _format_session_payload(row)
    payload["operation_key"] = operation_key
    return resp_200(payload)


@router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str):
    try:
        subject, _ = await _authenticate_candidate(request)
    except KunlianInvalidTokenError:
        return _error_response(401, "INVALID_TOKEN", "Invalid execution token")
    except (KunlianNotConfiguredError, KunlianTimeoutError):
        return _error_response(503, "UNAVAILABLE", "OIDC introspection unavailable")
    except Exception:
        return _error_response(403, "FORBIDDEN", "Execution subject resolution failed")

    try:
        service = await _build_candidate_runtime_service(request.app)
        row = await service.query(subject, session_id)
    except RunError as exc:
        return _map_run_error(exc)

    return resp_200(_format_session_payload(row))


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(request: Request, session_id: str, response: Response):
    try:
        subject, _ = await _authenticate_candidate(request)
    except KunlianInvalidTokenError:
        return _error_response(401, "INVALID_TOKEN", "Invalid execution token")
    except (KunlianNotConfiguredError, KunlianTimeoutError):
        return _error_response(503, "UNAVAILABLE", "OIDC introspection unavailable")
    except Exception:
        return _error_response(403, "FORBIDDEN", "Execution subject resolution failed")

    try:
        service = await _build_candidate_runtime_service(request.app)
        row = await service.cancel(subject, session_id)
    except RunError as exc:
        return _map_run_error(exc)

    response.status_code = 202 if row.status == "CANCEL_REQUESTED" else 200
    return resp_200(
        {
            "session_id": row.session_id,
            "status": row.status.lower(),
            "cancel_state": {"CANCEL_REQUESTED": "ACCEPTED", "CANCELLED": "CONFIRMED"}.get(
                row.status, "ALREADY_TERMINAL"
            ),
        }
    )
