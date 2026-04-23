from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, UniqueConstraint, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class DepartmentKnowledgeSpaceBase(SQLModelSerializable):
    tenant_id: int = Field(default=1, index=True, description='Tenant ID')
    department_id: int = Field(
        sa_column=Column(
            ForeignKey('department.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        description='Department.id',
    )
    space_id: int = Field(
        sa_column=Column(
            ForeignKey('knowledge.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        description='Knowledge Space id',
    )
    created_by: int = Field(default=0, index=True, description='Creator user id')
    approval_enabled: bool = Field(
        default=True,
        description='Whether uploads in this department knowledge space require approval',
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text('1'),
        ),
    )
    sensitive_check_enabled: bool = Field(
        default=False,
        description='Whether uploads in this department knowledge space require content safety check',
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text('0'),
        ),
    )
    create_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP'),
        ),
    )
    update_time: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'),
        ),
    )


class DepartmentKnowledgeSpace(DepartmentKnowledgeSpaceBase, table=True):
    __tablename__ = 'department_knowledge_space'
    __table_args__ = (
        UniqueConstraint('department_id', name='uk_dks_department_id'),
        UniqueConstraint('space_id', name='uk_dks_space_id'),
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class DepartmentKnowledgeSpaceDao(DepartmentKnowledgeSpaceBase):
    @classmethod
    async def aget_all(cls) -> List[DepartmentKnowledgeSpace]:
        async with get_async_db_session() as session:
            result = await session.exec(select(DepartmentKnowledgeSpace))
            return result.all()

    @classmethod
    async def acreate(
        cls,
        *,
        tenant_id: int,
        department_id: int,
        space_id: int,
        created_by: int,
        approval_enabled: bool = True,
        sensitive_check_enabled: bool = False,
    ) -> DepartmentKnowledgeSpace:
        row = DepartmentKnowledgeSpace(
            tenant_id=tenant_id,
            department_id=department_id,
            space_id=space_id,
            created_by=created_by,
            approval_enabled=approval_enabled,
            sensitive_check_enabled=sensitive_check_enabled,
        )
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aupdate(cls, row: DepartmentKnowledgeSpace) -> DepartmentKnowledgeSpace:
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aget_by_department_id(
        cls, department_id: int,
    ) -> Optional[DepartmentKnowledgeSpace]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.department_id == department_id,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_department_ids(
        cls, department_ids: List[int],
    ) -> List[DepartmentKnowledgeSpace]:
        if not department_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.department_id.in_(department_ids),
                )
            )
            return result.all()

    @classmethod
    async def aget_by_space_id(
        cls, space_id: int,
    ) -> Optional[DepartmentKnowledgeSpace]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.space_id == space_id,
                )
            )
            return result.first()

    @classmethod
    async def aget_by_space_ids(
        cls, space_ids: List[int],
    ) -> List[DepartmentKnowledgeSpace]:
        if not space_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(DepartmentKnowledgeSpace).where(
                    DepartmentKnowledgeSpace.space_id.in_(space_ids),
                )
            )
            return result.all()

    @classmethod
    async def aget_space_id_by_department_id(
        cls, department_id: int,
    ) -> Optional[int]:
        row = await cls.aget_by_department_id(department_id)
        return row.space_id if row else None

    @classmethod
    async def aget_department_ids_by_space_ids(
        cls, space_ids: List[int],
    ) -> Dict[int, int]:
        rows = await cls.aget_by_space_ids(space_ids)
        return {row.space_id: row.department_id for row in rows}
