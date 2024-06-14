from datetime import datetime
from typing import List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from pydantic import validator
from sqlalchemy import Column, DateTime, text, func
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
    password_update_time: Optional[datetime] = Field(index=False, description="密码最近的修改时间")


class UserRead(UserBase):
    user_id: Optional[int]
    role: Optional[str]
    access_token: Optional[str]


class UserQuery(UserBase):
    user_id: Optional[int]
    user_name: Optional[str]


class UserLogin(UserBase):
    password: str
    user_name: str
    captcha_key: Optional[str]
    captcha: Optional[str]


class UserCreate(UserBase):
    password: Optional[str]
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
    def filter_users(cls, user_ids: List[int], keyword: str = None, page: int = 0, limit: int = 0) -> (List[User], int):
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
    def create_user(cls, user: UserCreate) -> User:
        db_user = User.model_validate(user)
        with session_getter() as session:
            session.add(db_user)
            session.commit()
            session.refresh(db_user)
            return db_user
