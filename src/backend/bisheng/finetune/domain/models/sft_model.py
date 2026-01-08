from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, delete, text, update
from sqlmodel import Field, select, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session


# Available for trainingmodelVertical
class SftModelBase(SQLModelSerializable):
    id: int = Field(default=None, nullable=False, primary_key=True, description='Uniqueness quantificationID')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class SftModel(SftModelBase, table=True):
    model_name: str = Field(index=True, description='Model name that can be used for fine-tuning training')


class SftModelDao(SftModel):

    @classmethod
    async def get_sft_model(cls, model_name: str) -> SftModel | None:
        async with get_async_db_session() as session:
            statement = select(SftModel).where(SftModel.model_name == model_name)
            return (await session.exec(statement)).first()

    @classmethod
    async def get_all_sft_model(cls):
        async with get_async_db_session() as session:
            statement = select(SftModel)
            return (await session.exec(statement)).all()

    @classmethod
    async def insert_sft_model(cls, model_name: str) -> SftModel:
        async with get_async_db_session() as session:
            model = SftModel(model_name=model_name)
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return model

    @classmethod
    async def delete_sft_model(cls, model_name: str) -> bool:
        async with get_async_db_session() as session:
            statement = delete(SftModel).where(col(SftModel.model_name) == model_name)
            await session.exec(statement)
            await session.commit()
        return True

    @classmethod
    async def change_sft_model(cls, old_model_name, model_name) -> bool:
        async with get_async_db_session() as session:
            update_statement = update(SftModel).where(SftModel.model_name == old_model_name).values(
                model_name=model_name)
            update_ret = await session.exec(update_statement)
            await session.commit()
            return update_ret.rowcount != 0
