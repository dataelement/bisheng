from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text, func, delete, and_, UniqueConstraint
from sqlmodel import Field, select

# 默认普通用户角色的ID
DefaultRole = 2
# 超级管理员角色ID
AdminRole = 1


class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='前端展示名称')
    group_id: Optional[int] = Field(index=True)
    remark: Optional[str] = Field(index=False)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Role(RoleBase, table=True):
    __table_args__ = (UniqueConstraint('group_id', 'role_name', name='group_role_name_uniq'),)
    id: Optional[int] = Field(default=None, primary_key=True)


class RoleRead(RoleBase):
    id: Optional[int]


class RoleUpdate(RoleBase):
    role_name: Optional[str]
    remark: Optional[str]


class RoleCreate(RoleBase):
    pass


class RoleDao(RoleBase):

    @classmethod
    def get_role_by_groups(cls, group: List[int], keyword: str = None, page: int = 0, limit: int = 0) -> List[Role]:
        """
        获取用户组内的角色列表, 不包含系统管理员角色
        params:
            group: 用户组ID列表
            page: 页数
            limit: 每页条数
        return: 角色列表
        """
        statement = select(Role).where(Role.id > AdminRole)
        if group:
            statement = statement.where(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(Role.create_time.desc())
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_role_by_groups(cls, group: List[int], keyword: str = None) -> int:
        """
        统计用户组内的角色数量，参数如上
        """
        statement = select(func.count(Role.id)).where(Role.id > AdminRole)
        if group:
            statement = statement.where(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        with session_getter() as session:
            return session.scalar(statement)

    @classmethod
    def insert_role(cls, role: RoleCreate):
        with session_getter() as session:
            session.add(role)
            session.commit()
            session.refresh(role)
            return role

    @classmethod
    def get_role_by_ids(cls, role_ids: List[int]) -> List[Role]:
        with session_getter() as session:
            return session.query(Role).filter(Role.id.in_(role_ids)).all()

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
            session.exec(delete(UserRole).where(UserRole.id.in_([one.id for one in all_user])))
            session.exec(delete(Role).where(Role.group_id == group_id))
            session.commit()
