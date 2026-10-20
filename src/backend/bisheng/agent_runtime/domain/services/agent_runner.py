"""Prepare and finish one skill-capable agent run (F078 design decisions 1, 3, 10).

Workflow agent nodes and assistants build their agent with
``langchain.agents.create_agent`` and pass in whatever ``aprepare`` returns.
Without skills the plan is empty — no middleware, no workspace, no executor —
so the agent behaves exactly as before (spec AC-25). With skills the plan adds:

- ``FilesystemMiddleware`` over the MinIO-backed workspace (file tools);
- ``SkillsMiddleware`` over the local cache directory (advertises the skills);
- ``SkillPromptMiddleware`` (the rules for using skills);
- the invalid tool-call repair middleware, last on purpose: its ``after_model``
  hook must see the model output first;
- the code interpreter bound to the workspace, replacing a copy the author may
  have added to the tool list.

``afinish`` always runs the clean-up, even when collecting deliverables fails;
a failed ``aprepare`` runs the same clean-up before it raises.

Both coroutines set the tenant context themselves: a sync caller runs them
through ``run_async_safe`` on a background loop, which does not inherit the
caller's context variables.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.agent_runtime.domain.services.agent_workspace import AgentWorkspace, PreparedWorkspace, WorkspaceKey
from bisheng.agent_runtime.domain.services.code_tool import (
    CODE_INTERPRETER_TOOL_KEY,
    CodeToolResult,
    CodeToolStatus,
    abuild_workspace_code_tool,
)
from bisheng.agent_runtime.domain.services.deliverables import DeliverableTarget, acollect_deliverables
from bisheng.agent_runtime.domain.services.skill_prompt_middleware import SkillPromptMiddleware, SkillPromptVariant
from bisheng.agent_runtime.domain.services.skill_resolver import resolve_skills
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.linsight import AgentSkillExecutorUnsupportedError
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id
from bisheng.linsight.domain.services.skill_provisioning import WORKSPACE_SKILLS_DIR
from bisheng_langchain.gpts.tools.code_interpreter.local_run_registry import release_local_run

REACT_EXECUTOR = "ReAct"
NOTICE_CODE_EXECUTOR_MISSING = "code_executor_missing"


@dataclass
class AgentRunSpec:
    tenant_id: int
    user_id: int
    workspace_key: WorkspaceKey
    skill_names: list[str] | None
    executor_type: str
    tools: list[BaseTool]
    input_files: list[tuple[str, bytes]]
    app_type: ApplicationTypeEnum
    app_id: str
    app_name: str
    # None means: do not collect deliverables.
    deliverable_target: DeliverableTarget | None = None


@dataclass
class RunnerPlan:
    middleware: list
    tools: list[BaseTool]
    notices: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    prompt_variant: SkillPromptVariant | None = None


def _filesystem_middleware(backend):
    from deepagents.middleware.filesystem import FilesystemMiddleware

    return FilesystemMiddleware(backend=backend)


def _skills_middleware(file_dir: str):
    # The workspace backend lists only files, never directories, so a
    # SkillsMiddleware on top of it would discover no skill. List the local
    # cache instead; the model still reads /skills/<name>/SKILL.md through the
    # workspace file tools.
    from deepagents.backends.filesystem import FilesystemBackend
    from deepagents.middleware.skills import SkillsMiddleware

    return SkillsMiddleware(
        backend=FilesystemBackend(root_dir=file_dir, virtual_mode=True),
        sources=[(f"/{WORKSPACE_SKILLS_DIR}/", "Skills")],
    )


def _repair_middleware(tools: list):
    from bisheng.linsight.domain.services.invalid_tool_call_middleware import (
        build_invalid_tool_call_repair_middleware,
    )

    return build_invalid_tool_call_repair_middleware(tools=tools, is_subagent=False)


class AgentRunner:
    def __init__(
        self,
        spec: AgentRunSpec,
        *,
        minio=None,
        code_tool_builder: Callable[..., Awaitable[CodeToolResult]] = abuild_workspace_code_tool,
    ) -> None:
        self.spec = spec
        self._minio = minio
        self._code_tool_builder = code_tool_builder
        self._workspace: AgentWorkspace | None = None
        self._prepared: PreparedWorkspace | None = None
        self._code_tool: BaseTool | None = None

    @property
    def uses_skills(self) -> bool:
        return bool(self.spec.skill_names)

    async def _aminio(self):
        if self._minio is None:
            from bisheng.core.storage.minio.minio_manager import get_minio_storage

            self._minio = await get_minio_storage()
        return self._minio

    async def aprepare(self) -> RunnerPlan:
        spec = self.spec
        if not self.uses_skills:
            return RunnerPlan(middleware=[], tools=list(spec.tools))
        if spec.executor_type == REACT_EXECUTOR:
            raise AgentSkillExecutorUnsupportedError()

        token = set_current_tenant_id(spec.tenant_id)
        try:
            rows = await resolve_skills(spec.skill_names)
            minio = await self._aminio()
            self._workspace = AgentWorkspace(key=spec.workspace_key, minio=minio, tenant_id=spec.tenant_id)
            self._prepared = await self._workspace.aprepare(skills=rows, input_files=spec.input_files)
            code_result = await self._code_tool_builder(
                file_dir=self._prepared.file_dir,
                workspace_prefix=spec.workspace_key.object_prefix.rstrip("/"),
                user_id=spec.user_id,
                app_type=spec.app_type,
                app_id=spec.app_id,
                app_name=spec.app_name,
            )
        except BaseException:
            # The caller never gets a plan to finish, so release what was set up here.
            await self._arelease()
            raise
        finally:
            current_tenant_id.reset(token)

        notices: list[str] = []
        tools = [tool for tool in spec.tools if tool.name != CODE_INTERPRETER_TOOL_KEY]
        if code_result.status is CodeToolStatus.READY:
            self._code_tool = code_result.tool
            tools.append(code_result.tool)
        else:
            notices.append(NOTICE_CODE_EXECUTOR_MISSING)

        if self._code_tool is not None:
            variant = SkillPromptVariant.WITH_EXECUTOR
        else:
            variant = SkillPromptVariant.NO_EXECUTOR

        middleware = [
            _filesystem_middleware(self._prepared.backend),
            _skills_middleware(self._prepared.file_dir),
            SkillPromptMiddleware(variant),
            _repair_middleware(tools),
        ]
        logger.info(
            "act=agent_runtime_run phase=prepare svid={} run_id={} skills={} executor={} notices={}",
            spec.workspace_key.svid,
            self._workspace.run_id,
            self._prepared.skill_names,
            code_result.status.value,
            notices,
        )
        return RunnerPlan(
            middleware=middleware,
            tools=tools,
            notices=notices,
            skill_names=self._prepared.skill_names,
            prompt_variant=variant,
        )

    async def afinish(self) -> list[dict]:
        """Collect the run's deliverables, then release every local resource."""
        if self._workspace is None or self._prepared is None:
            return []
        spec = self.spec
        token = set_current_tenant_id(spec.tenant_id)
        files: list[dict] = []
        try:
            if spec.deliverable_target is not None:
                files = await acollect_deliverables(
                    await self._aminio(),
                    self._prepared.file_dir,
                    self._prepared.baseline,
                    spec.deliverable_target,
                )
            logger.info(
                "act=agent_runtime_run phase=finish svid={} run_id={} deliverables={}",
                spec.workspace_key.svid,
                self._workspace.run_id,
                len(files),
            )
            return files
        finally:
            await self._arelease()
            current_tenant_id.reset(token)

    async def _arelease(self) -> None:
        """Release the local run directory and the executor."""
        if self._workspace is None:
            return
        svid = self.spec.workspace_key.svid
        try:
            if self._code_tool is not None:
                await asyncio.to_thread(self._code_tool.close)
            if self._prepared is not None:
                # Frees the retained local-isolation run dir and its uid.
                await asyncio.to_thread(release_local_run, self._prepared.file_dir)
        except Exception:
            logger.exception("act=agent_runtime_release_failed svid={}", svid)
        self._workspace.cleanup_local()
