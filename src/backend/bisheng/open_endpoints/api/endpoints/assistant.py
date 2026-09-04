"""API-key authenticated assistant adapters."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from bisheng.api.services.assistant import AssistantService
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import OpenAIChatCompletionReq
from bisheng.assistant.domain.services.published_assistant_service import PublishedAssistantService
from bisheng.common.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.schemas.api import PageData, resp_200
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.open_api.api.dependencies import watch_websocket_credential
from bisheng.open_api.domain.context import get_current_open_api_principal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal
from bisheng.open_endpoints.domain.utils import get_open_api_operator
from bisheng.utils import get_request_ip

router = APIRouter(prefix="/assistant", tags=["OpenAPI", "Assistant"])


@router.post("/chat/completions")
@open_api_scope("assistant:invoke", session=True)
async def assistant_chat_completions(request: Request, req_data: OpenAIChatCompletionReq):
    assistant_id = UUID(req_data.model).hex
    logger.info(
        "act=assistant_chat_completions assistant_id={} stream={} ip={}",
        req_data.model,
        req_data.stream,
        get_request_ip(request),
    )
    try:
        operator = get_open_api_operator()
        started = time.time()
        completion, assistant_info = await PublishedAssistantService.complete(
            assistant_id=assistant_id,
            model=req_data.model,
            messages=req_data.messages,
            stream=req_data.stream,
            temperature=req_data.temperature,
            operator=operator,
        )
        if completion.stream is not None:
            return StreamingResponse(completion.stream, media_type="text/event-stream")
        return completion.payload
    except Exception as exc:
        logger.opt(exception=True).error("assistant completion failed")
        return JSONResponse(status_code=500, content=str(exc), media_type="application/json")
    finally:
        if "operator" in locals() and "assistant_info" in locals():
            ended = time.time()
            await telemetry_service.log_event(
                user_id=operator.user_id,
                event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                trace_id=trace_id_var.get(),
                event_data=ApplicationAliveEventData(
                    app_id=assistant_id,
                    app_name=assistant_info.name,
                    app_type=ApplicationTypeEnum.ASSISTANT,
                    chat_id="",
                    start_time=int(started),
                    end_time=int(ended),
                ),
            )
            await telemetry_service.log_event(
                user_id=operator.user_id,
                event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
                trace_id=trace_id_var.get(),
                event_data=ApplicationProcessEventData(
                    app_id=assistant_id,
                    app_name=assistant_info.name,
                    app_type=ApplicationTypeEnum.ASSISTANT,
                    chat_id="",
                    start_time=int(started),
                    end_time=int(ended),
                    process_time=int((ended - started) * 1000),
                ),
            )


@router.get("/info/{assistant_id}")
@open_api_scope("assistant:read")
async def get_assistant_info(request: Request, assistant_id: UUID):
    normalized_id = assistant_id.hex
    logger.info("act=get_open_api_operator assistant_id={} ip={}", normalized_id, get_request_ip(request))
    data = await PublishedAssistantService.get_info(normalized_id, get_open_api_operator())
    return resp_200(data=data)


@router.get("/list", status_code=200)
@open_api_scope("assistant:read")
async def get_assistant_list(
    request: Request,
    name: str | None = Query(default=None, description="assistant name, fuzzy matching"),
    tag_id: int | None = Query(default=None, description="label ID"),
    page: int = Query(default=1, gt=0, description="Page"),
    limit: int = Query(default=10, gt=0, description="Listings Per Page"),
    status: int | None = Query(default=None, description="Online status"),
):
    logger.info("open_api_get_list ip={}", request.client.host if request.client else "")
    data, total = await AssistantService.get_assistant(
        get_open_api_operator(),
        name,
        status,
        tag_id,
        page,
        limit,
    )
    return resp_200(PageData(data=data, total=total))


@router.websocket("/chat/{assistant_id}")
@open_api_scope("assistant:invoke", session=True)
async def chat(*, websocket: WebSocket, assistant_id: str, chat_id: str | None = None):
    logger.info("act=assistant_chat_ws assistant_id={} ip={}", assistant_id, get_request_ip(websocket))
    operator = get_open_api_operator()
    try:
        principal = get_current_open_api_principal()
        if principal is None:
            raise HTTPException(status_code=500, detail="Open API execution identity is missing")
        session_subject = session_subject_from_principal(principal)
        await PublishedAssistantService.validate_websocket_session(
            assistant_id=assistant_id,
            chat_id=chat_id,
            session_subject=session_subject,
        )
        async with watch_websocket_credential(websocket):
            await chat_manager.dispatch_client(
                websocket,
                assistant_id,
                chat_id,
                operator,
                WorkType.GPTS,
                websocket,
                session_subject=session_subject,
            )
    except WebSocketException as exc:
        logger.error("websocket exception: {}", exc)
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as exc:
        logger.opt(exception=True).error("assistant websocket failed")
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        code = (
            http_status.WS_1008_POLICY_VIOLATION
            if "Could not validate credentials" in str(exc)
            else http_status.WS_1011_INTERNAL_ERROR
        )
        await websocket.close(code=code, reason=message)
