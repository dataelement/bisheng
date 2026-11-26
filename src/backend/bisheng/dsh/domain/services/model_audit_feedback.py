"""Optional rating I/O stays off the model call path."""

import asyncio

from sqlalchemy.exc import IntegrityError

from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking


class DshModelAuditFeedbackService:
    def __init__(self, modes, repository_scope):
        self.modes, self.repository_scope = modes, repository_scope

    async def apply(self, principal, command):
        with principal_scope(principal), profile_scope(int(principal.tenant_id)):
            mode = await self.modes.read_effective()
            if mode.read_failed:
                return {"status": "DISABLED"}

            def write():
                for attempt in range(2):
                    try:
                        with self.repository_scope() as repository:
                            result = repository.apply_feedback(int(principal.user_id), command)
                        return result
                    except IntegrityError:
                        if attempt:
                            raise

            async with asyncio.timeout(5):
                return await run_audit_blocking(write)
