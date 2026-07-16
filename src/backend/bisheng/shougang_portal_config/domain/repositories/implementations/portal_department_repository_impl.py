"""Tenant-safe primary-department lookup for portal personalization."""

from collections.abc import Iterable

from sqlalchemy.engine import Row
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.database.models.department import Department, UserDepartment
from bisheng.shougang_portal_config.domain.repositories.interfaces.portal_department_repository import (
    PortalDepartmentRepository,
)


def normalize_department_id_rows(rows: Iterable[object]) -> list[int]:
    """Normalize driver-dependent scalar, tuple, and SQLAlchemy Row results."""
    normalized: list[int] = []
    for row in rows:
        value = row[0] if isinstance(row, (Row, tuple, list)) else row
        normalized.append(int(value))
    return normalized


class PortalDepartmentRepositoryImpl(PortalDepartmentRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_primary_department_ids_for_user(self, user_id: int) -> list[int]:
        # Join through Department so strict tenant filtering also protects the
        # tenant-less UserDepartment relation table.
        with strict_tenant_filter():
            result = await self.session.exec(
                select(Department.id)
                .join(UserDepartment, UserDepartment.department_id == Department.id)
                .where(
                    UserDepartment.user_id == int(user_id),
                    UserDepartment.is_primary == 1,
                )
                .order_by(Department.id)
            )
        return normalize_department_id_rows(result.all())
