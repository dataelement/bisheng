from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from bisheng.database.models.role import AdminRole, DefaultRole
from bisheng.database.models.user_group import UserGroup
from bisheng.database.models.user_role import UserRole
from pydantic import validator
from sqlalchemy import Column, DateTime, func, text
from sqlmodel import Field, select


class UserBase(SQLModelSerializable):
    user_name: str = Field(index=True, unique=True)
    email: Optional[str] = Field(index=True)
    phone_number: Optional[str] = Field(index=True)
    dept_id: Optional[str] = Field(index=True)
    remark: Optional[str] = Field(index=False)
    delete: int = Field(index=False, default=0)
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))

    @validator('user_name')
    def validate_str(v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            raise ValueError('user_name 不能为空')
        return v


class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)
    password: str = Field(index=False)
    password_update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')),
                                                     description='密码最近的修改时间')


class UserRead(UserBase):
    user_id: Optional[int]
    role: Optional[str]
    access_token: Optional[str]
    web_menu: Optional[List[str]]
    admin_groups: Optional[List[int]]  # 所管理的用户组ID列表


class UserQuery(UserBase):
    user_id: Optional[int]
    user_name: Optional[str]


class UserLogin(UserBase):
    password: str
    user_name: str
    captcha_key: Optional[str]
    captcha: Optional[str]


class UserCreate(UserBase):
    password: Optional[str] = Field(default='')
    captcha_key: Optional[str]
    captcha: Optional[str]


class UserUpdate(SQLModelSerializable):
    user_id: int
    delete: Optional[int] = 0


class UserDao(UserBase):

    @classmethod
    def get_user(cls, user_id: int) -> User | None:
        with session_getter() as session:
            statement = select(User).where(User.user_id == user_id)
            return session.exec(statement).first()

    @classmethod
    def get_user_by_ids(cls, user_ids: List[int]) -> List[User] | None:
        with session_getter() as session:
            statement = select(User).where(User.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    def get_user_by_username(cls, username: str) -> User | None:
        with session_getter() as session:
            statement = select(User).where(User.user_name == username)
            return session.exec(statement).first()

    @classmethod
    def update_user(cls, user: User) -> User:
        with session_getter() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def filter_users(cls,
                     user_ids: List[int],
                     keyword: str = None,
                     page: int = 0,
                     limit: int = 0) -> (List[User], int):
        statement = select(User)
        count_statement = select(func.count(User.user_id))
        if user_ids:
            statement = statement.where(User.user_id.in_(user_ids))
            count_statement = count_statement.where(User.user_id.in_(user_ids))
        if keyword:
            statement = statement.where(User.user_name.like(f'%{keyword}%'))
            count_statement = count_statement.where(User.user_name.like(f'%{keyword}%'))
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(User.user_id.desc())
        with session_getter() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    def get_unique_user_by_name(cls, user_name: str) -> User | None:
        with session_getter() as session:
            statement = select(User).where(User.user_name == user_name)
            return session.exec(statement).first()

    @classmethod
    def search_user_by_name(cls, user_name: str) -> List[User] | None:
        with session_getter() as session:
            statement = select(User).where(User.user_name.like('%{}%'.format(user_name)))
            return session.exec(statement).all()

    @classmethod
    def create_user(cls, db_user: User) -> User:
        with session_getter() as session:
            session.add(db_user)
            session.commit()
            session.refresh(db_user)
            return db_user

    @classmethod
    def add_user_and_default_role(cls, user: User) -> User:
        """
        新增用户，并添加默认角色
        """
        with session_getter() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            db_user_role = UserRole(user_id=user.user_id, role_id=DefaultRole)
            session.add(db_user_role)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def add_user_and_admin_role(cls, user: User) -> User:
        """
        新增用户，并添加超级管理员角色
        """
        with session_getter() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            db_user_role = UserRole(user_id=user.user_id, role_id=AdminRole)
            session.add(db_user_role)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def add_user_with_groups_and_roles(cls, user: User, group_ids: List[int],
                                       role_ids: List[int]) -> User:
        with session_getter() as session:
            session.add(user)
            session.flush()
            for group_id in group_ids:
                db_user_group = UserGroup(user_id=user.user_id, group_id=group_id)
                session.add(db_user_group)
            for role_id in role_ids:
                db_user_role = UserRole(user_id=user.user_id, role_id=role_id)
                session.add(db_user_role)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    def get_all_users(cls, page: int = 0, limit: int = 0) -> List[User]:
        """
        分页获取所有用户
        """
        statement = select(User)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        with session_getter() as session:
            return session.exec(statement).all()
