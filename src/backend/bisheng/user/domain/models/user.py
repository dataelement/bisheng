from datetime import datetime
from typing import List, Optional

from pydantic import field_validator
from sqlalchemy import Column, DateTime, func, text
from sqlalchemy.orm import selectinload
from sqlmodel import Field, select, Relationship, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session, get_async_db_session
from bisheng.database.constants import AdminRole, DefaultRole
from bisheng.database.models.group import Group
from bisheng.database.models.role import Role
from bisheng.database.models.user_group import UserGroup
from bisheng.user.domain.models.user_role import UserRole


class UserBase(SQLModelSerializable):
    user_name: str = Field(index=True, unique=True)
    email: Optional[str] = Field(default=None, index=True)
    phone_number: Optional[str] = Field(default=None, index=True)
    dept_id: Optional[str] = Field(default=None, index=True)
    remark: Optional[str] = Field(default=None, index=False)
    delete: int = Field(default=0, index=False)
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))

    @field_validator('user_name')
    @classmethod
    def validate_str(cls, v):
        # dict_keys(['description', 'name', 'id', 'data'])
        if not v:
            raise ValueError('user_name 不能为空')
        return v


class User(UserBase, table=True):
    user_id: Optional[int] = Field(default=None, primary_key=True)
    password: str = Field(index=False)
    password_update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')), description='密码最近的修改时间')

    # 定义groups和roles的查询关系
    groups: List["Group"] = Relationship(link_model=UserGroup)
    roles: List["Role"] = Relationship(link_model=UserRole)

    __tablename__ = "user"


class UserRead(UserBase):
    user_id: Optional[int] = None
    role: Optional[str] = None  # admin / group_admin
    access_token: Optional[str] = None
    web_menu: Optional[List[str]] = None
    admin_groups: Optional[List[int]] = None  # 所管理的用户组ID列表


class UserQuery(UserBase):
    pass


class UserLogin(UserBase):
    password: str

    captcha_key: Optional[str] = None
    captcha: Optional[str] = None


class UserCreate(UserBase):
    password: Optional[str] = Field(default='')
    captcha_key: Optional[str] = None
    captcha: Optional[str] = None


class UserUpdate(SQLModelSerializable):
    user_id: int
    delete: Optional[int] = 0


class UserDao(UserBase):

    @classmethod
    def get_user(cls, user_id: int) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_id == user_id)
            return session.exec(statement).first()

    @classmethod
    async def aget_user(cls, user_id: int) -> User | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_id == user_id)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def get_user_by_ids(cls, user_ids: List[int]) -> List[User] | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_id.in_(user_ids))
            return session.exec(statement).all()

    @classmethod
    async def aget_user_by_ids(cls, user_ids: List[int]) -> List[User] | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_id.in_(user_ids))
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_user_by_username(cls, username: str) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name == username)
            return session.exec(statement).first()

    @classmethod
    async def aget_user_by_username(cls, username: str) -> User | None:
        async with get_async_db_session() as session:
            statement = select(User).where(User.user_name == username)
            result = await session.exec(statement)
            return result.first()

    @classmethod
    def update_user(cls, user: User) -> User:
        with get_sync_db_session() as session:
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    @classmethod
    async def aupdate_user(cls, user: User) -> User:
        async with get_async_db_session() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    @classmethod
    def _filter_users_statement(cls,
                                statement,
                                user_ids: List[int],
                                keyword: str = None):
        if user_ids:
            statement = statement.where(User.user_id.in_(user_ids))
        if keyword:
            statement = statement.where(User.user_name.like(f'%{keyword}%'))
        return statement.order_by(User.user_id.desc())

    @classmethod
    def filter_users(cls,
                     user_ids: List[int],
                     keyword: str = None,
                     page: int = 0,
                     limit: int = 0) -> (List[User], int):
        statement = select(User)
        statement = cls._filter_users_statement(statement, user_ids, keyword)
        count_statement = select(func.count(User.user_id))
        count_statement = cls._filter_users_statement(count_statement, user_ids, keyword)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(User.user_id.desc())
        with get_sync_db_session() as session:
            return session.exec(statement).all(), session.scalar(count_statement)

    @classmethod
    async def afilter_users(cls,
                            user_ids: List[int],
                            keyword: str = None,
                            page: int = 0,
                            limit: int = 0) -> List[User]:
        statement = select(User)
        statement = cls._filter_users_statement(statement, user_ids, keyword)
        if page and limit:
            statement = statement.offset((page - 1) * limit).limit(limit)
        statement = statement.order_by(User.user_id.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    def get_unique_user_by_name(cls, user_name: str) -> User | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name == user_name)
            return session.exec(statement).first()

    @classmethod
    def search_user_by_name(cls, user_name: str) -> List[User] | None:
        with get_sync_db_session() as session:
            statement = select(User).where(User.user_name.like('%{}%'.format(user_name)))
            return session.exec(statement).all()

    @classmethod
    def create_user(cls, db_user: User) -> User:
        with get_sync_db_session() as session:
            session.add(db_user)
            session.commit()
            session.refresh(db_user)
            return db_user

    @classmethod
    def add_user_and_default_role(cls, user: User) -> User:
        """
        新增用户，并添加默认角色
        """
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_user_with_group_role(cls, *, start_time: datetime = None, end_time: datetime = None,
                                 user_ids: List[int] = None, page: int = 0, page_size: int = 0) -> List[User]:
        statement = select(User)
        if start_time and end_time:
            statement = statement.where(User.create_time >= start_time, User.create_time < end_time)
        if page and page_size:
            statement = statement.offset((page - 1) * page_size).limit(page_size)
        if user_ids:
            statement = statement.where(col(User.user_id).in_(user_ids))
        statement = statement.order_by(User.user_id)
        statement = statement.options(
            selectinload(User.groups),  # type: ignore
            selectinload(User.roles)  # type: ignore
        )
        with get_sync_db_session() as session:
            return session.exec(statement).all()

    @classmethod
    def get_first_user(cls) -> User | None:
        statement = select(User).order_by(col(User.user_id).asc()).limit(1)
        with get_sync_db_session() as session:
            return session.exec(statement).first()
