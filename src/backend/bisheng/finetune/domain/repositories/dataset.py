from sqlmodel import col, select

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.finetune.domain.models.dataset import FinetuneDataset


class FinetuneDatasetRepository:
    @staticmethod
    async def save(record: FinetuneDataset) -> FinetuneDataset:
        async with get_async_db_session() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
        return record

    @staticmethod
    async def find_by_url(url: str) -> FinetuneDataset | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(FinetuneDataset).where(FinetuneDataset.url == url))).first()

    @staticmethod
    async def find_by_id(version_id: str) -> FinetuneDataset | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(FinetuneDataset).where(FinetuneDataset.id == version_id))).first()

    @staticmethod
    async def list_training(data_type: str | None, page: int, limit: int):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                records = (
                    await session.exec(
                        select(FinetuneDataset)
                        .where(FinetuneDataset.purpose == "training")
                        .order_by(col(FinetuneDataset.create_time).desc(), col(FinetuneDataset.id).desc())
                    )
                ).all()
        # Reports predate a separate modality column. Keep the query dialect-neutral for MySQL/DM8.
        matching = [record for record in records if not data_type or record.report.get("data_type") == data_type]
        return matching[(page - 1) * limit : page * limit], len(matching)
