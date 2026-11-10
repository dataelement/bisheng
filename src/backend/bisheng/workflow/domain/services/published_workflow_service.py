"""Shared workflow execution used by authenticated v2 and public v3 adapters."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.flow import WorkFlowInvalidUserInputError
from bisheng.common.errcode.http_error import NotFoundError
from bisheng.database.models.flow import Flow, FlowDao, FlowType
from bisheng.database.models.session import MessageSession
from bisheng.open_api.domain.context import OpenApiExecutionSnapshot
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, workflow_stateful_worker
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.schemas.platform_agent import uses_platform_agent
from bisheng.workflow.domain.schemas.platform_knowledge import uses_platform_knowledge


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
        has_knowledge = uses_platform_knowledge(workflow_info.data)
        if has_knowledge:
            from bisheng.workflow.application.platform_knowledge import actual_user_from_snapshot

            actual_user_from_snapshot(execution_snapshot, operator_user_id)
        elif uses_platform_agent(workflow_info.data):
            from bisheng.workflow.application.platform_agent import actual_user_from_snapshot

            actual_user_from_snapshot(execution_snapshot, operator_user_id)
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

        callback = RedisCallback(
            unique_id,
            workflow_id,
            chat_id,
            operator_user_id,
            source="api",
            **({"tenant_id": execution_snapshot.tenant_id} if has_knowledge else {}),
        )
        worker = await workflow_stateful_worker.find_task_node(chat_id)
        status_info = callback.get_workflow_status()
        snapshot_data = execution_snapshot.model_dump(mode="json")
        if not status_info:
            reference = None
            options = {}
            if uses_platform_agent(workflow_info.data):
                from bisheng.workflow.application.platform_agent import actual_user_from_snapshot, get_service

                service = get_service()
                login_user = actual_user_from_snapshot(execution_snapshot, operator_user_id)
                # 在正式图上应用普通节点覆盖后冻结。平台节点和发布绑定不得覆盖。
                execution, dispatch_id = await service.admit(
                    login_user, workflow_id, unique_id, workflow_info.data, "PUBLISHED", override=override
                )
                reference = {"execution_id": execution["execution_id"], "dispatch_id": dispatch_id}
                callback.set_platform_agent_reference(execution["execution_id"])
                options = {
                    "kwargs": {"platform_agent_execution": reference},
                    "headers": {"tenant_id": login_user.tenant_id},
                }
            else:
                getattr(callback, "clear_platform_agent_reference", lambda: None)()
            knowledge_reference = None
            if has_knowledge:
                from bisheng.workflow.application.platform_knowledge import actual_user_from_snapshot, prepare_execution

                login_user = actual_user_from_snapshot(execution_snapshot, operator_user_id)
                try:
                    frozen_graph, knowledge_reference = await prepare_execution(
                        login_user,
                        workflow_id,
                        unique_id,
                        workflow_info.data,
                        published=True,
                        override=override,
                    )
                except Exception:
                    if reference:
                        service.repository.request_stop(reference["execution_id"])
                    raise
                callback.bind_platform_knowledge_execution(knowledge_reference["execution_id"])
                options.setdefault("kwargs", {})["platform_knowledge_execution"] = knowledge_reference
                options["headers"] = {"tenant_id": login_user.tenant_id}
                callback.set_workflow_data(frozen_graph)
            else:
                if isinstance(getattr(callback, "platform_knowledge_execution_id", None), str):
                    callback.clear_platform_knowledge_reference()
                callback.set_workflow_data(workflow_info.data, override=override)
            callback.set_workflow_status(WorkflowStatus.WAITING.value)
            try:
                execute_workflow.apply_async(
                    [unique_id, workflow_id, chat_id, operator_user_id, "api", snapshot_data], queue=worker, **options
                )
            except Exception:
                if reference:
                    service.repository.request_stop(reference["execution_id"])
                if knowledge_reference:
                    callback.knowledge_store.stop(knowledge_reference["execution_id"])
                raise
        elif status_info["status"] == WorkflowStatus.INPUT.value:
            if not user_input:
                raise WorkFlowInvalidUserInputError(msg="workflow waiting for user input, but user input not provided")
            if not message_id:
                raise WorkFlowInvalidUserInputError(msg="message_id is required when providing user input")
            options = {}
            execution_id = callback.get_platform_agent_reference()
            if execution_id:
                from bisheng.workflow.application.platform_agent import actual_user_from_snapshot, get_service

                service = get_service()
                login_user = actual_user_from_snapshot(execution_snapshot, operator_user_id)
                actor = await service.authorize(login_user, workflow_id, "use")
                record = service.repository.get_execution(execution_id)
                if (record["user_id"], record["tenant_id"]) != (actor.user_id, actor.tenant_id):
                    from bisheng.common.errcode.flow import PlatformAgentExecutionError

                    raise PlatformAgentExecutionError()
            knowledge_id = getattr(callback, "platform_knowledge_execution_id", None)
            has_knowledge_run = isinstance(knowledge_id, str)
            agent_reference = None
            knowledge_reference = None

            def claim_agent_resume():
                nonlocal agent_reference
                dispatch_id = service.repository.prepare_resume(execution_id, actor)
                agent_reference = {"execution_id": execution_id, "dispatch_id": dispatch_id}
                options.setdefault("kwargs", {})["platform_agent_execution"] = agent_reference
                options["headers"] = {"tenant_id": actor.tenant_id}

            async def claim_protected_resume():
                nonlocal knowledge_reference
                from bisheng.workflow.application.platform_knowledge import (
                    BrowserPlatformKnowledgeRuntime,
                    actual_user_from_snapshot,
                )

                if execution_id:
                    claim_agent_resume()
                login_user = actual_user_from_snapshot(execution_snapshot, operator_user_id)
                knowledge_reference = await BrowserPlatformKnowledgeRuntime().resume(
                    login_user,
                    workflow_id,
                    unique_id,
                    knowledge_id,
                )
                options.setdefault("kwargs", {})["platform_knowledge_execution"] = knowledge_reference
                options["headers"] = {"tenant_id": login_user.tenant_id}

            if not has_knowledge_run:
                await callback.async_set_user_input(user_input, message_id, verify_input=True)
                if execution_id:
                    claim_agent_resume()
            try:
                if has_knowledge_run:
                    await callback.async_set_user_input(
                        user_input, message_id, verify_input=True, before_write=claim_protected_resume
                    )
                await callback.async_set_workflow_status(WorkflowStatus.INPUT_OVER.value)
                continue_workflow.apply_async(
                    [unique_id, workflow_id, chat_id, operator_user_id, "api", snapshot_data], queue=worker, **options
                )
            except Exception:
                if agent_reference:
                    service.repository.request_stop(execution_id)
                if knowledge_reference:
                    callback.knowledge_store.stop(knowledge_id)
                raise
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
        reference = getattr(callback, "get_platform_agent_reference", lambda: None)()
        if isinstance(reference, str) and len(reference) == 32 and session_subject.subject_type == "user":
            from bisheng.common.dependencies.user_deps import UserPayload
            from bisheng.workflow.application.platform_agent import BrowserPlatformAgentRuntime

            user = UserPayload(user_id=operator_user_id, tenant_id=session_subject.tenant_id, user_role=[])
            if await BrowserPlatformAgentRuntime().stop_long(user, workflow_id, session_id, reference):
                await callback.async_set_workflow_stop(long_committed=True)
                return
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
