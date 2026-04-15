from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Column, DateTime, Integer, String, delete, func, text, update
from sqlalchemy.schema import UniqueConstraint
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session

# Default User GroupID
DefaultGroup = 2


class GroupBase(SQLModelSerializable):
    group_name: str = Field(index=False, description='用户组名称')
    remark: Optional[str] = Field(default=None, index=False)
    visibility: str = Field(
        default='public',
        sa_column=Column(String(16), nullable=False, server_default=text("'public'"),
                         comment='Visibility: public/private'),
    )
    create_user: Optional[int] = Field(default=None, index=True, description="Creating a user'sID")
    update_user: Optional[int] = Field(default=None, description="Update user'sID")
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class Group(GroupBase, table=True):
    __tablename__ = 'group'
    # id = 2 Represents the default user group
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text('1'),
                         index=True, comment='Tenant ID'),
    )

    __table_args__ = (
        UniqueConstraint('tenant_id', 'group_name', name='uk_tenant_group_name'),
    )


class GroupRead(GroupBase):
    id: Optional[int] = None
    group_admins: Optional[List[Dict]] = None


class GroupUpdate(GroupBase):
    role_name: Optional[str] = None
    remark: Optional[str] = None


class GroupCreate(GroupBase):
    group_admins: Optional[List[int]] = None


class GroupDao(GroupBase):

    @classmethod
    def get_user_group(cls, group_id: int) -> Group | None:
        with get_sync_db_session() as session:
            statement = select(Group).where(Group.id == group_id)
            return session.exec(statement).first()

    @classmethod
    def insert_group(cls, group: GroupCreate) -> Group:
        with get_sync_db_session() as session:
            group_add = Group.validate(group)
            session.add(group_add)
            session.commit()
            session.refresh(group_add)
            return group_add

    @classmethod
    def get_all_group(cls) -> list[Group]:
        with get_sync_db_session() as session:
            statement = select(Group).order_by(Group.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    def get_group_by_ids(cls, ids: List[int]) -> list[Group]:
        if not ids:
            raise ValueError('ids is empty')
        with get_sync_db_session() as session:
            statement = select(Group).where(Group.id.in_(ids)).order_by(Group.update_time.desc())
            return session.exec(statement).all()

    @classmethod
    async def aget_group_by_ids(cls, ids: List[int]) -> list[Group]:
        if not ids:
            raise ValueError('ids is empty')
        async with get_async_db_session() as session:
            statement = select(Group).where(Group.id.in_(ids)).order_by(Group.update_time.desc())
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def delete_group(cls, group_id: int):
        with get_sync_db_session() as session:
            session.exec(delete(Group).where(Group.id == group_id))
            session.commit()

    @classmethod
    def update_group(cls, group: Group) -> Group:
        with get_sync_db_session() as session:
            session.add(group)
            session.commit()
            session.refresh(group)
            return group

    @classmethod
    def update_group_update_user(cls, group_id: int, user_id: int):
        with get_sync_db_session() as session:
            statement = update(Group).where(Group.id == group_id).values(update_user=user_id,
                                                                         update_time=datetime.now())
            session.exec(statement)
            session.commit()

    # --- Async methods (F003) ---

    @classmethod
    async def aget_by_id(cls, group_id: int) -> Optional['Group']:
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            result = await session.exec(select(Group).where(Group.id == group_id))
            return result.first()

    @classmethod
    async def acreate(cls, group: 'Group') -> 'Group':
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            session.add(group)
            await session.commit()
            await session.refresh(group)
            return group

    @classmethod
    async def aupdate(cls, group: 'Group') -> 'Group':
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            session.add(group)
            await session.commit()
            await session.refresh(group)
            return group

    @classmethod
    async def adelete(cls, group_id: int) -> None:
        async with get_async_db_session() as session:
            session.exec(delete(Group).where(Group.id == group_id))
            await session.commit()

    @classmethod
    async def aget_all_groups(
        cls, page: int = 1, limit: int = 20, keyword: str = '',
    ) -> Tuple[List['Group'], int]:
        """Paginated list of all groups for current tenant (auto-filtered)."""
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            base = select(Group)
            if keyword:
                base = base.where(Group.group_name.like(f'%{keyword}%'))
            # total count
            count_stmt = select(func.count()).select_from(base.subquery())
            total = (await session.exec(count_stmt)).one()
            # paginated data
            stmt = base.order_by(Group.update_time.desc()).offset((page - 1) * limit).limit(limit)
            result = await session.exec(stmt)
            return result.all(), total

    @classmethod
    async def acheck_name_duplicate(
        cls, group_name: str, exclude_id: int = None,
    ) -> bool:
        """Check if group_name already exists within current tenant."""
        async with get_async_db_session() as session:
            stmt = select(Group).where(Group.group_name == group_name)
            if exclude_id is not None:
                stmt = stmt.where(Group.id != exclude_id)
            result = await session.exec(stmt)
            return result.first() is not None

    @classmethod
    async def aget_visible_groups(
        cls, user_id: int, page: int = 1, limit: int = 20, keyword: str = '',
    ) -> Tuple[List['Group'], int]:
        """Non-admin view: public groups + private groups where user is member/admin."""
        from bisheng.database.models.user_group import UserGroup
        async with get_async_db_session() as session:
            session.expire_on_commit = False
            # Get group IDs where user is member or admin
            member_stmt = select(UserGroup.group_id).where(UserGroup.user_id == user_id)
            member_result = await session.exec(member_stmt)
            raw_gids = member_result.all()
            user_group_ids = [
                int(x[0]) if isinstance(x, tuple) else int(x) for x in raw_gids
            ]

            visibility_cond = Group.visibility == 'public'
            creator_cond = Group.create_user == user_id
            if user_group_ids:
                stmt = select(Group).where(
                    visibility_cond | creator_cond | Group.id.in_(user_group_ids),
                )
            else:
                stmt = select(Group).where(visibility_cond | creator_cond)
            if keyword:
                stmt = stmt.where(Group.group_name.like(f'%{keyword}%'))

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = (await session.exec(count_stmt)).one()

            stmt = stmt.order_by(Group.update_time.desc()).offset((page - 1) * limit).limit(limit)
            result = await session.exec(stmt)
            return result.all(), total
