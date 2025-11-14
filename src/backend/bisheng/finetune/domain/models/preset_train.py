from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlmodel import Column, DateTime, Field, select, text, col

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.utils import generate_uuid


# Finetune任务的预置训练集
class PresetTrainBase(SQLModelSerializable):
    id: str = Field(default=None, primary_key=True, description='预置训练文件唯一ID')
    url: str = Field(default='', description='minIo上的文件链接')
    name: str = Field(default='', index=True, description='上传的文件名字')
    user_id: str = Field(default='', index=True, description='创建人ID')
    user_name: str = Field(default='', index=True, description='创建人姓名')
    type: int = Field(default=0, index=True, description='0 文件 1 QA')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class PresetTrain(PresetTrainBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)


class PresetTrainDao(PresetTrainBase):

    @classmethod
    async def insert_batch(cls, models: List[PresetTrain]) -> List[PresetTrain]:
        async with get_async_db_session() as session:
            for one in models:
                session.add(one)
            await session.commit()
            for one in models:
                await session.refresh(one)
            return models

    @classmethod
    async def delete_one(cls, model: PresetTrain) -> bool:
        async with get_async_db_session() as session:
            await session.delete(model)
            await session.commit()
        return True

    @classmethod
    async def find_one(cls, file_id: str) -> PresetTrain | None:
        async with get_async_db_session() as session:
            statement = select(PresetTrain).where(PresetTrain.id == file_id)
            return (await session.exec(statement)).first()

    @classmethod
    async def find_all(cls) -> List[PresetTrain]:
        async with get_async_db_session() as session:
            statement = select(PresetTrain)
            return (await session.exec(statement)).all()

    @classmethod
    async def search_name(cls,
                          keyword: str = None,
                          page_size: int = None,
                          page_num: int = None) -> Tuple[List[PresetTrain], int]:
        async with get_async_db_session() as session:
            statement = select(PresetTrain)
            count = select(func.count(PresetTrain.id))
            if keyword:
                statement = statement.where(col(PresetTrain.name).like('%{}%'.format(keyword)))
                count = count.where(col(PresetTrain.name).like('%{}%'.format(keyword)))
            if page_num and page_size:
                statement = statement.offset((page_num - 1) * page_size).limit(page_size)
            statement = statement.order_by(col(PresetTrain.create_time).desc())

            return (await session.exec(statement)).all(), await session.scalar(count)
