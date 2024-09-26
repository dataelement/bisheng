from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID, uuid4

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import func
from sqlmodel import Column, DateTime, Field, select, text


# Finetune任务的预置训练集
class PresetTrainBase(SQLModelSerializable):
    id: str = Field(default=None, primary_key=True, description='预置训练文件唯一ID')
    url: str = Field(default='', description='minIo上的文件链接')
    name: str = Field(default='', index=True, description='上传的文件名字')
    user_id: str = Field(default='', index=True, description='创建人ID')
    user_name: str = Field(default='', index=True, description='创建人姓名')
    type: int = Field(default=0, index=True, description='0 文件 1 QA')
    create_time: Optional[datetime] = Field(sa_column=Column(
        DateTime, nullable=False, index=True, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=False,
                         server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


class PresetTrain(PresetTrainBase, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)


class PresetTrainDao(PresetTrainBase):

    @classmethod
    def insert_batch(cls, models: List[PresetTrain]) -> List[PresetTrain]:
        with session_getter() as session:
            for one in models:
                session.add(one)
            session.commit()
            for one in models:
                session.refresh(one)
            return models

    @classmethod
    def delete_one(cls, model: PresetTrain) -> bool:
        with session_getter() as session:
            session.delete(model)
            session.commit()
        return True

    @classmethod
    def find_one(cls, file_id: UUID) -> PresetTrain | None:
        with session_getter() as session:
            statement = select(PresetTrain).where(PresetTrain.id == file_id)
            return session.exec(statement).first()

    @classmethod
    def find_all(cls) -> List[PresetTrain]:
        with session_getter() as session:
            statement = select(PresetTrain)
            return session.exec(statement).all()

    @classmethod
    def search_name(cls,
                    keyword: str = None,
                    page_size: int = None,
                    page_num: int = None) -> Tuple[List[PresetTrain], int]:
        with session_getter() as session:
            statement = select(PresetTrain)
            count = select(func.count(PresetTrain.id))
            if keyword:
                statement = statement.where(PresetTrain.name.like('%{}%'.format(keyword)))
                count = count.where(PresetTrain.name.like('%{}%'.format(keyword)))
            if page_num and page_size:
                statement = statement.offset((page_num - 1) * page_size).limit(page_size)
            statement = statement.order_by(PresetTrain.create_time.desc())

            return session.exec(statement).all(), session.scalar(count)
