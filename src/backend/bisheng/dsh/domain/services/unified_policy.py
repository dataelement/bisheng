"""Transaction boundary for enterprise policy changes."""

import asyncio

from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository


async def policy_transaction(callback):
    def execute():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            result = callback(UnifiedPolicyRepository(session))
            session.commit()
            return result

    return await asyncio.to_thread(execute)
