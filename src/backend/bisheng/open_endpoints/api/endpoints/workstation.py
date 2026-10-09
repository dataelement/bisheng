"""Key-authenticated adapters for workstation chat: daily mode and task mode (F073)."""

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Request

from bisheng.api.v1.schemas import UnifiedResponseModel, resp_200
from bisheng.common.errcode.open_api import OpenApiTaskModeUnsupportedError
from bisheng.open_api.api.dependencies import get_open_api_execution
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.daily_chat_service import OpenDailyChatService
from bisheng.open_api.domain.services.task_mode_service import (
    OpenTaskModeService,
    parse_task_submission,
    validate_body,
)
from bisheng.open_endpoints.domain.utils import get_open_api_operator_async
from bisheng.workstation.domain.services.chat_service import stream_chat_completion
from bisheng.workstation.domain.services.workstation_service import WorkStationService

router = APIRouter(prefix="/workstation", tags=["OpenAPI", "WorkStation"])

RUN_MODE_DAILY = "daily"
RUN_MODE_TASK = "task"


@router.get("/config", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke")
async def get_workstation_config(
    run_mode: str | None = Query(default=None, description="daily (default) or task"),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    operator = await get_open_api_operator_async()
    if run_mode == RUN_MODE_TASK:
        return resp_200(data=await OpenTaskModeService.task_config(principal, operator))
    if run_mode not in (None, RUN_MODE_DAILY):
        raise OpenApiTaskModeUnsupportedError()
    return resp_200(data=await WorkStationService.get_open_api_daily_config(operator))


@router.get("/config/knowledge", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke")
async def list_task_knowledge(
    request: Request,
    type: Literal["library", "space"] = Query(..., description="library = document knowledge base"),
    name: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    operator = await get_open_api_operator_async()
    page = await OpenTaskModeService.list_knowledge(
        request,
        principal,
        operator,
        knowledge_type=type,
        name=name,
        cursor=cursor,
        page_size=page_size,
    )
    return resp_200(data=page)


@router.post("/chat/completions")
@open_api_scope("chat:invoke", session=True)
async def chat_completions(
    request: Request,
    payload: dict[str, Any] = Body(...),
    principal: OpenApiPrincipal = Depends(get_open_api_execution),
):
    """Daily mode (``run_mode`` omitted or ``"daily"``) streams; ``run_mode="task"`` queues a task.

    The body is taken raw so one endpoint can serve both run modes (PRD D11 /
    D12); each branch validates it against its own model with FastAPI's error
    shape. The documented request schema is injected in ``openapi_schema``.
    """
    if payload.get("run_mode") == RUN_MODE_TASK:
        submission = parse_task_submission(payload)
        operator = await get_open_api_operator_async()
        submitted = await OpenTaskModeService.submit(principal, submission, operator)
        return resp_200(data=submitted.model_dump(mode="json"))

    data = validate_body(OpenDailyChatCompletionReq, payload)
    operator = await get_open_api_operator_async()
    internal, subject = await OpenDailyChatService.prepare_request(
        principal=principal,
        request=data,
        login_user=operator,
    )
    return await stream_chat_completion(
        request,
        internal,
        operator,
        session_subject=subject,
    )


@router.get("/tasks/{task_id}", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke", session=True)
async def get_task(task_id: str, principal: OpenApiPrincipal = Depends(get_open_api_execution)):
    view = await OpenTaskModeService.get_view(principal, task_id)
    return resp_200(data=view.model_dump(mode="json"))


@router.get("/tasks/{task_id}/files/{file_id}")
@open_api_scope("chat:invoke", session=True)
async def download_task_file(task_id: str, file_id: str, principal: OpenApiPrincipal = Depends(get_open_api_execution)):
    return await OpenTaskModeService.download(principal, task_id, file_id)


@router.post("/tasks/{task_id}/terminate", response_model=UnifiedResponseModel)
@open_api_scope("chat:invoke", session=True)
async def terminate_task(task_id: str, principal: OpenApiPrincipal = Depends(get_open_api_execution)):
    view = await OpenTaskModeService.terminate(principal, task_id)
    return resp_200(data=view.model_dump(mode="json"))
