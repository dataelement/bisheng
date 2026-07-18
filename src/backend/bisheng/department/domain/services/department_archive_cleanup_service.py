"""Best-effort cleanup after externally managed departments are archived."""

from __future__ import annotations

import logging

from sqlalchemy import delete
from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.department import Department, UserDepartment
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.database.models.role import Role
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.user.domain.models.user_role import UserRole

logger = logging.getLogger(__name__)


class DepartmentArchiveCleanupService:
    """Clean references that should not survive an archived department.

    Archive is a soft delete, so the department row remains for audit/relink.
    Memberships, department-admin grants, and department-scoped roles are
    removed because active permission paths must no longer resolve through the
    archived node.
    """

    @classmethod
    async def arun_for_archived_department(
        cls,
        department_id: int,
        reason: str = '',
    ) -> None:
        dept_id = int(department_id)
        try:
            cleanup = await cls._collect_and_delete_mysql_refs(dept_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'archive mysql cleanup failed for dept=%s reason=%s: %s',
                dept_id,
                reason,
                exc,
            )
            cleanup = {
                'parent_id': None,
                'member_user_ids': [],
                'admin_user_ids': [],
            }

        try:
            ops = []
            parent_id = cleanup.get('parent_id')
            if parent_id is not None:
                ops.extend(DepartmentChangeHandler.on_archived(dept_id, int(parent_id)))
            ops.extend(DepartmentChangeHandler.on_purged(
                dept_id,
                cleanup.get('member_user_ids') or [],
                cleanup.get('admin_user_ids') or [],
            ))
            await DepartmentChangeHandler.execute_async(ops)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'archive fga cleanup failed for dept=%s reason=%s: %s',
                dept_id,
                reason,
                exc,
            )

    @classmethod
    async def _collect_and_delete_mysql_refs(cls, department_id: int) -> dict:
        async with get_async_db_session() as session:
            dept = (await session.exec(
                select(Department).where(Department.id == department_id)
            )).first()
            if dept is None:
                return {
                    'parent_id': None,
                    'member_user_ids': [],
                    'admin_user_ids': [],
                }

            member_user_ids = [
                int(row[0] if isinstance(row, tuple) else row)
                for row in (await session.exec(
                    select(UserDepartment.user_id).where(
                        UserDepartment.department_id == department_id,
                    )
                )).all()
            ]
            admin_user_ids = [
                int(row[0] if isinstance(row, tuple) else row)
                for row in (await session.exec(
                    select(DepartmentAdminGrant.user_id).where(
                        DepartmentAdminGrant.department_id == department_id,
                    )
                )).all()
            ]
            scoped_role_ids = [
                int(row[0] if isinstance(row, tuple) else row)
                for row in (await session.exec(
                    select(Role.id).where(Role.department_id == department_id)
                )).all()
            ]

            if scoped_role_ids:
                await session.execute(
                    delete(UserRole).where(UserRole.role_id.in_(scoped_role_ids))
                )
                await session.execute(
                    delete(Role).where(Role.id.in_(scoped_role_ids))
                )
            await session.execute(
                delete(DepartmentAdminGrant).where(
                    DepartmentAdminGrant.department_id == department_id,
                )
            )
            await session.execute(
                delete(UserDepartment).where(
                    UserDepartment.department_id == department_id,
                )
            )
            await session.commit()

        return {
            'parent_id': getattr(dept, 'parent_id', None),
            'member_user_ids': member_user_ids,
            'admin_user_ids': admin_user_ids,
        }
