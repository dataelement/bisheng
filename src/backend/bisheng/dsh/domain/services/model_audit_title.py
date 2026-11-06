"""Optional title I/O is bounded and independent of the model call lifecycle."""

import asyncio

from sqlalchemy.exc import IntegrityError

from bisheng.dsh.domain.services.access import principal_scope
from bisheng.dsh.domain.services.profile import profile_scope
from bisheng.dsh.infrastructure.model_audit_blocking import run_audit_blocking


class DshModelAuditTitleService:
    def __init__(self, modes, repository_scope):
        self.modes, self.repository_scope = modes, repository_scope

    async def update(self, principal, command):
        with principal_scope(principal), profile_scope(int(principal.tenant_id)):
            mode = await self.modes.read_effective()
            if mode.read_failed:
                return {"status": "DISABLED"}

            def write():
                for attempt in range(2):
                    try:
                        with self.repository_scope() as repository:
                            result = repository.update_title(int(principal.user_id), command)
                        # Acknowledgement follows successful transaction commit.
                        return result
                    except IntegrityError:
                        if attempt:
                            raise

            async with asyncio.timeout(5):
                return await run_audit_blocking(write)
