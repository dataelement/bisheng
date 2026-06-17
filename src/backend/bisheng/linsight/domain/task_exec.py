import asyncio
import os
import shutil
import traceback
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import Token
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.common.services.config_service import settings
from bisheng.core.cache.utils import CACHE_DIR, create_cache_folder_async
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.external.http_client.http_client_manager import get_http_client
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.linsight.domain import utils as linsight_execute_utils
from bisheng.linsight.domain.models.linsight_execute_task import (
    ExecuteTaskStatusEnum,
    ExecuteTaskTypeEnum,
    LinsightExecuteTask,
    LinsightExecuteTaskDao,
)
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersion,
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.services.agent_factory import _resolve_model, create_linsight_agent
from bisheng.linsight.domain.services.state_message_manager import (
    LinsightStateMessageManager,
    MessageData,
    MessageEventType,
)
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.tool.domain.services.tool import ToolServices
from bisheng_langchain.linsight.const import TaskStatus
from bisheng_langchain.linsight.event import BaseEvent, ExecStep, GenerateSubTask, NeedUserInput, TaskEnd, TaskStart


class TaskExecutionError(Exception):
    """Task Execution Exception"""

    pass


class UserTerminationError(Exception):
    """User proactively terminates exceptions"""

    pass


# Task already in progress Exception
class TaskAlreadyInProgressError(Exception):
    """Task already in progress Exception"""

    pass


class LinsightWorkflowTask:
    """Workflow Task Executor - Responsible for managing the entire mission lifecycle"""

    USER_TERMINATION_CHECK_INTERVAL = 2

    def __init__(self):
        self._state_manager: LinsightStateMessageManager | None = None
        self._is_terminated = False
        self._termination_task: asyncio.Task | None = None
        self._final_result: TaskEnd | None = None
        # Fallback answer captured from the agent's final message when no
        # TaskEnd is emitted (direct-answer/greeting short-circuit, F035).
        self._last_assistant_text: str | None = None
        # Set when an ask_user interrupt parked the task (WAITING_FOR_USER_INPUT).
        # astream then halts with no TaskEnd, but this is NOT a direct-answer
        # completion — the task must stay parked, not push a FINAL_RESULT.
        self._waiting_for_input: bool = False
        self.file_dir: str | None = None
        self.session_version_id: str | None = None
        self.llm: BaseChatModel | None = None  # For storageLLMInstances

    # ==================== Resource Management ====================

    @asynccontextmanager
    async def _managed_execution(self):
        """Context manager for managing execution resources"""

        self._state_manager = LinsightStateMessageManager(self.session_version_id)
        session_model = await self._get_session_model(self.session_version_id)

        # Check session status
        if await self._is_session_in_progress(session_model):
            raise TaskAlreadyInProgressError("Task already in progress")

        try:
            # Start Termination Monitoring
            await self._start_termination_monitor(session_model)

            # Initialization file directory
            self.file_dir = await self._init_file_directory(session_model)

            yield session_model

        finally:
            await self._cleanup_resources()

    async def _cleanup_resources(self):
        """Clean up resources"""
        try:
            # Stop Terminating Monitoring
            await self._stop_termination_monitor()

            # Clean File Directory
            if self.file_dir and os.path.exists(self.file_dir):
                shutil.rmtree(self.file_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Resource cleanup failed: {e}")

    # ==================== Core Execution Logic ====================

    async def async_run(self, session_version_id: str) -> None:
        """Asynchronous Task Execution Entry"""

        self.session_version_id = session_version_id
        trace_id_var.set(self.session_version_id)
        logger.info(f"Start the task: session_version_id={self.session_version_id}")
        tenant_context_token: Token | None = None
        try:
            tenant_context_token = await self._restore_tenant_context(session_version_id)

            async with self._managed_execution() as session_model:
                await self._execute_workflow(session_model)

        except UserTerminationError:
            logger.info(f"Task was actively terminated by the user: session_version_id={self.session_version_id}")
        except TaskAlreadyInProgressError:
            logger.warning(f"Task already in progress: session_version_id={self.session_version_id}")
        except TaskExecutionError as e:
            logger.error(
                f"Task execution failed: {e} : session_version_id={self.session_version_id}",
                exc_info=True,
            )
            await self._handle_execution_error(e)
        except Exception as e:
            logger.error(f"Unknown error: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)
        finally:
            if tenant_context_token is not None:
                current_tenant_id.reset(tenant_context_token)

    async def _restore_tenant_context(self, session_version_id: str) -> Token:
        """Restore tenant ContextVar for standalone Linsight worker tasks."""
        try:
            with bypass_tenant_filter():
                session_model = await LinsightSessionVersionDao.get_by_id(session_version_id)
        except Exception as e:
            raise TaskExecutionError(f"Failed to restore tenant context: {e}") from e

        if not session_model:
            raise TaskExecutionError(f"Session version not found: {session_version_id}")

        tenant_id = session_model.tenant_id
        if tenant_id is None:
            raise TaskExecutionError(f"Session version {session_version_id} is missing tenant_id")

        return set_current_tenant_id(int(tenant_id))

    # ==================== Resume (park-and-release, Track B) ====================

    async def async_resume(self, session_version_id: str, user_input=None) -> None:
        """Resume a parked (WAITING_FOR_USER_INPUT) task after the user answered.

        park-and-release entry point (design §4.4 / §4.6): a parked task holds no
        worker slot; once the user answers, /workbench/user-input lpush'es a
        resume payload to the queue head and an idle worker picks it up and calls
        this method. We rebuild the agent on the SAME LangGraph ``thread_id =
        session_version_id`` (so the persisted interrupt checkpoint is found) and
        drive ``Command(resume=user_input)``. thread_id reuse + a Redis-backed
        checkpointer let resume run in any worker process at any time.
        """
        self.session_version_id = session_version_id
        trace_id_var.set(self.session_version_id)
        logger.info(f"Resume the task: session_version_id={self.session_version_id}")
        tenant_context_token: Token | None = None
        try:
            tenant_context_token = await self._restore_tenant_context(session_version_id)
            async with self._managed_resume() as session_model:
                await self._resume_workflow(session_model, user_input)
        except UserTerminationError:
            logger.info(f"Resumed task terminated by user: session_version_id={self.session_version_id}")
        except TaskAlreadyInProgressError:
            logger.warning(f"Resumed task already in progress: session_version_id={self.session_version_id}")
        except TaskExecutionError as e:
            logger.error(f"Resume task execution failed: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)
        except Exception as e:
            logger.error(f"Unknown error on resume: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)
        finally:
            if tenant_context_token is not None:
                current_tenant_id.reset(tenant_context_token)

    @asynccontextmanager
    async def _managed_resume(self):
        """Like ``_managed_execution`` but for the resume path.

        A parked session is legitimately IN_PROGRESS, so the
        ``_is_session_in_progress`` guard (which rejects re-entry on the fresh
        path) must NOT apply here — resume is precisely re-entry into the same
        session. Everything else (termination monitor, file dir, cleanup) is the
        same as the fresh path.
        """
        self._state_manager = LinsightStateMessageManager(self.session_version_id)
        session_model = await self._get_session_model(self.session_version_id)
        try:
            await self._start_termination_monitor(session_model)
            self.file_dir = await self._init_file_directory(session_model)
            yield session_model
        finally:
            await self._cleanup_resources()

    async def _resume_workflow(self, session_model: LinsightSessionVersion, user_input) -> None:
        """Rebuild the agent on the same thread (Redis checkpointer) and drive resume."""
        from bisheng.linsight.domain.services.checkpointer import make_checkpointer

        self.llm = await self._get_llm(session_model)
        tools = await self._generate_tools(session_model)
        try:
            # Rebuild on the SAME thread_id with a durable checkpointer so the
            # parked interrupt checkpoint is located (design §4.4).
            agent = await self._create_agent(session_model, tools, checkpointer=make_checkpointer())
            self._check_termination()
            await self._drive_resume(agent, session_model, user_input)
            # Finalize the resumed turn. Without this the resumed task never
            # pushes FINAL_RESULT (the frontend keeps spinning on the answered
            # ask_user) — the fresh/continue paths finalize, the resume path
            # historically did not. _handle_task_completion no-ops if the agent
            # parked AGAIN (another ask_user this round) via _waiting_for_input.
            await self._handle_task_completion(session_model)
        finally:
            for one in tools:
                if one.name == "bisheng_code_interpreter":
                    one.close()
                    break

    async def _drive_resume(self, agent, session_model: LinsightSessionVersion, user_input) -> None:
        """Resume driver — reuses the Track-A astream + StreamEventMapper pipeline.

        Feeds ``Command(resume=user_input)`` into the same LangGraph thread
        (``thread_id = session_version_id``) so resumed chunks are normalised and
        rendered identically to the fresh path (design §4.4). The durable
        checkpointer is already bound to the agent at construction; thread_id
        reuse locates the persisted interrupt checkpoint.
        """
        from langgraph.types import Command

        linsight_conf = settings.get_linsight_conf()
        mapper = StreamEventMapper(svid=session_model.id)
        config = {
            "configurable": {"thread_id": session_model.id},
            "recursion_limit": getattr(linsight_conf, "max_steps", 200),
        }
        async for chunk in agent.astream(
            Command(resume=user_input),
            config=config,
            stream_mode=["updates", "messages", "values"],
            subgraphs=True,
        ):
            mode, raw, namespace = self._unpack_stream_chunk(chunk)
            if mode == "values" and not namespace and isinstance(raw, dict):
                text = self._extract_last_message_text(raw.get("messages"))
                if text:
                    self._last_assistant_text = text
            for event in mapper.normalize(mode, raw, namespace=namespace):
                await self._handle_event(agent, event, session_model)

    # ==================== Continue (multi-turn conversation) ====================

    async def async_continue(self, session_version_id: str, question: str) -> None:
        """Continue a finished conversation with a new user turn (F035 multi-turn).

        Unlike ``async_resume`` (which answers a parked ask_user interrupt via
        ``Command(resume=...)``), this feeds a brand-new ``HumanMessage`` into the
        SAME LangGraph thread (``thread_id = session_version_id``). Because the
        Redis checkpointer persists the full message history, the agent keeps the
        prior context — the follow-up is interpreted against everything said
        before, not in isolation. One task-mode conversation therefore stays a
        single session_version + single thread across every round (the legacy
        "new version per submit" model is bypassed for follow-ups).
        """
        self.session_version_id = session_version_id
        trace_id_var.set(self.session_version_id)
        logger.info(f"Continue the conversation: session_version_id={self.session_version_id}")
        tenant_context_token: Token | None = None
        try:
            tenant_context_token = await self._restore_tenant_context(session_version_id)
            async with self._managed_resume() as session_model:
                await self._continue_workflow(session_model, question)
        except UserTerminationError:
            logger.info(f"Continued task terminated by user: session_version_id={self.session_version_id}")
        except TaskExecutionError as e:
            logger.error(f"Continue task execution failed: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)
        except Exception as e:
            logger.error(f"Unknown error on continue: session_version_id={self.session_version_id}, error={e}")
            await self._handle_execution_error(e)
        finally:
            if tenant_context_token is not None:
                current_tenant_id.reset(tenant_context_token)

    async def _continue_workflow(self, session_model: LinsightSessionVersion, question: str) -> None:
        """Rebuild the agent on the same thread and drive a new user turn."""
        from bisheng.linsight.domain.services.checkpointer import make_checkpointer

        # A continued round starts from COMPLETED; flip back to IN_PROGRESS so the
        # frontend leaves the "done" state and re-opens the WS event stream.
        await self._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

        self.llm = await self._get_llm(session_model)
        tools = await self._generate_tools(session_model)
        try:
            allowed_knowledge_ids = await self._resolve_allowed_knowledge_ids(session_model)
            linsight_tools = await ToolServices.init_linsight_tools(
                root_path=self.file_dir, allowed_knowledge_ids=allowed_knowledge_ids
            )
            tools.extend(linsight_tools)
            agent = await self._create_agent(session_model, tools, checkpointer=make_checkpointer())
            self._check_termination()
            await self._drive_continue(agent, session_model, question)
            await self._handle_task_completion(session_model)
        finally:
            for one in tools:
                if one.name == "bisheng_code_interpreter":
                    one.close()
                    break

    async def _drive_continue(self, agent, session_model: LinsightSessionVersion, question: str) -> None:
        """Continue driver — feeds a new HumanMessage into the same thread.

        Shares the astream + StreamEventMapper pipeline with the fresh/resume
        paths so continued chunks render identically. ``thread_id`` reuse +
        durable checkpointer mean the new turn appends to the persisted message
        history and the agent answers with full prior context.
        """
        linsight_conf = settings.get_linsight_conf()
        mapper = StreamEventMapper(svid=session_model.id)
        config = {
            "configurable": {"thread_id": session_model.id},
            "recursion_limit": getattr(linsight_conf, "max_steps", 200),
        }
        agent_input = {"messages": [{"role": "user", "content": question}]}
        async for chunk in agent.astream(
            agent_input,
            config=config,
            stream_mode=["updates", "messages", "values"],
            subgraphs=True,
        ):
            mode, raw, namespace = self._unpack_stream_chunk(chunk)
            if mode == "values" and not namespace and isinstance(raw, dict):
                text = self._extract_last_message_text(raw.get("messages"))
                if text:
                    self._last_assistant_text = text
            for event in mapper.normalize(mode, raw, namespace=namespace):
                await self._handle_event(agent, event, session_model)

    async def _execute_workflow(self, session_model: LinsightSessionVersion):
        """Execute the core logic of the workflow"""

        # Update session status to in progress
        await self._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

        # F035 Track J: write a placeholder task turn at start so a refresh
        # mid-execution (incl. parked HITL) still sees the in-flight turn in the
        # unified conversation stream; completion upserts the same row with the
        # final answer. The live state (running / waiting_for_user_input) is read
        # by SV from the linsight detail endpoints on reload.
        await linsight_execute_utils.persist_task_turn_message(session_model)

        # Initialization Execution Component
        self.llm = await self._get_llm(session_model)
        tools = await self._generate_tools(session_model)
        try:
            # Build Tool List. The knowledge tool is gated by the user's
            # accessible-KB whitelist (C4) so the model cannot search a KB/file
            # it has no access to.
            allowed_knowledge_ids = await self._resolve_allowed_knowledge_ids(session_model)
            linsight_tools = await ToolServices.init_linsight_tools(
                root_path=self.file_dir, allowed_knowledge_ids=allowed_knowledge_ids
            )
            tools.extend(linsight_tools)
            # Create agent (deepagents CompiledStateGraph, F035 §2.1).
            # Durable Redis checkpointer (same as the resume path) so a HITL
            # interrupt parked here is locatable on resume — which rebuilds the
            # agent on the same thread_id in a possibly different worker process.
            from bisheng.linsight.domain.services.checkpointer import make_checkpointer

            agent = await self._create_agent(session_model, tools, checkpointer=make_checkpointer())

            # Check if terminated during initialization
            self._check_termination()

            # F035: the legacy `agent.generate_task` precall is removed. With the
            # deepagents kernel the task清单 is produced by the planner during
            # `astream` (write_todos) and emitted as GenerateSubTask by the
            # StreamEventMapper -> _handle_generate_subtask -> _save_task_info
            # (design §3.3 row 2). Tasks are no longer pre-generated/saved here.
            success = await self._execute_agent_tasks(agent, session_model)
        finally:
            # Clean the sandbox of the code interpreter
            for one in tools:
                if one.name == "bisheng_code_interpreter":
                    one.close()
                    break

        if success:
            await self._handle_task_completion(session_model)
        else:
            await self._handle_user_termination(session_model)
            raise UserTerminationError("Task terminated by user")

    # ==================== Session and State Management ====================

    async def _get_session_model(self, session_version_id: str) -> LinsightSessionVersion:
        """Get session model"""
        try:
            return await LinsightSessionVersionDao.get_by_id(session_version_id)
        except Exception as e:
            raise TaskExecutionError(f"Failed to get session model: {e}")

    async def _is_session_in_progress(self, session_model: LinsightSessionVersion) -> bool:
        """Check if the session is already in progress"""
        if session_model.status == SessionVersionStatusEnum.IN_PROGRESS:
            logger.info(f"Sessions {session_model.id} Already in progress")
            return True
        return False

    async def _update_session_status(self, session_model: LinsightSessionVersion, status: SessionVersionStatusEnum):
        """Update session status"""
        session_model.status = status
        await self._state_manager.set_session_version_info(session_model)

    # ==================== Component Initialization ====================

    async def _get_llm(self, session_model: LinsightSessionVersion) -> BaseChatModel:
        """Resolve the per-task execution LLM (tool init / helper calls).

        Reuses ``agent_factory._resolve_model`` so this helper LLM and the agent
        itself share one model-resolution path: the per-task ``model`` chosen at
        submit time (``session_model.model``), falling back to the tenant
        ``linsight_default_model_id`` only when it is empty. Previously this
        ignored the per-task model and always pulled the tenant default, so a
        task with a valid frontend-selected model still failed when the tenant
        default was missing/deleted/offline. F022 INV-T18: tenant resolution +
        share fallback are threaded inside ``_resolve_model`` via
        ``session_model.tenant_id`` (admin-scope ContextVar is unset in the
        Worker subprocess).
        """
        try:
            return await _resolve_model(session_model, getattr(session_model, "model", None))
        except Exception as e:
            # Keep the generic user-facing message, but chain + log the real
            # cause so the original stack trace surfaces (project error-handling
            # rule: never launder exceptions into a flat message).
            logger.exception(f"Linsight LLM resolution failed: session_version_id={self.session_version_id}")
            raise TaskExecutionError(
                "The task has been terminated, please contact the administrator to check the status of the Ideas task execution model"
            ) from e

    @create_cache_folder_async
    async def _init_file_directory(self, session_model: LinsightSessionVersion) -> str:
        """Initialization file directory"""
        file_dir = os.path.join(CACHE_DIR, "linsight", session_model.id[:8])
        file_dir = os.path.normpath(file_dir)
        os.makedirs(file_dir, exist_ok=True)

        if not session_model.files:
            return file_dir

        # Concurrent downloads
        download_tasks = [self._download_file(file_info, file_dir) for file_info in session_model.files]

        results = await asyncio.gather(*download_tasks, return_exceptions=True)

        # Record Download Failed Files
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                file_name = os.path.basename(session_model.files[i]["markdown_file_path"])
                logger.error(f"This content failed to load {file_name}: {result}")

        return file_dir

    async def _download_file(self, file_info: dict, target_dir: str) -> str:
        """Download individual files"""
        object_name = file_info["markdown_file_path"]
        file_name = file_info.get("markdown_filename", os.path.basename(object_name))
        file_path = os.path.join(target_dir, file_name)
        minio_client = await get_minio_storage()
        try:
            file_url = await minio_client.get_share_link(object_name, clear_host=False)
            http_client = await get_http_client()

            with open(file_path, "wb") as f:
                async for chunk in http_client.stream(method="GET", url=str(file_url)):
                    f.write(chunk)

            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise ValueError(f"File download failed or empty: {object_name}")

            return file_path

        except Exception as e:
            logger.error(f"Download failed {object_name}: {e}")
            raise

    async def _generate_tools(self, session_model: LinsightSessionVersion) -> list:
        """Build Tool List"""
        if not session_model.tools:
            return []

        return await LinsightWorkbenchImpl.init_linsight_config_tools(
            session_version=session_model, llm=self.llm, need_upload=True, file_dir=self.file_dir
        )

    async def _create_agent(self, session_model: LinsightSessionVersion, tools: list, checkpointer=None):
        """Create the deepagents-backed agent (F035 §2.1).

        Returns a LangGraph ``CompiledStateGraph`` driven by ``agent.astream``.
        Model selection follows the per-task ``model`` persisted on the session
        (design §2.2.1); tenant resolution + share fallback live inside the
        factory's call to ``LLMService.get_bisheng_linsight_llm``. We inject the
        REAL WorkspaceBackend (MinIO truth + write-through cache, design §9) so
        the agent's write_file/read_file tools actually persist — the factory's
        FakeWorkspaceBackend default is a test stub with no ``awrite``. The
        resume path passes a Redis-backed ``checkpointer`` so the parked
        interrupt checkpoint (thread_id = session_version_id) is located.
        """
        from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

        minio = await get_minio_storage()
        backend = WorkspaceBackend(svid=session_model.id, minio=minio, file_dir=self.file_dir)
        return await create_linsight_agent(
            session_model=session_model,
            tools=tools,
            model_id=getattr(session_model, "model", None),
            file_dir=self.file_dir,
            svid=session_model.id,
            checkpointer=checkpointer,
            backend=backend,
        )

    # ==================== Mission Execution ====================

    async def _save_task_info(self, session_model: LinsightSessionVersion, task_info: list[dict]):
        """Save Task Information.

        Idempotent on replay: on a HITL resume LangGraph replays the graph from
        the persisted checkpoint, so ``write_todos`` (and thus this method) can
        fire again with the SAME task ids that were already persisted before the
        park. A plain batch INSERT then hits a duplicate-PK IntegrityError and
        kills the resume. So we only insert task ids that don't yet exist for this
        session_version, and reuse the persisted rows (which carry the latest
        status/result) for the ones that do — keeping the pushed task list whole.
        """
        try:
            tasks = []
            # step_idIt doesn't have to be regular.step_int, FROMagentGot ittask_infoThe order is the execution order
            sorted_data = task_info

            for index, task_info in enumerate(sorted_data):
                previous_task_id = sorted_data[index - 1]["id"] if index > 0 else None
                next_task_id = sorted_data[index + 1]["id"] if index < len(sorted_data) - 1 else None
                task = LinsightExecuteTask(
                    id=task_info["id"],
                    parent_task_id=task_info.get("parent_id"),
                    session_version_id=session_model.id,
                    previous_task_id=previous_task_id,
                    next_task_id=next_task_id,
                    task_type=ExecuteTaskTypeEnum.COMPOSITE
                    if task_info.get("node_loop")
                    else ExecuteTaskTypeEnum.SINGLE,
                    task_data=task_info,
                )
                tasks.append(task)

            # Skip rows already persisted for this SV (resume replay) — insert only
            # the new ones, but keep the full ordered list (persisted row preferred,
            # so its status/result survives) for the state push.
            existing = await LinsightExecuteTaskDao.get_by_session_version_id(session_model.id)
            existing_by_id = {t.id: t for t in (existing or [])}
            new_tasks = [t for t in tasks if t.id not in existing_by_id]
            if new_tasks:
                await LinsightExecuteTaskDao.batch_create_tasks(new_tasks)

            merged = [existing_by_id.get(t.id, t) for t in tasks]
            await self._state_manager.set_execution_tasks(merged)

            # Push Generate Task Message
            await self._state_manager.push_message(
                MessageData(
                    event_type=MessageEventType.TASK_GENERATE, data={"tasks": [task.model_dump() for task in merged]}
                )
            )

            logger.info(f"Set {len(merged)} execution tasks ({len(new_tasks)} newly inserted)")

        except Exception as e:
            logger.error(f"Failed to save task information: {e}")
            raise TaskExecutionError(f"Failed to save task information: {e}")

    async def _execute_agent_tasks(self, agent, session_model) -> bool:
        """Perform agent tasks - deepagents astream + StreamEventMapper (F035 §3.2).

        Replaces the legacy ``agent.ainvoke`` generator with the LangGraph
        ``agent.astream`` protocol. Each raw chunk is translated by the pure
        ``StreamEventMapper.normalize`` into 0..N ``BaseEvent`` instances, which
        the existing ``_handle_event`` dispatch table consumes unchanged. The
        mapper holds only translation bookkeeping (call_id merge, todo task_id
        diff, terminal dedup) — all Redis/MySQL side effects stay in
        ``_handle_event`` (design §3.2 / §3.4).
        """
        linsight_conf = settings.get_linsight_conf()
        mapper = StreamEventMapper(svid=session_model.id)

        async def agent_execution():
            """Agent performs a task via astream + mapper."""
            file_list = await LinsightWorkbenchImpl.prepare_file_list(session_model)
            # F035 Track J: rebuild prior conversation context (by chat_id) so a
            # fresh task turn answers with the whole conversation in view, not just
            # this turn's question (the per-session checkpointer can't see earlier
            # daily/task turns — design §3.2).
            history_summary = await linsight_execute_utils.build_prior_conversation_summary(session_model.session_id)
            # F035 unified-resource: deepagents flow skips the SOP step where the
            # knowledge list used to be injected, so resolve the user's KBs here
            # (coarse: all org/personal KBs of the enabled type) and feed their ids
            # to the agent — otherwise search_knowledge_base has no real id to use.
            knowledge_block = await self._resolve_knowledge_block(session_model)
            # First-message input: prior context + question + sop + file pointer block.
            task_input = self._build_agent_input(session_model, file_list, history_summary, knowledge_block)
            config = {
                "configurable": {"thread_id": self.session_version_id},
                # max_steps -> recursion_limit (design §2.5)
                "recursion_limit": getattr(linsight_conf, "max_steps", 200),
            }
            # subgraphs=True so subagent (子图) events冒泡父流 with a namespace
            # prefix the mapper uses to归并 nested step cards (design §3.1/§3.7).
            async for chunk in agent.astream(
                task_input,
                config=config,
                stream_mode=["updates", "messages", "values"],
                subgraphs=True,
            ):
                mode, raw, namespace = self._unpack_stream_chunk(chunk)
                # Capture the agent's latest top-level reply as a fallback
                # answer for the no-TaskEnd case (e.g. a greeting the planner
                # answers directly without spawning sub-tasks).
                if mode == "values" and not namespace and isinstance(raw, dict):
                    text = self._extract_last_message_text(raw.get("messages"))
                    if text:
                        self._last_assistant_text = text
                for event in mapper.normalize(mode, raw, namespace=namespace):
                    await self._handle_event(agent, event, session_model)
            return True

        async def termination_monitor():
            """End monitoring task"""
            while True:
                await asyncio.sleep(0.5)  # <g id="Bold">Qn,</g>0.5Seconds checked once
                self._check_termination()

        try:
            # Create two concurrent tasks
            # Preparing user-uploaded files
            agent_task = asyncio.create_task(agent_execution())
            monitor_task = asyncio.create_task(termination_monitor())

            # Waiting for any one task to be completed
            done, pending = await asyncio.wait([agent_task, monitor_task], return_when=asyncio.FIRST_COMPLETED)

            # Cancel Incomplete Task
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.debug("Successfully unsuspended task")
                    pass

            # Review completed task results
            for task in done:
                if task.exception():
                    if isinstance(task.exception(), UserTerminationError):
                        logger.info("Agent task terminated by user")
                        return False
                    else:
                        raise task.exception()
                else:
                    # If the agent task is completed normally
                    if task == agent_task:
                        logger.info("The agent task is completed normally")
                        return True

            return True

        except UserTerminationError:
            logger.info("Agent task terminated by user")
            return False
        except Exception as e:
            logger.error(f"task_exec_error {traceback.format_exc()}")
            raise TaskExecutionError(f"Agent task execution failed: {e}")

    @staticmethod
    def _build_agent_input(
        session_model: LinsightSessionVersion,
        file_list,
        history_summary: str | None = None,
        knowledge_block: str | None = None,
    ) -> dict:
        """Assemble the first-message input for the deepagents graph.

        LangGraph agents take ``{"messages": [...]}``. We seed the user turn with
        the prior conversation context (F035 Track J, by chat_id) + question + SOP
        guidance; the file pointer block (offload-first, design §9) and the
        available knowledge-base list (so ``search_knowledge_base`` has real ids)
        are appended when present. The deepagents kernel plans the todo清单 from
        this seed during astream.
        """
        parts: list[str] = []
        if history_summary:
            parts.append(history_summary)
        if session_model.question:
            parts.append(str(session_model.question))
        if session_model.sop:
            parts.append(f"\n# 执行规范(SOP)\n{session_model.sop}")
        if file_list:
            parts.append(f"\n# 可用文件\n{file_list}")
        if knowledge_block:
            parts.append(
                f"\n# 可用知识库(用 search_knowledge_base 检索,knowledge_id 用下方括号内的 id)\n{knowledge_block}"
            )
        content = "\n".join(parts) if parts else (session_model.question or "")
        return {"messages": [{"role": "user", "content": content}]}

    async def _resolve_user_knowledge_bases(self, session_model: LinsightSessionVersion) -> list:
        """Resolve the user's accessible knowledge bases (coarse, permission-safe).

        org_knowledge_enabled -> all NORMAL KBs; personal -> all PRIVATE KBs,
        each capped by the linsight ``max_knowledge_num``. ``aget_user_knowledge``
        already filters to KBs the user can see, so this list IS the permission
        whitelist — both the prompt advertisement (``_resolve_knowledge_block``)
        and the tool gate (``_resolve_allowed_knowledge_ids``) derive from it, so
        what the model is told it may search and what it is actually allowed to
        search stay in lockstep.
        """
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, KnowledgeTypeEnum

        linsight_conf = settings.get_linsight_conf()
        cap = getattr(linsight_conf, "max_knowledge_num", 0) or 0
        if cap <= 0:
            return []
        kbs: list = []
        if session_model.org_knowledge_enabled:
            kbs += await KnowledgeDao.aget_user_knowledge(
                session_model.user_id, None, KnowledgeTypeEnum.NORMAL, limit=cap
            )
        if session_model.personal_knowledge_enabled:
            kbs += await KnowledgeDao.aget_user_knowledge(
                session_model.user_id, None, KnowledgeTypeEnum.PRIVATE, limit=cap
            )
        return kbs

    async def _resolve_knowledge_block(self, session_model: LinsightSessionVersion) -> str | None:
        """Render the user's accessible KBs into a prompt block advertising each
        KB's id, so the agent's search_knowledge_base tool can target a real id."""
        try:
            kbs = await self._resolve_user_knowledge_bases(session_model)
            if not kbs:
                return None
            knowledge_strs = await LinsightWorkbenchImpl.prepare_knowledge_list(kbs)
            return "\n".join(knowledge_strs) if knowledge_strs else None
        except Exception as e:
            logger.warning(f"Failed to resolve knowledge block: {e}")
            return None

    async def _resolve_allowed_knowledge_ids(self, session_model: LinsightSessionVersion) -> set[str]:
        """Build the SearchKnowledgeBase whitelist (C4 permission isolation).

        Allowed = the user-visible KB ids (same source as the prompt block) plus
        this session's uploaded file ids (``search_linsight_file`` targets). The
        tool refuses any id outside this set, so a hallucinated/coaxed id can
        never reach another tenant's KB or another session's uploaded file.
        """
        allowed: set[str] = set()
        for f in session_model.files or []:
            fid = f.get("file_id") if isinstance(f, dict) else None
            if fid:
                allowed.add(str(fid))
        try:
            kbs = await self._resolve_user_knowledge_bases(session_model)
            for kb in kbs:
                allowed.add(str(kb.id))
        except Exception as e:
            logger.warning(f"Failed to resolve allowed knowledge ids: {e}")
        return allowed

    @staticmethod
    def _unpack_stream_chunk(chunk):
        """Normalize an astream chunk into ``(mode, raw, namespace)``.

        With ``subgraphs=True`` + multi ``stream_mode`` LangGraph yields
        ``(namespace, mode, data)`` triples; without subgraphs it yields
        ``(mode, data)`` pairs. This tolerates both shapes so the mapper always
        receives a consistent ``(mode, raw, namespace)`` (design §3.1).
        """
        if isinstance(chunk, tuple) and len(chunk) == 3:
            namespace, mode, raw = chunk
            return mode, raw, namespace
        if isinstance(chunk, tuple) and len(chunk) == 2:
            mode, raw = chunk
            return mode, raw, None
        # Defensive: unexpected shape — treat as a values snapshot with no ns.
        return "values", chunk, None

    @staticmethod
    def _extract_last_message_text(messages) -> str | None:
        """Pull plain text from the last message of a graph values snapshot.

        Tolerates LangChain message objects and dicts, and content that is a
        string or a list of content blocks (multimodal/tool-call shape).
        """
        if not messages:
            return None
        last = messages[-1]
        content = getattr(last, "content", None)
        if content is None and isinstance(last, dict):
            content = last.get("content")
        if isinstance(content, str):
            return content.strip() or None
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            return "".join(parts).strip() or None
        return None

    # ==================== Event processing ====================

    async def _handle_event(self, agent, event: BaseEvent, session_model: LinsightSessionVersion):
        """handle incidents"""

        event_handlers: dict[type[BaseEvent], Callable] = {
            GenerateSubTask: self._handle_generate_subtask,
            TaskStart: self._handle_task_start,
            TaskEnd: self._handle_task_end,
            NeedUserInput: self._handle_need_user_input,
            ExecStep: self._handle_exec_step,
        }

        handler = event_handlers.get(type(event))
        if handler:
            await handler(agent, event, session_model)
        else:
            logger.warning(f"Unknown event type: {type(event)}")

    async def _handle_generate_subtask(self, agent, event: GenerateSubTask, session_model: LinsightSessionVersion):
        """Handle build subtask events"""
        await self._save_task_info(session_model, event.subtask)
        logger.debug(f"Generate subtasks: {event}")

    async def _handle_task_start(self, agent, event: TaskStart, session_model: LinsightSessionVersion):
        """Handle task start events"""
        task_data = await self._state_manager.update_execution_task_status(
            task_id=event.task_id, status=ExecuteTaskStatusEnum.IN_PROGRESS
        )

        await self._state_manager.push_message(MessageData(event_type=MessageEventType.TASK_START, data=task_data))

    async def _handle_task_end(self, agent, event: TaskEnd, session_model: LinsightSessionVersion):
        """Handle task end events"""
        status = (
            ExecuteTaskStatusEnum.SUCCESS if event.status == TaskStatus.SUCCESS.value else ExecuteTaskStatusEnum.FAILED
        )

        # F035 fix: TaskEnd.data is frequently empty for deepagents tasks; passing
        # it as task_data would OVERWRITE the task_data stored at write_todos time
        # (which holds the task name), leaving completed tasks with an empty
        # task_data — so the history view rebuilt from the DB shows blank task
        # rows. Only overwrite task_data when the event actually carries it;
        # otherwise preserve the write_todos task_data (and its name).
        update_kwargs = {"status": status, "result": {"answer": event.answer}}
        if event.data:
            update_kwargs["task_data"] = event.data
        task_data = await self._state_manager.update_execution_task_status(task_id=event.task_id, **update_kwargs)

        await self._state_manager.push_message(MessageData(event_type=MessageEventType.TASK_END, data=task_data))

        # Save Final Result
        self._final_result = event

    async def _handle_need_user_input(self, agent, event: NeedUserInput, session_model: LinsightSessionVersion):
        """Handle events that require user input (park-and-release, F035 §4.6).

        With the deepagents kernel, ``interrupt()`` halts ``astream`` after the
        ``__interrupt__`` chunk. We no longer spawn a polling coroutine: this
        handler just records the call-user-input step, flips the task to
        WAITING_FOR_USER_INPUT and pushes the ``user_input`` event. The agent
        loop then ends naturally; the task驻留 in the checkpointer. Re-queue +
        ``Command(resume)``续跑 is owned by Track B (worker.py +
        /workbench/user-input endpoint), not by an in-place wait here.
        """
        # Record the interrupt as a history step so set_user_input can locate
        # the matching call_user_input entry later.
        await self._state_manager.add_execution_task_step(event.task_id, step=event)

        await self._state_manager.update_execution_task_status(
            event.task_id,
            status=ExecuteTaskStatusEnum.WAITING_FOR_USER_INPUT,
        )

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.USER_INPUT, data=event.model_dump())
        )

        # The agent loop ends naturally after this interrupt. Mark the task as
        # parked so _handle_task_completion does NOT mistake the missing TaskEnd
        # for a direct-answer completion and push a FINAL_RESULT (which would
        # close the session and hide the clarify card).
        self._waiting_for_input = True

    async def _handle_exec_step(self, agent, event: ExecStep, session_model: LinsightSessionVersion):
        """Handle execution step events.

        Files written by a step are persisted by the deepagents WorkspaceBackend
        (MinIO truth + write-through cache) and surfaced as deliverables by
        ``get_final_result_file`` (output/ zone scan), so no per-step file upload
        is done here. The legacy ``handle_step_event_extra`` hook (which keyed off
        the retired local_file tool names) is removed.
        """
        await self._state_manager.add_execution_task_step(event.task_id, step=event)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.TASK_EXECUTE_STEP, data=event.model_dump())
        )

    # F035 §4.5/§4.6: the legacy `_wait_for_user_input` coroutine and the
    # `_wait_for_input_completion` 1s polling loop are REMOVED. Under
    # park-and-release there is no in-place wait: `interrupt()` halts `astream`,
    # `_handle_need_user_input` pushes the `user_input` event and releases the
    # worker. The /workbench/user-input endpoint persists the answer and
    # re-queues the task; an idle worker resumes via `Command(resume)` (Track B).

    # ==================== Terminate Inspection ====================

    def _check_termination(self):
        """Check if terminated"""
        if self._is_terminated:
            logger.info("Termination signal detected, ready to terminate agent task")
            raise UserTerminationError("Task terminated by user")

    async def _start_termination_monitor(self, session_model: LinsightSessionVersion):
        """Start Termination Monitoring"""

        async def monitor():
            while not self._is_terminated:
                try:
                    if await self._check_user_termination():
                        self._is_terminated = True
                        break
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)
                except Exception as e:
                    logger.error(f"Terminate Monitoring Exception: {e}")
                    await asyncio.sleep(self.USER_TERMINATION_CHECK_INTERVAL)

        self._termination_task = asyncio.create_task(monitor())

    async def _stop_termination_monitor(self):
        """Stop Terminating Monitoring"""
        if self._termination_task and not self._termination_task.done():
            self._termination_task.cancel()
            try:
                await self._termination_task
            except asyncio.CancelledError:
                pass

    async def _check_user_termination(self) -> bool:
        """Check if the user is actively terminating"""
        if self._is_terminated:
            return True

        try:
            current_session = await self._state_manager.get_session_version_info()
            return current_session and current_session.status == SessionVersionStatusEnum.TERMINATED
        except Exception as e:
            logger.error(f"Failed to check user termination status: {e}")
            return False

    async def _handle_user_termination(self, session_model: LinsightSessionVersion):
        """Handling user unsolicited termination"""
        logger.info(f"Handling User Termination {session_model.id}")

        session_model.status = SessionVersionStatusEnum.TERMINATED
        session_model.output_result = {"answer": "Task has been actively stopped by the user"}

        await self._state_manager.set_session_version_info(session_model)

        # Set all tasks to failed
        await self._set_tasks_failed()

        # Push termination message
        await self._state_manager.push_message(
            MessageData(
                event_type=MessageEventType.TASK_TERMINATED,
                data={
                    "message": "Task has been actively stopped by the user",
                    "session_id": session_model.id,
                    "terminated_at": datetime.now().isoformat(),
                },
            )
        )

    # ==================== Task Completion Processing ====================

    async def _handle_task_completion(self, session_model: LinsightSessionVersion):
        """Processing Task Completion"""
        if self._waiting_for_input:
            # An ask_user interrupt parked the task; astream halted with no
            # TaskEnd on purpose. Leave it WAITING — the user-input endpoint
            # will re-queue and resume it. Do not push any completion message.
            logger.info("Task parked on user input; skipping completion handling")
            return

        if not self._final_result:
            # No TaskEnd was emitted — the agent answered directly without
            # planning sub-tasks (e.g. a greeting). Don't leave the frontend
            # stuck on '规划中': fall back to the agent's final message so the
            # user still gets a reply and the session closes.
            logger.warning("No final task result; using direct-answer fallback")
            await self._handle_direct_answer_completion(session_model)
            return

        if self._final_result.status == TaskStatus.SUCCESS.value:
            await self._handle_task_success(session_model)
        else:
            await self._handle_task_failure(session_model, "Task execution failed:<g id='1'></g> ")

    async def _handle_direct_answer_completion(self, session_model: LinsightSessionVersion):
        """Complete a session that produced no TaskEnd event.

        The deepagents planner can answer trivial inputs (greetings, plain Q&A)
        directly without emitting sub-tasks, so ``self._final_result`` stays
        unset. Push the agent's final message as the result and close the
        session COMPLETED so the user still gets feedback instead of an endless
        '规划中'. Fall back to a clean failure if no text was captured, so the
        frontend still unsticks.
        """
        answer = (self._last_assistant_text or "").strip()
        if not answer:
            await self._handle_task_failure(session_model, "Task produced no result")
            return

        session_model.status = SessionVersionStatusEnum.COMPLETED
        # A direct-answer completion with NO sub-tasks is a genuine trivial reply
        # (greeting / plain Q&A) — no deliverable expected, keep final_files empty.
        # But a weak model can plan (write_todos) yet finish without a TaskEnd or any
        # output/ file; that still warrants a report. So when todos were generated,
        # collect any output/ deliverable and otherwise synthesize one from the
        # answer (F035 backstop) — same as the _handle_task_success path.
        final_files = []
        execution_tasks = await self._state_manager.get_execution_tasks()
        if execution_tasks:
            file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
            final_files = await linsight_execute_utils.get_final_result_file(
                session_model=session_model, file_details=file_details, answer=answer
            )
            if not final_files:
                final_files = await linsight_execute_utils.build_fallback_report_file(
                    session_model=session_model, answer=answer, file_dir=self.file_dir
                )
        session_model.output_result = {
            "answer": answer,
            "final_files": final_files,
            "all_from_session_files": [],
        }
        await self._state_manager.set_session_version_info(session_model)
        # F035 Track J: land the answer in the unified conversation stream.
        await linsight_execute_utils.persist_task_turn_message(session_model)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.FINAL_RESULT, data=session_model.model_dump())
        )
        logger.info(f"Task completed via direct-answer fallback ({len(final_files)} report files)")

    async def _handle_task_success(self, session_model: LinsightSessionVersion):
        """Processing task successful"""
        try:
            # Read File Directory File Details
            file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
            logger.debug(f"Read File Directory File Details: {file_details}")

            # The TaskEnd answer can be empty when the model delegates to `task`
            # sub-agents (the parent's final message carries no text). Fall back to
            # the last streamed assistant text so the answer field — and the
            # synthesized report below — still carry the real content.
            answer = (self._final_result.answer or "").strip() or (self._last_assistant_text or "").strip()

            final_result_files = await linsight_execute_utils.get_final_result_file(
                session_model=session_model, file_details=file_details, answer=answer
            )
            # F035 backstop: weak models can finish without ever writing an output/
            # deliverable (they loop on write_todos), leaving no report. Synthesize
            # one from the final answer so the task always yields a report file.
            if not final_result_files:
                final_result_files = await linsight_execute_utils.build_fallback_report_file(
                    session_model=session_model, answer=answer, file_dir=self.file_dir
                )
            execution_tasks = await self._state_manager.get_execution_tasks()
            all_from_session_files = await linsight_execute_utils.get_all_files_from_session(
                execution_tasks=execution_tasks, file_details=file_details
            )

            # Update session status
            session_model.status = SessionVersionStatusEnum.COMPLETED
            session_model.output_result = {
                "answer": answer,
                "final_files": final_result_files,
                "all_from_session_files": all_from_session_files,
            }

            # Save session information and push messages
            await self._state_manager.set_session_version_info(session_model)
            # F035 Track J: land the answer in the unified conversation stream.
            await linsight_execute_utils.persist_task_turn_message(session_model)
            await self._state_manager.push_message(
                MessageData(event_type=MessageEventType.FINAL_RESULT, data=session_model.model_dump())
            )

            logger.info(f"Task completed successfully, processed {len(final_result_files)} files")

        except Exception as e:
            logger.error(f"An error occurred while processing the task successfully: {e}")
            raise TaskExecutionError(f"An error occurred while processing the task successfully: {e}")

    # Modify All Task Failure Processing Logic
    async def _set_tasks_failed(self):
        """Set all tasks to failed"""
        try:
            # Get All Execute Tasks
            execution_tasks = await self._state_manager.get_execution_tasks()

            for task in execution_tasks:
                # Update each task status to Terminated
                if task.status not in [
                    ExecuteTaskStatusEnum.TERMINATED,
                    ExecuteTaskStatusEnum.SUCCESS,
                    ExecuteTaskStatusEnum.FAILED,
                ]:
                    await self._state_manager.update_execution_task_status(
                        task_id=task.id, status=ExecuteTaskStatusEnum.TERMINATED
                    )
        except Exception as e:
            logger.warning(f"Error setting task failed: {e}")

    async def _handle_task_failure(self, session_model: LinsightSessionVersion, error_msg: str):
        """Processing task failed"""
        session_model.status = SessionVersionStatusEnum.FAILED
        session_model.output_result = {"error_message": error_msg}
        await self._state_manager.set_session_version_info(session_model)
        # F035 Track J: still land a (failed) task turn in the unified stream so the
        # conversation isn't left with a dangling question; extra points to the SV
        # whose detail panel shows the failure.
        await linsight_execute_utils.persist_task_turn_message(session_model)

        # Set all tasks to failed
        await self._set_tasks_failed()

        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.ERROR_MESSAGE, data={"error": error_msg})
        )
        system_config = await settings.aget_all_config()
        # DapatkanLinsight_invitation_code
        linsight_invitation_code = system_config.get("linsight_invitation_code", False)
        if linsight_invitation_code:
            await InviteCodeService.revoke_invite_code(user_id=session_model.user_id)

    async def _handle_execution_error(self, error: Exception):
        """Processing execution error"""
        try:
            session_model = await LinsightSessionVersionDao.get_by_id(self.session_version_id)
            await self._handle_task_failure(session_model, str(error))
        except Exception as e:
            logger.error(f"Processing execution error failed: session_version_id={self.session_version_id}, error={e}")
