import asyncio
import inspect
import json

from fastapi import Request, WebSocket
from loguru import logger

from bisheng.api.services.audit_log import AuditLogService
from bisheng.api.v1.schema.workflow import WorkflowEventType
from bisheng.chat_session.domain.chat import ChatSessionService
from bisheng.common.chat.clients.base import BaseClient
from bisheng.common.chat.types import WorkType
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.chat import WorkflowOfflineError
from bisheng.common.errcode.flow import PlatformAgentExecutionError, PlatformAgentPermissionError
from bisheng.database.models.flow import FlowDao, FlowStatus
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.session import MessageSession
from bisheng.utils import generate_uuid, get_request_ip
from bisheng.worker.workflow.redis_callback import RedisCallback
from bisheng.worker.workflow.tasks import continue_workflow, execute_workflow, workflow_stateful_worker
from bisheng.workflow.common.workflow import WorkflowStatus

WORKFLOW_STATUS_CHECK_FINISHED = {
    "event": "workflow_status_checked",
    "status": "finished",
}

def _valid_agent_execution_id(value):
    return isinstance(value, str) and len(value) == 32 and all(char in "0123456789abcdef" for char in value)


class WorkflowClient(BaseClient):
    @property
    def execution_snapshot(self):
        context = self.current_execution_context
        return context.execution_snapshot if context is not None else self._connection_execution_snapshot

    @execution_snapshot.setter
    def execution_snapshot(self, value):
        self._connection_execution_snapshot = value

    @property
    def session_subject(self):
        context = self.current_execution_context
        return context.session_subject if context is not None else self._connection_session_subject

    @session_subject.setter
    def session_subject(self, value):
        self._connection_session_subject = value

    def _causal_headers(self):
        context = self.current_execution_context
        if context is None or context.causal_context is None:
            return {}
        return {
            "headers": {"kunlian_causal_context": dict(context.causal_context), "tenant_id": context.operator.tenant_id}
        }

    def __init__(
        self,
        request: Request,
        client_key: str,
        client_id: str,
        chat_id: str,
        user_id: int,
        login_user: UserPayload,
        work_type: WorkType,
        websocket: WebSocket,
        **kwargs,
    ):
        super().__init__(request, client_key, client_id, chat_id, user_id, login_user, work_type, websocket, **kwargs)

        self.workflow: RedisCallback | None = None
        self._connection_chat_id = chat_id
        self._stopped_long_reference: str | None = None
        self.latest_history: ChatMessage | None = None
        self.hash_key = None
        self.ws_closed = False
        self.run_lock = asyncio.Lock()
        self.session_subject = kwargs.get("session_subject")
        self.execution_snapshot = kwargs.get("execution_snapshot")

    async def close(self, force_stop=False):
        # If the user is not actively stopping, setwsTurn the flag off, but there is no need to abortworkflowExecution
        if not force_stop:
            self.ws_closed = True
        # Non-Session Mode OffworkflowImplementation, Session mode determines if the user took the initiative to close
        if self.workflow:
            if force_stop or (not self.chat_id and getattr(self.login_user, "auth_source", None) != "kunlian"):
                runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
                if force_stop and getattr(runtime, "stop_long", None) is not None:
                    workflow = self.workflow
                    ref = (
                        getattr(workflow, "platform_agent_execution_id", None)
                        or workflow.get_platform_agent_reference()
                    )
                    if await runtime.stop_long(self.login_user, workflow.workflow_id, workflow.unique_id, ref):
                        await workflow.async_set_workflow_stop(long_committed=True)
                        if self.workflow is workflow or self.workflow is None:
                            self._stopped_long_reference = ref
                            self.workflow = None
                            try:
                                summary = await runtime.long_status(
                                    self.login_user, workflow.workflow_id, workflow.unique_id, ref
                                )
                                if self.workflow is None and summary:
                                    await self.send_response("processing", "info", {"agent_long_task": summary})
                            finally:
                                if self.workflow is None:
                                    await self.send_response("processing", "close", "")
                        await super().close()
                        return
                await self.workflow.async_set_workflow_stop()
                workflow_over = await self.workflow_run()
                while not workflow_over:
                    if self.ws_closed:
                        break
                    workflow_over = await self.workflow_run()
                    await asyncio.sleep(0.5)
        elif force_stop:
            await self.send_response("processing", "close", "")
        await super().close()

    async def _handle_message(self, message: dict[any, any]):
        logger.debug("----------------------------- start handle message -----------------------")
        if message.get("action") == "init_data":
            # InisialisasiworkflowDATA
            await self.init_workflow(message)
        elif message.get("action") == "check_status":
            await self.check_status(message)
        elif message.get("action") == "input":
            await self.handle_user_input(message.get("data"))
        elif message.get("action") == "agent_interaction_submit":
            await self.submit_agent_interaction(message)
        elif message.get("action") == "stop":
            if await self._handle_long_task_resume(message, stop=True) is None and not await self.stop_agent_interaction(message):
                await self.close(force_stop=True)
            # await self.stop_handle_message(message)
        else:
            logger.warning("not support action: %s", message.get("action"))

    async def init_history(self):
        if not self.chat_id:
            return
        self.latest_history = await ChatMessageDao.aget_latest_message_by_chatid(self.chat_id)
        if not self.latest_history:
            # The user clicks New Session to log the audit
            AuditLogService.create_chat_workflow(self.login_user, get_request_ip(self.request), self.client_id)

    def _interaction_session(self, message):
        chat_id = self._connection_chat_id
        if not chat_id or message.get("chat_id", chat_id) != chat_id or message.get("flow_id", self.client_id) != self.client_id:
            raise PlatformAgentPermissionError()
        if self.session_subject is not None and self.session_subject.subject_type != "user":
            raise PlatformAgentPermissionError()
        return f"{chat_id}_async_task_id"

    async def _send_interaction_error(self, runtime, exc, execution_id=None, *, submit=False):
        error = runtime.public_error(exc) if runtime is not None else PlatformAgentExecutionError()
        payload = {
            **error.to_dict(data={}),
            "agent_interaction_error": "retry" if submit and isinstance(error, PlatformAgentExecutionError) else "blocked",
        }
        if _valid_agent_execution_id(execution_id):
            payload["execution_id"] = execution_id
        await self.send_response("error", "over", payload)

    async def submit_agent_interaction(self, message):
        runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
        try:
            session = self._interaction_session(message)
            if getattr(runtime, "submit_interaction", None) is None:
                raise PlatformAgentExecutionError()
            if not _valid_agent_execution_id(message.get("execution_id")):
                raise PlatformAgentExecutionError()
            result = await runtime.submit_interaction(
                self.login_user, self.client_id, session,
                *(message.get(key) for key in ("execution_id", "interaction_id", "revision", "submission_id", "answer")),
            )
            await self.send_response("processing", "info", result["message"])
        except Exception as exc:
            await self._send_interaction_error(runtime, exc, message.get("execution_id"), submit=True)

    async def stop_agent_interaction(self, message):
        runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
        explicit = "execution_id" in message
        reference = message.get("execution_id")
        if not explicit and (
            getattr(runtime, "stop_interaction", None) is None
            or not self._connection_chat_id
            or (self.session_subject is not None and self.session_subject.subject_type != "user")
        ):
            return False
        try:
            if explicit and (not _valid_agent_execution_id(reference) or getattr(runtime, "stop_interaction", None) is None):
                raise PlatformAgentPermissionError()
            session = self._interaction_session(message)
            workflow = self.workflow or RedisCallback(session, self.client_id, self._connection_chat_id, self.user_id)
            if not explicit:
                reference = workflow.get_platform_agent_reference()
            result = await runtime.stop_interaction(self.login_user, self.client_id, session, reference)
            if result is None:
                if explicit:
                    raise PlatformAgentPermissionError()
                return False
            execution_id = result["execution_id"]
            current = workflow.get_platform_agent_reference()
            owns_stream = current in {None, execution_id} and (self.workflow is None or self.workflow is workflow)
            if owns_stream:
                self._stopped_long_reference = execution_id
                self.workflow = None
            if current == execution_id:
                await workflow.async_set_workflow_stop(long_committed=True)
            await self.send_response("processing", "info", result["message"])
            if owns_stream and self.workflow is None:
                await self.send_response("processing", "close", "")
            return True
        except Exception as exc:
            await self._send_interaction_error(runtime, exc, reference)
            return True

    async def _run_interaction_stream(self, runtime, workflow, execution_id):
        login_user = self.login_user

        async def authorize_event(event):
            try:
                status = await runtime.interaction_status(login_user, workflow.workflow_id, workflow.unique_id, execution_id)
            except Exception as exc:
                await self._send_interaction_error(runtime, exc, execution_id)
                return None
            if status is None:
                return None
            category = event.get("category") if isinstance(event, dict) else event.category
            return status["output_allowed"] or category in {"processing", "error"}

        return await self.workflow_run(authorize_event=authorize_event)

    async def _check_agent_interaction(self, message, runtime, workflow, is_init):
        if (
            getattr(runtime, "interaction_status", None) is None
            or not self._connection_chat_id
        ):
            return False
        session = f"{self._connection_chat_id}_async_task_id"
        current = workflow.get_platform_agent_reference()
        reference = message.get("execution_id", current)
        try:
            if "execution_id" in message and not _valid_agent_execution_id(reference):
                raise PlatformAgentPermissionError()
            result = await runtime.interaction_status(self.login_user, self.client_id, session, reference)
            if result is None:
                return False
            self._interaction_session(message)
        except Exception as exc:
            await self._send_interaction_error(runtime, exc, reference)
            return True
        self.chat_id = self._connection_chat_id
        if is_init and (result["state"] == "READY" or (
            not result["active"] and message.get("initial_open") is not True
        )):
            return False
        execution_id = result["execution_id"]
        if not current and result["active"] and workflow.restore_platform_agent_reference(execution_id):
            current = execution_id
        if result["message"]:
            await self.send_response("processing", "info", result["message"])
        if current != execution_id or getattr(workflow, "platform_agent_execution_id", current) != execution_id:
            return True
        interaction = result["message"].get("agent_interaction")
        if interaction and interaction["phase"] == "WAITING_INPUT":
            return True
        status = workflow.get_workflow_status()
        if status and status["status"] != WorkflowStatus.INPUT.value and not self.run_lock.locked():
            self.workflow = workflow
            await self._run_interaction_stream(runtime, workflow, execution_id)
        elif not result["active"] and (not status or status["status"] == WorkflowStatus.INPUT.value):
            self._stopped_long_reference = execution_id
            if self.workflow is not None and self.workflow.get_platform_agent_reference() == execution_id:
                self.workflow = None
        return True

    async def _handle_long_task_resume(self, message, *, is_init=False, stop=False):
        runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
        action = getattr(runtime, "stop_long_task_resume" if stop else "long_task_resume_status", None)
        chat_id = getattr(self, "_connection_chat_id", None)
        if action is None or not chat_id or self.execution_snapshot is not None:
            return None
        subject = self.session_subject
        if subject is not None and subject.subject_type != "user":
            return None
        session = f"{chat_id}_async_task_id"
        reference = message.get("execution_id")
        if "execution_id" in message and not _valid_agent_execution_id(reference):
            return None
        try:
            if stop:
                self._interaction_session(message)
            result = await action(self.login_user, self.client_id, session, reference)
            if result is None:
                return None
            self._interaction_session(message)
        except Exception as exc:
            await self._send_interaction_error(runtime, exc, reference)
            return False, session

        self.chat_id = chat_id
        if is_init and not result["active"] and message.get("initial_open") is not True:
            return True, session
        execution_id = result["execution_id"]
        await self.send_response("processing", "info", {"agent_long_task": result["summary"]})
        if output := result["output"]:
            await self.send_response(
                WorkflowEventType.OutputMsg.value, "over",
                {**output["message"], "agent_long_task_execution_id": execution_id},
                message_id=output["message_id"],
            )
        if not result["active"]:
            await self.send_response("processing", "close", {"agent_long_task_execution_id": execution_id})
        return False, session

    async def check_status(self, message: dict, is_init: bool = False) -> (bool, str):
        """
        bool: Indicates if re-execution is requiredworkflow
        """
        # chat ws connection first handle
        workflow_id = message.get("flow_id", self.client_id)
        chat_id = message.get("chat_id", "")
        runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
        if result := await self._handle_long_task_resume(message, is_init=is_init):
            return result
        workflow = None
        if getattr(runtime, "interaction_status", None) is not None and getattr(self, "_connection_chat_id", None):
            connection_chat = self._connection_chat_id
            session_id = f"{connection_chat}_async_task_id"
            workflow = RedisCallback(session_id, self.client_id, connection_chat, self.user_id)
            if await self._check_agent_interaction(message, runtime, workflow, is_init):
                return False, session_id
            if (chat_id, workflow_id) != (connection_chat, self.client_id):
                workflow = None
        self.chat_id = chat_id
        if self.chat_id and self.memory_register is not None:
            await self._register_memory_session()
        check_long = getattr(runtime, "long_status", None) is not None and self.chat_id and not is_init
        explicit_reference = check_long and "execution_id" in message
        requested_reference = message.get("execution_id")
        if explicit_reference and not _valid_agent_execution_id(requested_reference):
            raise PlatformAgentPermissionError()
        if self.chat_id and self.session_subject is not None:
            session = await ChatSessionService.get_subject_session_if_exists(
                self.chat_id,
                self.session_subject,
            )
            if session is not None and session.flow_id != workflow_id:
                from bisheng.common.errcode.http_error import NotFoundError

                raise NotFoundError.http_exception()
            if session is None and explicit_reference:
                raise PlatformAgentPermissionError()
            if session is None:
                workflow_db = FlowDao.get_flow_by_id(workflow_id)
                await ChatSessionService.create_subject_session(
                    MessageSession(
                        chat_id=self.chat_id,
                        flow_id=workflow_id,
                        flow_name=workflow_db.name,
                        flow_type=workflow_db.flow_type,
                        user_id=self.user_id,
                    ),
                    self.session_subject,
                )
        unique_id = generate_uuid()
        if self.chat_id:
            unique_id = f"{self.chat_id}_async_task_id"
        logger.debug(f"init workflow with unique_id: {unique_id}, workflow_id: {workflow_id}, chat_id: {self.chat_id}")
        workflow = workflow or RedisCallback(unique_id, workflow_id, self.chat_id, self.user_id)
        summary = None
        if explicit_reference:
            summary = await runtime.long_status(self.login_user, workflow_id, unique_id, requested_reference)
            current_reference = workflow.get_platform_agent_reference()
            if requested_reference != current_reference or requested_reference != getattr(
                workflow, "platform_agent_execution_id", current_reference
            ):
                if summary:
                    await self.send_response("processing", "info", {"agent_long_task": summary})
                return False, unique_id

        if self.chat_id:
            await self.init_history()
        self.workflow = workflow
        if not await self.ensure_workflow_available(workflow_id):
            return False, unique_id
        if (
            is_init
            and getattr(runtime, "stop_long", None) is not None
            and self._stopped_long_reference
            and self._stopped_long_reference == workflow.get_platform_agent_reference()
        ):
            self.workflow = None
            return True, unique_id

        if check_long and not explicit_reference:
            reference = workflow.get_platform_agent_reference()
            if reference:
                summary = await runtime.long_status(self.login_user, workflow_id, unique_id, reference)
        if summary:
            await self.send_response("processing", "info", {"agent_long_task": summary})
        if explicit_reference and requested_reference != workflow.get_platform_agent_reference():
            return False, unique_id

        status_info = self.workflow.get_workflow_status()
        if not status_info:
            # Indicates that the last run was completed
            self.workflow = None
            if summary:
                await self.send_response("processing", "close", "")
                return False, unique_id
            if self.latest_history and not is_init:
                # Let the front-end terminate the last run
                await self.send_response("processing", "close", WORKFLOW_STATUS_CHECK_FINISHED)
            return True, unique_id

        terminal_statuses = [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]
        if status_info["status"] in terminal_statuses:
            close_message = (
                WORKFLOW_STATUS_CHECK_FINISHED if self.latest_history and not is_init and not summary else ""
            )
            workflow_over = await self.workflow_run(close_message=close_message)
            return workflow_over, unique_id

        # Indicates that the session is still running
        if status_info["status"] == WorkflowStatus.INPUT.value and self.latest_history:
            # If it is a state waiting for user input, you need to resend the last input message to the front-end
            if self.latest_history.category in [
                WorkflowEventType.UserInput.value,
                WorkflowEventType.OutputWithInput.value,
                WorkflowEventType.OutputWithChoose.value,
            ]:
                send_message = self.latest_history.model_dump()
                send_message["message"] = json.loads(send_message["message"])
                send_message["message_id"] = send_message.pop("id")
                await self.send_json(send_message)

        await self.send_response("processing", "begin", "")
        logger.debug("init workflow over, continue run workflow")
        await self.workflow_run()
        return False, unique_id

    async def _register_memory_session(self) -> None:
        """F132: call the callback injected by the logged-in endpoint (never set for guest/open)."""
        try:
            result = self.memory_register(self.chat_id)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("memory session registration failed chat_id={}", self.chat_id)

    async def get_execute_worker(self) -> str | None:
        if not self.hash_key:
            self.hash_key = self.chat_id if self.chat_id else generate_uuid()
        return await workflow_stateful_worker.find_task_node(self.hash_key)

    async def init_workflow(self, message: dict):
        if self.workflow is not None:
            return
        try:
            workflow_data = message.get("data")
            workflow_id = message.get("flow_id", self.client_id)
            flag, unique_id = await self.check_status(message, is_init=True)
            # Description workflow In operation or offline
            if not flag:
                return
            # Start a new workflow
            self.workflow = RedisCallback(
                unique_id,
                workflow_id,
                self.chat_id,
                self.user_id,
                tenant_id=getattr(self.login_user, "tenant_id", None),
            )
            reference = None
            options = self._causal_headers()
            runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
            prepared = None
            if runtime is not None:
                prepared = await runtime.prepare(
                    self.login_user,
                    workflow_id,
                    unique_id,
                    workflow_data,
                    published=bool(self.chat_id),
                    execution_snapshot=self.execution_snapshot,
                )
            if prepared is not None:
                workflow_data, reference = prepared
                self.workflow.set_platform_agent_reference(reference["execution_id"])
                options = {
                    **options,
                    "headers": {**options.get("headers", {}), "tenant_id": self.login_user.tenant_id},
                    "kwargs": {"platform_agent_execution": reference},
                }
            else:
                getattr(self.workflow, "clear_platform_agent_reference", lambda: None)()
            knowledge_runtime = getattr(self, "kwargs", {}).get("platform_knowledge_runtime")
            knowledge_prepared = None
            if knowledge_runtime is not None:
                knowledge_prepared = await knowledge_runtime.prepare(
                    self.login_user,
                    workflow_id,
                    unique_id,
                    workflow_data,
                    published=bool(self.chat_id),
                    execution_snapshot=self.execution_snapshot,
                )
            if knowledge_prepared:
                workflow_data, knowledge_reference = knowledge_prepared
                self.workflow.bind_platform_knowledge_execution(knowledge_reference["execution_id"])
                options = {
                    **options,
                    "headers": {**options.get("headers", {}), "tenant_id": self.login_user.tenant_id},
                    "kwargs": {**options.get("kwargs", {}), "platform_knowledge_execution": knowledge_reference},
                }
            else:
                getattr(self.workflow, "clear_platform_knowledge_reference", lambda: None)()
            await self.workflow.async_set_workflow_data(workflow_data)
            await self.workflow.async_set_workflow_status(WorkflowStatus.WAITING.value)
            # Start asynchronous task

            execute_workflow.apply_async(
                [
                    unique_id,
                    workflow_id,
                    self.chat_id,
                    self.user_id,
                    "api" if self.execution_snapshot is not None else "platform",
                    dict(self.execution_snapshot) if self.execution_snapshot is not None else None,
                ],
                queue=await self.get_execute_worker(),
                **options,
            )
            await self.send_response("processing", "begin", "")
            if reference and getattr(runtime, "is_interaction_graph", lambda _: False)(workflow_data):
                await self._run_interaction_stream(runtime, self.workflow, reference["execution_id"])
            elif reference and await self._handle_long_task_resume({"execution_id": reference["execution_id"]}):
                self.workflow = None
            else:
                await self.workflow_run()
        except Exception as e:
            if locals().get("knowledge_reference"):
                knowledge_runtime.abort(self.login_user, workflow_id, unique_id, knowledge_reference["execution_id"])
            if locals().get("knowledge_runtime") and not locals().get("reference"):
                e = knowledge_runtime.public_error(e)
                logger.warning("昆联检索运行受理失败")
            elif locals().get("reference"):
                runtime.abort(reference["execution_id"])
                e = runtime.public_error(e)
                logger.opt(exception=(type(e), e, None)).error("init platform Agent workflow failed")
            else:
                logger.exception("init_workflow_error")
            self.workflow = None
            await self.send_response("error", "over", {"status_code": 500, "message": str(e)})
            return

    async def workflow_run(self, close_message: str | dict = "", *, authorize_event=None):
        async with self.run_lock:
            return await self._workflow_run(close_message=close_message, authorize_event=authorize_event)

    async def _workflow_run(self, close_message: str | dict = "", *, authorize_event=None):
        logger.debug("start workflow run")
        workflow = self.workflow
        if not workflow:
            logger.warning("workflow is over by other task")
            return True

        # Needs to constantly evolve fromredisGet inworkflowReturned Message
        async for event in workflow.get_response_until_break():
            if self.workflow is not workflow:
                return True
            payload = event.get("message") if isinstance(event, dict) else getattr(event, "message", None)
            if isinstance(payload, dict) and "agent_long_task_execution_id" in payload:
                # 持久化长任务输出仅由会话授权入口回读。
                continue
            if authorize_event is not None:
                allowed = await authorize_event(event)
                if allowed is None:
                    if self.workflow is workflow:
                        self.workflow = None
                    return True
                if self.workflow is not workflow:
                    return True
                if not allowed:
                    continue
            await self.send_json(event)

        if self.workflow is not workflow:
            return True
        status_info = await workflow.async_get_workflow_status()
        if self.workflow is not workflow:
            return True
        if not status_info or status_info["status"] in [WorkflowStatus.FAILED.value, WorkflowStatus.SUCCESS.value]:
            logger.debug(f"workflow is {status_info}, clear workflow object")
            await workflow.async_clear_workflow_status()
            if self.workflow is workflow:
                self.workflow = None
                await self.send_response("processing", "close", close_message)
            return True

        # Description runs to the state to be entered
        elif status_info["status"] != WorkflowStatus.INPUT.value:
            logger.warning(f"workflow status is unknown: {status_info}")
        return False

    async def ensure_workflow_available(self, workflow_id: str) -> bool:
        # Builder preview uses an empty chat ID and may execute draft workflows.
        if not self.chat_id:
            return True
        workflow_db = FlowDao.get_flow_by_id(workflow_id)
        if workflow_db and workflow_db.status == FlowStatus.ONLINE.value:
            return True

        if self.workflow:
            await self.workflow.async_set_workflow_stop()
            # The worker consumes the stop marker before terminal-state cleanup.
            self.workflow = None
        await WorkflowOfflineError().websocket_close_message(websocket=self.websocket, close_ws=False)
        await self.send_response("processing", "close", "")
        return False

    async def handle_user_input(self, data: dict):
        if not await self.ensure_workflow_available(self.client_id):
            return
        logger.info(f"get user input: {data}")
        if not self.workflow:
            await self.send_response("processing", "close", "")
            return
        status_info = await self.workflow.async_get_workflow_status()
        if not status_info:
            self.workflow = None
            await self.send_response("processing", "close", "")
            return
        if status_info["status"] != WorkflowStatus.INPUT.value:
            logger.warning(f"workflow is not input status: {status_info}")
        else:
            user_input = {}
            message_id = None
            new_message = None
            new_files = None
            # Currently one input node is supported
            for node_id, node_info in data.items():
                user_input[node_id] = node_info["data"]
                message_id = node_info.get("message_id")
                new_message = node_info.get("message")
                # Attachments as data — the node reads them from
                # ``dialog_files_content``, this is what the message keeps.
                new_files = node_info.get("files")
                break
            options = self._causal_headers()
            knowledge_id = getattr(self.workflow, "platform_knowledge_execution_id", None)
            if isinstance(knowledge_id, str) and self.workflow.get_platform_knowledge_reference() != knowledge_id:
                from bisheng.common.errcode.flow import PlatformKnowledgeExecutionError

                raise PlatformKnowledgeExecutionError()
            execution_id = getattr(self.workflow, "get_platform_agent_reference", lambda: None)()
            runtime = getattr(self, "kwargs", {}).get("platform_agent_runtime")
            if execution_id:
                if runtime is None:
                    from bisheng.common.errcode.flow import PlatformAgentExecutionError

                    raise PlatformAgentExecutionError()
                reference = await runtime.resume(
                    self.login_user, self.client_id, execution_id, published=bool(self.chat_id)
                )
                options = {
                    **options,
                    "headers": {**options.get("headers", {}), "tenant_id": self.login_user.tenant_id},
                    "kwargs": {"platform_agent_execution": reference},
                }
            knowledge_runtime = getattr(self, "kwargs", {}).get("platform_knowledge_runtime")
            if isinstance(knowledge_id, str):
                if knowledge_runtime is None:
                    raise RuntimeError("knowledge execution context is missing")
                try:
                    knowledge_reference = await knowledge_runtime.resume(
                        self.login_user,
                        self.workflow.workflow_id,
                        self.workflow.unique_id,
                        knowledge_id,
                    )
                except Exception:
                    if execution_id:
                        runtime.abort(execution_id)
                    raise
                options = {
                    **options,
                    "headers": {**options.get("headers", {}), "tenant_id": self.login_user.tenant_id},
                    "kwargs": {**options.get("kwargs", {}), "platform_knowledge_execution": knowledge_reference},
                }
            try:
                await self.workflow.async_set_user_input(
                    user_input, message_id=message_id, message_content=new_message, files=new_files
                )
                await self.workflow.async_set_workflow_status(WorkflowStatus.INPUT_OVER.value)
                continue_workflow.apply_async(
                    [
                        self.workflow.unique_id,
                        self.workflow.workflow_id,
                        self.workflow.chat_id,
                        self.user_id,
                        "api" if self.execution_snapshot is not None else "platform",
                        dict(self.execution_snapshot) if self.execution_snapshot is not None else None,
                    ],
                    queue=await self.get_execute_worker(),
                    **options,
                )
            except Exception as error:
                if isinstance(knowledge_id, str):
                    knowledge_runtime.abort(
                        self.login_user, self.workflow.workflow_id, self.workflow.unique_id, knowledge_id
                    )
                if execution_id:
                    runtime.abort(execution_id)
                    raise runtime.public_error(error) from None
                raise
            await self.workflow_run()
        # await self.workflow_run()
