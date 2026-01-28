from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import Column, DateTime, delete, text
from sqlmodel import Field, select

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_sync_db_session


class DatasetBase(SQLModelSerializable):
    user_id: Optional[int] = Field(index=True, description='Create Userid')
    name: str = Field(index=True, description='Dataset Name')
    type: str = Field(index=False, default=0, description='Reserved Fields')
    description: Optional[str] = Field(default=None, index=False, description='Dataset description')
    object_name: Optional[str] = Field(default=None, index=False, description='data setS3Part Name')
    create_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')))
    update_time: Optional[datetime] = Field(default=None, sa_column=Column(
        DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')))


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
        with get_sync_db_session() as session:
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
        with get_sync_db_session() as session:
            return session.scalar(select(Dataset.id).where(*filters))

    @classmethod
    def insert(cls, dataset: DatasetCreate):
        with get_sync_db_session() as session:
            db_insert = Dataset.validate(dataset)
            session.add(db_insert)
            session.commit()
            session.refresh(db_insert)
            return db_insert

    @classmethod
    def get_dataset_by_name(cls, name: str):
        with get_sync_db_session() as session:
            return session.exec(select(Dataset).where(Dataset.name == name)).all()

    @classmethod
    def update(cls, data: Dataset):
        with get_sync_db_session() as session:
            session.add(data)
            session.commit()
            session.refresh(data)
            return data

    @classmethod
    def delete(cls, dataset_id: int):
        with get_sync_db_session() as session:
            session.exec(delete(Dataset).where(Dataset.id == dataset_id))
            session.commit()
