"""仅供隔离测试应用装配的昆联候选运行接口。"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.permission import (
    PermissionCheckFailedError,
    PermissionPublishNotReadyError,
    PermissionServiceUnavailableError,
)
from bisheng.common.schemas.api import resp_200, resp_500
from bisheng.workflow.domain.schemas.kunlian_workflow_invocation import (
    RUN_EVENT_LIMIT,
    InteractionAnswer,
    RunError,
    RunRequest,
)

_HTTP_CODES = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "SESSION_NOT_FOUND": 404,
    "VERSION_UNAVAILABLE": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "IDEMPOTENCY_EXPIRED": 409,
    "INTERACTION_CONSUMED": 409,
    "INPUT_TIMEOUT": 409,
    "CONTROL_UNAVAILABLE": 409,
    "EVENT_CURSOR_EXPIRED": 409,
    "RESULT_NOT_AVAILABLE": 409,
    "INVALID_INPUT": 422,
    "UNAVAILABLE": 503,
}
_SAFE_FAILURES = {
    "QUEUE_TIMEOUT",
    "EXECUTION_TIMEOUT",
    "INPUT_TIMEOUT",
    "RESUME_QUEUE_TIMEOUT",
    "RESUME_EXECUTION_TIMEOUT",
    "EXECUTION_FAILED",
    "INVALID_OUTPUT",
    "FORBIDDEN",
    "RESUME_STATE_INVALID",
}


def _error(kind):
    status = _HTTP_CODES[kind]
    envelope = resp_500(code=status, message=kind)
    return JSONResponse(envelope.model_dump(), status_code=status, headers={"Cache-Control": "no-store"})


class _CandidateRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # 验证错误可能包含输入原文,对外只返回稳定分类。
                return _error("INVALID_INPUT")
            except RunError as exc:
                kind = str(exc)
                if kind not in _HTTP_CODES:
                    raise
                return _error(kind)
            except (
                SQLAlchemyError,
                PermissionCheckFailedError,
                PermissionPublishNotReadyError,
                PermissionServiceUnavailableError,
            ) as exc:
                logger.warning("昆联运行接口暂不可用,error_type={}", type(exc).__name__)
                return _error("UNAVAILABLE")

        return safe_handler


router = APIRouter(prefix="/kunlian/workflow-runs", route_class=_CandidateRoute)


def run_subject():
    # TODO [F122][EXT-01] 正式接入时从受信调用方和实际用户解析身份。
    raise RunError("UNAUTHENTICATED")


def run_service():
    raise RunError("UNAVAILABLE")


def _summary(row):
    return {
        "session_id": row.session_id,
        "workflow_id": row.workflow_id,
        "workflow_version_id": str(row.workflow_version_id),
        "status": row.status,
    }


def _cancel_state(row):
    return {"CANCEL_REQUESTED": "ACCEPTED", "CANCELLED": "CONFIRMED"}.get(row.status)


def _require_identifier(value):
    if len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
        raise RunError("SESSION_NOT_FOUND")


@router.post("", status_code=202)
async def submit(
    body: RunRequest,
    response: Response,
    key: Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,128}$")],
    subject=Depends(run_subject),
    service=Depends(run_service),
):
    # TODO [F122][EXT-02] 按正式协议映射字段、状态和错误码。
    row, created = await service.submit(subject, key, body)
    response.status_code = 202 if created else 200
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=_summary(row))


@router.get("/{session_id}")
async def query(
    session_id: str,
    response: Response,
    view: Literal["status", "result", "trace"] | None = None,
    subject=Depends(run_subject),
    service=Depends(run_service),
):
    _require_identifier(session_id)
    response.headers["Cache-Control"] = "no-store"
    if view == "status":
        row, resume_after = await service.status(subject, session_id)
        data = _summary(row)
        if row.error:
            data["error"] = row.error if row.error in _SAFE_FAILURES else "EXECUTION_FAILED"
        if cancel_state := _cancel_state(row):
            data["cancel_state"] = cancel_state
        if resume_after is not None:
            data["resume_after"] = resume_after
        return resp_200(data=data)
    if view == "result":
        return resp_200(data=await service.result(subject, session_id))
    if view == "trace":
        return resp_200(data=await service.trace(subject, session_id))
    row = await service.query(subject, session_id)
    data = _summary(row)
    if row.status == "SUCCEEDED":
        data["output"] = row.output
    elif row.status == "FAILED":
        data["error"] = (
            "EXECUTION_FAILED"
            if "run_control" in (row.material or {}) and row.error not in _SAFE_FAILURES
            else row.error
        )
    elif row.status == "WAITING_INPUT":
        # TODO [F123][EXT-02] 按正式合同映射表单、期限和轮询字段。
        data.update(
            interaction_id=row.material["interaction_id"], form=row.material["input_schema"], expires_at=row.deadline_at
        )
    return resp_200(data=data)


@router.post("/{session_id}/cancel", status_code=202)
async def cancel(session_id: str, response: Response, subject=Depends(run_subject), service=Depends(run_service)):
    # TODO [F127][EXT-02] 按正式合同映射取消受理及终态回执。
    _require_identifier(session_id)
    row = await service.cancel(subject, session_id)
    response.status_code = 202 if row.status == "CANCEL_REQUESTED" else 200
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data={**_summary(row), "cancel_state": _cancel_state(row) or "ALREADY_TERMINAL"})


@router.get("/{session_id}/events")
async def events(
    session_id: str,
    response: Response,
    after: Annotated[int, Query(ge=0, le=2**63 - 1)] = 0,
    limit: Annotated[int, Query(ge=1, le=RUN_EVENT_LIMIT)] = 20,
    subject=Depends(run_subject),
    service=Depends(run_service),
):
    # TODO [F127][EXT-03] 确认事件保留与轮询及追踪字段。
    # TODO [F127][EXT-04] 根据双方正式 OpenAPI 与样例完成联调。
    _require_identifier(session_id)
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=await service.events(subject, session_id, after, limit))


@router.post("/{session_id}/interactions/{interaction_id}/submit", status_code=202)
async def submit_interaction(
    session_id: str,
    interaction_id: str,
    body: InteractionAnswer,
    response: Response,
    key: Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[!-~]{1,128}$")],
    subject=Depends(run_subject),
    service=Depends(run_service),
):
    _require_identifier(session_id)
    _require_identifier(interaction_id)
    receipt, created = await service.answer(subject, session_id, interaction_id, key, body)
    response.status_code = 202 if created else 200
    response.headers["Cache-Control"] = "no-store"
    return resp_200(data=receipt)
