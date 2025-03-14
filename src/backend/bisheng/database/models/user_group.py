from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, select, update, func, Column, DateTime, delete, text

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.group import DefaultGroup
from bisheng.database.models.role import RoleDao
from bisheng.database.models.user_role import UserRoleDao


class UserGroupBase(SQLModelSerializable):
    user_id: int = Field(index=True, description='用户id')
    group_id: int = Field(index=True, description='组id')
    is_group_admin: bool = Field(default=False, index=False, description='是否是组管理员')  # 管理员不属于此用户组
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class UserGroup(UserGroupBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class UserGroupRead(UserGroupBase):
    id: Optional[int]


class UserGroupUpdate(UserGroupBase):
    user_id: Optional[int]
    group_id: Optional[int]
    is_group_admin: Optional[bool]
    remark: Optional[str]


class UserGroupCreate(UserGroupBase):
    pass


class UserGroupDao(UserGroupBase):

    @classmethod
    def get_user_group(cls, user_id: int) -> List[UserGroup]:
        """
        获取用户所在的用户组
        """
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 0)
            return session.exec(statement).all()

    @classmethod
    def get_users_group(cls, user_id: List[int]) -> List[UserGroup]:
        """
        批量获取用户所在的用户组
        """
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id.in_(user_id)).where(UserGroup.is_group_admin == 0)
            return session.exec(statement).all()

    @classmethod
    def get_user_admin_group(cls, user_id: int) -> List[UserGroup]:
        """
        获取用户是管理员的用户组
        """
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id).where(UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    def insert_user_group(cls, user_group: UserGroupCreate) -> UserGroup:
        with session_getter() as session:
            user_group = UserGroup.validate(user_group)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def insert_user_group_admin(cls, user_id: int, group_id: int) -> UserGroup:
        """
        将用户设置为组管理员
        """
        with session_getter() as session:
            user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=True)
            session.add(user_group)
            session.commit()
            session.refresh(user_group)
            return user_group

    @classmethod
    def delete_user_group(cls, user_id: int, group_id: int) -> None:
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.user_id == user_id,
                                                UserGroup.group_id == group_id)
            user_group = session.exec(statement).first()
            session.delete(user_group)
            session.commit()

    @classmethod
    def delete_user_groups(cls, user_id: int, group_ids: List[int]):
        """
        将用户从某些组中移除
        """
        #取消将用户和组下角色的关联关系
        group_roles = RoleDao.get_role_by_groups(group_ids)
        if group_roles:
            UserRoleDao.delete_user_roles(user_id, [one.id for one in group_roles])
        with session_getter() as session:
            # 先把旧的用户组全部清空
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
        将用户添加到某些组
        """
        with session_getter() as session:
            for group_id in group_ids:
                user_group = UserGroup(user_id=user_id, group_id=group_id, is_group_admin=0)
                session.add(user_group)
            session.commit()

    @classmethod
    def get_group_user(cls,
                       group_id: int,
                       page_size: int = None,
                       page_num: int = None) -> List[UserGroup]:
        """
        获取分组下的所有用户，不包含管理员
        """
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id).where(UserGroup.is_group_admin == 0)
            if page_num and page_size:
                statement = statement.offset(
                    (int(page_num) - 1) * int(page_size)).limit(int(page_size))
            return session.exec(statement).all()

    @classmethod
    def get_groups_user(cls,
                        group_ids: List[int],
                        page: int = 0,
                        limit: int = 0) -> List[int]:
        """
        批量获取分组下的用户
        """
        with session_getter() as session:
            statement = select(UserGroup.user_id).where(UserGroup.group_id.in_(group_ids)).where(
                UserGroup.is_group_admin == 0)
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            statement = statement.group_by(UserGroup.user_id).order_by(UserGroup.id.asc())
            return session.exec(statement).all()

    @classmethod
    def get_groups_users(cls, group_ids: List[int], page: int = 0, limit: int = 0):
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids)).where(
                UserGroup.is_group_admin == 0)
            if page and limit:
                statement = statement.offset((page - 1) * limit).limit(limit)
            statement = statement.order_by(UserGroup.id.asc())
            return session.exec(statement).all()

    @classmethod
    def count_groups_user(cls, group_ids: List[int]) -> int:
        """
        统计用户组下的用户数量
        """
        with session_getter() as session:
            statement = select(func.count(func.distinct(UserGroup.user_id))).where(UserGroup.group_id.in_(group_ids)).where(
                UserGroup.is_group_admin == 0)
            return session.scalar(statement)

    @classmethod
    def is_users_in_group(cls, group_id: int, user_ids: List[int]) -> List[UserGroup]:
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.group_id == group_id,
                                                UserGroup.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    def get_groups_admins(cls, group_ids: List[int]) -> List[UserGroup]:
        with session_getter() as session:
            statement = select(UserGroup).where(UserGroup.group_id.in_(group_ids),
                                                UserGroup.is_group_admin == 1)
            return session.exec(statement).all()

    @classmethod
    def update_user_groups(cls, user_groups: List[UserGroup]) -> List[UserGroup]:
        with session_getter() as session:
            session.add_all(user_groups)
            session.commit()
            return user_groups

    @classmethod
    def add_default_user_group(cls, user_id: int) -> None:
        """
        给默认用户组内添加用户
        """
        with session_getter() as session:
            user_group = UserGroup(user_id=user_id, group_id=DefaultGroup, is_group_admin=False)
            session.add(user_group)
            session.commit()

    @classmethod
    def delete_group_admins(cls, group_id: int, admin_ids: List[int]) -> None:
        """
        批量删除用户组的admin
        """
        with session_getter() as session:
            statement = delete(UserGroup).where(
                UserGroup.group_id == group_id).where(
                UserGroup.user_id.in_(admin_ids)).where(
                UserGroup.is_group_admin == 1)
            session.exec(statement)
            session.commit()

    @classmethod
    def delete_group_all_admin(cls, group_id: int) -> None:
        """
        删除用户组下所有的管理员
        """
        with session_getter() as session:
            statement = delete(UserGroup).where(
                UserGroup.group_id == group_id).where(
                UserGroup.is_group_admin == 1)
            session.exec(statement)
            session.commit()
