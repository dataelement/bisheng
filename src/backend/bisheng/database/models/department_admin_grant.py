"""Persisted source of department-level OpenFGA ``admin`` grants.

SSO WeCom leader sync only revokes rows marked ``sso``; management UI
grants use ``manual`` so they are not cleared by reconcile.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, UniqueConstraint, delete
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session

DEPARTMENT_ADMIN_GRANT_SOURCE_SSO = 'sso'
DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL = 'manual'


class DepartmentAdminGrant(SQLModelSerializable, table=True):
    __tablename__ = 'department_admin_grant'

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey('user.user_id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
    )
    department_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey('department.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
    )
    grant_source: str = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            comment='sso | manual',
        ),
    )

    __table_args__ = (
        UniqueConstraint(
            'user_id', 'department_id',
            name='uk_dept_admin_grant_user_dept',
        ),
    )


class DepartmentAdminGrantDao:
    """CRUD for ``department_admin_grant``."""

    @classmethod
    async def aget_user_ids_by_department(
        cls, department_id: int,
    ) -> List[int]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentAdminGrant.user_id).where(
                    DepartmentAdminGrant.department_id == department_id,
                )
            )
            return [int(row[0] if isinstance(row, tuple) else row) for row in result.all()]

    @classmethod
    async def aget_by_user_and_departments(
        cls, user_id: int, department_ids: List[int],
    ) -> List[DepartmentAdminGrant]:
        if not department_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentAdminGrant).where(
                    DepartmentAdminGrant.user_id == user_id,
                    DepartmentAdminGrant.department_id.in_(department_ids),
                )
            )
            return list(result.all())

    @classmethod
    async def aupsert(
        cls, user_id: int, department_id: int, grant_source: str,
    ) -> None:
        if grant_source not in (
            DEPARTMENT_ADMIN_GRANT_SOURCE_SSO,
            DEPARTMENT_ADMIN_GRANT_SOURCE_MANUAL,
        ):
            raise ValueError(f'invalid grant_source: {grant_source!r}')
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentAdminGrant).where(
                    DepartmentAdminGrant.user_id == user_id,
                    DepartmentAdminGrant.department_id == department_id,
                )
            )
            row = result.first()
            if row is None:
                session.add(DepartmentAdminGrant(
                    user_id=user_id,
                    department_id=department_id,
                    grant_source=grant_source,
                ))
            else:
                row.grant_source = grant_source
                session.add(row)
            await session.commit()

    @classmethod
    async def adelete(cls, user_id: int, department_id: int) -> None:
        async with get_async_db_session() as session:
            await session.execute(
                delete(DepartmentAdminGrant).where(
                    DepartmentAdminGrant.user_id == user_id,
                    DepartmentAdminGrant.department_id == department_id,
                )
            )
            await session.commit()

    @classmethod
    async def aget_user_ids_for_department(cls, department_id: int) -> List[int]:
        """All user_ids with a manual/SSO department admin grant on this dept."""
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentAdminGrant.user_id).where(
                    DepartmentAdminGrant.department_id == department_id,
                )
            )
            rows = result.all()
            return [int(r[0]) for r in rows]

    @classmethod
    async def adelete_for_department_users(
        cls, department_id: int, user_ids: List[int],
    ) -> None:
        if not user_ids:
            return
        async with get_async_db_session() as session:
            await session.execute(
                delete(DepartmentAdminGrant).where(
                    DepartmentAdminGrant.department_id == department_id,
                    DepartmentAdminGrant.user_id.in_(user_ids),
                )
            )
            await session.commit()
