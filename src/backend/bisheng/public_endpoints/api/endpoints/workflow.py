"""Published workflow HTTP and WebSocket adapters."""

from __future__ import annotations

import time
import uuid
from uuid import UUID

from fastapi import APIRouter, Body, Path, Request, WebSocket
from fastapi import status as http_status
from fastapi.responses import StreamingResponse
from loguru import logger

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schema.workflow import WorkflowEvent, WorkflowEventType, WorkflowStream
from bisheng.api.v1.schemas import resp_200
from bisheng.common.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.public_endpoints.domain.services.guest_policy import PublicAccessError, public_execution
from bisheng.workflow.domain.services.published_workflow_service import PublishedWorkflowService

router = APIRouter(prefix="/workflow", tags=["PublicAPI", "Workflow"])


async def _telemetry(*, execution, invocation, ended: float) -> None:
    await telemetry_service.log_event(
        user_id=execution.operator.user_id,
        event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
        trace_id=trace_id_var.get(),
        event_data=ApplicationAliveEventData(
            app_id=invocation.workflow_id,
            app_name=invocation.workflow.name,
            app_type=ApplicationTypeEnum.WORKFLOW,
            chat_id=invocation.session_id,
            start_time=int(invocation.start_time),
            end_time=int(ended),
        ),
    )


@router.post("/invoke")
async def invoke_workflow(
    request: Request,
    workflow_id: UUID = Body(..., description="Workflow UniqueID"),
    override: dict | None = Body(default=None, description="override node params"),
    stream: bool = Body(default=True, description="Whether to stream calls"),
    user_input: dict | None = Body(default=None, description="User input", alias="input"),
    message_id: int | None = Body(default=None, description="Unique user-input message ID"),
    session_id: str | None = Body(default=None, description="Workflow call session ID"),
):
    del request
    normalized_id = workflow_id.hex
    async with public_execution("workflow", normalized_id) as execution:
        snapshot = execution.snapshot.model_copy(
            update={"trace_id": str(trace_id_var.get() or uuid.uuid4().hex)}
        )
        invocation = await PublishedWorkflowService.prepare_invocation(
            workflow_id=normalized_id,
            operator_user_id=execution.operator.user_id,
            session_subject=execution.session_subject,
            execution_snapshot=snapshot,
            session_id=session_id,
            override=override,
            user_input=user_input,
            message_id=message_id,
        )

        async def events(collected: list):
            async for output in PublishedWorkflowService.iter_events(invocation, stream=stream):
                event = (
                    WorkflowEvent(event=WorkflowEventType.Close.value)
                    if output.close
                    else WorkFlowService.convert_chat_response_to_workflow_event(output.data)
                )
                envelope = WorkflowStream(session_id=invocation.session_id, data=event)
                collected.append(envelope.data)
                yield f"data: {envelope.model_dump_json()}\n\n"

        collected: list = []
        if not stream:
            async for _ in events(collected):
                pass
            await _telemetry(execution=execution, invocation=invocation, ended=time.time())
            return resp_200(data={"session_id": invocation.session_id, "events": collected})

        async def streaming_events():
            async with public_execution("workflow", normalized_id) as stream_execution:
                try:
                    async for item in events(collected):
                        yield item
                finally:
                    await _telemetry(execution=stream_execution, invocation=invocation, ended=time.time())

        return StreamingResponse(streaming_events(), media_type="text/event-stream")


@router.post("/stop")
async def stop_workflow(
    workflow_id: UUID = Body(..., description="Workflow UniqueID"),
    session_id: str = Body(..., description="Workflow call session ID"),
):
    normalized_id = workflow_id.hex
    async with public_execution("workflow", normalized_id) as execution:
        await PublishedWorkflowService.stop(
            workflow_id=normalized_id,
            session_id=session_id,
            operator_user_id=execution.operator.user_id,
            session_subject=execution.session_subject,
        )
        return resp_200()


@router.websocket("/chat/{workflow_id}")
async def workflow_ws(
    *,
    workflow_id: UUID = Path(..., description="Workflow UniqueID"),
    websocket: WebSocket,
    chat_id: str | None = None,
):
    normalized_id = workflow_id.hex
    try:
        async with public_execution("workflow", normalized_id) as execution:
            await PublishedWorkflowService.validate_websocket_session(
                workflow_id=normalized_id,
                chat_id=chat_id,
                session_subject=execution.session_subject,
            )
            snapshot = execution.snapshot.model_copy(
                update={"trace_id": str(trace_id_var.get() or uuid.uuid4().hex)}
            )
            await chat_manager.dispatch_client(
                websocket,
                normalized_id,
                chat_id,
                execution.operator,
                WorkType.WORKFLOW,
                websocket,
                session_subject=execution.session_subject,
                execution_snapshot=snapshot.model_dump(mode="json"),
            )
    except PublicAccessError as exc:
        await websocket.close(code=http_status.WS_1008_POLICY_VIOLATION, reason=exc.message)
    except Exception as exc:
        logger.opt(exception=True).error("public workflow websocket failed")
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
