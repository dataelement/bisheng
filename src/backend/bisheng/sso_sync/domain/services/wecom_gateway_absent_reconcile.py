"""Reconcile WeCom users absent from a Gateway full import batch."""

from __future__ import annotations

import logging
from typing import Set

from sqlalchemy import update
from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.user.domain.models.user import User, UserDao

logger = logging.getLogger(__name__)


async def disable_wecom_users_absent_from_import(
    imported_external_ids: Set[str],
) -> int:
    """Disable active WeCom users not present in the current Gateway batch.

    The Gateway endpoint sends a full user snapshot. Any existing WeCom user
    omitted from that snapshot has left the upstream org and must be disabled.
    Token versions are bumped so existing sessions are forced out.
    """
    imported = {
        str(one).strip()
        for one in (imported_external_ids or set())
        if one is not None and str(one).strip()
    }

    async with get_async_db_session() as session:
        stmt = select(User.user_id).where(
            User.source == WECOM_SOURCE,
            User.delete == 0,
        )
        if imported:
            stmt = stmt.where(~User.external_id.in_(imported))

        rows = (await session.exec(stmt)).all()
        user_ids = [
            int(row[0] if isinstance(row, tuple) else row)
            for row in rows
        ]
        if not user_ids:
            return 0

        await session.exec(
            update(User)
            .where(User.user_id.in_(user_ids))
            .values(delete=1, disable_source='wecom_absent')
        )
        await session.commit()

    disabled = 0
    for user_id in user_ids:
        try:
            await UserDao.aincrement_token_version(user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'Failed to bump token_version for absent WeCom user %s: %s',
                user_id,
                exc,
            )
        disabled += 1
    return disabled
