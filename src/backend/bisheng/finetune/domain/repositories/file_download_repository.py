"""Resolve finetune files through durable tenant-scoped records."""

from sqlmodel import select

from bisheng.core.database import get_async_db_session
from bisheng.finetune.domain.models.finetune import Finetune
from bisheng.finetune.domain.models.preset_train import PresetTrain


class FileDownloadRepository:
    @staticmethod
    async def preset_by_object(object_name: str):
        async with get_async_db_session() as session:
            return (await session.exec(select(PresetTrain).where(PresetTrain.url == object_name))).first()

    @staticmethod
    async def owned_jobs(user_id: int):
        async with get_async_db_session() as session:
            return list((await session.exec(select(Finetune).where(Finetune.user_id == user_id))).all())
