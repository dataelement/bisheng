"""Tool-owned tenant/state checks and opt-in saved OpenAPI execution."""

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.errcode.dsh import (
    DshToolPermissionDeniedError,
    DshToolPublicationInvalidError,
    DshToolServiceUnavailableError,
)
from bisheng.tool.domain.services.published_schema import PublishedSchema


class PublishedToolService:
    def __init__(self, repository, permission=None):
        self.repository = repository
        self.permission = permission

    async def verify(self, tenant_id, tool_id, user, action, tool_code=None):
        tool, category = await self.repository.snapshot(tool_id)
        if (
            tool is None
            or category is None
            or tool.tenant_id != tenant_id
            or category.tenant_id != tenant_id
            or tool.type != category.id
            or tool.is_delete
            or category.is_delete
            or tool.is_preset != 0
            or category.is_preset != 0
        ):
            raise DshToolPublicationInvalidError()
        permission = self.permission
        if permission is None:
            from bisheng.permission.application.business_authorization import check_business_action

            permission = check_business_action
        try:
            allowed = await permission(user, resource_type="tool", resource_id=category.id, action=action)
        except BaseErrorCode:
            raise DshToolServiceUnavailableError() from None
        if not allowed:
            raise DshToolPermissionDeniedError()
        schema = PublishedSchema.from_saved(tool, category)
        if tool_code == "bs_web_search":
            properties = schema.schema["properties"]
            if (
                set(properties) - {"query", "maxResults"}
                or set(schema.schema.get("required", [])) != {"query"}
                or properties.get("query", {}).get("type") != "string"
                or ("maxResults" in properties and properties["maxResults"].get("type") != "integer")
            ):
                raise DshToolPublicationInvalidError()
        return tool, category, schema

    async def prepare(self, tenant_id, user_id, publication, arguments):
        from bisheng.tool.domain.services.executor import ToolExecutor

        user = await ToolExecutor._build_permission_user(user_id, tenant_id)
        try:
            tool, category, schema = await self.verify(
                tenant_id, publication.tool_id, user, "use", publication.tool_code
            )
        except DshToolPublicationInvalidError:
            raise DshToolServiceUnavailableError() from None
        arguments = schema.validate(arguments)
        try:
            executor = await ToolExecutor.init_published_openapi(
                tool, category, schema, user_id=user_id, tool_code=publication.tool_code, limits=publication.limits
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
