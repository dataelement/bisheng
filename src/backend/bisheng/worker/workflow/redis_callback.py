import asyncio
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

from langchain_core.documents import Document
from loguru import logger

from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.api.v1.schemas import ChatResponse
from bisheng.citation.domain.schemas.citation_schema import CitationRegistryItemSchema, CitationType
from bisheng.citation.domain.services.citation_prompt_helper import (
    attach_temp_object_names,
    collect_rag_citation_registry_items,
    save_message_citations_sync,
    select_registry_items_for_persistence,
    strip_unregistered_citation_markers,
)
from bisheng.common.chat.utils import sync_judge_source, sync_process_source_document
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.errcode.flow import (
    PlatformAgentExecutionError,
    PlatformKnowledgeExecutionError,
    WorkFlowInvalidUserInputError,
    WorkFlowNodeRunMaxTimesError,
    WorkFlowNodeUpdateError,
    WorkFlowTaskBusyError,
    WorkFlowTaskOtherError,
    WorkFlowVersionUpdateError,
    WorkFlowWaitUserTimeoutError,
)
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.config_service import settings
from bisheng.common.utils.title_generator import generate_conversation_title_sync
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.chat_attachment import promote_chat_attachments_sync
from bisheng.database.models.flow import FlowDao, FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession, MessageSessionDao
from bisheng.llm.domain import LLMService
from bisheng.utils.threadpool import thread_pool
from bisheng.workflow.callback.base_callback import BaseCallback
from bisheng.workflow.callback.event import (
    GuideQuestionData,
    GuideWordData,
    NodeEndData,
    NodeStartData,
    OutputMsgChooseData,
    OutputMsgData,
    OutputMsgInputData,
    StreamMsgData,
    StreamMsgOverData,
    UserInputData,
)
from bisheng.workflow.common.workflow import WorkflowStatus
from bisheng.workflow.domain.repositories.platform_knowledge_run import KnowledgeRunRepository


class RedisCallback(BaseCallback):
    def __init__(self, unique_id: str, workflow_id: str, chat_id: str, user_id: int, **kwargs):
        # F022 INV-T18: Owner tenant of the Flow (set by the celery task entry
        # via tasks.py from FlowDao.get_flow_by_id) — used by sync helpers
        # such as generate_session_title that resolve workbench config in a
        # worker context with no admin-scope ContextVar.
        self.tenant_id = kwargs.pop("tenant_id", None)
        super().__init__()
        # Unique for asynchronous tasksID
        self.unique_id = unique_id
        self.workflow_id = workflow_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.workflow = None
        self.create_session = False
        self.source = kwargs.get("source", "platform")  # only platform or api

        self.new_session = None

        self.redis_client = get_redis_client_sync()
        self.workflow_data_key = f"workflow:{unique_id}:data"
        self.workflow_status_key = f"workflow:{unique_id}:status"
        self.workflow_event_key = f"workflow:{unique_id}:event"
        self.workflow_input_key = f"workflow:{unique_id}:input"
        self.workflow_stop_key = f"workflow:{unique_id}:stop"
        self.platform_agent_key = f"workflow:{unique_id}:platform-agent"
        self.platform_agent_execution_id = None
        self.workflow_expire_time = settings.get_workflow_conf().timeout * 60 + 60
        reference = self.get_platform_agent_reference()
        if reference:
            self.bind_platform_agent_execution(reference)
        self.platform_knowledge_execution_id = None
        self.platform_knowledge_owner = ""
        tenant = self.tenant_id or get_current_tenant_id()
        self.knowledge_store = KnowledgeRunRepository(workflow_id, unique_id, tenant, user_id, client=self.redis_client)
        knowledge_reference = self.get_platform_knowledge_reference()
        if knowledge_reference:
            self.bind_platform_knowledge_execution(knowledge_reference)

    def get_platform_knowledge_reference(self):
        store = getattr(self, "knowledge_store", None)
        record = store.current() if store else None
        return record["execution_id"] if record else None

    def bind_platform_knowledge_execution(self, execution_id, owner=""):
        self.platform_knowledge_execution_id = execution_id
        self.platform_knowledge_owner = owner
        self.workflow_status_key, self.workflow_event_key = self.knowledge_store.output_keys(execution_id)
        prefix = f"{self.knowledge_store.key}:{execution_id}"
        self.workflow_data_key = f"{prefix}:data"
        self.workflow_input_key = f"{prefix}:input"
        self.workflow_stop_key = f"{prefix}:stop"

    def clear_platform_knowledge_reference(self):
        execution_id = getattr(self, "platform_knowledge_execution_id", None)
        if not execution_id:
            return
        self.knowledge_store.clear(execution_id)
        self.platform_knowledge_execution_id = None
        agent = self.get_platform_agent_reference()
        if agent:
            self.bind_platform_agent_execution(agent)
        else:
            prefix = f"workflow:{self.unique_id}"
            self.workflow_data_key = f"{prefix}:data"
            self.workflow_status_key = f"{prefix}:status"
            self.workflow_event_key = f"{prefix}:event"
            self.workflow_input_key = f"{prefix}:input"
            self.workflow_stop_key = f"{prefix}:stop"

    def set_workflow_data(self, data: dict, override: dict | None = None):
        data = self.override_nodes_params(data, override)
        self.redis_client.set(self.workflow_data_key, data, expiration=self.workflow_expire_time)

    def set_platform_agent_reference(self, execution_id):
        if self.get_platform_agent_reference() != execution_id:
            from bisheng.workflow.application.platform_agent import get_service

            with get_service().repository.admission_scope(execution_id):
                self.redis_client.set(self.platform_agent_key, execution_id, expiration=3600 * 24 * 7)
        self.bind_platform_agent_execution(execution_id)

    def bind_platform_agent_execution(self, execution_id):
        self.platform_agent_execution_id = execution_id
        prefix = f"workflow:{self.unique_id}:platform-agent:{execution_id}"
        self.workflow_data_key = f"{prefix}:data"
        self.workflow_status_key = f"{prefix}:status"
        self.workflow_event_key = f"{prefix}:event"
        self.workflow_input_key = f"{prefix}:input"
        self.workflow_stop_key = f"{prefix}:stop"
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            self.bind_platform_knowledge_execution(knowledge_id, self.platform_knowledge_owner)

    def restore_platform_agent_reference(self, execution_id):
        from bisheng.workflow.application.platform_agent import get_service

        with get_service().repository.interaction_reference_scope(execution_id) as active:
            if not active:
                return False
            if not self.get_platform_agent_reference():
                self.redis_client.setNx(self.platform_agent_key, execution_id, expiration=3600 * 24 * 7)
            if self.get_platform_agent_reference() != execution_id:
                return False
        self.bind_platform_agent_execution(execution_id)
        return True

    def get_platform_agent_reference(self):
        key = getattr(self, "platform_agent_key", f"workflow:{self.unique_id}:platform-agent")
        reference = self.redis_client.get(key)
        return reference if isinstance(reference, str) and len(reference) == 32 else None

    def clear_platform_agent_reference(self):
        self._stop_platform_agent()
        self.redis_client.delete(self.platform_agent_key)
        self.platform_agent_execution_id = None
        prefix = f"workflow:{self.unique_id}"
        self.workflow_data_key = f"{prefix}:data"
        self.workflow_status_key = f"{prefix}:status"
        self.workflow_event_key = f"{prefix}:event"
        self.workflow_input_key = f"{prefix}:input"
        self.workflow_stop_key = f"{prefix}:stop"

    def _stop_platform_agent(self):
        reference = getattr(self, "platform_agent_execution_id", None) or self.get_platform_agent_reference()
        if reference:
            from bisheng.workflow.application.platform_agent import get_service

            get_service().repository.request_stop(reference)

    def _platform_status_allowed(self, status):
        reference = getattr(self, "platform_agent_execution_id", None)
        if not reference:
            return True
        if self.get_platform_agent_reference() != reference:
            return False
        from bisheng.workflow.application.platform_agent import get_service

        row = get_service().repository.get_execution(reference)
        if status == WorkflowStatus.SUCCESS.value:
            return row["state"] == "SUCCEEDED"
        if row["state"] == "SUCCEEDED":
            return False
        if status == WorkflowStatus.FAILED.value:
            self._stop_platform_agent()
            return True
        return row["state"] in {"READY", "RUNNING", "WAITING"} and not row["stop_requested"]

    @staticmethod
    def override_nodes_params(data: dict, override: dict | None = None) -> dict:
        if not override:
            return data

        def replace_param(one_params: list[dict], one_node_id: str):
            for param in one_params:
                param_key = param.get("key")
                if param_key not in override[one_node_id]:
                    continue
                param["value"] = override[one_node_id][param_key]

        nodes = data.get("nodes", [])
        for node in nodes:
            node_data = node.get("data", {})
            node_id = node_data.get("id")
            if node_id not in override:
                continue
            group_params = node_data.get("group_params", [])
            for group_param in group_params:
                replace_param(group_param.get("params", []), node_id)
        return data

    async def async_set_workflow_data(self, data: dict):
        await self.redis_client.aset(self.workflow_data_key, data, expiration=self.workflow_expire_time)

    def get_workflow_data(self) -> dict:
        return self.redis_client.get(self.workflow_data_key)

    def set_workflow_status(self, status: str, reason: str | None = None):
        if not self._platform_status_allowed(status):
            return
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            self.knowledge_store.status(knowledge_id, self.platform_knowledge_owner, status, reason)
            return
        if status == WorkflowStatus.FAILED.value:
            self._stop_platform_agent()
        self.redis_client.set(
            self.workflow_status_key,
            {"status": status, "reason": reason, "time": time.time()},
            expiration=3600 * 24 * 7,
        )
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # Message Events and StatuskeyConsumption may also be required
            self.redis_client.delete(self.workflow_data_key)
            self.redis_client.delete(self.workflow_input_key)

    async def async_set_workflow_status(self, status: str, reason: str | None = None):
        if not self._platform_status_allowed(status):
            return
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            self.knowledge_store.status(knowledge_id, self.platform_knowledge_owner, status, reason)
            return
        if status == WorkflowStatus.FAILED.value:
            self._stop_platform_agent()
        await self.redis_client.aset(
            self.workflow_status_key,
            {"status": status, "reason": reason, "time": time.time()},
            expiration=3600 * 24 * 7,
        )
        if status in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            # Message Events and StatuskeyConsumption may also be required
            await self.redis_client.adelete(self.workflow_data_key)
            await self.redis_client.adelete(self.workflow_input_key)

    def get_workflow_status(self) -> dict | None:
        bound = getattr(self, "platform_knowledge_execution_id", None)
        if bound and self.get_platform_knowledge_reference() != bound:
            return {"status": WorkflowStatus.FAILED.value, "reason": "workflow execution replaced", "time": time.time()}
        workflow_status = self.redis_client.get(self.workflow_status_key)
        return workflow_status

    async def async_get_workflow_status(self) -> dict | None:
        bound = getattr(self, "platform_knowledge_execution_id", None)
        if bound and await asyncio.to_thread(self.get_platform_knowledge_reference) != bound:
            return {"status": WorkflowStatus.FAILED.value, "reason": "workflow execution replaced", "time": time.time()}
        workflow_status = await self.redis_client.aget(self.workflow_status_key)
        return workflow_status

    def clear_workflow_status(self):
        self.redis_client.delete(self.workflow_status_key)
        self.redis_client.delete(self.workflow_stop_key)
        self.redis_client.delete(self.workflow_data_key)

    async def async_clear_workflow_status(self):
        await self.redis_client.adelete(self.workflow_status_key)
        await self.redis_client.adelete(self.workflow_stop_key)
        await self.redis_client.adelete(self.workflow_data_key)

    def insert_workflow_response(self, event: dict):
        reference = getattr(self, "platform_agent_execution_id", None)
        if reference:
            if self.get_platform_agent_reference() != reference:
                return
            event = {**event, "_platform_agent_execution_id": reference}
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            self.knowledge_store.event(knowledge_id, self.platform_knowledge_owner, event)
            return
        self.redis_client.rpush(self.workflow_event_key, json.dumps(event), expiration=self.workflow_expire_time)

    def get_workflow_response(self) -> ChatResponse | None:
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            while response := self.knowledge_store.pop(knowledge_id):
                payload = json.loads(response)
                reference = payload.pop("_platform_agent_execution_id", None)
                if not reference or reference == self.get_platform_agent_reference():
                    return ChatResponse(**payload)
            return None
        response = self.redis_client.lpop(self.workflow_event_key)
        while response:
            payload = json.loads(response)
            reference = payload.pop("_platform_agent_execution_id", None)
            if reference and reference != self.get_platform_agent_reference():
                response = self.redis_client.lpop(self.workflow_event_key)
                continue
            response = payload
            break
        if self.get_workflow_stop():
            self.redis_client.delete(self.workflow_event_key)
            return None
        if response:
            response = ChatResponse(**response)
        return response

    async def async_get_workflow_response(self) -> ChatResponse | None:
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            return await asyncio.to_thread(self.get_workflow_response)
        response = await self.redis_client.alpop(self.workflow_event_key)
        while response:
            payload = json.loads(response)
            reference = payload.pop("_platform_agent_execution_id", None)
            if reference and reference != self.get_platform_agent_reference():
                response = await self.redis_client.alpop(self.workflow_event_key)
                continue
            response = payload
            break
        if await self.async_get_workflow_stop():
            await self.redis_client.adelete(self.workflow_event_key)
            return None
        if response:
            response = ChatResponse(**response)
        return response

    def build_chat_response(self, category, category_type, message, extra=None, files=None):
        return ChatResponse(
            user_id=self.user_id,
            chat_id=self.chat_id,
            flow_id=self.workflow_id,
            type=category_type,
            message=message,
            category=category,
            extra=extra,
            files=files,
        )

    def parse_workflow_failed(self, status_info: dict) -> ChatResponse | None:
        if getattr(self, "platform_knowledge_execution_id", None):
            from bisheng.common.errcode.flow import knowledge_error_from_reason

            return self.build_chat_response(
                WorkflowEventType.Error.value,
                "over",
                message=knowledge_error_from_reason(status_info.get("reason")).to_dict(),
            )
        if self.get_platform_agent_reference():
            from bisheng.common.errcode import flow as flow_errors

            for error_type in vars(flow_errors).values():
                if (
                    isinstance(error_type, type)
                    and issubclass(error_type, flow_errors.PlatformAgentError)
                    and getattr(error_type, "Msg", None) == status_info["reason"]
                ):
                    return self.build_chat_response(
                        WorkflowEventType.Error.value, "over", message=error_type().to_dict()
                    )
        if status_info["reason"].find("-- has run more than the maximum number of times") != -1:
            return self.build_chat_response(
                WorkflowEventType.Error.value,
                "over",
                message=WorkFlowNodeRunMaxTimesError(exception=status_info["reason"].split("--")[0]).to_dict(),
            )
        elif status_info["reason"].find("workflow wait user input timeout") != -1:
            return self.build_chat_response(
                WorkflowEventType.Error.value, "over", message=WorkFlowWaitUserTimeoutError().to_dict()
            )
        elif status_info["reason"].find("-- node params is error") != -1:
            return self.build_chat_response(
                WorkflowEventType.Error.value,
                "over",
                message=WorkFlowNodeUpdateError(exception=status_info["reason"].split("--")[0]).to_dict(),
            )
        elif status_info["reason"].find("-- workflow node is update") != -1:
            return self.build_chat_response(
                WorkflowEventType.Error.value,
                "over",
                message=WorkFlowVersionUpdateError(exception=status_info["reason"].split("--")[0]).to_dict(),
            )
        elif status_info["reason"].find("stop by user") != -1:
            return None
        else:
            return self.build_chat_response(
                WorkflowEventType.Error.value, "over", WorkFlowTaskOtherError(exception=status_info["reason"]).to_dict()
            )

    def sync_get_response_until_break(self) -> Iterator[ChatResponse]:
        while True:
            # get workflow status
            status_info = self.get_workflow_status()
            if not status_info:
                yield self.build_chat_response(
                    WorkflowEventType.Error.value,
                    "over",
                    message=WorkFlowTaskOtherError(exception=Exception("workflow status not found")).to_dict(),
                )
                break
            elif status_info["status"] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                while True:
                    chat_response = self.get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                if status_info["status"] == WorkflowStatus.FAILED.value:
                    error_resp = self.parse_workflow_failed(status_info)
                    if error_resp:
                        yield error_resp
                break
            elif status_info["status"] == WorkflowStatus.INPUT.value:
                while True:
                    chat_response = self.get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                break
            elif (
                status_info["status"] in [WorkflowStatus.WAITING.value, WorkflowStatus.INPUT_OVER.value]
                and time.time() - status_info["time"] > 10
            ):
                # 10No status update received in seconds, descriptionworkflowNot started, could becelery workerThreads full
                self.set_workflow_status(WorkflowStatus.FAILED.value, "workflow task execute busy")
                yield self.build_chat_response(
                    WorkflowEventType.Error.value, "over", message=WorkFlowTaskBusyError().to_dict()
                )
                break
            elif time.time() - status_info["time"] > 86400:
                yield self.build_chat_response(
                    WorkflowEventType.Error.value,
                    "over",
                    WorkFlowTaskOtherError(exception=Exception("workflow status not update over 1 day")).to_dict(),
                )
                self.set_workflow_status(WorkflowStatus.FAILED.value, "workflow status not update over 1 day")
                self.set_workflow_stop()
                break
            else:
                chat_response = self.get_workflow_response()
                if not chat_response:
                    time.sleep(1)
                    continue
                yield chat_response

    async def get_response_until_break(self) -> AsyncIterator[ChatResponse]:
        """Continuous accessworkflowright of privacyresponseuntil the end of the run is encountered or pending entry"""
        while True:
            # get workflow status
            status_info = await self.async_get_workflow_status()
            if not status_info:
                yield self.build_chat_response(
                    WorkflowEventType.Error.value,
                    "over",
                    message=WorkFlowTaskOtherError(exception=Exception("workflow status not found")).to_dict(),
                )
                break
            elif status_info["status"] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
                while True:
                    chat_response = await self.async_get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                if status_info["status"] == WorkflowStatus.FAILED.value:
                    error_resp = self.parse_workflow_failed(status_info)
                    if error_resp:
                        yield error_resp
                break
            elif status_info["status"] == WorkflowStatus.INPUT.value:
                while True:
                    chat_response = await self.async_get_workflow_response()
                    if not chat_response:
                        break
                    yield chat_response
                break
            elif (
                status_info["status"] in [WorkflowStatus.WAITING.value, WorkflowStatus.INPUT_OVER.value]
                and time.time() - status_info["time"] > 10
            ):
                # 10No status update received in seconds, descriptionworkflowNot started, could becelery workerThreads full
                await self.async_set_workflow_status(WorkflowStatus.FAILED.value, "workflow task execute busy")
                yield self.build_chat_response(
                    WorkflowEventType.Error.value, "over", message=WorkFlowTaskBusyError().to_dict()
                )
                break
            elif time.time() - status_info["time"] > 86400:
                yield self.build_chat_response(
                    WorkflowEventType.Error.value,
                    "over",
                    message=WorkFlowTaskOtherError(
                        exception=Exception("workflow status not update over 1 day")
                    ).to_dict(),
                )
                await self.async_set_workflow_status(
                    WorkflowStatus.FAILED.value, "workflow status not update over 1 day"
                )
                await self.async_set_workflow_stop()
                break
            else:
                chat_response = await self.async_get_workflow_response()
                if not chat_response:
                    await asyncio.sleep(0.01)
                    continue
                yield chat_response

    def set_user_input(
        self, data: dict, message_id: int | None = None, message_content: str | None = None, verify_input: bool = False
    ):
        if self.chat_id and message_id:
            message_db = self._own_message(ChatMessageDao.get_message_by_id(message_id), verify_input)
            self.update_old_message(data, message_db, message_content, verify_input)
        # Notify Asynchronous Task User Input
        self.redis_client.set(self.workflow_input_key, data, expiration=self.workflow_expire_time)
        return

    async def async_set_user_input(
        self,
        data: dict,
        message_id: int | None = None,
        message_content: str | None = None,
        verify_input: bool = False,
        files: list | None = None,
        *,
        before_write: Callable[[], Awaitable[None]] | None = None,
    ):
        chat_response, message = None, None
        if self.chat_id and message_id:
            message_db = self._own_message(await ChatMessageDao.aget_message_by_id(message_id), verify_input)
            changes = self._update_old_message(data, message_db, message_content, verify_input, files)
            if changes:
                chat_response, message = changes
        if before_write is not None:
            await before_write()
        if chat_response:
            self.save_chat_message(chat_response)
        elif message:
            await ChatMessageDao.aupdate_message_model(message)
        # Notify Asynchronous Task User Input
        await self.redis_client.aset(self.workflow_input_key, data, expiration=self.workflow_expire_time)
        return

    def _own_message(self, message_db: ChatMessage | None, verify_input: bool) -> ChatMessage | None:
        """When verifying caller input, a message of another session counts as not found."""
        if verify_input and message_db is not None and message_db.chat_id != self.chat_id:
            return None
        return message_db

    @staticmethod
    def _verify_node_input(input_schema_message: dict, user_input: dict) -> dict:
        """Return the input of the waiting node; the caller input must be an object per node."""
        node_id = input_schema_message["node_id"]
        if not isinstance(user_input, dict) or node_id not in user_input:
            raise WorkFlowInvalidUserInputError(msg=f"input does not contain the waiting node {node_id}")
        node_input = user_input[node_id]
        if not isinstance(node_input, dict):
            raise WorkFlowInvalidUserInputError(msg=f"input of node {node_id} must be an object")
        return node_input

    @classmethod
    def _verify_input_schema(cls, input_schema_message: dict, user_input: dict):
        """Verify that the user input matches the input schema"""
        user_input = cls._verify_node_input(input_schema_message, user_input)
        input_schema = input_schema_message["input_schema"]
        if input_schema["tab"] == "form_input":
            user_input_keys = dict.fromkeys(user_input.keys())
            for key_info in input_schema["value"]:
                key = key_info["key"]
                if key not in user_input:
                    raise WorkFlowInvalidUserInputError(msg=f"key {key} not found in user input")
                user_input_keys.pop(key)
            if user_input_keys:
                raise WorkFlowInvalidUserInputError(msg=f"extra key {list(user_input_keys.keys())} found in user input")
        else:
            if input_schema["key"] not in user_input:
                raise WorkFlowInvalidUserInputError(msg=f"key {input_schema['key']} not found in user input")

    _INPUT_CATEGORIES = frozenset(
        {
            WorkflowEventType.UserInput.value,
            WorkflowEventType.OutputWithInput.value,
            WorkflowEventType.OutputWithChoose.value,
        }
    )

    @classmethod
    def _update_old_message(
        cls,
        user_input: dict,
        message_db: ChatMessage,
        message_content: str,
        verify_input: bool = False,
        files: list | None = None,
    ):
        """
        if ChatResponse is not None: add new message
        if ChatMessage is not None: update old message
        return ChatResponse | None, ChatMessage | None
        """
        if not message_db:
            if verify_input:
                raise WorkFlowInvalidUserInputError(msg="message_id does not match a message in this session")
            return None
        # Update the input and selection of the user in the output to be entered message
        old_message = json.loads(message_db.message)
        if verify_input:
            if message_db.category not in cls._INPUT_CATEGORIES:
                raise WorkFlowInvalidUserInputError(msg="message_id does not refer to a message that waits for input")
            if message_db.category != WorkflowEventType.UserInput.value:
                node_input = cls._verify_node_input(old_message, user_input)
                if old_message["key"] not in node_input:
                    raise WorkFlowInvalidUserInputError(msg=f"key {old_message['key']} not found in user input")
        if message_db.category == WorkflowEventType.OutputWithInput.value:
            old_message["hisValue"] = user_input[old_message["node_id"]][old_message["key"]]
        elif message_db.category == WorkflowEventType.OutputWithChoose.value:
            old_message["hisValue"] = user_input[old_message["node_id"]][old_message["key"]]
        elif message_db.category == WorkflowEventType.UserInput.value:
            if verify_input:
                cls._verify_input_schema(old_message, user_input)
            user_input = user_input[old_message["node_id"]]

            # If the front-end passes user input, the front-end content is used.
            if message_content:
                user_input_message = message_content
            # Instructions are form inputs
            elif old_message["input_schema"]["tab"] == "form_input":
                user_input_message = ""
                for key_info in old_message["input_schema"]["value"]:
                    user_input_message += f"{key_info['value']}:{user_input.get(key_info['key'], '')}\n"
            else:
                # Description Dialog Input, Uploaded file information needs to be added, It is related to the data structure of the input node.
                user_input_message = user_input[old_message["input_schema"]["key"]]
                dialog_files_content = user_input.get("dialog_files_content", [])
                for one in dialog_files_content:
                    user_input_message += f"\n{os.path.basename(one).split('?')[0]}"
            return ChatResponse(
                message=user_input_message,
                category="question",
                # Carry the attachments as data, not just as filenames appended
                # to the text — that is what lets them render and be kept.
                files=files or [],
            ), None
        message_db.message = json.dumps(old_message, ensure_ascii=False)
        return None, message_db

    def update_old_message(
        self,
        user_input: dict,
        message_db: ChatMessage,
        message_content: str,
        verify_input: bool = False,
        files: list | None = None,
    ):
        chat_response, message = self._update_old_message(user_input, message_db, message_content, verify_input, files)
        if chat_response:
            self.save_chat_message(chat_response)
            return
        if message:
            ChatMessageDao.update_message_model(message)

    def get_user_input(self) -> dict | None:
        ret = self.redis_client.get(self.workflow_input_key)
        if ret:
            self.redis_client.delete(self.workflow_input_key)
        return ret

    def set_workflow_stop(self):
        from bisheng.worker.workflow.tasks import stop_workflow

        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id and not self.knowledge_store.stop(knowledge_id):
            return

        reference = getattr(self, "platform_agent_execution_id", None)
        if reference and reference != self.get_platform_agent_reference():
            return
        self._stop_platform_agent()
        self.redis_client.set(self.workflow_stop_key, 1, expiration=3600 * 24)
        self._dispatch_stop_task(stop_workflow)

    async def async_set_workflow_stop(self, *, long_committed=False):
        from bisheng.worker.workflow.tasks import stop_workflow

        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id and not self.knowledge_store.stop(knowledge_id):
            return

        reference = getattr(self, "platform_agent_execution_id", None)
        if reference and reference != self.get_platform_agent_reference():
            return
        if not long_committed:
            self._stop_platform_agent()
            await self.redis_client.aset(self.workflow_stop_key, 1, expiration=3600 * 24)
            self._dispatch_stop_task(stop_workflow)
            return
        try:
            await self.redis_client.aset(self.workflow_stop_key, 1, expiration=3600 * 24)
            await self.async_set_workflow_status(WorkflowStatus.FAILED.value, "workflow stop by user")
            self._dispatch_stop_task(stop_workflow)
        except Exception as exc:
            # 停止意图已经提交。通知失败由执行行门禁及补偿处理。
            logger.warning("平台 Agent 停止通知待补偿, error_type={}", type(exc).__name__)

    def on_agent_long_task(self, summary):
        self.insert_workflow_response(
            self.build_chat_response("processing", "info", message={"agent_long_task": summary}).model_dump()
        )

    def _dispatch_stop_task(self, task):
        reference = getattr(self, "platform_agent_execution_id", None) or self.get_platform_agent_reference()
        knowledge_id = getattr(self, "platform_knowledge_execution_id", None)
        if knowledge_id:
            task.apply_async(
                [self.unique_id, self.workflow_id, self.chat_id, self.user_id],
                kwargs={"platform_agent_execution_id": reference, "platform_knowledge_execution_id": knowledge_id},
                headers={"tenant_id": self.tenant_id or get_current_tenant_id()},
            )
            return
        if reference:
            task.apply_async(
                [self.unique_id, self.workflow_id, self.chat_id, self.user_id],
                kwargs={"platform_agent_execution_id": reference},
                headers={"tenant_id": self.tenant_id or get_current_tenant_id()},
            )
        else:
            task.delay(self.unique_id, self.workflow_id, self.chat_id, self.user_id)

    def get_workflow_stop(self) -> bool | None:
        """In order to stop in timeworkflow, Do not cache memory"""
        return self.redis_client.get(self.workflow_stop_key) == 1

    async def async_get_workflow_stop(self) -> bool | None:
        """In order to stop in timeworkflow, Do not cache memory"""
        return await self.redis_client.aget(self.workflow_stop_key) == 1

    def send_chat_response(self, chat_response: ChatResponse):
        """Send a chat message"""
        self.insert_workflow_response(chat_response.dict())

        # Determine if it needs to be stoppedworkflow, Don't judge when streaming, queries are too frequent and can't be stoppedworkflow
        if chat_response.category == WorkflowEventType.StreamMsg.value:
            return
        if self.workflow and self.get_workflow_stop():
            self.workflow.stop()

    def save_chat_message(
        self,
        chat_response: ChatResponse,
        source_documents=None,
        citation_registry_items: list[CitationRegistryItemSchema] | None = None,
    ) -> int | str | None:
        """save chat message to database
        return message id
        """
        owner = getattr(self, "platform_knowledge_owner", "")
        if owner:
            reference = getattr(self, "platform_agent_execution_id", None)
            if reference and reference != self.get_platform_agent_reference():
                raise PlatformKnowledgeExecutionError()
            self.knowledge_store.check(self.platform_knowledge_execution_id, owner)
        if not self.chat_id:
            items = self._finalize_citation_items(
                chat_response,
                source_documents=source_documents,
                citation_registry_items=citation_registry_items,
            )
            save_message_citations_sync(
                message_id=None,
                items=items,
                chat_id=self.chat_id,
                flow_id=self.workflow_id,
            )
            # Generate a fake messageidPrevent duplicate front-end message rendering
            return uuid.uuid4().hex

        # Judgment traceability
        if source_documents:
            result = {}
            extra = {}
            if isinstance(source_documents, Document):
                result = source_documents
            source, result = sync_judge_source(result, source_documents, self.chat_id, extra)
            chat_response.source = source
            chat_response.extra = json.dumps(extra, ensure_ascii=False)

        # Attachments the user sent become permanent here, not at upload time —
        # uploads sit in the temp bucket, which clears itself every 3 days.
        # Only the user's own files: what the workflow produced is out of scope.
        # Keyed on category, not is_bot: that field defaults to True, so a
        # question would have been skipped.
        if chat_response.category == "question":
            promote_chat_attachments_sync(chat_response.files, self.user_id)

        # Resolve citations BEFORE the insert: the stored answer must not keep a
        # marker the registry cannot back, so the same item set decides both what
        # is persisted and what survives in the text.
        items = self._finalize_citation_items(
            chat_response,
            source_documents=source_documents,
            citation_registry_items=citation_registry_items,
        )

        message = ChatMessageDao.insert_one(
            ChatMessage(
                user_id=self.user_id,
                chat_id=self.chat_id,
                flow_id=self.workflow_id,
                type=chat_response.type,
                is_bot=chat_response.is_bot,
                source=chat_response.source,
                message=chat_response.message
                if isinstance(chat_response.message, str)
                else json.dumps(chat_response.message, ensure_ascii=False),
                extra=chat_response.extra,
                category=chat_response.category,
                files=json.dumps(chat_response.files, ensure_ascii=False),
            )
        )

        save_message_citations_sync(
            message_id=message.id,
            items=items,
            chat_id=self.chat_id,
            flow_id=self.workflow_id,
        )

        # If the document is traceable, handle the recallchunk
        if chat_response.source not in [0, 4]:
            thread_pool.submit(
                f"workflow_source_document_{self.chat_id}",
                sync_process_source_document,
                source_documents,
                self.chat_id,
                message.id,
                chat_response.message.get("msg"),
            )

        # Determine if a new session is needed
        if not self.create_session and chat_response.category != WorkflowEventType.UserInput.value:
            # Insert a new session without session data
            if not MessageSessionDao.get_one(self.chat_id):
                db_workflow = FlowDao.get_flow_by_id(self.workflow_id)
                self.new_session = MessageSessionDao.insert_one(
                    MessageSession(
                        chat_id=self.chat_id,
                        flow_id=self.workflow_id,
                        flow_name=db_workflow.name,
                        flow_type=FlowType.WORKFLOW.value,
                        user_id=self.user_id,
                    )
                )
                # RecordTelemetryJournal
                telemetry_service.log_event_sync(
                    user_id=self.user_id,
                    event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
                    trace_id=trace_id_var.get(),
                    event_data=NewMessageSessionEventData(
                        session_id=self.chat_id,
                        app_id=self.workflow_id,
                        source=self.source,
                        app_name=db_workflow.name,
                        app_type=ApplicationTypeEnum.WORKFLOW,
                    ),
                )

            self.create_session = True

        # A greeting can create the session before the user submits anything.
        # Only a persisted question contains content suitable for its title.
        if chat_response.category == "question":
            thread_pool.submit(f"workflow_generate_title_{self.chat_id}", self.generate_session_title)

        return message.id

    @staticmethod
    def _scrub_fabricated_citations(message, items):
        """Drop citation markers the registry cannot back, before the answer is stored.

        The prompt forbids inventing a source id, but nothing enforced it: an
        invented id still renders as a footnote whose detail endpoint 404s, so
        the reader is told "溯源详情加载失败" for what is actually a hallucination.
        Strip those markers where the answer is finalized instead of teaching
        every reader to distrust the ones that remain.

        Mirrors ``_extract_message_text``: a workflow answer arrives either as a
        bare string or as a dict whose ``msg`` holds it.
        """
        if isinstance(message, str):
            return strip_unregistered_citation_markers(message, items)
        if isinstance(message, dict) and isinstance(message.get("msg"), str):
            scrubbed = strip_unregistered_citation_markers(message["msg"], items)
            if scrubbed != message["msg"]:
                return {**message, "msg": scrubbed}
        return message

    def _finalize_citation_items(
        self,
        chat_response: ChatResponse,
        source_documents=None,
        citation_registry_items: list[CitationRegistryItemSchema] | None = None,
    ) -> list[CitationRegistryItemSchema]:
        """Scrub invented markers, then persist only what the (scrubbed) answer cites.

        Canvas debug has no chat_id and used to skip the scrub, so a model that
        copied the prompt example ``knowledgesearch_18f5868b:0`` rendered a
        dead superscript. Scrub against the full registry first: unknown ids
        that sit next to a real citation are dropped; an answer that cited
        nothing registered is rewritten onto this round's ``tempsearch_`` /
        ``knowledgesearch_`` keys so the superscript still opens the file.
        """
        raw_items = list(citation_registry_items or [])
        if not raw_items and source_documents:
            documents = source_documents if isinstance(source_documents, list) else [source_documents]
            raw_items = collect_rag_citation_registry_items(documents)
        chat_response.message = self._scrub_fabricated_citations(chat_response.message, raw_items)
        items = select_registry_items_for_persistence(raw_items, self._extract_message_text(chat_response.message))
        items = self._attach_temp_object_names(items)
        if hasattr(chat_response, "citation_registry_items"):
            chat_response.citation_registry_items = items
        if hasattr(chat_response, "citations"):
            chat_response.citations = items
        return items

    @staticmethod
    def _resolve_citation_items(
        answer_text: str,
        source_documents=None,
        citation_registry_items: list[CitationRegistryItemSchema] | None = None,
    ) -> list[CitationRegistryItemSchema]:
        items = list(citation_registry_items or [])
        if not items and source_documents:
            documents = source_documents if isinstance(source_documents, list) else [source_documents]
            items = collect_rag_citation_registry_items(documents)
        return select_registry_items_for_persistence(items, answer_text)

    def _load_question_attachment_files(self) -> list[dict]:
        """Question-message files already promoted by F043, used to fill objectName."""
        files: list[dict] = []
        if not self.chat_id:
            return files
        try:
            messages = ChatMessageDao.get_messages_by_chat_id(self.chat_id, category_list=["question"], limit=20)
            for message in messages:
                raw = message.files
                parsed = json.loads(raw) if isinstance(raw, str) else (raw or [])
                if isinstance(parsed, list):
                    files.extend(file for file in parsed if isinstance(file, dict))
        except Exception:
            logger.exception("failed to load question attachments for temp citations")
        return files

    def _attach_temp_object_names(
        self,
        items: list[CitationRegistryItemSchema],
    ) -> list[CitationRegistryItemSchema]:
        """Write F043 object keys onto cited temp items before they are persisted."""
        if not items:
            return items
        try:
            return attach_temp_object_names(items, self._load_question_attachment_files(), self.user_id)
        except Exception:
            logger.exception("failed to attach temp object names; dropping temp citations")
            return [item for item in items if item.type != CitationType.TEMP]

    @staticmethod
    def _extract_message_text(message: str | dict | list | None) -> str:
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            msg = message.get("msg")
            if isinstance(msg, str):
                return msg
            return json.dumps(message, ensure_ascii=False)
        if message is None:
            return ""
        return json.dumps(message, ensure_ascii=False)

    def generate_session_title(self):
        session = MessageSessionDao.get_one(self.chat_id)
        if not session:
            return
        if session.name and session.name != "New Chat":
            return

        input_message = ChatMessageDao.get_messages_by_chat_id(self.chat_id, ["question"], 1)
        if not input_message or not input_message[0].message:
            return
        question = input_message[0].message

        llm_conf = LLMService.get_workbench_llm_sync(tenant_id=self.tenant_id)
        if not llm_conf or not llm_conf.chat_title_llm or not llm_conf.chat_title_llm.id:
            return
        llm = LLMService.get_bisheng_llm_sync(
            model_id=llm_conf.chat_title_llm.id,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name="workflow_chat_title",
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=self.user_id,
        )
        title = generate_conversation_title_sync(question=question, llm=llm)
        updated = MessageSessionDao.update_session_name_sync(
            session.chat_id, title, only_if_default=True, tenant_id=session.tenant_id
        )
        if updated and self.new_session:
            self.new_session.name = title

    def on_node_start(self, data: NodeStartData):
        """node start event"""
        logger.debug(f"node start: {data}")
        self.send_chat_response(
            ChatResponse(
                message=data.dict(),
                category=WorkflowEventType.NodeRun.value,
                type="start",
                flow_id=self.workflow_id,
                chat_id=self.chat_id,
            )
        )

    def on_node_end(self, data: NodeEndData):
        """node end event"""
        logger.debug(f"node end: {data}")
        self.send_chat_response(
            ChatResponse(
                message=data.dict(),
                category=WorkflowEventType.NodeRun.value,
                type="end",
                flow_id=self.workflow_id,
                chat_id=self.chat_id,
            )
        )

    def on_user_input(self, data: UserInputData):
        """user input event"""
        logger.debug(f"user input: {data}")
        chat_response = ChatResponse(
            message=data.dict(),
            category=WorkflowEventType.UserInput.value,
            type="over",
            flow_id=self.workflow_id,
            chat_id=self.chat_id,
        )
        msg_id = self.save_chat_message(chat_response)
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_guide_word(self, data: GuideWordData):
        """guide word event"""
        logger.debug(f"guide word: {data}")
        self.send_chat_response(
            ChatResponse(
                message=data.dict(),
                category=WorkflowEventType.GuideWord.value,
                type="over",
                flow_id=self.workflow_id,
                chat_id=self.chat_id,
            )
        )

    def on_guide_question(self, data: GuideQuestionData):
        """guide question event"""
        logger.debug(f"guide question: {data}")
        self.send_chat_response(
            ChatResponse(
                message=data.dict(),
                category=WorkflowEventType.GuideQuestion.value,
                type="over",
                flow_id=self.workflow_id,
                chat_id=self.chat_id,
            )
        )

    def on_output_msg(self, data: OutputMsgData):
        logger.debug(f"output msg: {data}")
        chat_response = ChatResponse(
            message=data.dict(exclude={"source_documents", "citation_registry_items"}),
            category=WorkflowEventType.OutputMsg.value,
            extra="",
            type="over",
            flow_id=self.workflow_id,
            chat_id=self.chat_id,
            files=data.files,
            citations=data.citation_registry_items,
            citation_registry_items=data.citation_registry_items,
        )
        msg_id = self.save_chat_message(
            chat_response,
            source_documents=data.source_documents,
            citation_registry_items=data.citation_registry_items,
        )
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def publish_long_task_resume_output(self, message_id, message):
        self.send_chat_response(ChatResponse(
            message={**message, "agent_long_task_execution_id": self.platform_agent_execution_id},
            message_id=message_id, category=WorkflowEventType.OutputMsg.value,
            type="over", flow_id=self.workflow_id, chat_id=self.chat_id, extra="",
        ))

    def on_stream_msg(self, data: StreamMsgData):
        logger.debug(f"stream msg: {data}")
        self.send_chat_response(
            ChatResponse(
                message=data.dict(),
                category=WorkflowEventType.StreamMsg.value,
                extra="",
                type="stream",
                flow_id=self.workflow_id,
                chat_id=self.chat_id,
            )
        )

    def on_stream_over(self, data: StreamMsgOverData):
        logger.debug(f"stream over: {data}")
        # Replaceminioright of privacysharePrefix bynginxShare  ugly solve
        minio_share = settings.get_minio_conf().sharepoint
        data.msg = data.msg.replace(f"http://{minio_share}", "")
        chat_response = ChatResponse(
            message=data.dict(exclude={"source_documents", "citation_registry_items"}),
            category=WorkflowEventType.StreamMsg.value,
            extra="",
            type="end",
            flow_id=self.workflow_id,
            chat_id=self.chat_id,
            citations=data.citation_registry_items,
            citation_registry_items=data.citation_registry_items,
        )
        msg_id = self.save_chat_message(
            chat_response,
            source_documents=data.source_documents,
            citation_registry_items=data.citation_registry_items,
        )
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_output_choose(self, data: OutputMsgChooseData):
        logger.debug(f"output choose: {data}")
        chat_response = ChatResponse(
            message=data.dict(exclude={"source_documents", "citation_registry_items"}),
            category=WorkflowEventType.OutputWithChoose.value,
            extra="",
            type="over",
            flow_id=self.workflow_id,
            chat_id=self.chat_id,
            files=data.files,
            citations=data.citation_registry_items,
            citation_registry_items=data.citation_registry_items,
        )
        msg_id = self.save_chat_message(
            chat_response,
            source_documents=data.source_documents,
            citation_registry_items=data.citation_registry_items,
        )
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)

    def on_output_input(self, data: OutputMsgInputData):
        logger.debug(f"output input: {data}")
        chat_response = ChatResponse(
            message=data.dict(exclude={"source_documents", "citation_registry_items"}),
            category=WorkflowEventType.OutputWithInput.value,
            extra="",
            type="over",
            flow_id=self.workflow_id,
            chat_id=self.chat_id,
            files=data.files,
            citations=data.citation_registry_items,
            citation_registry_items=data.citation_registry_items,
        )
        msg_id = self.save_chat_message(
            chat_response,
            source_documents=data.source_documents,
            citation_registry_items=data.citation_registry_items,
        )
        if msg_id:
            chat_response.message_id = msg_id
        self.send_chat_response(chat_response)


class LongTaskResumeOutput(BaseCallback):
    """只暂存 4D 的纯文本。节点事件和输出在事务前不进入会话流。"""

    def __init__(self):
        super().__init__()
        self.message = None

    def on_output_msg(self, data: OutputMsgData):
        if self.message is not None or data.files or data.source_documents or data.citation_registry_items:
            raise PlatformAgentExecutionError()
        self.message = data.model_dump(exclude={"source_documents", "citation_registry_items"})
