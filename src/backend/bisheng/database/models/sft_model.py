from datetime import datetime
from typing import Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text, update
from sqlmodel import Field, select


# 可用于训练的model列表
class SftModelBase(SQLModelSerializable):
    id: int = Field(default=None, nullable=False, primary_key=True, description='唯一ID')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class SftModel(SftModelBase, table=True):
    model_name: str = Field(index=True, description='可用于微调训练的模型名称')


class SftModelDao(SftModel):

    @classmethod
    def get_sft_model(cls, model_name: str) -> SftModel | None:
        with session_getter() as session:
            statement = select(SftModel).where(SftModel.model_name == model_name)
            return session.exec(statement).first()

    @classmethod
    def get_all_sft_model(cls):
        with session_getter() as session:
            statement = select(SftModel)
            return session.exec(statement).all()

    @classmethod
    def insert_sft_model(cls, model_name: str) -> SftModel:
        with session_getter() as session:
            model = SftModel(model_name=model_name)
            session.add(model)
            session.commit()
            session.refresh(model)
        return model

    @classmethod
    def delete_sft_model(cls, model_name: str) -> bool:
        with session_getter() as session:
            statement = delete(SftModel).where(SftModel.model_name == model_name)
            session.exec(statement)
            session.commit()
        return True

    @classmethod
    def change_sft_model(cls, old_model_name, model_name) -> bool:
        with session_getter() as session:
            update_statement = update(SftModel).where(SftModel.model_name == old_model_name).values(
                model_name=model_name)
            update_ret = session.exec(update_statement)
            session.commit()
            return update_ret.rowcount != 0
