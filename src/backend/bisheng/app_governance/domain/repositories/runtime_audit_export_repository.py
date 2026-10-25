"""Persistent export ownership, separate from the streaming source session."""

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from bisheng.app_governance.domain.models.runtime_audit import RuntimeAuditExport, RuntimeAuditQuerySnapshot
from bisheng.common.errcode.app_governance import RuntimeAuditExportUnavailableError
from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session


class RuntimeAuditExportRepository:
    def __init__(self, factory=get_async_db_session):
        self.factory = factory

    async def get(self, tenant_id, job_id):
        with tenant_execution_scope(tenant_id):
            async with self.factory() as s:
                return (
                    await s.exec(
                        select(RuntimeAuditExport).where(
                            RuntimeAuditExport.id == job_id, RuntimeAuditExport.tenant_id == tenant_id
                        )
                    )
                ).first()

    async def create(self, row):
        try:
            with tenant_execution_scope(row.tenant_id):
                async with self.factory() as s:
                    existing = (
                        await s.exec(
                            select(RuntimeAuditExport).where(
                                RuntimeAuditExport.creator_user_id == row.creator_user_id,
                                RuntimeAuditExport.request_id == row.request_id,
                            )
                        )
                    ).first()
                    if existing:
                        if existing.snapshot_id != row.snapshot_id:
                            raise RuntimeAuditExportUnavailableError()
                        return existing
                    s.add(row)
                    await s.commit()
            return row
        except IntegrityError:
            with tenant_execution_scope(row.tenant_id):
                async with self.factory() as s:
                    existing = (
                        await s.exec(
                            select(RuntimeAuditExport).where(
                                RuntimeAuditExport.creator_user_id == row.creator_user_id,
                                RuntimeAuditExport.request_id == row.request_id,
                            )
                        )
                    ).first()
                    if existing and existing.snapshot_id == row.snapshot_id:
                        return existing
            raise

    async def claim(self, tenant_id, job_id, holder):
        with tenant_execution_scope(tenant_id):
            async with self.factory() as s:
                anchor = (
                    await s.exec(
                        select(RuntimeAuditExport)
                        .where(RuntimeAuditExport.tenant_id == tenant_id)
                        .order_by(RuntimeAuditExport.created_at, RuntimeAuditExport.id)
                        .limit(1)
                        .with_for_update()
                    )
                ).first()
                if anchor is None:
                    return None
                now = datetime.utcnow()
                running = (
                    await s.exec(
                        select(func.count())
                        .select_from(RuntimeAuditExport)
                        .where(
                            RuntimeAuditExport.tenant_id == tenant_id,
                            RuntimeAuditExport.status == "running",
                            RuntimeAuditExport.lease_until > now,
                        )
                    )
                ).one()
                if running >= 2:
                    return None
                row = (
                    await s.exec(
                        select(RuntimeAuditExport)
                        .where(RuntimeAuditExport.id == job_id, RuntimeAuditExport.tenant_id == tenant_id)
                        .with_for_update()
                    )
                ).first()
                now = datetime.utcnow()
                if (
                    not row
                    or row.status not in {"pending", "running"}
                    or (row.status == "running" and row.lease_until and row.lease_until > now)
                ):
                    return None
                row.epoch += 1
                row.attempt += 1
                row.status = "running"
                row.lease_holder = holder
                row.lease_until = now + timedelta(seconds=120)
                row.selection_started_at = now
                row.processed_rows = 0
                row.manifest_object_key = None
                row.manifest_digest = None
                row.final_count = None
                s.add(row)
                await s.commit()
                return row

    async def checkpoint(self, job, **values):
        with tenant_execution_scope(job.tenant_id):
            async with self.factory() as s:
                row = (
                    await s.exec(
                        select(RuntimeAuditExport)
                        .where(RuntimeAuditExport.id == job.id, RuntimeAuditExport.tenant_id == job.tenant_id)
                        .with_for_update()
                    )
                ).first()
                now = datetime.utcnow()
                if (
                    not row
                    or row.status != "running"
                    or row.epoch != job.epoch
                    or row.lease_holder != job.lease_holder
                    or row.lease_until <= now
                ):
                    raise RuntimeAuditExportUnavailableError()
                for key, value in values.items():
                    setattr(row, key, value)
                row.lease_until = now + timedelta(seconds=120)
                s.add(row)
                await s.commit()
                return row

    async def terminate(self, tenant_id, job_id, status):
        with tenant_execution_scope(tenant_id):
            async with self.factory() as s:
                row = (
                    await s.exec(
                        select(RuntimeAuditExport)
                        .where(RuntimeAuditExport.id == job_id, RuntimeAuditExport.tenant_id == tenant_id)
                        .with_for_update()
                    )
                ).first()
                if row:
                    row.status = status
                    row.epoch += 1
                    row.lease_until = None
                    s.add(row)
                    await s.commit()
                return row

    async def recoverable(self):
        # Scheduler enumeration only; every job re-enters its own tenant and is
        # authorized again before any source read or object delivery.
        now = datetime.utcnow()
        with bypass_tenant_filter():
            async with self.factory() as s:
                return list(
                    (
                        await s.exec(
                            select(RuntimeAuditExport)
                            .where(
                                or_(
                                    RuntimeAuditExport.status == "pending",
                                    and_(RuntimeAuditExport.status == "running", RuntimeAuditExport.lease_until < now),
                                )
                            )
                            .order_by(RuntimeAuditExport.created_at)
                            .limit(50)
                        )
                    ).all()
                )

    async def worker_user(self, user_id):
        from bisheng.user.domain.models.user import User

        with bypass_tenant_filter():
            async with self.factory() as s:
                return (await s.exec(select(User).where(User.user_id == user_id, User.delete == 0))).first()

    async def gc_candidates(self):
        now = datetime.utcnow()
        with bypass_tenant_filter():
            async with self.factory() as session:
                return list(
                    (
                        await session.exec(
                            select(RuntimeAuditExport)
                            .where(RuntimeAuditExport.gc_completed_at.is_(None))
                            .where(
                                or_(
                                    RuntimeAuditExport.status.in_(["failed", "expired"]),
                                    and_(
                                        RuntimeAuditExport.status == "ready",
                                        RuntimeAuditExport.download_expires_at < now,
                                    ),
                                )
                            )
                            .order_by(RuntimeAuditExport.created_at)
                            .limit(50)
                        )
                    ).all()
                )

    async def clear_snapshots(self):
        from sqlalchemy import delete

        now = datetime.utcnow()
        # Only unreferenced/terminal selections are eligible. Filter in SQL so
        # a long-running queue cannot starve later expired snapshots.
        referenced = (
            select(RuntimeAuditExport.id)
            .where(
                RuntimeAuditExport.snapshot_id == RuntimeAuditQuerySnapshot.id,
                RuntimeAuditExport.tenant_id == RuntimeAuditQuerySnapshot.tenant_id,
                or_(
                    RuntimeAuditExport.status.in_(["pending", "running"]),
                    and_(RuntimeAuditExport.status == "ready", RuntimeAuditExport.download_expires_at > now),
                ),
            )
            .exists()
        )
        with bypass_tenant_filter():
            async with self.factory() as session:
                stale = list(
                    (
                        await session.exec(
                            select(RuntimeAuditQuerySnapshot)
                            .where(RuntimeAuditQuerySnapshot.expires_at < now, ~referenced)
                            .limit(100)
                        )
                    ).all()
                )
                for row in stale:
                    await session.execute(
                        delete(RuntimeAuditQuerySnapshot).where(
                            RuntimeAuditQuerySnapshot.id == row.id, RuntimeAuditQuerySnapshot.tenant_id == row.tenant_id
                        )
                    )
                await session.commit()

    async def mark_gc_complete(self, tenant_id, job_id):
        with tenant_execution_scope(tenant_id):
            async with self.factory() as session:
                row = (
                    await session.exec(
                        select(RuntimeAuditExport)
                        .where(RuntimeAuditExport.id == job_id, RuntimeAuditExport.tenant_id == tenant_id)
                        .with_for_update()
                    )
                ).first()
                if row and row.status in {"failed", "expired"}:
                    row.gc_completed_at = datetime.utcnow()
                    session.add(row)
                    await session.commit()
