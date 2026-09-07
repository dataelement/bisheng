"""Published assistant HTTP and WebSocket adapters."""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Request, WebSocket
from fastapi import status as http_status
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schemas import OpenAIChatCompletionReq
from bisheng.assistant.domain.services.published_assistant_service import PublishedAssistantService
from bisheng.common.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.schemas.api import resp_200
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData, ApplicationProcessEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.public_endpoints.domain.services.guest_policy import PublicAccessError, public_execution
from bisheng.utils import get_request_ip

router = APIRouter(prefix="/assistant", tags=["PublicAPI", "Assistant"])


async def _record_telemetry(*, execution, assistant_id: str, assistant_info, started: float) -> None:
    ended = time.time()
    await telemetry_service.log_event(
        user_id=execution.operator.user_id,
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
        user_id=execution.operator.user_id,
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


@router.post("/chat/completions")
async def assistant_chat_completions(request: Request, req_data: OpenAIChatCompletionReq):
    assistant_id = UUID(req_data.model).hex
    logger.info(
        "act=public_assistant_completion assistant_id={} stream={} ip={}",
        assistant_id,
        req_data.stream,
        get_request_ip(request),
    )
    try:
        async with public_execution("assistant", assistant_id) as execution:
            started = time.time()
            completion, assistant_info = await PublishedAssistantService.complete(
                assistant_id=assistant_id,
                model=req_data.model,
                messages=req_data.messages,
                stream=req_data.stream,
                temperature=req_data.temperature,
                operator=execution.operator,
            )
            if completion.stream is None:
                await _record_telemetry(
                    execution=execution,
                    assistant_id=assistant_id,
                    assistant_info=assistant_info,
                    started=started,
                )
                return completion.payload

            async def stream_events():
                async with public_execution("assistant", assistant_id) as stream_execution:
                    try:
                        async for item in completion.stream:
                            yield item
                    finally:
                        await _record_telemetry(
                            execution=stream_execution,
                            assistant_id=assistant_id,
                            assistant_info=assistant_info,
                            started=started,
                        )

            return StreamingResponse(stream_events(), media_type="text/event-stream")
    except PublicAccessError:
        raise
    except Exception as exc:
        logger.opt(exception=True).error("public assistant completion failed")
        return JSONResponse(status_code=500, content=str(exc), media_type="application/json")


@router.get("/info/{assistant_id}")
async def get_assistant_info(request: Request, assistant_id: UUID):
    del request
    normalized_id = assistant_id.hex
    async with public_execution("assistant", normalized_id) as execution:
        data = await PublishedAssistantService.get_info(normalized_id, execution.operator)
        return resp_200(data=data)


@router.websocket("/chat/{assistant_id}")
async def assistant_ws(*, websocket: WebSocket, assistant_id: str, chat_id: str | None = None):
    try:
        normalized_id = UUID(assistant_id).hex
        async with public_execution("assistant", normalized_id) as execution:
            await PublishedAssistantService.validate_websocket_session(
                assistant_id=normalized_id,
                chat_id=chat_id,
                session_subject=execution.session_subject,
            )
            await chat_manager.dispatch_client(
                websocket,
                normalized_id,
                chat_id,
                execution.operator,
                WorkType.GPTS,
                websocket,
                session_subject=execution.session_subject,
            )
    except PublicAccessError as exc:
        await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason=exc.message)
    except Exception as exc:
        logger.opt(exception=True).error("public assistant websocket failed")
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
