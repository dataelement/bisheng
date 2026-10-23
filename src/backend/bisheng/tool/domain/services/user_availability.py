"""Account availability is enforced alongside resource use permission."""

from bisheng.tool.domain.repositories.user_availability import UserToolAvailabilityRepository


def manages_availability(tool) -> bool:
    return getattr(tool, "is_preset", None) in (0, 1, 2) and bool(getattr(tool, "id", None))


def uses_account_availability(app_type) -> bool:
    """Personal Chat and Work preferences are separate from published applications."""
    return app_type in ("daily_chat", "linsight", "dsh_desktop")


class UserToolAvailabilityService:
    def __init__(self, user_id: int, repository=None):
        self.user_id = user_id
        self.repository = repository or UserToolAvailabilityRepository()

    async def disabled_ids(self, tools) -> set[int]:
        if any(manages_availability(tool) for tool in tools):
            return await self.repository.disabled_ids(self.user_id)
        return set()

    async def ensure_enabled(self, tool_id: int):
        if tool_id in await self.repository.disabled_ids(self.user_id):
            raise PermissionError("Tool is turned off for this account")

    def is_enabled_sync(self, tool_id: int) -> bool:
        return self.repository.enabled_sync(self.user_id, tool_id)

    def ensure_enabled_sync(self, tool_id: int):
        if not self.is_enabled_sync(tool_id):
            raise PermissionError("Tool is turned off for this account")

    async def save(self, tool_id: int, enabled: bool):
        await self.repository.save(self.user_id, tool_id, enabled)
