from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class KnowledgeSpaceLevelEnum(str, Enum):
    PUBLIC = 'public'
    DEPARTMENT = 'department'
    TEAM = 'team'
    PERSONAL = 'personal'


class KnowledgeSpaceOwnerTypeEnum(str, Enum):
    TENANT_ROOT_DEPARTMENT = 'tenant_root_department'
    DEPARTMENT = 'department'
    USER_GROUP = 'user_group'
    USER = 'user'


class KnowledgeSpaceScopeBase(SQLModelSerializable):
    tenant_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text('1'),
            index=True,
            comment='Tenant ID',
        ),
    )
    space_id: int = Field(
        sa_column=Column(
            ForeignKey('knowledge.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='Knowledge space id',
        ),
    )
    level: KnowledgeSpaceLevelEnum = Field(
        sa_column=Column(String(32), nullable=False, comment='public/department/team/personal'),
    )
    owner_type: KnowledgeSpaceOwnerTypeEnum = Field(
        sa_column=Column(String(64), nullable=False, comment='Scope owner type'),
    )
    owner_id: int = Field(
        sa_column=Column(Integer, nullable=False, comment='Scope owner id'),
    )
    created_by: int = Field(default=0, index=True, description='Creator user id')
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


class KnowledgeSpaceScope(KnowledgeSpaceScopeBase, table=True):
    __tablename__ = 'knowledge_space_scope'
    __table_args__ = (
        UniqueConstraint('space_id', name='uk_kss_space_id'),
        Index('idx_kss_tenant_level', 'tenant_id', 'level'),
        Index('idx_kss_tenant_owner', 'tenant_id', 'owner_type', 'owner_id'),
    )

    id: Optional[int] = Field(default=None, primary_key=True)


class KnowledgeSpaceScopeDao(KnowledgeSpaceScopeBase):
    @classmethod
    async def acreate(
        cls,
        *,
        tenant_id: int,
        space_id: int,
        level: KnowledgeSpaceLevelEnum,
        owner_type: KnowledgeSpaceOwnerTypeEnum,
        owner_id: int,
        created_by: int,
    ) -> KnowledgeSpaceScope:
        row = KnowledgeSpaceScope(
            tenant_id=tenant_id,
            space_id=space_id,
            level=level,
            owner_type=owner_type,
            owner_id=owner_id,
            created_by=created_by,
        )
        async with get_async_db_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    @classmethod
    async def aget_by_space_id(cls, space_id: int) -> Optional[KnowledgeSpaceScope]:
        async with get_async_db_session() as session:
            result = await session.exec(
                select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == space_id)
            )
            return result.first()

    @classmethod
    async def aget_by_space_ids(cls, space_ids: List[int]) -> List[KnowledgeSpaceScope]:
        if not space_ids:
            return []
        async with get_async_db_session() as session:
            result = await session.exec(
                select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id.in_(space_ids))
            )
            return result.all()

    @classmethod
    async def aget_map_by_space_ids(cls, space_ids: List[int]) -> Dict[int, KnowledgeSpaceScope]:
        rows = await cls.aget_by_space_ids(space_ids)
        return {int(row.space_id): row for row in rows}
