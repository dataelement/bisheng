"""Transaction boundary for enterprise policy changes."""

import asyncio

from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.user.application.avatar import read_visible_user_avatar_urls


async def policy_transaction(callback):
    def execute():
        from bisheng.core.database import get_sync_db_session

        with get_sync_db_session() as session:
            result = callback(UnifiedPolicyRepository(session))
            session.commit()
            return result

    return await asyncio.to_thread(execute)


async def with_visibility_avatars(payload: dict, tenant_id: int) -> dict:
    """Decorate the visible model's authorized user labels after the policy transaction."""
    users = payload.get("users") or []
    avatars = await read_visible_user_avatar_urls((tenant_id, user["value"]) for user in users)
    if not avatars:
        return payload
    return {
        **payload,
        "users": [
            {**user, "avatar": avatars[(tenant_id, user["value"])]} if (tenant_id, user["value"]) in avatars else user
            for user in users
        ],
    }
