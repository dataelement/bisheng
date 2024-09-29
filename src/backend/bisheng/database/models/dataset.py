from datetime import datetime
from typing import Any, List, Optional

from bisheng.database.base import session_getter
from bisheng.database.models.base import SQLModelSerializable
from sqlalchemy import Column, DateTime, delete, text
from sqlmodel import Field, select


class DatasetBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True, description='创建用户id')
    name: str = Field(index=True, description='数据集名称')
    type: str = Field(index=False, default=0, description='预留字段')
    description: Optional[str] = Field(index=False, description='数据集描述')
    object_name: Optional[str] = Field(index=False, description='数据集S3名称')
    create_time: Optional[datetime] = Field(
        sa_column=Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(
        sa_column=Column(DateTime,
                         nullable=True,
                         server_default=text('CURRENT_TIMESTAMP'),
                         onupdate=text('CURRENT_TIMESTAMP')))


class Dataset(DatasetBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class DatasetCreate(DatasetBase):
    pass


class DatasetRead(DatasetBase):
    user_name: Optional[str]
    url: Optional[str]


class DatasetUpdate(DatasetBase):
    pass


class DatasetDao(DatasetBase):

    @classmethod
    def filter_dataset_by_ids(cls,
                              dataset_ids: List[int],
                              keyword: str = None,
                              page: int = 0,
                              limit: int = 0) -> List[Dataset]:
        with session_getter() as session:
            query = select(Dataset)
            if dataset_ids:
                query = query.where(Dataset.id.in_(dataset_ids))
            if keyword:
                query = query.where(Dataset.name.like(f'%{keyword}%'))
            if page and limit:
                query = query.order_by(Dataset.update_time.desc()).offset(
                    (page - 1) * limit).limit(limit)

            return session.exec(query).all()

    @classmethod
    def get_count_by_filter(cls, filters: List[Any]) -> int:
        with session_getter() as session:
            return session.scalar(select(Dataset.id).where(*filters))

    @classmethod
    def insert(cls, dataset: DatasetCreate):
        with session_getter() as session:
            db_insert = Dataset.validate(dataset)
            session.add(db_insert)
            session.commit()
            session.refresh(db_insert)
            return db_insert

    @classmethod
    def get_dataset_by_name(cls, name: str):
        with session_getter() as session:
            return session.exec(select(Dataset).where(Dataset.name == name)).all()

    @classmethod
    def update(cls, data: Dataset):
        with session_getter() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete(cls, dataset_id: int):
        with session_getter() as session:
            session.exec(delete(Dataset).where(Dataset.id == dataset_id))
            session.commit()
