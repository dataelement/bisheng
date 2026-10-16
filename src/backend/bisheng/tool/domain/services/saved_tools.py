"""Tool-owned tenant/state checks and opt-in saved OpenAPI execution."""

from sqlalchemy.exc import SQLAlchemyError

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import (
    DshToolNotFoundError,
    DshToolPermissionDeniedError,
    DshToolServiceUnavailableError,
    DshToolUnsupportedError,
)
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.saved_schema import SavedToolSchema


class SavedToolService:
    async def verify(self, tenant_id, tool_key, user_id):
        from bisheng.tool.domain.services.executor import ToolExecutor

        try:
            tool = await GptsToolsDao.aget_tool_by_tool_key(tool_key)
            category = await GptsToolsDao.aget_one_tool_type(tool.type) if tool else None
        except SQLAlchemyError:
            raise DshToolServiceUnavailableError() from None
        if (
            tool is None
            or category is None
            or tool.tenant_id != tenant_id
            or category.tenant_id != tenant_id
            or tool.type != category.id
            or tool.is_delete
            or category.is_delete
        ):
            raise DshToolNotFoundError()
        try:
            await ToolExecutor._ensure_use_permission_async(category, user_id)
        except PermissionError:
            raise DshToolPermissionDeniedError() from None
        except BaseErrorCode:
            raise DshToolServiceUnavailableError() from None
        if tool.is_preset != 0 or category.is_preset != 0:
            raise DshToolUnsupportedError()
        schema = SavedToolSchema.from_saved(tool, category)
        return tool, category, schema

    async def prepare(self, tenant_id, user_id, tool_key, arguments, limits):
        from bisheng.tool.domain.services.executor import ToolExecutor

        tool, category, schema = await self.verify(tenant_id, tool_key, user_id)
        arguments = schema.validate(arguments)
        try:
            executor = await ToolExecutor.init_saved_openapi(
                tool, category, schema, user_id=user_id, tool_code=tool_key, limits=limits
            )
        except PermissionError:
            raise DshToolPermissionDeniedError() from None
        except BaseErrorCode:
            raise DshToolServiceUnavailableError() from None
        return executor, arguments

    async def execute(self, executor, arguments):
        from langsmith import tracing_context

        # Full schema validation precedes this call. Use the existing execution
        # and metadata telemetry wrapper without BaseTool's ambient callback setup.
        with tracing_context(enabled=False):
            return await executor._arun(config={"callbacks": []}, **arguments)
