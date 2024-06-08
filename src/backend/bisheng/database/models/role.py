from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, text, func
from sqlmodel import Field, select


class RoleBase(SQLModelSerializable):
    role_name: str = Field(index=False, description='前端展示名称', unique=True)
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
        获取用户组内的角色列表
        params:
            group: 用户组ID列表
            page: 页数
            limit: 每页条数
        return: 角色列表
        """
        statement = select(Role).filter(Role.group_id.in_(group))
        if keyword:
            statement = statement.filter(Role.role_name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def count_role_by_groups(cls, group: List[int], keyword: str = None) -> int:
        """
        统计用户组内的角色数量，参数如上
        """
        statement = select(func.count(Role.id)).filter(Role.group_id.in_(group))
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
