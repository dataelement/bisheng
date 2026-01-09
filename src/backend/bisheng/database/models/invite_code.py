from datetime import datetime
from typing import Optional, List

from sqlmodel import Field, Column, text, DateTime, select, update

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


class InviteCodeBase(SQLModelSerializable):
    """
    Invitation code model for storing invitation code information.
    """

    code: str = Field(..., index=True, unique=True, description='Invitation Code')
    batch_id: str = Field(..., index=True, description='BatchesID')
    batch_name: str = Field(..., description='Batch')
    limit: int = Field(..., description='Usage Limits')
    used: Optional[int] = Field(default=0, description='Used times')
    bind_user: Optional[int] = Field(default=0, index=True, description='Linked UsersID')
    created_id: Optional[int] = Field(default=None, index=True, description='creatorID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class InviteCode(InviteCodeBase, table=True):
    id: Optional[int] = Field(default=None, index=True, primary_key=True, description='Uniqueness quantificationID')


class InviteCodeDao(InviteCodeBase):
    """
    The invitation code data access object, which is used to manipulate the invitation code data.
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
        Get a valid invitation code bound by the user
        """
        statement = select(InviteCode).where(InviteCode.bind_user == bind_user).where(
            InviteCode.used < InviteCode.limit).order_by(InviteCode.id.asc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def get_user_all_code(cls, bind_user: int) -> list[InviteCode]:
        """
        Get all invitation codes linked by a user
        """
        statement = select(InviteCode).where(InviteCode.bind_user == bind_user).order_by(InviteCode.id.desc())
        async with get_async_db_session() as session:
            result = await session.exec(statement)
            return result.all()

    @classmethod
    async def bind_invite_code(cls, user_id: int, code: str) -> bool:
        """
        Binding Invitation Code
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
        Revoke Invitation Code
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
