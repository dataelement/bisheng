from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, Column, DateTime, text, select, delete, String

from bisheng.database.models.base import SQLModelSerializable, SQLModel
from bisheng.database.base import session_getter

# TODO merge_check 2
# class PromiseBase(SQLModelSerializable):
#     id: Optional[int] = Field(primary_key=True, description='唯一ID')
#     business_id: str = Field(default=None, index=True, description='业务唯一标识')
#     promise_id: str = Field(default=None, description='承诺书唯一标识')
#     user_id: str = Field(default=None, index=True, description='创建用户ID')
#     create_time: Optional[datetime] = Field(sa_column=Column(
#         DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
#     update_time: Optional[datetime] = Field(
#         sa_column=Column(DateTime,
#                          nullable=False,
#                          server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class PromiseBase(SQLModel):
    id: Optional[int] = Field(default=None, primary_key=True, description='唯一ID')
    business_id: str = Field(default=None, index=True, description='业务唯一标识')
    promise_id: str = Field(default=None, description='承诺书唯一标识')
    user_id: str = Field(default=None, index=True, description='创建用户ID')

    create_time: Optional[datetime] = Field(
        default=None,
        nullable=False,
        index=True,
        sa_column_kwargs={'server_default': text('CURRENT_TIMESTAMP')}
    )
    update_time: Optional[datetime] = Field(
        default=None,
        nullable=False,
        sa_column_kwargs={
            'server_default': text('CURRENT_TIMESTAMP'),
            'onupdate': text('CURRENT_TIMESTAMP')
        }
    )


class Promise(PromiseBase, table=True):
    """ 记录哪些业务有承诺书配置 """
    __tablename__ = 'business_promise'


class UserPromise(PromiseBase, table=True):
    """ 记录用户签署了哪些承诺书 """
    __tablename__ = 'user_promise'
    business_name: str = Field(default=None, sa_column=Column(String(length=1024)), description='签署时的业务名称')
    promise_name: str = Field(default=None, sa_column=Column(String(length=1024)), description='签署时的承诺书名称')
    user_id: str = Field(default=None, index=True, description='签署用户的唯一ID')
    user_name: str = Field(default=None, description='签署时用户的用户名')


class PromiseDao(PromiseBase):

    @classmethod
    def create(cls, data: Promise, delete_other: bool = False) -> Promise:
        with session_getter() as session:
            if delete_other:
                session.exec(delete(Promise).where(Promise.business_id == data.business_id))
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_promise(cls, business_id: str, promise_id: str = None) -> List[Promise]:
        """ 获取某个业务的所有承诺书 """
        statement = select(Promise).where(Promise.business_id == business_id)
        if promise_id:
            statement = statement.where(Promise.promise_id == promise_id)
        with session_getter() as session:
            return session.exec(statement).all()

    @classmethod
    def create_user_promise(cls, data: UserPromise) -> UserPromise:
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def get_user_promise(cls, user_id: str, business_ids: List[str] = None) -> List[UserPromise]:
        """ 获取用户签署的承诺书 """
        statement = select(UserPromise).where(UserPromise.user_id == user_id)
        if business_ids:
            statement = statement.where(UserPromise.business_id.in_(business_ids))
        with session_getter() as session:
            return session.exec(statement).all()
