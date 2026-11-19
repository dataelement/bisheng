"""Read display avatars for already-authorized user and tenant pairs."""

import asyncio
from collections.abc import Iterable

from loguru import logger
from sqlalchemy.exc import SQLAlchemyError

from bisheng.core.context.base import ContextError
from bisheng.user.application.runtime_identity import read_current_person_records


async def read_visible_user_avatar_urls(identity_pairs: Iterable[tuple[int, int]]) -> dict[tuple[int, int], str]:
    """Sign current avatars only for users whose active identity matches a requested tenant."""
    requested = {(tenant_id, user_id) for tenant_id, user_id in identity_pairs if tenant_id > 0 and user_id > 0}
    if not requested:
        return {}

    try:
        records = await read_current_person_records({user_id for _, user_id in requested})
    except (ContextError, SQLAlchemyError) as error:
        # Unknown membership cannot authorize a link. The callers can still show their rows.
        logger.warning("Avatar identity lookup unavailable ({})", type(error).__name__)
        return {}

    avatars: dict[tuple[int, int], str] = {}
    for user_id, (user, state, tenant_id) in records.items():
        if user is None or state != "active" or tenant_id is None or (tenant_id, user_id) not in requested:
            continue
        avatar = (user.avatar or "").strip()
        if avatar:
            avatars[tenant_id, user_id] = avatar

    if not avatars:
        return {}
    from bisheng.user.domain.services.user import UserService

    urls = await asyncio.gather(
        *(UserService.get_display_avatar_url(user_id, avatar) for (_, user_id), avatar in avatars.items())
    )
    return {pair: url for pair, url in zip(avatars, urls, strict=True) if url}
