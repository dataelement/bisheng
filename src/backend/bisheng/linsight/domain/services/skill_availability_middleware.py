"""Recheck an executing task's skill grants before each model or tool operation."""

from langchain.agents.middleware.types import AgentMiddleware

from bisheng.linsight.domain.services.user_skills import UserSkillsService
from bisheng.utils.async_utils import run_async_safe


class SkillAvailabilityMiddleware(AgentMiddleware):
    def __init__(self, user_id, names):
        self.user_id = user_id
        self.names = set(names)

    async def ensure_available(self):
        allowed = {row.name for row, _ in await UserSkillsService(self.user_id).records()}
        if self.names - allowed:
            raise PermissionError("A selected skill is unavailable. Select enabled skills and retry.")

    async def awrap_model_call(self, request, handler):
        await self.ensure_available()
        return await handler(request)

    async def awrap_tool_call(self, request, handler):
        await self.ensure_available()
        return await handler(request)

    def wrap_model_call(self, request, handler):
        run_async_safe(self.ensure_available())
        return handler(request)

    def wrap_tool_call(self, request, handler):
        run_async_safe(self.ensure_available())
        return handler(request)
