"""Shared workflow execution used by authenticated v2 and public v3 adapters."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.http_error import NotFoundError, ServerError
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.session import MessageSession
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, workflow_stateful_worker
from bisheng.workflow.common.workflow import WorkflowStatus


@dataclass(frozen=True, slots=True)
class WorkflowInvocation:
    workflow: Flow
    callback: RedisCallback
    workflow_id: str
    session_id: str
    chat_id: str
    start_time: float


@dataclass(frozen=True, slots=True)
class WorkflowOutputEvent:
    data: object | None = None
    close: bool = False


class PublishedWorkflowService:
    """Keep transport authentication out of workflow execution semantics."""

    @staticmethod
    async def get_workflow(workflow_id: str) -> Flow:
        workflow = await FlowDao.aget_flow_by_id(workflow_id)
        if workflow is None or workflow.flow_type != FlowType.WORKFLOW.value:
            raise NotFoundError.http_exception()
        return workflow

    @classmethod
    async def prepare_invocation(
        cls,
        *,
        workflow_id: str,
        operator_user_id: int,
        session_subject: SessionSubject,
        execution_snapshot: OpenApiExecutionSnapshot,
        session_id: str | None,
        override: dict | None,
        user_input: dict | None,
        message_id: int | None,
    ) -> WorkflowInvocation:
        workflow_info = await cls.get_workflow(workflow_id)
        if not session_id:
            chat_id = uuid.uuid4().hex
            unique_id = f"{chat_id}_async_task_id"
            session_id = unique_id
        else:
            chat_id = session_id.split("_", 1)[0]
            unique_id = session_id

        session = await ChatSessionService.get_subject_session_if_exists(chat_id, session_subject)
        if session is not None and session.flow_id != workflow_id:
            raise NotFoundError.http_exception()
        if session is None:
            await ChatSessionService.create_subject_session(
                MessageSession(
                    chat_id=chat_id,
                    flow_id=workflow_id,
                    flow_name=workflow_info.name,
                    flow_type=FlowType.WORKFLOW.value,
                    user_id=operator_user_id,
                ),
                session_subject,
            )

        callback = RedisCallback(unique_id, workflow_id, chat_id, operator_user_id, source="api")
        worker = await workflow_stateful_worker.find_task_node(chat_id)
        status_info = callback.get_workflow_status()
        snapshot_data = execution_snapshot.model_dump(mode="json")
        if not status_info:
            callback.set_workflow_data(workflow_info.data, override=override)
            callback.set_workflow_status(WorkflowStatus.WAITING.value)
            execute_workflow.apply_async(
                [unique_id, workflow_id, chat_id, operator_user_id, "api", snapshot_data],
                queue=worker,
            )
        elif status_info["status"] == WorkflowStatus.INPUT.value:
            if not user_input:
                raise ServerError(msg="workflow waiting for user input, but user input not provided")
            if not message_id:
                raise ServerError(msg="message_id is required when providing user input")
            await callback.async_set_user_input(user_input, message_id, verify_input=True)
            await callback.async_set_workflow_status(WorkflowStatus.INPUT_OVER.value)
            continue_workflow.apply_async(
                [unique_id, workflow_id, chat_id, operator_user_id, "api", snapshot_data],
                queue=worker,
            )
        return WorkflowInvocation(
            workflow=workflow_info,
            callback=callback,
            workflow_id=workflow_id,
            session_id=session_id,
            chat_id=chat_id,
            start_time=time.time(),
        )

    @staticmethod
    async def iter_events(invocation: WorkflowInvocation, *, stream: bool) -> AsyncIterator[WorkflowOutputEvent]:
        async for event in invocation.callback.get_response_until_break():
            if event.category == "node_run":
                continue
            if not stream and event.category == "stream_msg" and event.type == "stream":
                continue
            yield WorkflowOutputEvent(data=event)
        status_info = await invocation.callback.async_get_workflow_status()
        if status_info and status_info["status"] in {WorkflowStatus.SUCCESS.value, WorkflowStatus.FAILED.value}:
            await invocation.callback.async_clear_workflow_status()
        if status_info and status_info["status"] == WorkflowStatus.SUCCESS.value:
            yield WorkflowOutputEvent(close=True)

    @staticmethod
    async def stop(
        *,
        workflow_id: str,
        session_id: str,
        operator_user_id: int,
        session_subject: SessionSubject,
    ) -> None:
        chat_id = session_id.split("_", 1)[0]
        session = await ChatSessionService.get_subject_session(chat_id, session_subject)
        if session.flow_id != workflow_id:
            raise NotFoundError.http_exception()
        callback = RedisCallback(session_id, workflow_id, chat_id, operator_user_id, source="api")
        await callback.async_set_workflow_stop()

    @classmethod
    async def validate_websocket_session(
        cls,
        *,
        workflow_id: str,
        chat_id: str | None,
        session_subject: SessionSubject,
    ) -> None:
        await cls.get_workflow(workflow_id)
        if not chat_id:
            return
        session = await ChatSessionService.get_subject_session_if_exists(chat_id, session_subject)
        if session is not None and session.flow_id != workflow_id:
            raise NotFoundError.http_exception()


__all__ = [
    "PublishedWorkflowService",
    "WorkflowInvocation",
    "WorkflowOutputEvent",
]
