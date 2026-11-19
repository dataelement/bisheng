"""昆联工作流资料同步事件持久 Outbox 仓储。"""

from __future__ import annotations

from dataclasses import dataclass
import time

from sqlalchemy import or_
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
from bisheng.core.database import get_async_db_session
from bisheng.workflow.domain.models.kunlian_snapshot_outbox import KunlianWorkflowSnapshotOutbox

STATUS_PENDING = "PENDING"
STATUS_RETRYING = "RETRYING"
STATUS_DELIVERED = "DELIVERED"
STATUS_FAILED = "FAILED"
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_RETRYING)


@dataclass(frozen=True)
class ClaimedSnapshotEvent:
    """已认领待投递的快照同步事件。"""

    event_id: str
    tenant_id: int
    workflow_id: str
    actor_sub: str
    payload_json: str
    attempts: int


class KunlianSnapshotOutboxRepository:
    """管理 workflow_kl_snapshot_outbox 的入队、认领、重试调度与状态更新。"""

    def __init__(self, *, session_factory=None, clock=None):
        self._session_factory = session_factory or get_async_db_session
        self._clock = clock or (lambda: int(time.time()))

    async def enqueue(
        self,
        *,
        tenant_id: int,
        workflow_id: str,
        actor_sub: str,
        event_id: str,
        payload_json: str,
    ) -> KunlianWorkflowSnapshotOutbox:
        now = self._clock()
        row = KunlianWorkflowSnapshotOutbox(
            event_id=event_id,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            actor_sub=actor_sub,
            payload_json=payload_json,
            status=STATUS_PENDING,
            attempts=0,
            next_retry_at=now,
        )
        with tenant_execution_scope(tenant_id):
            async with self._session_factory() as session:
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return row

    async def claim_by_event_id(
        self,
        tenant_id: int,
        event_id: str,
        *,
        claim_ttl_seconds: int = 60,
        ignore_schedule: bool = False,
    ) -> ClaimedSnapshotEvent | None:
        now = self._clock()
        stale_before = now - claim_ttl_seconds
        with tenant_execution_scope(tenant_id):
            async with self._session_factory() as session:
                stmt = (
                    select(KunlianWorkflowSnapshotOutbox)
                    .where(
                        KunlianWorkflowSnapshotOutbox.tenant_id == tenant_id,
                        KunlianWorkflowSnapshotOutbox.event_id == event_id,
                    )
                    .with_for_update()
                )
                row = (await session.exec(stmt)).first()
                if row is None or row.status not in ACTIVE_STATUSES:
                    return None
                if not ignore_schedule and row.next_retry_at > now:
                    return None
                if row.claimed_at is not None and row.claimed_at > stale_before:
                    return None
                row.claimed_at = now
                session.add(row)
                await session.commit()
                return ClaimedSnapshotEvent(
                    event_id=row.event_id,
                    tenant_id=row.tenant_id,
                    workflow_id=row.workflow_id,
                    actor_sub=row.actor_sub,
                    payload_json=row.payload_json,
                    attempts=row.attempts,
                )

    async def list_due_references(
        self,
        *,
        limit: int = 100,
        claim_ttl_seconds: int = 60,
    ) -> list[tuple[int, str]]:
        now = self._clock()
        stale_before = now - claim_ttl_seconds
        with bypass_tenant_filter():
            async with self._session_factory() as session:
                stmt = (
                    select(
                        KunlianWorkflowSnapshotOutbox.tenant_id,
                        KunlianWorkflowSnapshotOutbox.event_id,
                    )
                    .where(
                        KunlianWorkflowSnapshotOutbox.status.in_(ACTIVE_STATUSES),
                        KunlianWorkflowSnapshotOutbox.next_retry_at <= now,
                        or_(
                            KunlianWorkflowSnapshotOutbox.claimed_at.is_(None),
                            KunlianWorkflowSnapshotOutbox.claimed_at <= stale_before,
                        ),
                    )
                    .order_by(KunlianWorkflowSnapshotOutbox.next_retry_at.asc())
                    .limit(limit)
                )
                rows = (await session.exec(stmt)).all()
                return [(int(tenant_id), str(event_id)) for tenant_id, event_id in rows]

    async def mark_delivered(
        self,
        tenant_id: int,
        event_id: str,
        *,
        status_code: int,
        request_id: str | None = None,
    ) -> None:
        now = self._clock()
        with tenant_execution_scope(tenant_id):
            async with self._session_factory() as session:
                stmt = (
                    select(KunlianWorkflowSnapshotOutbox)
                    .where(
                        KunlianWorkflowSnapshotOutbox.tenant_id == tenant_id,
                        KunlianWorkflowSnapshotOutbox.event_id == event_id,
                    )
                    .with_for_update()
                )
                row = (await session.exec(stmt)).first()
                if row is None:
                    return
                row.status = STATUS_DELIVERED
                row.attempts += 1
                row.claimed_at = None
                row.delivered_at = now
                row.last_status_code = status_code
                row.last_request_id = (request_id or "")[:128] or None
                row.last_error = None
                session.add(row)
                await session.commit()

    async def mark_retry(
        self,
        tenant_id: int,
        event_id: str,
        *,
        delay_seconds: int,
        status_code: int | None = None,
        request_id: str | None = None,
        error: str | None = None,
    ) -> None:
        now = self._clock()
        with tenant_execution_scope(tenant_id):
            async with self._session_factory() as session:
                stmt = (
                    select(KunlianWorkflowSnapshotOutbox)
                    .where(
                        KunlianWorkflowSnapshotOutbox.tenant_id == tenant_id,
                        KunlianWorkflowSnapshotOutbox.event_id == event_id,
                    )
                    .with_for_update()
                )
                row = (await session.exec(stmt)).first()
                if row is None or row.status == STATUS_DELIVERED:
                    return
                row.status = STATUS_RETRYING
                row.attempts += 1
                row.claimed_at = None
                row.next_retry_at = now + max(1, int(delay_seconds))
                row.last_status_code = status_code
                row.last_request_id = (request_id or "")[:128] or None
                row.last_error = (error or "")[:255] or None
                session.add(row)
                await session.commit()

    async def mark_failed(
        self,
        tenant_id: int,
        event_id: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with tenant_execution_scope(tenant_id):
            async with self._session_factory() as session:
                stmt = (
                    select(KunlianWorkflowSnapshotOutbox)
                    .where(
                        KunlianWorkflowSnapshotOutbox.tenant_id == tenant_id,
                        KunlianWorkflowSnapshotOutbox.event_id == event_id,
                    )
                    .with_for_update()
                )
                row = (await session.exec(stmt)).first()
                if row is None or row.status == STATUS_DELIVERED:
                    return
                row.status = STATUS_FAILED
                row.attempts += 1
                row.claimed_at = None
                row.last_status_code = status_code
                row.last_request_id = (request_id or "")[:128] or None
                row.last_error = (error or "")[:255] or None
                session.add(row)
                await session.commit()
