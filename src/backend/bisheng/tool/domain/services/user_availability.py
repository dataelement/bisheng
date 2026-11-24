"""Account availability is enforced alongside resource visibility permission."""

from bisheng.tool.domain.repositories.user_availability import UserToolAvailabilityRepository


def manages_availability(tool) -> bool:
    return getattr(tool, "is_preset", None) in (0, 1, 2) and bool(getattr(tool, "id", None))


def uses_account_availability(app_type) -> bool:
    """Personal Chat and Work preferences are separate from published applications."""
    return app_type in ("daily_chat", "linsight", "dsh_desktop")


class UserToolAvailabilityService:
    """A user's personal on/off switch for a tool.

    F005: a tool the workstation config auto-enables ignores the switch; the
    user cannot see it to turn it back on. The config is read only when a
    personal opt-out is actually on record, so the common path costs nothing.
    """

    def __init__(self, user_id: int, repository=None):
        self.user_id = user_id
        self.repository = repository or UserToolAvailabilityRepository()

    @staticmethod
    async def _aauto_enabled_ids() -> set[int]:
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        return await WorkStationService.aauto_enabled_tool_ids()

    @staticmethod
    def _auto_enabled_ids_sync() -> set[int]:
        from bisheng.workstation.domain.services.workstation_service import WorkStationService

        return WorkStationService.auto_enabled_tool_ids()

    async def disabled_ids(self, tools) -> set[int]:
        if any(manages_availability(tool) for tool in tools):
            disabled = set(await self.repository.disabled_ids(self.user_id))
            if disabled:
                disabled -= await self._aauto_enabled_ids()
            return disabled
        return set()

    async def ensure_enabled(self, tool_id: int):
        if (
            tool_id in await self.repository.disabled_ids(self.user_id)
            and tool_id not in await self._aauto_enabled_ids()
        ):
            raise PermissionError("Tool is turned off for this account")

    def is_enabled_sync(self, tool_id: int) -> bool:
        return self.repository.enabled_sync(self.user_id, tool_id) or tool_id in self._auto_enabled_ids_sync()

    def ensure_enabled_sync(self, tool_id: int):
        if not self.is_enabled_sync(tool_id):
            raise PermissionError("Tool is turned off for this account")

    async def save(self, tool_id: int, enabled: bool):
        await self.repository.save(self.user_id, tool_id, enabled)
