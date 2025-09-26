from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, Column, text, DateTime, select, update

from bisheng.core.database import get_async_db_session
from bisheng.database.models.base import SQLModelSerializable


class InviteCodeBase(SQLModelSerializable):
    """
    邀请码模型，用于存储邀请码信息。
    """

    code: str = Field(..., index=True, unique=True, description='邀请码')
    batch_id: str = Field(..., index=True, description='批次ID')
    batch_name: str = Field(..., description='批次名称')
    limit: int = Field(..., description='使用限制次数')
    used: Optional[int] = Field(default=0, description='已使用次数')
    bind_user: Optional[int] = Field(default=0, index=True, description='绑定的用户ID')
    created_id: Optional[int] = Field(default=None, index=True, description='创建者ID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'), onupdate=text('CURRENT_TIMESTAMP')))


class InviteCode(InviteCodeBase, table=True):
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description='唯一ID')


class InviteCodeDao(InviteCodeBase):
    """
    邀请码数据访问对象，用于操作邀请码数据。
    """

    @classmethod
    async def insert_invite_code(cls, invite_code: List[InviteCode]) -> List[InviteCode]:
        async with get_async_db_session() as session:
            session.add_all(invite_code)
            await session.commit()
            return invite_code

    @classmethod
    async def get_user_bind_code(cls, bind_user: int) -> list[InviteCode]:
        """
        获取用户绑定的有效的邀请码
        """
        statement = select(InviteCode).where(InviteCode.bind_user == bind_user).where(
            InviteCode.used < InviteCode.limit).order_by(InviteCode.id.asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def get_user_all_code(cls, bind_user: int) -> list[InviteCode]:
        """
        获取用户绑定的所有邀请码
        """
        statement = select(InviteCode).where(InviteCode.bind_user == bind_user).order_by(InviteCode.id.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def bind_invite_code(cls, user_id: int, code: str) -> bool:
        """
        绑定邀请码
        """
        statement = update(InviteCode).where(InviteCode.code == code).where(InviteCode.bind_user == 0).values(
            bind_user=user_id
        )
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            await session.commit()
            if result.rowcount > 0:
                return True
            return False

    @classmethod
    async def use_invite_code(cls, user_id: int, code: str) -> bool:
        statement = update(InviteCode).where(InviteCode.code == code).where(InviteCode.bind_user == user_id).values(
            used=InviteCode.used + 1
        ).where(InviteCode.used < InviteCode.limit)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            await session.commit()
            if result.rowcount > 0:
                return True
            return False

    @classmethod
    async def revoke_invite_code_used(cls, user_id: int, code: str) -> bool:
        """
        撤销邀请码
        """
        statement = update(InviteCode).where(InviteCode.code == code).where(InviteCode.bind_user == user_id).values(
            used=InviteCode.used - 1
        ).where(InviteCode.used > 0)
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            await session.commit()
            if result.rowcount > 0:
                return True
            return False
