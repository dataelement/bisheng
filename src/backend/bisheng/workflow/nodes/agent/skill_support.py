"""Skills for the workflow agent node (F078).

``AgentNodeSkills`` turns the node's configuration into an ``AgentRunSpec`` and
drives one ``AgentRunner`` per run. The node stays synchronous: the async
preparation and clean-up run through ``run_async_safe`` (design decision 4).

Errors a user must see with their own code (11077-11079) are re-raised as
``AgentSkillRunError``, whose text carries the error as JSON behind a marker so
the workflow failure event can hand the code and the skill name to the
frontend for translation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from bisheng.agent_runtime.domain.services.agent_runner import AgentRunner, AgentRunSpec, RunnerPlan
from bisheng.agent_runtime.domain.services.agent_workspace import WorkspaceKey
from bisheng.agent_runtime.domain.services.deliverables import DeliverableTarget
from bisheng.agent_runtime.domain.services.tmp_session import (
    TmpSessionService,
    tmp_deliverable_dir,
    tmp_session_key,
)
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.linsight import (
    AgentSkillDeletedError,
    AgentSkillDisabledError,
    AgentSkillExecutorUnsupportedError,
)
from bisheng.core.cache.utils import file_download
from bisheng.utils import generate_uuid
from bisheng.utils.async_utils import run_async_safe

AGENT_SKILL_ERROR_MARKER = "-- agent skill error --"
NOTICE_DELIVERABLES_FAILED = "deliverables_failed"
FILES_URL_PREFIX = "/api/v1/agent-runtime/files"
# Copying skills and pulling a workspace can take a while; run_async_safe's
# default 10-second timeout is far too short (design pitfall 15).
PREPARE_TIMEOUT_SECONDS = 600
FINISH_TIMEOUT_SECONDS = 600

_USER_FACING_ERRORS = (AgentSkillDisabledError, AgentSkillDeletedError, AgentSkillExecutorUnsupportedError)
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


class AgentSkillRunError(Exception):
    """A skill error that must reach the user with its own code."""

    def __init__(self, error: BaseErrorCode, node_name: str) -> None:
        self.error = error
        super().__init__(f"{node_name}: {error.message} {AGENT_SKILL_ERROR_MARKER}{error.to_json_str()}")


def parse_agent_skill_error(reason: str | None) -> dict | None:
    """Return the ``{status_code, status_message, data}`` dict carried by a failure reason."""
    if not reason or AGENT_SKILL_ERROR_MARKER not in reason:
        return None
    try:
        return json.loads(reason.split(AGENT_SKILL_ERROR_MARKER, 1)[1])
    except ValueError:
        return None


def format_deliverables(files: list[dict]) -> str:
    """Text value of the node's deliverables variable: one ``name: url`` per line."""
    return "\n".join(f"{one['file_name']}: {one['file_url']}" for one in files)


@dataclass
class AgentNodeSkillRun:
    """State of one run: the plan the agent is built from, then the result."""

    runner: AgentRunner
    plan: RunnerPlan
    files: list[dict] = field(default_factory=list)


class AgentNodeSkills:
    def __init__(self, node) -> None:
        self.node = node
        params = node.node_params
        self.skill_names: list[str] = [one["key"] for one in params.get("skill_list") or [] if one.get("key")]
        self.input_file_vars: list[str] = list(params.get("input_files") or [])
        # Without a chat id or a temporary session (an unknown caller), fall
        # back to a fresh temporary session so files stay downloadable by the user.
        self._tmp_session_id = node.tmp_session_id or (None if node.chat_id else generate_uuid())

    @property
    def enabled(self) -> bool:
        return bool(self.skill_names)

    @property
    def surface(self) -> str:
        return f"wf-{_UNSAFE.sub('_', self.node.id)}"

    def workspace_key(self) -> WorkspaceKey:
        if self.node.chat_id:
            return WorkspaceKey.formal(self.node.chat_id, self.surface)
        return WorkspaceKey.temp(self._tmp_session_id, self.surface)

    def deliverable_target(self) -> DeliverableTarget:
        node = self.node
        if node.chat_id:
            session_key = node.chat_id
            object_dir = f"chat/{node.user_id}/agent/{node.chat_id}"
            use_tmp = False
        else:
            session_key = tmp_session_key(self._tmp_session_id)
            object_dir = tmp_deliverable_dir(self._tmp_session_id)
            use_tmp = True
        return DeliverableTarget(
            object_dir=object_dir,
            use_tmp_bucket=use_tmp,
            url_for=lambda file_id: f"{FILES_URL_PREFIX}/{session_key}/{file_id}",
        )

    def collect_input_files(self) -> list[tuple[str, bytes]]:
        """Download the upstream file variables the node copies into ``uploads/``."""
        pairs: list[tuple[str, bytes]] = []
        for var in self.input_file_vars:
            value = self.node.get_other_node_variable(var)
            paths = value if isinstance(value, list) else [value]
            for path in paths:
                if not path or not isinstance(path, str):
                    continue
                local_path, file_name = file_download(path)
                with open(local_path, "rb") as f:
                    pairs.append((file_name, f.read()))
        return pairs

    def _spec(self, executor_type: str, tools: list) -> AgentRunSpec:
        node = self.node
        return AgentRunSpec(
            tenant_id=node.tenant_id,
            user_id=node.user_id,
            workspace_key=self.workspace_key(),
            skill_names=self.skill_names,
            executor_type=executor_type,
            tools=tools,
            input_files=self.collect_input_files(),
            app_type=ApplicationTypeEnum.WORKFLOW,
            app_id=node.workflow_id,
            app_name=node.workflow_name or node.workflow_id,
            deliverable_target=self.deliverable_target(),
        )

    def prepare(self, executor_type: str, tools: list) -> AgentNodeSkillRun:
        runner = AgentRunner(self._spec(executor_type, tools))

        async def _prepare() -> RunnerPlan:
            if self._tmp_session_id is not None:
                from bisheng.core.cache.redis_manager import get_redis_client
                from bisheng.core.storage.minio.minio_manager import get_minio_storage

                service = TmpSessionService(redis=await get_redis_client(), minio=await get_minio_storage())
                await service.aregister(self._tmp_session_id, user_id=self.node.user_id, tenant_id=self.node.tenant_id)
            return await runner.aprepare()

        try:
            plan = run_async_safe(_prepare(), timeout=PREPARE_TIMEOUT_SECONDS)
        except _USER_FACING_ERRORS as error:
            raise AgentSkillRunError(error, self.node.name) from error
        return AgentNodeSkillRun(runner=runner, plan=plan)

    def finish(self, run: AgentNodeSkillRun) -> list[dict]:
        try:
            run.files = run_async_safe(run.runner.afinish(), timeout=FINISH_TIMEOUT_SECONDS)
        except Exception:
            # Losing the files must not lose the answer the user already has, but
            # it must not be silent either: the user gets a notice (C8).
            logger.exception("act=agent_node_finish_failed node_id={}", self.node.id)
            run.files = []
            run.plan.notices.append(NOTICE_DELIVERABLES_FAILED)
        return run.files
