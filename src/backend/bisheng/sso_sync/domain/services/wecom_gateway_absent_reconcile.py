"""Reconcile WeCom users absent from a Gateway full import batch."""

from __future__ import annotations

import logging
from typing import List, Set, Tuple

from sqlalchemy import delete, update
from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import UserDepartment
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.sso_sync.domain.constants import WECOM_SOURCE
from bisheng.user.domain.models.user import User, UserDao

logger = logging.getLogger(__name__)


def _normalize_int_ids(rows) -> List[int]:
    """Normalize ``select(User.user_id)`` rows to plain ints across drivers."""
    out: List[int] = []
    for row in rows or []:
        if row is None:
            continue
        if isinstance(row, (list, tuple)):
            out.append(int(row[0]))
            continue
        try:
            out.append(int(row[0]))
        except (TypeError, KeyError, IndexError):
            out.append(int(row))
    return out


async def disable_wecom_users_absent_from_import(
    imported_external_ids: Set[str],
) -> int:
    """Disable active WeCom users not present in the current Gateway batch.

    The Gateway endpoint sends a full user snapshot. Any existing WeCom user
    omitted from that snapshot has left the upstream org: soft-disable the
    account, **remove all department memberships** (PRD 8c — no longer in the
    personnel list), revoke persisted SSO admin grants, and drop OpenFGA
    member/admin tuples. Token versions are bumped so existing sessions are
    forced out.
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

        result = await session.exec(stmt)
        user_ids = _normalize_int_ids(result.all())
        if not user_ids:
            return 0

        ud_result = await session.exec(
            select(UserDepartment.department_id, UserDepartment.user_id).where(
                UserDepartment.user_id.in_(user_ids),
            ),
        )
        dept_user_pairs: List[Tuple[int, int]] = []
        for row in ud_result.all():
            try:
                dept_id = int(row[0])
                uid = int(row[1])
            except (TypeError, ValueError, IndexError):
                continue
            dept_user_pairs.append((dept_id, uid))

        await session.execute(
            update(User)
            .where(User.user_id.in_(user_ids))
            .values(delete=1, disable_source='wecom_absent'),
        )
        await session.execute(
            delete(UserDepartment).where(UserDepartment.user_id.in_(user_ids)),
        )
        await session.execute(
            delete(DepartmentAdminGrant).where(
                DepartmentAdminGrant.user_id.in_(user_ids),
            ),
        )
        await session.commit()

    ops: list = []
    seen: set[Tuple[int, int]] = set()
    for dept_id, uid in dept_user_pairs:
        key = (dept_id, uid)
        if key in seen:
            continue
        seen.add(key)
        ops.extend(DepartmentChangeHandler.on_member_removed(dept_id, uid))
        ops.extend(DepartmentChangeHandler.on_admin_removed(dept_id, [uid]))
    if ops:
        await DepartmentChangeHandler.execute_async(ops)

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
