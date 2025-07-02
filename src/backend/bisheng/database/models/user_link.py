from typing import Optional
from datetime import datetime
from sqlmodel import Field, Column, DateTime, select
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import text, and_, delete
from typing import List
from bisheng.database.base import session_getter


class UserLinkBase(SQLModelSerializable):
    user_id: int = Field(index=True)
    type: str = Field(index=True,max_length=32)
    type_detail: str = Field(index=True,max_length=255, description='type相关信息')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP'),
        onupdate=text('CURRENT_TIMESTAMP')))
    

class UserLink(UserLinkBase, table=True):
    __tablename__ = 'user_link'
    id: Optional[int] = Field(default=None, primary_key=True)


class UserLinkDao(UserLinkBase):
    @classmethod
    def get_user_link(cls, user_id: int, types: list) -> List[UserLink]:
        with session_getter() as session:
            statement = select(UserLink).where(and_(UserLink.user_id == user_id, UserLink.type.in_(types)))
            return session.exec(statement).all()
    
    @classmethod
    def add_user_link(cls, user_id: int, type: str, type_detail: str) -> UserLink:
        with session_getter() as session:
            user_link = UserLink(user_id=user_id, type=type, type_detail=type_detail, create_time=datetime.now(), update_time=datetime.now())
            session.add(user_link)
            session.commit()
            return user_link

    @classmethod
    def delete_user_link(cls, user_id: int, type: str, type_detail: str) -> None:
        with session_getter() as session:
            statement = delete(UserLink).where(and_(UserLink.user_id == user_id, UserLink.type == type, UserLink.type_detail == type_detail))
            session.exec(statement)
            session.commit()
        return True
