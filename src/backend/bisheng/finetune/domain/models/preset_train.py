from datetime import datetime

from sqlalchemy import Integer, func
from sqlmodel import Column, DateTime, Field, col, select, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session

# FinetunePreset training set for tasks
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.utils import generate_uuid


class PresetTrainBase(SQLModelSerializable):
    id: str = Field(default=None, primary_key=True, description="Preset Training Files UniqueID")
    url: str = Field(default="", description="minIoFile link on")
    name: str = Field(default="", index=True, description="Uploaded file name")
    user_id: str = Field(default="", index=True, description="creatorID")
    user_name: str = Field(default="", index=True, description="creatorName")
    type: int = Field(default=0, index=True, description="0 Doc. 1 QA")
    data_type: str = Field(default="legacy", max_length=32, index=True, sa_column_kwargs={"server_default": "legacy"})
    source_type: str = Field(default="local", max_length=16, sa_column_kwargs={"server_default": "local"})
    version_id: str | None = Field(default=None, max_length=64, unique=True, index=True)
    source_dataset_id: str | None = Field(default=None, max_length=64)
    is_deleted: bool = Field(default=False, index=True, sa_column_kwargs={"server_default": "0"})
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    create_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, index=True, server_default=text("CURRENT_TIMESTAMP"))
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class PresetTrain(PresetTrainBase, table=True):
    id: str = Field(default_factory=generate_uuid, primary_key=True, unique=True)


class PresetTrainDao(PresetTrainBase):
    @classmethod
    async def insert_batch(cls, models: list[PresetTrain]) -> list[PresetTrain]:
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
            statement = select(PresetTrain).where(PresetTrain.id == file_id, col(PresetTrain.is_deleted).is_(False))
            with strict_tenant_filter():
                return (await session.exec(statement)).first()

    @classmethod
    async def find_all(cls) -> list[PresetTrain]:
        async with get_async_db_session() as session:
            statement = select(PresetTrain).where(col(PresetTrain.is_deleted).is_(False))
            with strict_tenant_filter():
                return (await session.exec(statement)).all()

    @classmethod
    async def find_by_url(cls, url: str) -> PresetTrain | None:
        async with get_async_db_session() as session:
            with strict_tenant_filter():
                return (
                    await session.exec(
                        select(PresetTrain).where(PresetTrain.url == url, col(PresetTrain.is_deleted).is_(False))
                    )
                ).first()

    @classmethod
    async def search_name(
        cls, keyword: str | None = None, page_size: int | None = None, page_num: int | None = None
    ) -> tuple[list[PresetTrain], int]:
        async with get_async_db_session() as session:
            statement = select(PresetTrain).where(col(PresetTrain.is_deleted).is_(False))
            count = select(func.count(PresetTrain.id)).where(col(PresetTrain.is_deleted).is_(False))
            if keyword:
                statement = statement.where(col(PresetTrain.name).like(f"%{keyword}%"))
                count = count.where(col(PresetTrain.name).like(f"%{keyword}%"))
            if page_num and page_size:
                statement = statement.offset((page_num - 1) * page_size).limit(page_size)
            statement = statement.order_by(col(PresetTrain.create_time).desc(), col(PresetTrain.id).desc())

            # Both administrators manage the selected tenant, even when a
            # legacy caller has made Root visible for explicit model sharing.
            with strict_tenant_filter():
                return (await session.exec(statement)).all(), await session.scalar(count)
