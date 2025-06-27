from datetime import datetime
from typing import List, Optional, Any, Dict

from sqlmodel import Field, select, Column, DateTime, text, func, delete, and_, UniqueConstraint, or_, Text

from sqlalchemy import Column, DateTime, text, func, delete, and_, UniqueConstraint
from sqlmodel import Field, select
from bisheng.database.models.group import GroupDao

from bisheng.database.base import session_getter
from bisheng.database.constants import AdminRole
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role_access import RoleAccess
from bisheng.database.models.user_role import UserRole

# 默认普通用户角色的ID
DefaultRole = 2


class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='前端展示名称')
    group_id: Optional[int] = Field(default=None, index=True)
    remark: Optional[str] = Field(default=None, index=False)
    is_bind_all: bool = Field(default=False, description='此角色是否绑定所有的子用户组')
    extra: Optional[str] = Field(default='', sa_column=Column(Text), description='额外信息')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class Role(RoleBase, table=True):
    __table_args__ = (UniqueConstraint('group_id', 'role_name', name='group_role_name_uniq'),)
    id: Optional[int] = Field(default=None, primary_key=True)


class RoleRead(RoleBase):
    id: Optional[int] = None
    user_ids: Optional[List[Dict]] = []  # 已绑定的用户列表


class RoleUpdate(RoleBase):
    role_name: Optional[str] = None
    remark: Optional[str] = None
    user_ids: Optional[List[int]] = []  # 已绑定的用户列表


class RoleCreate(RoleBase):
    user_ids: Optional[List[int]] = []  # 绑定的用户ID列表


class RoleDao(RoleBase):

    @classmethod
    def generate_role_group_statement(cls, statement, group: List[int], keyword: str = None,
                                      include_parent: bool = False, only_bind: bool = False):
        statement = statement.where(Role.id > AdminRole)
        if group:
            parent_group_ids = []
            if include_parent:
                parent_groups = GroupDao.get_parent_groups_by_ids(group)
                parent_group_ids = [one.id for one in parent_groups]
            if parent_group_ids:
                statement = statement.where(or_(
                    and_(Role.group_id.in_(parent_group_ids), Role.is_bind_all == True),
                    Role.group_id.in_(group)
                ))
            else:
                statement = statement.where(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        if only_bind:
            statement = statement.where(Role.is_bind_all == True)
        return statement

    @classmethod
    def get_role_by_groups(cls, group: List[int], keyword: str = None, page: int = 0, limit: int = 0,
                           include_parent: bool = False, only_bind: bool = False) -> List[Role]:
        """
        获取用户组内的角色列表, 不包含系统管理员角色
        params:
            group: 用户组ID列表
            page: 页数
            limit: 每页条数
            include_parent: 是否包含父级用户组的bind角色
            only_bind: 是否只获取属于查询用户组的绑定角色
        return: 角色列表
        """
        statement = select(Role)
        statement = cls.generate_role_group_statement(statement, group, keyword, include_parent, only_bind)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Role.create_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_role_by_groups(cls, group: List[int], keyword: str = None, include_parent: bool = False,
                             only_bind: bool = False) -> int:
        """
        统计用户组内的角色数量，参数如上
        """
        statement = select(func.count(Role.id))
        statement = cls.generate_role_group_statement(statement, group, keyword, include_parent, only_bind)
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def insert_role(cls, role: Role):
        with session_getter() as session:
            session.add(role)
            session.commit()
            session.refresh(role)
            return role

    @classmethod
    def delete_role(cls, role_id: int):
        with session_getter() as session:
            session.exec(delete(Role).where(Role.id == role_id))
            session.exec(delete(UserRole).where(UserRole.role_id == role_id))
            session.exec(delete(RoleAccess).where(RoleAccess.role_id == role_id))
            session.commit()

    @classmethod
    def update_role(cls, data: Role):
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_role_by_ids(cls, role_ids: List[int], is_bind_all: bool = False) -> List[Role]:
        statement = select(Role).where(Role.id.in_(role_ids))
        if is_bind_all:
            statement = statement.where(Role.is_bind_all == True)
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def get_role_by_id(cls, role_id: int) -> Role:
        with session_getter() as session:
            return session.query(Role).filter(Role.id == role_id).first()

    @classmethod
    def delete_role_by_group_id(cls, group_id: int):
        """
        删除分组下所有的角色，清理用户对应的角色
        """
        from bisheng.database.models.user_role import UserRole
        with session_getter() as session:
            # 清理对应的用户
            all_user = select(UserRole, Role).join(
                Role, and_(UserRole.role_id == Role.id,
                           Role.group_id == group_id)).group_by(UserRole.id)
            all_user = session.exec(all_user).all()
            session.exec(delete(UserRole).where(UserRole.id.in_([one.UserRole.id for one in all_user])))
            session.exec(delete(Role).where(Role.group_id == group_id))
            session.commit()
