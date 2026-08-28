"""全文 Outbox 的 session-aware revision、租约和 CAS 实现。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, text, update
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
    KnowledgeFulltextOutboxStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_outbox_repository import (
    KnowledgeFulltextOutboxRepository,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_after_commit_service import (
    track_outbox_after_commit,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import (
    KnowledgeFulltextAutoRepairService,
)


class KnowledgeFulltextOutboxRepositoryImpl(KnowledgeFulltextOutboxRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def validate_storage(self) -> None:
        """只读访问 Outbox 表, 缺表或连接异常时由数据库异常失败关闭。"""
        await self.session.execute(select(KnowledgeFulltextOutbox.id).limit(1))

    async def list_by_ids(self, outbox_ids: list[int]) -> list[KnowledgeFulltextOutbox]:
        if not outbox_ids:
            return []
        if len(outbox_ids) > 1000:
            raise ValueError("outbox_ids must contain at most 1000 items")
        if any(int(outbox_id) <= 0 for outbox_id in outbox_ids):
            raise ValueError("outbox_ids must be positive")
        result = await self.session.execute(
            select(KnowledgeFulltextOutbox)
            .where(col(KnowledgeFulltextOutbox.id).in_(list(dict.fromkeys(outbox_ids))))
            .order_by(KnowledgeFulltextOutbox.id.asc())
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def list_auto_repair_candidates(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[KnowledgeFulltextOutbox]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        source_error = or_(
            KnowledgeFulltextOutbox.error_summary
            == "KnowledgeFulltextChunkCorruptedError:sync_failed",
            and_(
                KnowledgeFulltextOutbox.error_summary
                == "KnowledgeFulltextChunkNotReadyError:sync_failed",
                KnowledgeFulltextOutbox.retry_count
                >= constants.KNOWLEDGE_FULLTEXT_AUTO_REPAIR_NOT_READY_FAILURES,
            ),
        )
        repair_delivery = col(KnowledgeFulltextOutbox.error_summary).in_(
            [
                "KnowledgeFulltextAutoRepairRequested:repair_pending",
                "KnowledgeFulltextAutoRepairProcessing:repair_processing",
            ]
        )
        result = await self.session.execute(
            select(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.aggregate_type
                == KnowledgeFulltextAggregateType.FILE.value,
                KnowledgeFulltextOutbox.desired_action
                == KnowledgeFulltextDesiredAction.SYNC_CURRENT.value,
                KnowledgeFulltextOutbox.desired_revision
                > KnowledgeFulltextOutbox.applied_revision,
                col(KnowledgeFulltextOutbox.status).in_(
                    [
                        KnowledgeFulltextOutboxStatus.PENDING.value,
                        KnowledgeFulltextOutboxStatus.PROCESSING.value,
                        KnowledgeFulltextOutboxStatus.FAILED.value,
                    ]
                ),
                or_(source_error, repair_delivery),
                or_(
                    KnowledgeFulltextOutbox.lease_until.is_(None),
                    KnowledgeFulltextOutbox.lease_until < now,
                ),
            )
            .order_by(KnowledgeFulltextOutbox.update_time.asc(), KnowledgeFulltextOutbox.id.asc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def request_sync(
        self,
        *,
        aggregate_type: KnowledgeFulltextAggregateType,
        aggregate_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
        max_retries: int,
        knowledge_id: int | None = None,
    ) -> KnowledgeFulltextOutbox:
        if self.session.bind is not None and self.session.bind.dialect.name == "mysql":
            row = await self._request_sync_mysql(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                desired_action=desired_action,
                trigger_type=trigger_type,
                tenant_id=tenant_id,
                max_retries=max_retries,
                knowledge_id=knowledge_id,
            )
        else:
            statement = (
                select(KnowledgeFulltextOutbox)
                .where(
                    KnowledgeFulltextOutbox.tenant_id == tenant_id,
                    KnowledgeFulltextOutbox.aggregate_type == aggregate_type.value,
                    KnowledgeFulltextOutbox.aggregate_id == aggregate_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            result = await self.session.execute(statement)
            row = result.scalars().first()
            if row is None and self.session.bind is not None and self.session.bind.dialect.name == "dm":
                # DM8 requires serializing the initial insert without native upsert support.
                await self.session.execute(text("LOCK TABLE knowledge_fulltext_outbox IN EXCLUSIVE MODE"))
                row = (await self.session.execute(statement)).scalars().first()
            if row is None:
                row = KnowledgeFulltextOutbox(
                    tenant_id=tenant_id,
                    aggregate_type=aggregate_type.value,
                    aggregate_id=aggregate_id,
                    knowledge_id=knowledge_id,
                    desired_action=desired_action.value,
                    desired_revision=1,
                    applied_revision=0,
                    trigger_type=trigger_type,
                    status=KnowledgeFulltextOutboxStatus.PENDING.value,
                    max_retries=max_retries,
                )
            else:
                self._merge_request(
                    row,
                    knowledge_id=knowledge_id,
                    desired_action=desired_action,
                    trigger_type=trigger_type,
                    max_retries=max_retries,
                )
            self.session.add(row)
            await self.session.flush()
            await self.session.refresh(row)
        track_outbox_after_commit(self.session, row)
        return row

    async def _request_sync_mysql(
        self,
        *,
        aggregate_type: KnowledgeFulltextAggregateType,
        aggregate_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
        max_retries: int,
        knowledge_id: int | None,
    ) -> KnowledgeFulltextOutbox:
        table = KnowledgeFulltextOutbox.__table__
        statement = mysql_insert(table).values(
            tenant_id=tenant_id,
            aggregate_type=aggregate_type.value,
            aggregate_id=aggregate_id,
            knowledge_id=knowledge_id,
            desired_action=desired_action.value,
            desired_revision=1,
            applied_revision=0,
            trigger_type=trigger_type,
            status=KnowledgeFulltextOutboxStatus.PENDING.value,
            retry_count=0,
            max_retries=max_retries,
        )
        await self.session.execute(
            statement.on_duplicate_key_update(
                knowledge_id=statement.inserted.knowledge_id,
                desired_action=statement.inserted.desired_action,
                desired_revision=table.c.desired_revision + 1,
                trigger_type=statement.inserted.trigger_type,
                status=KnowledgeFulltextOutboxStatus.PENDING.value,
                retry_count=0,
                max_retries=statement.inserted.max_retries,
                next_retry_at=None,
                lease_owner=None,
                lease_until=None,
                fanout_cursor=None,
                error_summary=None,
            )
        )
        result = await self.session.execute(
            select(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.tenant_id == tenant_id,
                KnowledgeFulltextOutbox.aggregate_type == aggregate_type.value,
                KnowledgeFulltextOutbox.aggregate_id == aggregate_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = result.scalars().one()
        await self.session.flush()
        return row

    @staticmethod
    def _merge_request(
        row: KnowledgeFulltextOutbox,
        *,
        knowledge_id: int | None,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        max_retries: int,
    ) -> None:
        row.knowledge_id = knowledge_id
        row.desired_action = desired_action.value
        row.desired_revision += 1
        row.trigger_type = trigger_type
        row.status = KnowledgeFulltextOutboxStatus.PENDING.value
        row.retry_count = 0
        row.max_retries = max_retries
        row.next_retry_at = None
        row.lease_owner = None
        row.lease_until = None
        row.fanout_cursor = None
        row.error_summary = None

    async def list_dispatchable(self, *, now: datetime, limit: int) -> list[KnowledgeFulltextOutbox]:
        statement = (
            select(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.desired_revision > KnowledgeFulltextOutbox.applied_revision,
                col(KnowledgeFulltextOutbox.status).in_(
                    [
                        KnowledgeFulltextOutboxStatus.PENDING.value,
                        KnowledgeFulltextOutboxStatus.FAILED.value,
                        KnowledgeFulltextOutboxStatus.PROCESSING.value,
                    ]
                ),
                or_(
                    KnowledgeFulltextOutbox.next_retry_at.is_(None),
                    KnowledgeFulltextOutbox.next_retry_at <= now,
                ),
                or_(
                    KnowledgeFulltextOutbox.lease_until.is_(None),
                    KnowledgeFulltextOutbox.lease_until < now,
                ),
                KnowledgeFulltextOutbox.retry_count < KnowledgeFulltextOutbox.max_retries,
            )
            .order_by(KnowledgeFulltextOutbox.update_time.asc(), KnowledgeFulltextOutbox.id.asc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def claim(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> KnowledgeFulltextOutbox | None:
        result = await self.session.execute(
            update(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.id == outbox_id,
                KnowledgeFulltextOutbox.desired_revision == revision,
                KnowledgeFulltextOutbox.desired_revision > KnowledgeFulltextOutbox.applied_revision,
                KnowledgeFulltextOutbox.retry_count < KnowledgeFulltextOutbox.max_retries,
                or_(
                    KnowledgeFulltextOutbox.lease_until.is_(None),
                    KnowledgeFulltextOutbox.lease_until < now,
                ),
                or_(
                    KnowledgeFulltextOutbox.next_retry_at.is_(None),
                    KnowledgeFulltextOutbox.next_retry_at <= now,
                ),
            )
            .values(
                status=KnowledgeFulltextOutboxStatus.PROCESSING.value,
                lease_owner=lease_owner,
                lease_until=lease_until,
            )
        )
        if not result.rowcount:
            return None
        await self.session.flush()
        return await self._get_fresh(outbox_id)

    async def is_current_lease(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        statement = select(KnowledgeFulltextOutbox.id).where(
            KnowledgeFulltextOutbox.id == outbox_id,
            KnowledgeFulltextOutbox.desired_revision == revision,
            KnowledgeFulltextOutbox.lease_owner == lease_owner,
            KnowledgeFulltextOutbox.lease_until >= now,
        )
        return (await self.session.execute(statement)).first() is not None

    async def mark_success(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.id == outbox_id,
                KnowledgeFulltextOutbox.desired_revision == revision,
                KnowledgeFulltextOutbox.lease_owner == lease_owner,
            )
            .values(
                applied_revision=revision,
                status=KnowledgeFulltextOutboxStatus.SUCCESS.value,
                retry_count=0,
                next_retry_at=None,
                lease_owner=None,
                lease_until=None,
                error_summary=None,
                last_success_at=now,
            )
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def release_pending(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.id == outbox_id,
                KnowledgeFulltextOutbox.desired_revision == revision,
                KnowledgeFulltextOutbox.lease_owner == lease_owner,
            )
            .values(
                status=KnowledgeFulltextOutboxStatus.PENDING.value,
                lease_owner=None,
                lease_until=None,
            )
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def mark_failure(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        now: datetime,
        error_summary: str,
        retry_base_seconds: int,
        retry_max_seconds: int,
    ) -> bool:
        row = await self._get_fresh(outbox_id)
        if row is None or row.desired_revision != revision or row.lease_owner != lease_owner:
            return False
        retry_count = row.retry_count + 1
        exhausted = retry_count >= row.max_retries
        delay_seconds = min(retry_max_seconds, retry_base_seconds * (2 ** max(0, retry_count - 1)))
        error_type = (
            error_summary if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error_summary or "") else "RuntimeError"
        )
        result = await self.session.execute(
            update(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.id == outbox_id,
                KnowledgeFulltextOutbox.desired_revision == revision,
                KnowledgeFulltextOutbox.lease_owner == lease_owner,
            )
            .values(
                status=(
                    KnowledgeFulltextOutboxStatus.FAILED.value
                    if exhausted
                    else KnowledgeFulltextOutboxStatus.PENDING.value
                ),
                retry_count=retry_count,
                next_retry_at=None if exhausted else now + timedelta(seconds=delay_seconds),
                lease_owner=None,
                lease_until=None,
                error_summary=f"{error_type}:sync_failed",
            )
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def request_auto_repair(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str | None,
        fingerprint: str,
        error_type: str,
        now: datetime,
    ) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        row = await self._get_fresh_for_update(outbox_id)
        if (
            row is None
            or row.desired_revision != revision
            or row.desired_revision <= row.applied_revision
            or row.aggregate_type != KnowledgeFulltextAggregateType.FILE.value
            or row.desired_action != KnowledgeFulltextDesiredAction.SYNC_CURRENT.value
        ):
            return "stale"
        if lease_owner is not None and row.lease_owner != lease_owner:
            return "stale"
        if (
            lease_owner is None
            and row.lease_owner is not None
            and row.lease_until is not None
            and row.lease_until >= now
        ):
            return "stale"

        payload = dict(row.payload_snapshot or {})
        existing = dict(payload.get("fulltext_auto_repair") or {})
        if existing.get("fingerprint") == fingerprint:
            requested_revision = int(existing.get("requested_revision") or revision)
            state = str(existing.get("state") or "")
            if state in {"requested", "processing"} and row.desired_revision <= requested_revision:
                return "already_requested"
            existing["state"] = "exhausted"
            existing["finished_at"] = now.isoformat()
            existing["error_type"] = error_type
            payload["fulltext_auto_repair"] = existing
            row.payload_snapshot = payload
            row.status = KnowledgeFulltextOutboxStatus.FAILED.value
            row.retry_count = row.max_retries
            row.next_retry_at = None
            row.lease_owner = None
            row.lease_until = None
            row.error_summary = "KnowledgeFulltextAutoRepairExhausted:repair_exhausted"
            self.session.add(row)
            await self.session.flush()
            return "exhausted"

        repair = KnowledgeFulltextAutoRepairService.new_payload(
            fingerprint=fingerprint,
            error_type=error_type,
            now=now,
        )
        repair["requested_revision"] = revision
        repair["repair_owner"] = None
        payload["fulltext_auto_repair"] = repair
        row.payload_snapshot = payload
        row.status = KnowledgeFulltextOutboxStatus.FAILED.value
        row.retry_count = row.max_retries
        row.next_retry_at = None
        row.lease_owner = None
        row.lease_until = None
        row.error_summary = "KnowledgeFulltextAutoRepairRequested:repair_pending"
        self.session.add(row)
        await self.session.flush()
        return "requested"

    async def claim_auto_repair(
        self,
        *,
        outbox_id: int,
        fingerprint: str,
        lease_owner: str,
        now: datetime,
        lease_until: datetime,
    ) -> KnowledgeFulltextOutbox | None:
        row = await self._get_fresh_for_update(outbox_id)
        if row is None:
            return None
        payload = dict(row.payload_snapshot or {})
        repair = dict(payload.get("fulltext_auto_repair") or {})
        state = str(repair.get("state") or "")
        raw_repair_lease_until = repair.get("lease_until")
        try:
            repair_lease_until = (
                datetime.fromisoformat(str(raw_repair_lease_until))
                if raw_repair_lease_until
                else None
            )
        except ValueError:
            repair_lease_until = None
        lease_available = (
            state == "requested"
            or repair_lease_until is None
            or repair_lease_until < now
        )
        if (
            repair.get("fingerprint") != fingerprint
            or state not in {"requested", "processing"}
            or not lease_available
        ):
            return None
        repair["state"] = "processing"
        repair["started_at"] = now.isoformat()
        repair["repair_owner"] = lease_owner
        repair["lease_until"] = lease_until.isoformat()
        payload["fulltext_auto_repair"] = repair
        row.payload_snapshot = payload
        row.status = KnowledgeFulltextOutboxStatus.FAILED.value
        row.retry_count = row.max_retries
        row.lease_owner = lease_owner
        row.lease_until = lease_until
        row.error_summary = "KnowledgeFulltextAutoRepairProcessing:repair_processing"
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def finish_auto_repair(
        self,
        *,
        outbox_id: int,
        fingerprint: str,
        lease_owner: str,
        success: bool,
        error_type: str | None,
        now: datetime,
    ) -> bool:
        row = await self._get_fresh_for_update(outbox_id)
        if row is None:
            return False
        payload = dict(row.payload_snapshot or {})
        repair = dict(payload.get("fulltext_auto_repair") or {})
        if (
            repair.get("fingerprint") != fingerprint
            or repair.get("state") != "processing"
            or repair.get("repair_owner") != lease_owner
        ):
            return False
        repair["state"] = "completed" if success else "failed"
        repair["finished_at"] = now.isoformat()
        repair["error_type"] = error_type or repair.get("error_type")
        repair["repair_owner"] = None
        repair["lease_until"] = None
        payload["fulltext_auto_repair"] = repair
        row.payload_snapshot = payload
        if success:
            row.status = (
                KnowledgeFulltextOutboxStatus.PENDING.value
                if row.desired_revision > row.applied_revision
                else KnowledgeFulltextOutboxStatus.SUCCESS.value
            )
            row.retry_count = 0
            row.next_retry_at = now if row.desired_revision > row.applied_revision else None
            row.error_summary = None
        else:
            repair["state"] = "exhausted"
            payload["fulltext_auto_repair"] = repair
            row.payload_snapshot = payload
            row.status = KnowledgeFulltextOutboxStatus.FAILED.value
            row.retry_count = row.max_retries
            row.next_retry_at = None
            row.error_summary = "KnowledgeFulltextAutoRepairExhausted:repair_exhausted"
        if row.lease_owner == lease_owner:
            row.lease_owner = None
            row.lease_until = None
        self.session.add(row)
        await self.session.flush()
        return True

    async def save_fanout_cursor(
        self,
        *,
        outbox_id: int,
        revision: int,
        lease_owner: str,
        cursor: dict | None,
    ) -> bool:
        result = await self.session.execute(
            update(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.id == outbox_id,
                KnowledgeFulltextOutbox.desired_revision == revision,
                KnowledgeFulltextOutbox.lease_owner == lease_owner,
            )
            .values(fanout_cursor=cursor)
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def _get_fresh(self, outbox_id: int) -> KnowledgeFulltextOutbox | None:
        result = await self.session.execute(
            select(KnowledgeFulltextOutbox)
            .where(KnowledgeFulltextOutbox.id == outbox_id)
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def _get_fresh_for_update(self, outbox_id: int) -> KnowledgeFulltextOutbox | None:
        result = await self.session.execute(
            select(KnowledgeFulltextOutbox)
            .where(KnowledgeFulltextOutbox.id == outbox_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()
