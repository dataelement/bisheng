"""SQLModel implementation of scheduled filelib sync run log repository."""

from __future__ import annotations

from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import strict_tenant_filter
from bisheng.open_endpoints.domain.models.filelib_scheduled_sync_run_log import FilelibScheduledSyncRunLog
from bisheng.open_endpoints.domain.repositories.interfaces.filelib_scheduled_sync_run_log_repository import (
    FilelibScheduledSyncRunLogCreate,
    FilelibScheduledSyncRunLogRepository,
    FilelibScheduledSyncRunLogUpdate,
)


class FilelibScheduledSyncRunLogRepositoryImpl(FilelibScheduledSyncRunLogRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert(self, payload: FilelibScheduledSyncRunLogCreate) -> int:
        model = FilelibScheduledSyncRunLog(
            tenant_id=payload.tenant_id,
            job_code=payload.job_code,
            trigger_type=payload.trigger_type,
            status=payload.status,
            developer_token_id=payload.developer_token_id,
            file_id=payload.file_id,
            knowledge_id=payload.knowledge_id,
            file_name=payload.file_name,
            error_message=payload.error_message,
            start_time=payload.start_time,
            end_time=payload.end_time,
            duration_ms=payload.duration_ms,
        )
        self.session.add(model)
        await self.session.flush()
        assert model.id is not None
        return int(model.id)

    async def update(self, run_id: int, payload: FilelibScheduledSyncRunLogUpdate) -> None:
        with strict_tenant_filter():
            result = await self.session.exec(
                select(FilelibScheduledSyncRunLog).where(FilelibScheduledSyncRunLog.id == run_id)
            )
        model = result.first()
        if model is None:
            raise ValueError(f"run log {run_id} not found")
        if payload.status is not None:
            model.status = payload.status
        if payload.developer_token_id is not None:
            model.developer_token_id = payload.developer_token_id
        if payload.file_id is not None:
            model.file_id = payload.file_id
        if payload.knowledge_id is not None:
            model.knowledge_id = payload.knowledge_id
        if payload.file_name is not None:
            model.file_name = payload.file_name
        if payload.error_message is not None:
            model.error_message = payload.error_message
        if payload.end_time is not None:
            model.end_time = payload.end_time
        if payload.duration_ms is not None:
            model.duration_ms = payload.duration_ms
        self.session.add(model)
        await self.session.flush()

    async def list_by_tenant(
        self,
        tenant_id: int,
        *,
        job_code: str,
        page: int,
        limit: int,
    ) -> tuple[list[FilelibScheduledSyncRunLog], int]:
        filters = (
            FilelibScheduledSyncRunLog.tenant_id == tenant_id,
            FilelibScheduledSyncRunLog.job_code == job_code,
        )
        with strict_tenant_filter():
            total_result = await self.session.exec(
                select(func.count()).select_from(FilelibScheduledSyncRunLog).where(*filters)
            )
            total = int(total_result.one())
            result = await self.session.exec(
                select(FilelibScheduledSyncRunLog)
                .where(*filters)
                .order_by(
                    col(FilelibScheduledSyncRunLog.start_time).desc(),
                    col(FilelibScheduledSyncRunLog.id).desc(),
                )
                .offset((page - 1) * limit)
                .limit(limit)
            )
        return list(result.all()), total
