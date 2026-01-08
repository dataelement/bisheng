from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, delete, text, INT
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.models.group import DefaultGroup


class UserGroupBase(SQLModelSerializable):
    user_id: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE"
    )

    group_id: Optional[int] = Field(
        default=None,
        foreign_key="group.id",
        primary_key=True,
        ondelete="CASCADE"
    )
    is_group_admin: bool = Field(default=False, index=False, description='Is Group Admin')  # Admin does not belong to this user group
    remark: Optional[str] = Field(default=None, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class UserGroup(UserGroupBase, table=True):
    id: Optional[int] = Field(default=None, sa_column=Column(INT, primary_key=True, autoincrement=True))


class UserGroupRead(UserGroupBase):
    id: Optional[int] = None


class UserGroupUpdate(UserGroupBase):
    user_id: Optional[int] = None
    group_id: Optional[int] = None
    is_group_admin: Optional[bool] = None
    remark: Optional[str] = None


class UserGroupCreate(UserGroupBase):
    pass


class UserGroupDao(UserGroupBase):

    @classmethod
    def get_user_group(cls, user_id: int) -> List[UserGroup]:
        """
        Get the user group the user is in
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 0)
            return session.exec(statement).all()

    @classmethod
    async def aget_user_group(cls, user_id: int) -> List[UserGroup]:
        """
        Get the user group the user is in asynchronously
        """
        statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 0)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_user_admin_group(cls, user_id: int) -> List[UserGroup]:
        """
        Get user groups where the user is an administrator
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    async def aget_user_admin_group(cls, user_id: int, group_id: int = None) -> List[UserGroup]:
        """
        Get user groups where the user is an administrator, If it passes,group_idOnly the group's admin information will be retrieved
        """
        statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 1)
        if group_id:
            statement = statement.where(UserGroup.group_id == group_id)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def insert_user_group(cls, user_group: UserGroupCreate) -> UserGroup:
        with get_sync_db_session() as session:
            user_group = UserGroup.validate(user_group)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def insert_user_group_admin(cls, user_id: int, group_id: int) -> UserGroup:
        """
        Set user as group administrator
        """
        with get_sync_db_session() as session:
            user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=True)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def delete_user_group(cls, user_id: int, group_id: int) -> None:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id,
                                                UserGroup.group_id == group_id)
            user_group = session.exec(statement).first()
            session.delete(user_group)
            session.commit()

    @classmethod
    def delete_user_groups(cls, user_id: int, group_ids: List[int]):
        """
        Remove users from certain groups
        """
        with get_sync_db_session() as session:
            # Empty all old user groups first
            statement = delete(UserGroup).where(
                UserGroup.user_id == user_id).where(
                UserGroup.is_group_admin == 0).where(
                UserGroup.group_id.in_(group_ids)
            )
            session.exec(statement)
            session.commit()

    @classmethod
    def add_user_groups(cls, user_id: int, group_ids: List[int]):
        """
        Add users to some groups
        """
        with get_sync_db_session() as session:
            for group_id in group_ids:
                user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=0)
                session.add(user_group)
            session.commit()

    @classmethod
    def get_group_user(cls,
                       group_id: int,
                       page_size: str = None,
                       page_num: str = None) -> List[UserGroup]:
        """
        Get all users in a group, excluding admins
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id).where(UserGroup.is_group_admin == 0)
            if page_num and page_size:
                statement = statement.offset(
                    (int(page_num) - 1) * int(page_size)).limit(int(page_size))
            return session.exec(statement).all()

    @classmethod
    def get_groups_user(cls,
                        group_ids: List[int],
                        page: int = 0,
                        limit: int = 0) -> List[UserGroup]:
        """
        Batch Get Users Under Grouping
        """
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids)).where(
                UserGroup.is_group_admin == 0)
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            return session.exec(statement).all()

    @classmethod
    def is_users_in_group(cls, group_id: int, user_ids: List[int]) -> List[UserGroup]:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id,
                                                UserGroup.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    def get_groups_admins(cls, group_ids: List[int]) -> List[UserGroup]:
        with get_sync_db_session() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids),
                                                UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    def update_user_groups(cls, user_groups: List[UserGroup]) -> List[UserGroup]:
        with get_sync_db_session() as session:
            session.add_all(user_groups)
            session.commit()
            return user_groups

    @classmethod
    async def add_default_user_group(cls, user_id: int) -> None:
        """
        Add users to the default user group
        """
        async with get_async_db_session() as session:
            user_group = UserGroup(user_id=user_id, group_id=DefaultGroup, is_group_admin=False)
            session.add(user_group)
            await session.commit()

    @classmethod
    def delete_group_admins(cls, group_id: int, admin_ids: List[int]) -> None:
        """
        Bulk delete user groupsadmin
        """
        with get_sync_db_session() as session:
            statement = delete(UserGroup).where(
                UserGroup.group_id == group_id).where(
                UserGroup.user_id.in_(admin_ids)).where(
                UserGroup.is_group_admin == 1)
            session.exec(statement)
            session.commit()

    @classmethod
    def delete_group_all_admin(cls, group_id: int) -> None:
        """
        Remove all administrators under the user group
        """
        with get_sync_db_session() as session:
            statement = delete(UserGroup).where(
                UserGroup.group_id == group_id).where(
                UserGroup.is_group_admin == 1)
            session.exec(statement)
            session.commit()
