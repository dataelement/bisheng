"""Build the code interpreter bound to an agent workspace (F078 design decision 10).

The tool comes from the built-in ``bisheng_code_interpreter`` row. When the row
is missing the platform has no code executor, and the run continues without
one (spec AC-09). A failure while building it — a broken config, or a user who
may not use the tool — is reported the same way but logged as an error, so the
run never loses the executor silently.

Build the tool only after the workspace is fully prepared: the E2B executor
copies in the files that exist at build time.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.linsight.domain.services.code_tool_config import bind_code_config_to_workspace
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor

CODE_INTERPRETER_TOOL_KEY = "bisheng_code_interpreter"


class CodeToolStatus(StrEnum):
    READY = "ready"
    MISSING = "missing"
    ERROR = "error"


@dataclass
class CodeToolResult:
    tool: BaseTool | None
    status: CodeToolStatus
    reason: str = ""


async def abuild_workspace_code_tool(
    *,
    file_dir: str,
    workspace_prefix: str,
    user_id: int,
    app_type: ApplicationTypeEnum,
    app_id: str,
    app_name: str,
) -> CodeToolResult:
    row = await GptsToolsDao.aget_tool_by_tool_key(tool_key=CODE_INTERPRETER_TOOL_KEY)
    if not row:
        return CodeToolResult(tool=None, status=CodeToolStatus.MISSING, reason="code interpreter is not configured")
    try:
        # Same extra source as ToolExecutor.parse_preset_tool_params: the tool row
        # first, then its category (the built-in-tool UI writes the category).
        tool_type = None
        if not row.extra and getattr(row, "type", None):
            tool_type = await GptsToolsDao.aget_one_tool_type(tool_type_id=row.type)
        code_config = ToolExecutor.parse_preset_extra(row, tool_type)
        row.extra = bind_code_config_to_workspace(code_config, file_dir, workspace_prefix)
        tool = await ToolExecutor.init_by_tool_id(
            tool=row,
            app_id=app_id,
            app_name=app_name,
            app_type=app_type,
            user_id=user_id,
        )
    except Exception as exc:
        logger.exception("act=agent_code_tool_build_failed user_id={} workspace={}", user_id, workspace_prefix)
        return CodeToolResult(tool=None, status=CodeToolStatus.ERROR, reason=str(exc))
    return CodeToolResult(tool=tool, status=CodeToolStatus.READY)
