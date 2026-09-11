import time
import uuid
from uuid import UUID

from fastapi import APIRouter, Body, Path, WebSocket, WebSocketException
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.responses import StreamingResponse

from bisheng.api.services.workflow import WorkFlowService
from bisheng.api.v1.chat import chat_manager
from bisheng.api.v1.schema.workflow import WorkflowEvent, WorkflowEventType, WorkflowStream
from bisheng.api.v1.schemas import resp_200
from bisheng.common.chat.types import WorkType
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.errcode.http_error import ServerError
from bisheng.common.schemas.telemetry.event_data_schema import ApplicationAliveEventData
from bisheng.common.services import telemetry_service
from bisheng.core.logger import trace_id_var
from bisheng.open_api.api.dependencies import watch_websocket_credential
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot, get_current_open_api_principal
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.session_subject_service import session_subject_from_principal
from bisheng.open_endpoints.domain.schemas.workflow import OpenWorkflowInvokeRequest
from bisheng.open_endpoints.domain.utils import get_open_api_operator, get_open_api_operator_async
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.workflow.domain.services.published_workflow_service import PublishedWorkflowService

router = APIRouter(prefix='/workflow', tags=['OpenAPI', 'Workflow'])


@router.post('/invoke')
@open_api_scope("workflow:invoke", session=True)
async def invoke_workflow(body: OpenWorkflowInvokeRequest):
    login_user = get_open_api_operator()
    workflow_id = body.workflow_id.hex
    workflow_info = await PublishedWorkflowService.get_workflow(workflow_id)
    await require_business_action(
        login_user,
        resource_type="workflow",
        resource_id=workflow_id,
        action="use",
    )

    principal = get_current_open_api_principal()
    if principal is None:
        raise ServerError(msg="Open API execution identity is missing")
    session_subject = session_subject_from_principal(principal)

    execution_snapshot = OpenApiExecutionSnapshot.from_principal(
        principal,
        trace_id=str(trace_id_var.get() or uuid.uuid4().hex),
    )
    invocation = await PublishedWorkflowService.prepare_invocation(
        workflow_id=workflow_id,
        operator_user_id=login_user.user_id,
        session_subject=session_subject,
        execution_snapshot=execution_snapshot,
        session_id=body.session_id,
        override=body.override,
        user_input=body.input,
        message_id=body.message_id,
    )
    session_id = invocation.session_id
    logger.debug(f'waiting workflow over or input: {workflow_id}, {session_id}')

    async def handle_workflow_event(event_list: list):
        async for output in PublishedWorkflowService.iter_events(invocation, stream=bool(body.stream)):
            event = (
                WorkflowEvent(event=WorkflowEventType.Close.value)
                if output.close
                else WorkFlowService.convert_chat_response_to_workflow_event(output.data)
            )
            workflow_stream = WorkflowStream(session_id=session_id, data=event)
            event_list.append(workflow_stream.data)
            yield f'data: {workflow_stream.model_dump_json()}\n\n'

    res = []
    # Non-streaming returns a cumulative list of events
    if not body.stream:
        async for _ in handle_workflow_event(res):
            pass
        end_time = time.time()
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=workflow_id,
                                              app_name=workflow_info.name,
                                              app_type=ApplicationTypeEnum.WORKFLOW,
                                              chat_id=session_id,
                                              start_time=int(invocation.start_time),
                                              end_time=int(end_time)))
        return resp_200(data={
            'session_id': session_id,
            'events': res
        })
    try:
        return StreamingResponse(handle_workflow_event(res), media_type='text/event-stream')
    except Exception as exc:
        logger.exception(f'invoke_workflow error: {exc!s}')
        return JSONResponse(status_code=500, content=str(exc))
    finally:
        end_time = time.time()
        await telemetry_service.log_event(user_id=login_user.user_id,
                                          event_type=BaseTelemetryTypeEnum.APPLICATION_ALIVE,
                                          trace_id=trace_id_var.get(),
                                          event_data=ApplicationAliveEventData(
                                              app_id=workflow_id,
                                              app_name=workflow_info.name,
                                              app_type=ApplicationTypeEnum.WORKFLOW,
                                              chat_id=session_id,
                                              start_time=int(invocation.start_time),
                                              end_time=int(end_time)))


@router.post('/stop')
@open_api_scope("workflow:invoke", session=True)
async def stop_workflow(workflow_id: UUID = Body(..., description='Workflow UniqueID'),
                        session_id: str = Body(description='SessionsID,Once,workflowUnique identifier of the call')):
    workflow_id = workflow_id.hex
    login_user = await get_open_api_operator_async()
    principal = get_current_open_api_principal()
    if principal is None:
        raise ServerError(msg="Open API execution identity is missing")
    await PublishedWorkflowService.stop(
        workflow_id=workflow_id,
        session_id=session_id,
        operator_user_id=login_user.user_id,
        session_subject=session_subject_from_principal(principal),
    )
    return resp_200()


@router.websocket('/chat/{workflow_id}')
@open_api_scope("workflow:invoke", session=True)
async def workflow_ws(*,
                      workflow_id: UUID = Path(..., description='Workflow UniqueID'),
                      websocket: WebSocket,
                      chat_id: str | None = None):
    """ Use Exempt Login Link """
    try:
        workflow_id = workflow_id.hex
        # Authorize.jwt_required(auth_from='websocket', websocket=websocket)
        # payload = Authorize.get_jwt_subject()
        login_user = await get_open_api_operator_async()
        principal = get_current_open_api_principal()
        if principal is None:
            raise ServerError(msg="Open API execution identity is missing")
        session_subject = session_subject_from_principal(principal)
        await PublishedWorkflowService.validate_websocket_session(
            workflow_id=workflow_id,
            chat_id=chat_id,
            session_subject=session_subject,
        )
        execution_snapshot = OpenApiExecutionSnapshot.from_principal(
            principal,
            trace_id=str(trace_id_var.get() or uuid.uuid4().hex),
        ).model_dump(mode="json")
        async with watch_websocket_credential(websocket):
            await chat_manager.dispatch_client(
                websocket,
                workflow_id,
                chat_id,
                login_user,
                WorkType.WORKFLOW,
                websocket,
                session_subject=session_subject,
                execution_snapshot=execution_snapshot,
            )
    except WebSocketException as exc:
        logger.error(f'Websocket exception: {exc!s}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(exc))
    except Exception as e:
        logger.error(f'Websocket handle error: {e!s}')
        await websocket.close(code=http_status.WS_1011_INTERNAL_ERROR, reason=str(e))
