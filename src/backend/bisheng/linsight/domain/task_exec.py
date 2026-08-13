import asyncio
import os
import shutil
import traceback
from collections.abc import Callable
from contextlib import asynccontextmanager
from contextvars import Token
from datetime import datetime

from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError
from loguru import logger

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.common.services.config_service import settings
from bisheng.common.services.llm_error_classifier import classify_for_event
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
from bisheng.linsight.domain.services.binary_content_guard import CODE_INTERPRETER_TOOL
from bisheng.linsight.domain.services.resilience_middleware import _MAX_STATE_ONLY_REFUNDS
from bisheng.linsight.domain.services.state_message_manager import (
    LinsightStateMessageManager,
    MessageData,
    MessageEventType,
)
from bisheng.linsight.domain.services.stream_event_mapper import StreamEventMapper
from bisheng.linsight.domain.services.tool_loop_middleware import LinsightToolLoopError
from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl
from bisheng.linsight.domain.services.workspace_backend import UPLOADS_DIR
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


async def ensure_linsight_permission_runtime(manager=None) -> dict:
    """Initialize and verify Linsight's single F048 runtime pin."""

    if manager is None:
        if not settings.openfga.enabled:
            raise RuntimeError("linsight permission runtime is disabled")
        from bisheng.permission.application.process_runtime import ensure_f048_process_runtime_ready

        return await ensure_f048_process_runtime_ready(expected_role="linsight")

    instance = await manager.async_get_instance()
    healthy = bool(instance) and await manager.heartbeat()
    readiness = manager.readiness()
    if not healthy or not readiness.get("ready") or readiness.get("instance_role") != "linsight":
        raise RuntimeError("linsight permission runtime is not ready")
    return readiness


# Apology preambles prepended to a salvaged partial result, keyed to the REAL
# abort cause. Followed by the model's intermediate analysis so the user still
# gets meaningful output instead of a raw error.
#
# Why two: a single "模型未能正确调用写入工具" string used to cover both causes,
# and it was wrong every time it shipped — in the whole worker log the salvage
# path fired only on GraphRecursionError, never once on the tool-loop breaker.
# Blaming the write tool for a step-budget exhaustion sent everyone (users and
# us) down the wrong diagnostic path.
_PARTIAL_RESULT_PREAMBLE_TOOL_LOOP = (
    "抱歉，在生成报告文件时遇到问题，模型未能正确调用写入工具。以下是已完成的分析内容："
)
_PARTIAL_RESULT_PREAMBLE_STEP_LIMIT = "抱歉，任务执行步骤数已达上限，未能完全收尾。以下是已完成的内容："

# Friendly failure copy when the abort left nothing salvageable (no analysis text
# and no captured answer) — still a classified friendly card, never a raw dump.
# Same two-cause split as the preambles above.
_PARTIAL_NO_SALVAGE_TOOL_LOOP = (
    "任务未能完成：模型多次未能正确调用工具，且没有可供返回的中间结果。建议简化任务范围，或更换能力更强的模型后重试。"
)
# Appended to a NORMAL (successful) result when the turn budget made the agent
# wrap up ahead of schedule. Not an apology — the deliverables are real; the user
# just deserves to know the content was closed out on the materials already
# gathered rather than everything the task might have explored.
_SOFT_LANDING_NOTE = "任务步骤已接近模型调用次数上限，内容基于现有材料收尾。"

_PARTIAL_NO_SALVAGE_STEP_LIMIT = (
    "任务未能完成：任务执行步骤数已达上限，且没有可供返回的中间结果。建议简化任务范围，或拆成多轮执行。"
)


# Super-steps consumed per model turn on the main graph. Measured, not guessed:
# replaying a real run's Redis checkpoints yields the node cycle
#   model -> LinsightToolLoopBreakerMain.after_model -> TodoListMiddleware.after_model -> tools
# (213 checkpoints / 53 model turns, step counter ending at 211). Every middleware
# that implements before_model/after_model becomes its OWN graph node — and its own
# super-step — so adding one raises this number.
_STEPS_PER_MODEL_TURN = 4
# Headroom for the once-per-run before_agent nodes and the closing turn.
_RECURSION_LIMIT_MARGIN = 20


def _resolve_recursion_limit(linsight_conf) -> int:
    """LangGraph ``recursion_limit`` for one task run — always above the turn budget.

    ``max_steps`` is only a fuse; ``max_model_turns`` is the real gate, and the
    soft-landing ladder can only work if the fuse blows LATER than the budget.
    That is not automatic: ``get_linsight_conf()`` overlays values from the DB
    (``initdb_config``), which on any pre-existing deployment still holds the old
    ``max_steps: 200`` — far below the ~460 super-steps 115 turns needs. Raising
    the floor here means existing installs get the new behaviour without a DBA
    touching the config; an operator who deliberately raises ``max_steps`` still
    wins, since we only ever take the max.
    """
    configured = int(getattr(linsight_conf, "max_steps", 500) or 0)
    turn_limit = int(getattr(linsight_conf, "max_model_turns", 115) or 0)
    # Pure state-maintenance turns (a model call that only re-published the todo list)
    # are refunded, up to ``_MAX_STATE_ONLY_REFUNDS`` per budget bucket, so a run may
    # legitimately make more model calls than ``max_model_turns``. The fuse must still
    # blow LATER than the budget, or the soft-landing ladder is bypassed and the run
    # aborts into the partial-salvage path instead of finishing normally.
    floor = (turn_limit + _MAX_STATE_ONLY_REFUNDS) * _STEPS_PER_MODEL_TURN + _RECURSION_LIMIT_MARGIN
    if configured >= floor:
        return configured
    logger.warning(
        "linsight max_steps={} is below the {} super-steps needed by max_model_turns={}; "
        "raising the recursion ceiling so the turn budget stays the effective gate",
        configured,
        floor,
        turn_limit,
    )
    return floor


class LinsightWorkflowTask:
    """Workflow Task Executor - Responsible for managing the entire mission lifecycle"""

    # Poll interval (s) for the background termination monitor. Kept tight so a
    # stop request is detected promptly: at 2s a task that finishes within the
    # window escapes the cancel entirely (terminate-vs-complete race, 2026-06-18).
    USER_TERMINATION_CHECK_INTERVAL = 1

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
        # Set when the run was aborted by the L3 tool-loop breaker or the L4
        # recursion ceiling: instead of a raw failure, salvage the intermediate
        # analysis + retrieved knowledge and render it as a normal (partial)
        # result. ``_partial_salvage`` is the middleware-assembled body (empty for
        # a bare GraphRecursionError, which falls back to _last_assistant_text).
        self._partial_pending: bool = False
        self._partial_salvage: str | None = None
        self._partial_error: BaseException | None = None
        # Whether the LAST AIMessage of the most recent values snapshot still had
        # tool calls waiting to run. False means the model produced its closing
        # answer, so an abort raised right after it (a recursion ceiling hit on
        # the very step that would have ended the graph) must NOT be rendered as
        # a failed/partial run. Defaults True (conservative: assume mid-loop).
        self._last_ai_has_pending_tool_calls: bool = True
        # Shared with the MAIN graph's resilience middleware, which sets
        # ``soft_landing`` when the turn budget forced the run to wrap up early.
        # The result then carries a one-line note so the user knows the content
        # was closed out on the materials already gathered.
        self._turn_budget: dict = {}
        self.file_dir: str | None = None
        # Files present in ``file_dir`` before the agent ran (set by
        # _init_file_directory); the deliverable scan diffs against it.
        self._baseline_files: set[str] = set()
        # Set per run in _create_agent; gates every prompt hint that names the
        # code interpreter (prompt ⟺ tool lockstep).
        self._has_code_interpreter: bool = False
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

            # F035 problem 2: ensure the session-level pseudo task row exists so
            # planning/wrap-up/direct-answer steps (mapper routes them to
            # task_id = svid) are persisted and survive a refresh.
            await self._ensure_session_pseudo_task(session_model)

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

    async def async_run(
        self,
        session_version_id: str,
        tenant_id: int | None = None,
    ) -> None:
        """Asynchronous Task Execution Entry"""

        self.session_version_id = session_version_id
        trace_id_var.set(self.session_version_id)
        logger.info(f"Start the task: session_version_id={self.session_version_id}")
        tenant_context_token: Token | None = None
        try:
            tenant_context_token = await self._restore_tenant_context(
                session_version_id,
                task_tenant_id=tenant_id,
            )
            await ensure_linsight_permission_runtime()

            async with self._managed_execution() as session_model:
                await self._execute_workflow(session_model)

        except UserTerminationError:
            logger.info(f"Task was actively terminated by the user: session_version_id={self.session_version_id}")
        except TaskAlreadyInProgressError:
            logger.warning(f"Task already in progress: session_version_id={self.session_version_id}")
        except TaskExecutionError as e:
            # NEVER pass exc_info= to loguru: it has no such kwarg, so ANY kwarg makes
            # it str.format() the message. Provider errors embed literal braces
            # (``Error code: 429 - {'error': {...}}``), which format() reads as a
            # replacement field -> KeyError raised inside this except clause, skipping
            # _handle_execution_error and stranding the session IN_PROGRESS forever.
            logger.exception(f"Task execution failed: {e} : session_version_id={self.session_version_id}")
            await self._handle_execution_error(e)
        except Exception as e:
            logger.exception(f"Unknown error: session_version_id={self.session_version_id}")
            await self._handle_execution_error(e)
        finally:
            if tenant_context_token is not None:
                current_tenant_id.reset(tenant_context_token)

    async def _restore_tenant_context(
        self,
        session_version_id: str,
        *,
        task_tenant_id: int | None,
    ) -> Token:
        """Verify the queue payload against the row and restore ContextVar."""

        current_tenant_id.set(None)
        if isinstance(task_tenant_id, bool):
            raise TaskExecutionError("Linsight task tenant_id must be a positive integer")
        try:
            payload_tenant_id = int(task_tenant_id)
        except (TypeError, ValueError) as exc:
            raise TaskExecutionError("Linsight task tenant_id must be a positive integer") from exc
        if payload_tenant_id <= 0:
            raise TaskExecutionError("Linsight task tenant_id must be a positive integer")

        try:
            with bypass_tenant_filter():
                session_model = await LinsightSessionVersionDao.get_by_id(session_version_id)
        except Exception as e:
            raise TaskExecutionError(f"Failed to restore tenant context: {e}") from e

        if not session_model:
            raise TaskExecutionError(f"Session version not found: {session_version_id}")

        persisted_tenant_id = session_model.tenant_id
        if persisted_tenant_id is None:
            raise TaskExecutionError(f"Session version {session_version_id} is missing tenant_id")
        try:
            persisted_tenant_id = int(persisted_tenant_id)
        except (TypeError, ValueError) as exc:
            raise TaskExecutionError(f"Session version {session_version_id} has invalid tenant_id") from exc
        if persisted_tenant_id <= 0 or persisted_tenant_id != payload_tenant_id:
            raise TaskExecutionError(f"Linsight task tenant mismatch for session {session_version_id}")
        return set_current_tenant_id(payload_tenant_id)

    # ==================== Resume (park-and-release, Track B) ====================

    async def async_resume(
        self,
        session_version_id: str,
        user_input=None,
        tenant_id: int | None = None,
    ) -> None:
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
            tenant_context_token = await self._restore_tenant_context(
                session_version_id,
                task_tenant_id=tenant_id,
            )
            await ensure_linsight_permission_runtime()
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
            # F035 problem 2: resume/continue can also produce session-level
            # (task_id = svid) steps; ensure the pseudo task row is present.
            await self._ensure_session_pseudo_task(session_model)
            yield session_model
        finally:
            await self._cleanup_resources()

    async def _resume_workflow(self, session_model: LinsightSessionVersion, user_input) -> None:
        """Rebuild the agent on the same thread (Redis checkpointer) and drive resume."""
        from bisheng.linsight.domain.services.checkpointer import make_checkpointer

        # The task was parked as WAITING_FOR_USER_INPUT; resuming means it is
        # actively running again. Flip it back to IN_PROGRESS so status reflects
        # reality (and the worker-startup crash sweep, which scans IN_PROGRESS,
        # again covers it while a worker is genuinely driving it).
        await self._update_session_status(session_model, SessionVersionStatusEnum.IN_PROGRESS)

        self.llm = await self._get_llm(session_model)
        tools = await self._generate_tools(session_model)
        try:
            # Rebuild the SAME tool set the parked graph had — INCLUDING the C4
            # knowledge whitelist. The fresh/continue paths gate SearchKnowledgeBase
            # with allowed_knowledge_ids; resume MUST pass the same set, otherwise
            # (a) the resumed graph's tool topology diverges from the parked one, and
            # (b) the knowledge tool is rebuilt UNGATED (allowed_knowledge_ids=None),
            # bypassing the C4 whitelist — which since design #1 also leaks into the
            # researcher subagent's tool subset.
            allowed_knowledge_ids = await self._resolve_allowed_knowledge_ids(session_model)
            linsight_tools = await ToolServices.init_linsight_tools(
                root_path=self.file_dir, allowed_knowledge_ids=allowed_knowledge_ids
            )
            tools.extend(linsight_tools)
            # Rebuild on the SAME thread_id with a durable checkpointer so the
            # parked interrupt checkpoint is located (design §4.4).
            agent = await self._create_agent(session_model, tools, checkpointer=make_checkpointer())
            self._check_termination()
            await self._drive_resume(agent, session_model, user_input)
            # F035 reload parity: the resume re-stream above may have rewritten the
            # session pseudo task's history, dropping the is_completed/user_input
            # stamp on the answered clarify steps. Re-apply the persisted answers
            # (task_data.clarify_answers) so a refreshed turn still shows the
            # answered "已明确用户意图" rows. This is the last history write of the
            # turn, so it wins over anything the re-stream did.
            await self._state_manager.restamp_clarify_answers(session_model.id)
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
            "recursion_limit": _resolve_recursion_limit(linsight_conf),
        }
        try:
            async for chunk in agent.astream(
                Command(resume=user_input),
                config=config,
                stream_mode=["updates", "messages", "values"],
                subgraphs=True,
            ):
                mode, raw, namespace = self._unpack_stream_chunk(chunk)
                if mode == "values" and not namespace and isinstance(raw, dict):
                    self._capture_values_snapshot(raw)
                for event in mapper.normalize(mode, raw, namespace=namespace):
                    await self._handle_event(agent, event, session_model)
        except (LinsightToolLoopError, GraphRecursionError) as e:
            # L3/L4 on the resume path: stash the salvage; the caller's
            # _handle_task_completion renders it as a partial result.
            self._stash_partial_abort(e)

    # ==================== Continue (multi-turn conversation) ====================

    async def async_continue(
        self,
        session_version_id: str,
        question: str,
        tenant_id: int | None = None,
    ) -> None:
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
            tenant_context_token = await self._restore_tenant_context(
                session_version_id,
                task_tenant_id=tenant_id,
            )
            await ensure_linsight_permission_runtime()
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
            "recursion_limit": _resolve_recursion_limit(linsight_conf),
        }
        # Prepend the current-time block (same rationale as _build_agent_input):
        # per-task time awareness without busting the static system-prompt cache.
        agent_input = {
            "messages": [{"role": "user", "content": f"{self._current_time_block()}\n# 用户问题\n{question}"}]
        }
        try:
            async for chunk in agent.astream(
                agent_input,
                config=config,
                stream_mode=["updates", "messages", "values"],
                subgraphs=True,
            ):
                mode, raw, namespace = self._unpack_stream_chunk(chunk)
                if mode == "values" and not namespace and isinstance(raw, dict):
                    self._capture_values_snapshot(raw)
                for event in mapper.normalize(mode, raw, namespace=namespace):
                    await self._handle_event(agent, event, session_model)
        except (LinsightToolLoopError, GraphRecursionError) as e:
            # L3/L4 on the continue path: stash the salvage; the caller's
            # _handle_task_completion renders it as a partial result.
            self._stash_partial_abort(e)

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

        # Cross-turn continuity: seed this turn's workspace from the previous turn
        # so a follow-up (e.g. "convert the report to HTML") can read and build on
        # the prior turn's deliverables. New-turn path only (resume reuses the same
        # svid workspace). Best-effort — never blocks the turn.
        await self._seed_workspace_from_previous(session_model)
        # Must run between the seed and tool construction: the code interpreter's
        # file list is snapshotted from file_dir when the tool is built.
        await self._sync_workspace_originals(session_model)

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

        if session_model.files:
            # Only entries that carry a parsed-markdown object can be prefetched. A
            # file without ``markdown_file_path`` (e.g. an org-KB reference, or a file
            # still parsing) must be SKIPPED — not crash task startup. (The agent reads
            # uploaded sources through the WorkspaceBackend ``uploads/`` keys anyway, so
            # this local prefetch is best-effort cache warming, not the access path.)
            entries = [f for f in session_model.files if isinstance(f, dict) and f.get("markdown_file_path")]
            skipped = len(session_model.files) - len(entries)
            if skipped:
                logger.warning(f"{skipped} uploaded file(s) without markdown_file_path skipped for local prefetch")

            # A passthrough file has no separate markdown view — its seed object and
            # its original are the same bytes. It is fetched by the raw track below,
            # which lands it under ``uploads/`` where the pointer block says it is;
            # letting it through here as well would ALSO drop a flat copy at the task
            # root, and the code interpreter's file list (``os.walk``) would show the
            # same file twice under two different paths.
            downloadable = [f for f in entries if f.get("ingest_mode") != "passthrough"]

            # Concurrent downloads
            download_tasks = [self._download_file(file_info, file_dir) for file_info in downloadable]

            results = await asyncio.gather(*download_tasks, return_exceptions=True)

            # Record Download Failed Files
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    file_name = os.path.basename(downloadable[i].get("markdown_file_path") or "")
                    logger.error(f"This content failed to load {file_name}: {result}")

            # Second track: the ORIGINAL spreadsheets / documents. The code
            # interpreter's file list is built from ``os.walk(file_dir)``
            # (workbench_impl._init_bisheng_code_tool), so an original that never
            # lands here is invisible to pandas / python-docx / fitz — which is the
            # whole point of keeping it. Best-effort: a miss costs the precise-data
            # track, never the task.
            # Selected from ``entries``, not ``downloadable``: passthrough files are
            # excluded from the markdown track precisely so they arrive here.
            raw_files = [f for f in entries if f.get("raw_filename") and f.get("original_file_path")]
            if raw_files:
                raw_results = await asyncio.gather(
                    *[self._download_raw_original(f, file_dir) for f in raw_files], return_exceptions=True
                )
                for i, result in enumerate(raw_results):
                    if isinstance(result, Exception):
                        logger.warning(f"Original not prefetched {raw_files[i].get('raw_filename')}: {result}")

        # Baseline for deliverable detection: everything present BEFORE the agent
        # runs (i.e. the prefetched upload sources). Captured here — after the
        # prefetch, at the single point every driver goes through — so the
        # completion scan can tell what the agent actually produced.
        self._baseline_files = linsight_execute_utils.snapshot_file_paths(file_dir)

        return file_dir

    async def _download_file(self, file_info: dict, target_dir: str) -> str:
        """Download individual files"""
        object_name = file_info.get("markdown_file_path")
        if not object_name:
            raise ValueError("file entry missing markdown_file_path")
        file_name = file_info.get("markdown_filename", os.path.basename(object_name))
        file_path = os.path.join(target_dir, file_name)
        # ``markdown_filename`` carries the folder-upload sub-path (``年报/2024/Q1.md``)
        # for files that came in as part of a directory, so the parent dirs have to
        # exist before the write. os.makedirs on the flat case is a no-op.
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
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

    async def _download_raw_original(self, file_info: dict, target_dir: str) -> str:
        """Prefetch the ORIGINAL upload next to its markdown view.

        Mirrors ``_download_file`` but reads ``original_file_path`` (formal bucket)
        and lands under ``uploads/<raw_filename>``. The subdirectory is load-bearing:
        the workspace key is ``uploads/x.xlsx`` and that is the path the pointer
        block hands the model, while the code interpreter resolves paths relative to
        ``file_dir``. Landing the original flat here (the original implementation)
        meant the one path the model was told about did not exist in the sandbox —
        the whole point of carrying the original was lost. The markdown track stays
        flat on purpose: it is only ever read through ``read_file``, which goes to
        the workspace, so it needs no local path parity.
        """
        object_name = file_info["original_file_path"]
        file_path = os.path.join(target_dir, UPLOADS_DIR, file_info["raw_filename"])
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        minio_client = await get_minio_storage()
        file_url = await minio_client.get_share_link(object_name, clear_host=False)
        http_client = await get_http_client()

        with open(file_path, "wb") as f:
            async for chunk in http_client.stream(method="GET", url=str(file_url)):
                f.write(chunk)

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise ValueError(f"Original download failed or empty: {object_name}")
        return file_path

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
        from bisheng.linsight.domain.services.skill_provisioning import materialize_session_skills
        from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

        # Whether the code interpreter is actually bound this run (it is injected
        # only when the user selected it). Everything that points the model at it —
        # the uploaded-files pointer block and the binary read guard — must stay in
        # lockstep with this flag, or we recreate the "told to call a tool that
        # isn't there" failure mode.
        self._has_code_interpreter = any(getattr(t, "name", None) == CODE_INTERPRETER_TOOL for t in tools)

        minio = await get_minio_storage()
        backend = WorkspaceBackend(svid=session_model.id, minio=minio, file_dir=self.file_dir)
        # F035 Fork X: copy this run's allowed skill bundles into the workspace
        # /skills/ subtree (governance-enabled ∩ user-selected — the copy IS the
        # whitelist gate). Re-runs harmlessly on resume/continue since this builds a
        # fresh agent each time. skills_present gates attaching the skills middleware.
        copied_skills = await materialize_session_skills(
            backend, session_model.tenant_id, getattr(session_model, "skills", None)
        )
        return await create_linsight_agent(
            session_model=session_model,
            tools=tools,
            model_id=getattr(session_model, "model", None),
            file_dir=self.file_dir,
            svid=session_model.id,
            checkpointer=checkpointer,
            backend=backend,
            skills_present=bool(copied_skills),
            turn_budget_sink=self._turn_budget,
        )

    async def _seed_workspace_from_previous(self, session_model: LinsightSessionVersion) -> None:
        """Cross-turn continuity: copy the previous turn's deliverables/sources
        into this turn's workspace (跨轮工作区延续).

        A follow-up turn runs under a fresh ``session_version_id`` with an empty
        ``workspace/{svid}/`` prefix, so it cannot see a prior turn's output
        (e.g. ``output/report.md``) — ``read_file`` on it would otherwise fail.
        Server-side copy the immediately-previous version's ``output/`` +
        ``uploads/`` into this turn's prefix so ``read_file``/``ls`` transparently
        surface them. Best-effort — a failure never blocks the turn; the first
        turn (no predecessor) no-ops.
        """
        try:
            from bisheng.linsight.domain.services.workspace_backend import seed_workspace_from_previous

            versions = await LinsightSessionVersionDao.get_session_versions_by_session_id(session_model.session_id)
            # Ordered by version DESC. The most recent OTHER version is the
            # immediately-previous turn; its workspace is cumulative (it inherited
            # its own predecessor), so one copy carries the whole conversation.
            prev = next((v for v in versions if v.id != session_model.id), None)
            if prev is None:
                return
            minio = await get_minio_storage()
            copied = await seed_workspace_from_previous(minio, src_svid=prev.id, dst_svid=session_model.id)
            if copied:
                logger.info(
                    f"Seeded {copied} file(s) from previous turn {prev.id[:8]} into "
                    f"{session_model.id[:8]} (cross-turn continuity)"
                )
        except Exception as e:
            logger.warning(f"workspace seed-from-previous skipped (non-fatal): {e}")

    async def _sync_workspace_originals(self, session_model: LinsightSessionVersion) -> None:
        """Make workspace originals reachable by the code interpreter this turn.

        ``_init_file_directory`` prefetches originals from THIS turn's ``files``,
        which is empty on a follow-up ("总结一下刚才那个表") — the originals only
        exist in the workspace, copied there by the seed. The code interpreter's
        file list is built from the local ``file_dir``, so without this step the
        model sees ``uploads/x.xlsx`` in ``ls``, is told by the pointer block that
        it can compute on it, and then finds nothing in the sandbox.

        Runs after the seed and before tools are built. Idempotent: on a fresh turn
        the prefetch already wrote these files and ``_materialize`` serves them from
        cache. Best-effort — losing the precise-data track must never fail the turn.
        """
        try:
            from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend

            minio = await get_minio_storage()
            backend = WorkspaceBackend(svid=session_model.id, minio=minio, file_dir=self.file_dir)
            ls_res = await backend.als(UPLOADS_DIR)
            if getattr(ls_res, "error", None):
                return

            synced: list[str] = []
            for entry in ls_res.entries or []:
                rel = str(entry.get("path") or "").lstrip("/")
                # Markdown views are already local (or are read through read_file,
                # which goes to MinIO anyway); only the originals need a local copy.
                if not rel.startswith(f"{UPLOADS_DIR}/") or rel.endswith(".md"):
                    continue
                local_path = os.path.join(self.file_dir, rel)
                if os.path.exists(local_path):
                    continue
                if await asyncio.to_thread(backend.ensure_local, rel):
                    synced.append(local_path)

            if synced:
                # These arrived AFTER _init_file_directory took the baseline, so
                # without this they would look like files the agent produced and be
                # delivered back to the user as this turn's output.
                self._baseline_files.update(synced)
                logger.info(
                    "Synced {} workspace original(s) into the local task dir for the code interpreter",
                    len(synced),
                )
        except Exception as e:
            logger.warning(f"workspace original sync skipped (non-fatal): {e}")

    # ==================== Mission Execution ====================

    async def _ensure_session_pseudo_task(self, session_model: LinsightSessionVersion) -> None:
        """Create the session-level pseudo task row (F035 problem 2).

        The StreamEventMapper routes steps to ``task_id = svid`` whenever no todo
        is in_progress (planning phase, wrap-up, or a direct answer that plans no
        todo). Without a DB row whose id == svid, those steps hit the orphan
        branch in ``add_execution_task_step`` / ``update_execution_task_status``
        and are dropped — invisible after a refresh. This inserts one pseudo task
        (id == svid) to carry them. Idempotent: skips when it already exists, so
        resume/continue re-entry and concurrent workers are safe. tenant_id is
        injected by the SQLAlchemy tenant event (worker has restored the context).
        """
        svid = session_model.id
        try:
            existing = await LinsightExecuteTaskDao.get_by_id(svid)
            if existing:
                return
            pseudo = LinsightExecuteTask(
                id=svid,
                session_version_id=svid,
                parent_task_id=None,
                previous_task_id=None,
                next_task_id=None,
                task_type=ExecuteTaskTypeEnum.SINGLE,
                task_data={"name": "执行准备", "is_session_global": True},
                status=ExecuteTaskStatusEnum.IN_PROGRESS,
                history=[],
            )
            await LinsightExecuteTaskDao.batch_create_tasks([pseudo])
            logger.info(f"Created session-level pseudo task for {svid}")
        except Exception as e:
            # A concurrent worker may have created it first; non-fatal — orphan
            # steps simply fall back to the (now rare) skip branch.
            logger.warning(f"Failed to ensure session pseudo task for {svid}: {e}")

    async def _complete_session_pseudo_task(self, session_model: LinsightSessionVersion) -> None:
        """Mark the session pseudo task SUCCESS on normal completion (best-effort).

        Empty-history pseudo tasks are dropped by ``get_execute_task_detail`` so a
        SUCCESS flip on an empty one is harmless; one that carried orphan steps
        then shows as a completed "执行准备" node instead of a stuck in_progress.
        """
        try:
            await self._state_manager.update_execution_task_status(
                task_id=session_model.id, status=ExecuteTaskStatusEnum.SUCCESS
            )
        except Exception as e:
            logger.warning(f"Failed to finalize session pseudo task: {e}")

    async def _converge_task_rows_on_completion(self) -> None:
        """Close out task rows a NORMALLY finished run left hanging.

        ``linsight_execute_task`` used to be append-only: rows were inserted from the
        first ``write_todos`` snapshot and only ever updated on a status flip, so a run
        that finished after the model reshaped its plan left rows stuck at
        NOT_STARTED/IN_PROGRESS forever. The panel then reported a fake ratio on a
        COMPLETED session — measured on 180: "任务已完成 4/7" with 1 IN_PROGRESS and 2
        NOT_STARTED still in the table.

        ⚠️ ORDERING: must run AFTER ``_complete_session_pseudo_task``. The sweep walks
        every row including the svid pseudo task; finalizing that one first is what
        makes the sweep skip it instead of marking the session's own row TERMINATED.
        """
        await self._terminate_unfinished_tasks()

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

            # Positional alignment reuses an existing row id when the model REWRITES a
            # todo's wording, so without this the row would keep the title from the
            # very first plan for the rest of the run. Status/result are untouched.
            for task in tasks:
                prev = existing_by_id.get(task.id)
                if prev is None:
                    continue
                if (prev.task_data or {}).get("name") == (task.task_data or {}).get("name"):
                    continue
                # DAO directly (like the batch insert above): the state-manager helper
                # requires a ``status`` and returns a plain dict, both of which would
                # be wrong here — the status must not move, and ``merged`` below has
                # to stay a list of models. Redis is refreshed by the
                # ``set_execution_tasks(merged)`` call a few lines down.
                refreshed = await LinsightExecuteTaskDao.update_by_id(task.id, task_data=task.task_data)
                if refreshed is not None:
                    existing_by_id[task.id] = refreshed

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
            file_list = await LinsightWorkbenchImpl.prepare_file_list(
                session_model, has_code_interpreter=self._has_code_interpreter
            )
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
                "recursion_limit": _resolve_recursion_limit(linsight_conf),
            }
            # subgraphs=True so subagent (子图) events冒泡父流 with a namespace
            # prefix the mapper uses to归并 nested step cards (design §3.1/§3.7).
            # LIVE (design #1, 2026-06-17): the `task` subagent tool is RE-ENABLED —
            # agent_factory now registers a single "general-purpose" researcher
            # subagent and no longer strips `task`, so subgraph events ARE emitted
            # with a non-empty namespace. The mapper drops namespaced todos (the main
            # plan stays clean) and tags namespaced tool steps step_type="subagent".
            async for chunk in agent.astream(
                task_input,
                config=config,
                stream_mode=["updates", "messages", "values"],
                subgraphs=True,
            ):
                mode, raw, namespace = self._unpack_stream_chunk(chunk)
                # Capture the agent's latest top-level reply as a fallback
                # answer for the no-TaskEnd case (e.g. a greeting the planner
                # answers directly without spawning sub-tasks), plus whether it
                # left tool calls pending (drives the abort classification).
                if mode == "values" and not namespace and isinstance(raw, dict):
                    self._capture_values_snapshot(raw)
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
        except (LinsightToolLoopError, GraphRecursionError) as e:
            # L3/L4: a same-tool failure loop (LinsightToolLoopError, carries a
            # salvaged partial_result) or the recursion ceiling (GraphRecursionError,
            # bare) aborted the run. Do NOT surface a raw recursion error — stash the
            # salvage and return True so _handle_task_completion renders the
            # intermediate analysis as a normal (partial) result. See _handle_task_partial.
            self._stash_partial_abort(e)
            return True
        except Exception as e:
            logger.error(f"task_exec_error {traceback.format_exc()}")
            # ``from e`` preserves the original provider exception as __cause__ so
            # the failure classifier can unwrap it (e.g. an aliyun content-filter
            # BadRequestError) and emit a precise error_type to the frontend.
            raise TaskExecutionError(f"Agent task execution failed: {e}") from e

    @staticmethod
    def _current_time_block() -> str:
        """Current server-local time block for the first user message.

        Injected into the dynamic first message (NOT the static system prompt)
        so the system prompt stays byte-identical across tasks and remains
        prefix-cacheable by the model provider, while the agent still gets
        per-task time awareness. Uses server-local time, consistent with the
        repo-wide ``default_factory=datetime.now``.
        """
        now = datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        return f"# 当前时间\n{now.strftime('%Y-%m-%d %H:%M')} 周{weekday}（服务器本地时区）"

    @staticmethod
    def _build_agent_input(
        session_model: LinsightSessionVersion,
        file_list,
        history_summary: str | None = None,
        knowledge_block: str | None = None,
    ) -> dict:
        """Assemble the first-message input for the deepagents graph.

        LangGraph agents take ``{"messages": [...]}``. We seed the user turn with
        the prior conversation context (F035 Track J, by chat_id) + question; the
        file pointer block (offload-first, design §9) and the available
        knowledge-base list (so ``search_knowledge_base`` has real ids) are
        appended when present. The deepagents kernel plans the todo清单 from this
        seed during astream.
        """
        # Lead with the current-time block so the agent is time-aware. Placing it
        # in the (already dynamic) first user message keeps the system prompt
        # static and prefix-cacheable.
        parts: list[str] = [LinsightWorkflowTask._current_time_block()]
        if history_summary:
            parts.append(history_summary)
        if session_model.question:
            # Header the question like every other block (# 当前时间 / # 可用文件 /
            # # 可用知识库 / # 前情回顾) so it is clearly delimited from the time
            # block above it instead of bleeding into it.
            parts.append(f"# 用户问题\n{session_model.question}")
        if file_list:
            # file_list is a list[str] (prepare_file_list returns a single-element
            # list holding the <uploaded_files> block). Join it — interpolating the
            # list directly emits its Python repr (brackets/quotes + escaped "\n"),
            # mangling the pointer block the model has to parse.
            files_block = "\n".join(file_list) if isinstance(file_list, (list, tuple)) else str(file_list)
            parts.append(f"\n# 可用文件\n{files_block}")
        if knowledge_block:
            parts.append(
                f"\n# 可用知识库(用 search_knowledge_base 检索,knowledge_id 用下方括号内的 id)\n{knowledge_block}"
            )
        content = "\n".join(parts) if parts else (session_model.question or "")
        return {"messages": [{"role": "user", "content": content}]}

    async def _resolve_user_knowledge_bases(self, session_model: LinsightSessionVersion) -> list:
        """Resolve the EXACT knowledge bases the user picked in the daily picker.

        Mirrors daily mode (``_resolve_user_kb_selection``): load precisely the
        selected organization-KB ids + knowledge-space ids — NOT every KB of a
        coarse type. The deprecated ``org_knowledge_enabled`` /
        ``personal_knowledge_enabled`` booleans are intentionally NOT consulted
        here; an empty id selection means the user picked none. Both the prompt
        advertisement (``_resolve_knowledge_block``) and the tool gate
        (``_resolve_allowed_knowledge_ids``) derive from this list, so what the
        model is told it may search and what it is actually allowed to search stay
        in lockstep.
        """
        from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

        org_ids = [int(x) for x in (session_model.organization_knowledge_ids or [])]
        space_ids = [int(x) for x in (session_model.knowledge_space_ids or [])]
        ids = org_ids + space_ids
        if not ids:
            return []
        try:
            return list(await KnowledgeDao.aget_list_by_ids(ids))
        except Exception as e:
            logger.warning(f"Failed to load selected knowledge bases {ids}: {e}")
            return []

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

        Allowed = the user-visible KB / knowledge-space ids (same source as the
        prompt block). The tool refuses any id outside this set, so a
        hallucinated/coaxed id can never reach another tenant's KB. Uploaded files
        are NOT included: they are not searched through this tool — the agent reads
        their parsed markdown from the workspace via ``read_file``.
        """
        allowed: set[str] = set()
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
    def _is_assistant_message(msg) -> bool:
        """True iff ``msg`` is an assistant/AI message (not Tool/Human/System).

        Uses the LangChain ``.type`` discriminator ("ai" / "tool" / "human" /
        "system"; "AIMessageChunk" for streamed chunks) and falls back to the
        ``type``/``role`` key on dict-shaped messages.
        """
        t = getattr(msg, "type", None)
        if t is None and isinstance(msg, dict):
            t = msg.get("type") or msg.get("role")
        return t in ("ai", "assistant", "AIMessageChunk")

    @staticmethod
    def _message_text(msg) -> str | None:
        """Plain text of a single message's content (str or content-block list).

        Tolerates LangChain message objects and dicts, and content that is a
        string or a list of content blocks (multimodal/tool-call shape).
        """
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
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

    @staticmethod
    def _extract_last_message_text(messages) -> str | None:
        """Pull plain text from the last *assistant* message of a values snapshot.

        Walks backward to the last AIMessage carrying text, skipping
        ToolMessage / HumanMessage / etc. This matters on the L3/L4 abort paths:
        when a run is cut off mid tool-loop the trailing message is usually a raw
        ToolMessage — e.g. a ``bisheng_code_interpreter`` ``{"exitcode":..,
        "log":..}`` blob. Returning that as "the model's last words" leaked raw
        tool output into the user-facing partial-result salvage (apology preamble
        + body). Only genuine assistant text is eligible; when the model never
        produced any, return None so the caller degrades to a friendly failure
        instead of dumping tool JSON.
        """
        if not messages:
            return None
        for msg in reversed(messages):
            if not LinsightWorkflowTask._is_assistant_message(msg):
                continue
            text = LinsightWorkflowTask._message_text(msg)
            if text:
                return text
        return None

    @staticmethod
    def _last_ai_pending_tool_calls(messages) -> bool:
        """True when the LAST AIMessage still has tool calls waiting to run.

        This is the "did the model actually finish?" test. It must look at the
        *last* AIMessage — NOT the last one carrying text, which is what
        ``_extract_last_message_text`` walks back to. A closing turn ends with a
        text-only AIMessage (no tool_calls); a run cut off mid-loop ends with a
        ToolMessage whose preceding AIMessage still carries the pending call. If
        we reused the text-based walk, a tool-call-only AIMessage would be
        skipped and an unfinished run would look finished.

        Returns True (assume mid-loop) when no AIMessage exists at all, so the
        conservative partial-salvage path stays the default.
        """
        for msg in reversed(messages or []):
            if not LinsightWorkflowTask._is_assistant_message(msg):
                continue
            tool_calls = msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
            return bool(tool_calls)
        return True

    def _capture_values_snapshot(self, raw: dict) -> None:
        """Record what the agent's latest top-level ``values`` snapshot tells us.

        Two things, both consumed only on the completion paths: the last
        assistant text (fallback answer when no TaskEnd is emitted) and whether
        that turn left tool calls pending (see ``_last_ai_pending_tool_calls``).
        """
        messages = raw.get("messages")
        text = self._extract_last_message_text(messages)
        if text:
            self._last_assistant_text = text
        self._last_ai_has_pending_tool_calls = self._last_ai_pending_tool_calls(messages)

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
        # A "terminated" TaskEnd is a todo the model DROPPED from its plan (see
        # StreamEventMapper._diff_todos), not a task that failed. Mapping it to FAILED
        # would paint an error row in the panel — and, far worse, feed
        # ``self._final_result`` below, which ``_handle_task_completion`` routes into
        # ``_handle_task_failure`` for anything != success: a pruned todo arriving last
        # would fail the WHOLE session.
        if event.status == ExecuteTaskStatusEnum.TERMINATED.value:
            status = ExecuteTaskStatusEnum.TERMINATED
        elif event.status == TaskStatus.SUCCESS.value:
            status = ExecuteTaskStatusEnum.SUCCESS
        else:
            status = ExecuteTaskStatusEnum.FAILED

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

        # Save Final Result — a dropped todo is never the run's outcome.
        if status is not ExecuteTaskStatusEnum.TERMINATED:
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

        # Flip the SESSION-version status to WAITING_FOR_USER_INPUT too. Without
        # this the parked session stays IN_PROGRESS, and the worker-startup crash
        # sweep (check_and_terminate_incomplete_tasks scans IN_PROGRESS) sees a
        # parked task whose owner key was released by park-and-release and wrongly
        # marks it FAILED ("Worker node crash detected"). The dedicated WAITING
        # status keeps parked tasks out of that IN_PROGRESS sweep; resume flips it
        # back to IN_PROGRESS.
        await self._update_session_status(session_model, SessionVersionStatusEnum.WAITING_FOR_USER_INPUT)

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

        # Converge every task row the run never finished
        await self._terminate_unfinished_tasks()

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
        # Terminate-vs-complete race (2026-06-18): a stop request can land while
        # the agent is finishing its last step. The periodic monitor may miss a
        # task that completes inside the poll window, so the agent returns
        # "success" and this path would overwrite the user's TERMINATED status
        # with COMPLETED. Re-read the authoritative status (fresh from Redis) and
        # honor a termination that arrived before completion instead of clobbering
        # it. Covers the fresh-run, resume, and continue completion entry points.
        if await self._check_user_termination():
            logger.info("Termination detected at completion; honoring stop over completion")
            await self._handle_user_termination(session_model)
            return

        if self._waiting_for_input:
            # An ask_user interrupt parked the task; astream halted with no
            # TaskEnd on purpose. Leave it WAITING — the user-input endpoint
            # will re-queue and resume it. Do not push any completion message.
            logger.info("Task parked on user input; skipping completion handling")
            return

        if self._partial_pending and self._last_ai_has_pending_tool_calls:
            # L3/L4: aborted by the tool-loop breaker or recursion ceiling while
            # the model was still mid-loop. Render the salvaged intermediate
            # result instead of a raw failure.
            await self._handle_task_partial(session_model)
            return

        if self._partial_pending:
            # The abort landed AFTER the model had already produced its closing
            # answer: LangGraph's ``tick()`` checks ``step > stop`` BEFORE it
            # computes whether any task remains, so the very step that would have
            # ended the graph raises GraphRecursionError instead. Falling through
            # here hands the run to the normal completion paths below (TaskEnd ->
            # success, otherwise direct-answer), which collect the ``output/``
            # deliverables the model did write. No apology: nothing failed.
            logger.info(
                "Step ceiling hit after the model had already closed out "
                f"({type(self._partial_error).__name__}); completing normally"
            )

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
            # NB: ``<g id='1'></g>`` here was a machine-translation artifact that
            # clobbered the ``{...}`` interpolation (same class of bug fixed in
            # 54be7498e for the async_run error log). Restore the real failure
            # reason — TaskEnd.answer carries the agent's final result/message.
            await self._handle_task_failure(session_model, f"Task execution failed: {self._final_result.answer}")

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
        answer = self._with_soft_landing_note(answer)

        session_model.status = SessionVersionStatusEnum.COMPLETED
        # A direct-answer completion with NO sub-tasks is a genuine trivial reply
        # (greeting / plain Q&A) — no deliverable expected, keep final_files empty.
        # But a weak model can plan (write_todos) yet finish without a TaskEnd or any
        # output/ file; that still warrants a report. So when todos were generated,
        # collect any output/ deliverable and otherwise synthesize one from the
        # answer (F035 backstop) — same as the _handle_task_success path.
        final_files = []
        execution_tasks = await self._state_manager.get_execution_tasks()
        # Only REAL planned todos warrant a *synthesized* report. The always-present
        # session-level pseudo task (F035 problem 2) must NOT count here, otherwise
        # a trivial greeting/Q&A that planned no todo would wrongly get a report.
        planned_tasks = [
            t for t in execution_tasks if not (getattr(t, "task_data", None) or {}).get("is_session_global")
        ]
        # Always collect real ``output/`` deliverables, even with no planned todos:
        # a simple "把报告转成 docx/pdf" turn calls export_docx/export_pdf (or
        # write_file) and finishes WITHOUT planning a todo. Gating collection on
        # planned_tasks dropped those files from the result panel ("暂无产物文件")
        # though they were written to the workspace. read_file_directory returns []
        # for an empty output/, so a greeting still yields nothing here.
        file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
        final_files = await linsight_execute_utils.get_final_result_file(
            session_model=session_model, file_details=file_details, baseline_paths=self._baseline_files
        )
        # Synthesize a fallback report ONLY when the model actually planned work but
        # produced no deliverable — never for a trivial greeting/Q&A with no output.
        if not final_files and planned_tasks:
            final_files = await linsight_execute_utils.build_fallback_report_file(
                session_model=session_model, answer=answer, file_dir=self.file_dir
            )
        session_model.output_result = {
            "answer": answer,
            "final_files": final_files,
            "all_from_session_files": [],
        }
        self._flag_phantom_deliverables(session_model, answer, final_files)
        await self._state_manager.set_session_version_info(session_model)
        # F035 problem 2: finalize the session pseudo task carrying any
        # planning/direct-answer steps so it isn't left stuck in_progress.
        await self._complete_session_pseudo_task(session_model)
        await self._converge_task_rows_on_completion()
        # F035 Track J: land the answer in the unified conversation stream.
        await linsight_execute_utils.persist_task_turn_message(session_model)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.FINAL_RESULT, data=session_model.model_dump())
        )
        logger.info(f"Task completed via direct-answer fallback ({len(final_files)} report files)")

    def _flag_phantom_deliverables(self, session_model, answer: str, final_files: list[dict]) -> None:
        """Record deliverables the answer claims but the run never produced.

        Diagnosis only — deliberately does NOT repair. The prompt already forbids
        claiming a save without write_file, so a phantom means the model ignored
        it, and that is worth measuring: an earlier revision answered the false
        claim by creating the file, which made the run look healthy and left no
        trace of how often it happens.
        """
        phantom = linsight_execute_utils.detect_phantom_deliverables(answer, final_files)
        if not phantom:
            return
        logger.warning(
            "[linsight-phantom-deliverable] session={} answer claims {} file(s) the run never wrote: {}",
            session_model.id,
            len(phantom),
            ", ".join(phantom),
        )
        session_model.output_result["phantom_deliverables"] = phantom

    def _with_soft_landing_note(self, answer: str) -> str:
        """Append the wrap-up note when the turn budget cut the run short.

        Applied to the NORMAL completion paths only: the partial-salvage path
        already carries its own step-limit preamble.
        """
        if not self._turn_budget.get("soft_landing"):
            return answer
        return f"{answer}\n\n{_SOFT_LANDING_NOTE}" if answer else _SOFT_LANDING_NOTE

    def _stash_partial_abort(self, e: BaseException) -> None:
        """Record an L3/L4 abort so ``_handle_task_completion`` renders a salvaged
        partial result instead of a raw failure. Shared by the fresh / resume /
        continue drivers so a tool loop or recursion ceiling is handled uniformly.
        """
        logger.warning(f"task aborted, salvaging partial result: {type(e).__name__}: {e}")
        self._partial_pending = True
        self._partial_error = e
        self._partial_salvage = getattr(e, "partial_result", None)

    async def _handle_task_partial(self, session_model: LinsightSessionVersion):
        """Render a salvaged partial result after an L3/L4 abort.

        The L3 tool-loop breaker (``LinsightToolLoopError``) carries a
        middleware-assembled ``partial_result`` (analysis conclusions + a trimmed
        digest of retrieved knowledge). A bare L4 ``GraphRecursionError`` has no
        such body, so we fall back to the last streamed assistant text. Either
        way, surface it as a NORMAL (COMPLETED) result with an apology preamble —
        the user gets meaningful output instead of a raw recursion error. Mirrors
        ``_handle_direct_answer_completion``. If nothing is salvageable, degrade to
        a friendly classified failure (never a raw dump).
        """
        # Copy follows the REAL cause: only the tool-loop breaker means "the model
        # kept calling a tool wrong"; a recursion ceiling means the step budget ran
        # out, which has nothing to do with the write tools.
        is_tool_loop = isinstance(self._partial_error, LinsightToolLoopError)
        body = (self._partial_salvage or "").strip() or (self._last_assistant_text or "").strip()
        if not body:
            no_salvage = _PARTIAL_NO_SALVAGE_TOOL_LOOP if is_tool_loop else _PARTIAL_NO_SALVAGE_STEP_LIMIT
            await self._handle_task_failure(session_model, no_salvage, exc=self._partial_error)
            return

        preamble = _PARTIAL_RESULT_PREAMBLE_TOOL_LOOP if is_tool_loop else _PARTIAL_RESULT_PREAMBLE_STEP_LIMIT
        answer = f"{preamble}\n\n{body}"
        session_model.status = SessionVersionStatusEnum.COMPLETED
        # Collect any output/ deliverable the model managed to write before looping;
        # otherwise synthesize a report from the salvaged answer (same backstop as
        # the success / direct-answer paths).
        file_details = await linsight_execute_utils.read_file_directory(self.file_dir)
        final_files = await linsight_execute_utils.get_final_result_file(
            session_model=session_model, file_details=file_details, baseline_paths=self._baseline_files
        )
        if not final_files:
            final_files = await linsight_execute_utils.build_fallback_report_file(
                session_model=session_model, answer=answer, file_dir=self.file_dir
            )
        session_model.output_result = {
            "answer": answer,
            "final_files": final_files,
            "all_from_session_files": [],
            # Marker so the frontend/analytics can tell this was a degraded run
            # even though it renders as a normal result (no frontend change required).
            "partial": True,
        }
        self._flag_phantom_deliverables(session_model, answer, final_files)
        await self._state_manager.set_session_version_info(session_model)
        await self._complete_session_pseudo_task(session_model)
        await self._converge_task_rows_on_completion()
        await linsight_execute_utils.persist_task_turn_message(session_model)
        await self._state_manager.push_message(
            MessageData(event_type=MessageEventType.FINAL_RESULT, data=session_model.model_dump())
        )
        logger.info(f"Task completed via partial-result salvage ({len(final_files)} files)")

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
            answer = self._with_soft_landing_note(answer)

            final_result_files = await linsight_execute_utils.get_final_result_file(
                session_model=session_model, file_details=file_details, baseline_paths=self._baseline_files
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
            self._flag_phantom_deliverables(session_model, answer, final_result_files)

            # Save session information and push messages
            await self._state_manager.set_session_version_info(session_model)
            # F035 problem 2: finalize the session pseudo task carrying any
            # planning/wrap-up steps so it isn't left stuck in_progress.
            await self._complete_session_pseudo_task(session_model)
            await self._converge_task_rows_on_completion()
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
    async def _terminate_unfinished_tasks(self):
        """Converge every non-terminal task row to TERMINATED.

        Named for what it DOES — the old name (``_set_tasks_failed``) described
        neither the action nor the status it writes. Three callers, three meanings,
        one action: user stop, task failure, and normal completion, where the model
        simply stopped updating todos it never finished.

        Rows already SUCCESS / FAILED / TERMINATED are left alone, so this is
        idempotent and can never downgrade a delivered result.
        """
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
            logger.warning("Error converging unfinished task rows: {}", e)

    async def _handle_task_failure(
        self, session_model: LinsightSessionVersion, error_msg: str, *, exc: Exception | None = None
    ):
        """Processing task failed.

        Classifies the failure (灵思LLM容错) into a stable ``error_type`` (e.g.
        ``content_filter`` / ``quota_exhausted`` / ``network_timeout``) so the
        frontend can render a localized, user-friendly card instead of the raw
        provider message. ``exc`` (the original exception) is preferred for
        precise classification; without it the message string is classified
        best-effort. The raw provider text is kept in ``detail`` for the
        "view details" disclosure. Vendor-agnostic — see ``llm_error_classifier``.
        """
        classified = classify_for_event(exc if exc is not None else error_msg)
        session_model.status = SessionVersionStatusEnum.FAILED
        session_model.output_result = {
            "error_message": error_msg,
            "error_code": classified.error_code,
            "error_type": classified.error_type,
            "detail": classified.detail,
        }
        await self._state_manager.set_session_version_info(session_model)
        # F035 Track J: still land a (failed) task turn in the unified stream so the
        # conversation isn't left with a dangling question; extra points to the SV
        # whose detail panel shows the failure.
        await linsight_execute_utils.persist_task_turn_message(session_model)

        # Converge every task row the run never finished
        await self._terminate_unfinished_tasks()

        # error_message event: keep ``error`` for backward compatibility (old
        # clients display it raw); new fields drive the classified friendly card.
        await self._state_manager.push_message(
            MessageData(
                event_type=MessageEventType.ERROR_MESSAGE,
                data={
                    "error": error_msg,
                    "error_code": classified.error_code,
                    "error_type": classified.error_type,
                    "detail": classified.detail,
                },
            )
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
            # Pass the exception object (not just str) so the classifier can unwrap
            # TaskExecutionError -> original provider cause for a precise error_type.
            await self._handle_task_failure(session_model, str(error), exc=error)
        except Exception as e:
            logger.error(f"Processing execution error failed: session_version_id={self.session_version_id}, error={e}")
