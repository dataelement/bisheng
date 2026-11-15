"""Bind the existing session service at the authenticated transport boundary."""

from dataclasses import dataclass

from bisheng.core.session_activity import AuthenticatedActivity
from bisheng.dsh.domain.services.access import DshPrincipal
from bisheng.dsh.domain.services.local_session import DshLocalSessionService


@dataclass(frozen=True)
class DshSessionActivity(AuthenticatedActivity):
    sessions: DshLocalSessionService
    principal: DshPrincipal

    async def record(self) -> None:
        await self.sessions.record_activity(self.principal)
