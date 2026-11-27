"""Tenant-scoped dataset catalog and atomic immutable-version persistence."""

from sqlmodel import col, func, select

from bisheng.common.errcode.tenant import NoTenantContextError
from bisheng.core.context.tenant import get_current_tenant_id, strict_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.finetune.domain.models.dataset import FinetuneDataset
from bisheng.finetune.domain.models.finetune import Finetune
from bisheng.finetune.domain.models.preset_train import PresetTrain


class DatasetCatalogRepository:
    @staticmethod
    async def list(data_type=None, source_type=None, keyword=None, page=1, limit=20, ready_only=False):
        filters = [col(PresetTrain.is_deleted).is_(False)]
        if data_type:
            filters.append(PresetTrain.data_type == data_type)
        if source_type:
            filters.append(PresetTrain.source_type == source_type)
        if keyword:
            filters.append(col(PresetTrain.name).contains(keyword))
        statement = select(PresetTrain)
        count = select(func.count(PresetTrain.id))
        if ready_only:
            filters.extend([PresetTrain.data_type != "legacy", FinetuneDataset.purpose == "training"])
            statement = statement.join(FinetuneDataset, PresetTrain.version_id == FinetuneDataset.id)
            count = count.join(FinetuneDataset, PresetTrain.version_id == FinetuneDataset.id)
        with strict_tenant_filter():
            if ready_only:
                # COUNT queries can hide the joined mapper from automatic discovery.
                clause = build_tenant_filter_clause(FinetuneDataset.tenant_id)
                if clause is not None:
                    filters.append(clause)
            async with get_async_db_session() as session:
                catalogs = (
                    await session.exec(
                        statement.where(*filters)
                        .order_by(col(PresetTrain.create_time).desc(), col(PresetTrain.id).desc())
                        .offset((page - 1) * limit)
                        .limit(limit)
                    )
                ).all()
                total = await session.scalar(count.where(*filters))
                identifiers = [record.version_id for record in catalogs if record.version_id]
                versions = (
                    (await session.exec(select(FinetuneDataset).where(col(FinetuneDataset.id).in_(identifiers)))).all()
                    if identifiers
                    else []
                )
                by_id = {version.id: version for version in versions}
                return [(record, by_id.get(record.version_id)) for record in catalogs], total

    @staticmethod
    async def find(identifier: str, *, version=False, include_deleted=False):
        statement = select(PresetTrain).where(
            PresetTrain.version_id == identifier if version else PresetTrain.id == identifier
        )
        if not include_deleted:
            statement = statement.where(col(PresetTrain.is_deleted).is_(False))
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(statement)).first()

    @staticmethod
    async def save(catalog: PresetTrain, version: FinetuneDataset | None = None):
        if get_current_tenant_id() is None:
            raise NoTenantContextError()
        async with get_async_db_session() as session:
            if version is not None:
                session.add(version)
            session.add(catalog)
            await session.commit()
            await session.refresh(catalog)
            return catalog

    @staticmethod
    async def delete(identifier):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                record = (
                    await session.exec(
                        select(PresetTrain).where(PresetTrain.id == identifier, col(PresetTrain.is_deleted).is_(False))
                    )
                ).first()
                if record is None:
                    return False
                record.is_deleted = True
                session.add(record)
                await session.commit()
                return True

    @staticmethod
    async def job_by_upload(upload_id):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(select(Finetune).where(Finetune.transient_upload_id == upload_id))).first()

    @staticmethod
    async def historical_versions(after="", limit=100):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return list(
                    (
                        await session.exec(
                            select(FinetuneDataset)
                            .where(FinetuneDataset.purpose == "training", FinetuneDataset.id > after)
                            .order_by(FinetuneDataset.id)
                            .limit(limit)
                        )
                    ).all()
                )

    @staticmethod
    async def find_url(url, include_deleted=False):
        statement = select(PresetTrain).where(PresetTrain.url == url)
        if not include_deleted:
            statement = statement.where(col(PresetTrain.is_deleted).is_(False))
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return (await session.exec(statement)).first()

    @staticmethod
    async def historical_catalogs(after="", limit=100):
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                return list(
                    (
                        await session.exec(
                            select(PresetTrain).where(PresetTrain.id > after).order_by(PresetTrain.id).limit(limit)
                        )
                    ).all()
                )
