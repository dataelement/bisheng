"""User-owned read adapter for model-scoped DSH administration."""

from bisheng.core.database import get_async_db_session
from bisheng.user.domain.repositories.dsh_profile import UserDshProfileRepository


async def list_dsh_access_users(*, after_user_id: int = 0, limit: int = 20, keyword: str = "") -> list[tuple[int, str]]:
    async with get_async_db_session() as session:
        return await session.run_sync(
            lambda sync: UserDshProfileRepository.access_users(
                sync,
                after_user_id=after_user_id,
                limit=limit,
                keyword=keyword,
            )
        )
