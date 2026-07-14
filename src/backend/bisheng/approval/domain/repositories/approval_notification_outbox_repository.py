from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.approval.domain.models.approval_notification_outbox import (
    ApprovalNotificationOutbox,
    ApprovalNotificationOutboxStatus,
)
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session


class ApprovalNotificationOutboxRepository:
    @classmethod
    async def create_or_get(
        cls,
        row: ApprovalNotificationOutbox,
    ) -> ApprovalNotificationOutbox:
        async with get_async_db_session() as session:
            session.add(row)
            try:
                await session.commit()
                await session.refresh(row)
                return row
            except IntegrityError:
                await session.rollback()
                statement = select(ApprovalNotificationOutbox).where(
                    ApprovalNotificationOutbox.instance_id == row.instance_id,
                    ApprovalNotificationOutbox.event_type == row.event_type,
                )
                existing = (await session.exec(statement)).first()
                if existing is None:
                    raise
                return existing

    @classmethod
    async def get(cls, outbox_id: int) -> ApprovalNotificationOutbox | None:
        async with get_async_db_session() as session:
            return await session.get(ApprovalNotificationOutbox, outbox_id)

    @classmethod
    async def save(
        cls,
        row: ApprovalNotificationOutbox,
    ) -> ApprovalNotificationOutbox:
        async with get_async_db_session() as session:
            saved = await session.get(ApprovalNotificationOutbox, row.id)
            if saved is None:
                raise ValueError(f"approval notification outbox not found: {row.id}")
            for key, value in row.model_dump(mode="python", exclude_unset=False).items():
                setattr(saved, key, value)
            session.add(saved)
            await session.commit()
            await session.refresh(saved)
            return saved

    @classmethod
    async def mark_success(cls, outbox_id: int) -> ApprovalNotificationOutbox:
        row = await cls.get(outbox_id)
        if row is None:
            raise ValueError(f"approval notification outbox not found: {outbox_id}")
        row.status = ApprovalNotificationOutboxStatus.SUCCESS
        row.error_summary = None
        return await cls.save(row)

    @classmethod
    async def mark_failed(
        cls,
        outbox_id: int,
        error_summary: str,
    ) -> ApprovalNotificationOutbox:
        row = await cls.get(outbox_id)
        if row is None:
            raise ValueError(f"approval notification outbox not found: {outbox_id}")
        row.status = ApprovalNotificationOutboxStatus.FAILED
        row.retry_count += 1
        row.error_summary = error_summary[:2000]
        return await cls.save(row)

    @classmethod
    async def list_dispatchable(cls, *, limit: int = 100) -> list[ApprovalNotificationOutbox]:
        statement = (
            select(ApprovalNotificationOutbox)
            .where(
                ApprovalNotificationOutbox.status.in_(
                    (
                        ApprovalNotificationOutboxStatus.PENDING,
                        ApprovalNotificationOutboxStatus.FAILED,
                    )
                ),
                ApprovalNotificationOutbox.retry_count < ApprovalNotificationOutbox.max_retries,
            )
            .order_by(
                ApprovalNotificationOutbox.update_time.asc(),
                ApprovalNotificationOutbox.id.asc(),
            )
            .limit(limit)
        )
        async with get_async_db_session() as session:
            with bypass_tenant_filter():
                return list((await session.exec(statement)).all())
