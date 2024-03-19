from datetime import datetime
from typing import Optional

from bisheng.database.models.base import SQLModelSerializable
from pydantic import validator
from sqlalchemy import Column, DateTime, text
from sqlmodel import Field


class UserBase(SQLModelSerializable):
    user_name: str = Field(index=True, unique=True)
    email: Optional[str] = Field(index=True)
    phone_number: Optional[str] = Field(index=True)
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
    password: str
    captcha_key: Optional[str]
    captcha: Optional[str]


class UserUpdate(SQLModelSerializable):
    user_id: int
    delete: Optional[int] = 0
