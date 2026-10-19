"""Tenant/state checks for saved API tools, then the shared ToolExecutor entry."""

from langsmith import tracing_context
from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import (
    DshToolNotFoundError,
    DshToolPermissionDeniedError,
    DshToolServiceUnavailableError,
    DshToolUnsupportedError,
)
from bisheng.tool.domain.const import ToolPresetType
from bisheng.tool.domain.repositories.saved_tools import SavedToolRepository
from bisheng.tool.domain.services.bounded_openapi import BoundedOpenApiTools
from bisheng.tool.domain.services.executor import ToolExecutor, ToolInitializationError
from bisheng.tool.domain.services.saved_schema import SavedToolSchema


class SavedToolService:
    async def _load(self, tenant_id, tool_key):
        try:
            tool, category = await SavedToolRepository.load_by_name(tenant_id, tool_key)
        except SQLAlchemyError:
            raise DshToolServiceUnavailableError() from None
        if (
            tool is None
            or category is None
            or tool.tenant_id != tenant_id
            or category.tenant_id != tenant_id
            or tool.is_delete
            or category.is_delete
        ):
            raise DshToolNotFoundError()
        return tool, category

    async def prepare(self, tenant_id, user_id, tool_key, arguments, limits):
        tool, category = await self._load(tenant_id, tool_key)
        if tool.is_preset != ToolPresetType.API.value:
            raise DshToolUnsupportedError()
        try:
            # init_by_tool_id enforces the "use" permission before initialization.
            executor = await ToolExecutor.init_by_tool_id(
                tool=tool,
                app_id=tool_key,
                app_name="DSH tool invocation",
                app_type=ApplicationTypeEnum.DSH_DESKTOP,
                user_id=user_id,
                api_tool_factory=BoundedOpenApiTools.get_api_tool,
                max_output_bytes=limits.max_output_bytes,
                request_timeout=limits.timeout_seconds,
            )
        except PermissionError:
            raise DshToolPermissionDeniedError() from None
        except BaseErrorCode:
            raise DshToolServiceUnavailableError() from None
        except ToolInitializationError as error:
            logger.warning("Tool initialization failed tool={} cause={}", tool_key, type(error.__cause__).__name__)
            raise DshToolServiceUnavailableError() from None
        schema = SavedToolSchema.from_saved(tool, category)
        return executor, schema.validate(arguments)

    async def execute(self, executor, arguments):
        # Arguments are already validated; skip BaseTool's ambient callback/tracing setup.
        with tracing_context(enabled=False):
            return await executor._arun(config={"callbacks": []}, **arguments)
