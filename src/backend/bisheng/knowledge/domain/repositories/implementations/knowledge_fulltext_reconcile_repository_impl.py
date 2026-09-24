"""批次业务复核、Outbox 领取和限次修复意图; 事务由 Worker 管理。"""

from datetime import datetime, timedelta

from sqlmodel import col, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_outbox_repository_impl import (
    KnowledgeFulltextOutboxRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_source_repository_impl import (
    KnowledgeFulltextReconcileSourceRepository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_reconcile_state_repository_impl import (
    FulltextReconcileStateRepository,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_source_repository_impl import (
    KnowledgeFulltextSourceRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_auto_repair_service import KnowledgeFulltextAutoRepairService
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import KnowledgeFulltextDocumentService


class KnowledgeFulltextReconcileRepository:
    def __init__(self, session):
        self.session = session
        self.source = KnowledgeFulltextReconcileSourceRepository(session)
        self.state = FulltextReconcileStateRepository(session)
        self.outbox = KnowledgeFulltextOutboxRepositoryImpl(session)

    async def outboxes(self, ids: list[int], *, lock: bool = False) -> dict:
        query = (
            select(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.aggregate_type == "file",
                col(KnowledgeFulltextOutbox.aggregate_id).in_(ids),
                KnowledgeFulltextOutbox.tenant_id == 1,
            )
            .order_by(KnowledgeFulltextOutbox.aggregate_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        with bypass_tenant_filter():
            rows = (await self.session.execute(query)).scalars().all()
        return {int(r.aggregate_id): r for r in rows}

    async def claim_mutations(self, mutations: list, snapshots: dict, owner: str, now: datetime) -> tuple[dict, dict]:
        ids = sorted(m.file_id for m in mutations)
        if not ids:
            return {}, {}
        # 文件行锁只覆盖当前正文小批, 外层设置 ES 请求超时, 避免长期占用业务事务。
        await self.source._execute(
            select(KnowledgeFile.id).where(col(KnowledgeFile.id).in_(ids)).order_by(KnowledgeFile.id).with_for_update()
        )
        fresh = await self.source.snapshots(ids)
        existing = await self.outboxes(ids, lock=True)
        claimed, failures = {}, {}
        for mutation in mutations:
            file_id = mutation.file_id
            before, current = snapshots.get(file_id), fresh.get(file_id)
            if isinstance(current, Exception):
                failures[file_id] = "source_unavailable"
                continue
            if before != current:
                failures[file_id] = "source_changed"
                continue
            row = existing.get(file_id)
            if row is not None and row.desired_revision > row.applied_revision:
                if row.retry_count < row.max_retries or (row.lease_until is not None and row.lease_until >= now):
                    failures[file_id] = "busy_outbox"
                    continue
                # 源正文已完整重建时允许接管耗尽意图, 不重置仍在执行/退避的消费。
            row = await self.outbox.request_sync(
                aggregate_type=KnowledgeFulltextAggregateType.FILE,
                aggregate_id=file_id,
                knowledge_id=current.knowledge_id if current else None,
                desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT
                if mutation.document
                else KnowledgeFulltextDesiredAction.DELETE_CURRENT,
                trigger_type="daily_fulltext_reconcile",
                tenant_id=1,
                max_retries=8,
                notify_after_commit=False,
            )
            acquired = await self.outbox.claim(
                outbox_id=int(row.id),
                revision=row.desired_revision,
                lease_owner=owner,
                now=now,
                lease_until=now + timedelta(minutes=10),
            )
            if acquired is None:
                failures[file_id] = "busy_outbox"
            else:
                if mutation.document is not None:
                    mutation.document["sync_revision"] = int(row.desired_revision)
                claimed[file_id] = (int(row.id), int(row.desired_revision))
        return claimed, failures

    async def finish_mutations(self, claimed: dict, verified: set[int], owner: str, now: datetime) -> None:
        for file_id, (outbox_id, revision) in claimed.items():
            if file_id in verified:
                await self.outbox.mark_success(outbox_id=outbox_id, revision=revision, lease_owner=owner, now=now)
            else:
                await self.outbox.mark_failure(
                    outbox_id=outbox_id,
                    revision=revision,
                    lease_owner=owner,
                    now=now,
                    error_summary="FulltextReconcileVerificationError",
                    retry_base_seconds=300,
                    retry_max_seconds=1800,
                )

    async def request_repair(self, snapshot, now: datetime) -> str:
        # 发布/分享先修复本条目投影; 物理文件按实际内容源去重。
        kind = (
            "projection"
            if snapshot.logical_document_id
            and (snapshot.entry_type in {"publish", "share"} or snapshot.projection_status != "ready")
            else "parse"
        )
        file_id = snapshot.file_id if kind == "projection" else (snapshot.content_file_id or snapshot.file_id)
        current = await KnowledgeFulltextSourceRepositoryImpl(self.session).get_current_snapshot(snapshot.file_id)
        if (
            current is None
            or current.document_version_id != snapshot.document_version_id
            or current.content_generation != snapshot.content_generation
        ):
            return "source_changed"
        await self.source._execute(select(KnowledgeFile.id).where(KnowledgeFile.id == file_id).with_for_update())
        file = (await self.source._execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id))).scalars().first()
        if file is None or file.deleted_at is not None:
            return "source_changed"
        if file.status in {1, 5}:
            return "waiting_parse"
        if file.status != 2 or (kind == "parse" and not file.object_name):
            return "repair_exhausted_source"
        source = await self.source.get_auto_repair_source(file_id)
        fingerprint = KnowledgeFulltextAutoRepairService.fingerprint(source)
        old_outbox = (await self.outboxes([file_id], lock=True)).get(file_id)
        old_repair = dict((old_outbox.payload_snapshot or {}).get("fulltext_auto_repair") or {}) if old_outbox else {}
        if old_repair.get("fingerprint") == fingerprint and old_repair.get("coordinator") != "daily_reconcile":
            if old_repair.get("state") in {"exhausted", "completed", "failed", "superseded"}:
                return "repair_exhausted_existing"
            if old_repair.get("state") in {"requested", "processing"}:
                return "repair_pending_existing"
        ticket = await self.state.request_repair(file_id, fingerprint, kind, now)
        if ticket.fingerprint != fingerprint:
            return "repair_pending_previous_source"
        if ticket.status in {"exhausted", "resolved"}:
            return "repair_exhausted"
        if old_outbox is None:
            old_outbox = await self.outbox.request_sync(
                aggregate_type=KnowledgeFulltextAggregateType.FILE,
                aggregate_id=file_id,
                knowledge_id=file.knowledge_id,
                desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
                trigger_type="daily_fulltext_repair",
                tenant_id=1,
                max_retries=8,
                notify_after_commit=False,
            )
        payload = dict(old_outbox.payload_snapshot or {})
        # 与既有自动修复共享源指纹, 旧消费者看到已预留的指纹后不会再发起第二次解析。
        payload["fulltext_auto_repair"] = {
            "fingerprint": fingerprint,
            "state": "reconcile_reserved",
            "coordinator": "daily_reconcile",
            "task_id": ticket.task_id,
            "requested_at": now.isoformat(),
        }
        old_outbox.payload_snapshot = payload
        self.session.add(old_outbox)
        await self.session.flush()
        return "repair_pending"

    async def begin_repair(self, file_id: int, fingerprint: str, task_id: str, now: datetime) -> str | None:
        from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue

        rows = (
            (await self.source._execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id).with_for_update()))
            .scalars()
            .all()
        )
        ticket = await self.session.get(FulltextReconcileIssue, ("repair", file_id))
        if not rows or ticket is None or ticket.task_id != task_id or ticket.fingerprint != fingerprint:
            return None
        file = rows[0]
        source = await self.source.get_auto_repair_source(file_id)
        current = await KnowledgeFulltextSourceRepositoryImpl(self.session).get_current_snapshot(file_id)
        valid = (
            file.deleted_at is None
            and source is not None
            and current is not None
            and KnowledgeFulltextAutoRepairService.fingerprint(source) == fingerprint
        )
        if not valid:
            ticket.status = "exhausted"
            self.session.add(ticket)
            return None
        if file.status in {1, 5}:
            return None
        eligible = (
            current.model_copy(update={"projection_status": "ready"}) if ticket.reason == "projection" else current
        )
        if KnowledgeFulltextDocumentService.decide(eligible).value != "upsert":
            ticket.status = "exhausted"
            self.session.add(ticket)
            return None
        if not await self.state.claim_repair(file_id, fingerprint, task_id, now):
            return None
        if ticket.reason == "parse":
            file.status = 5
            self.session.add(file)
        await self.session.flush()
        return ticket.reason

    async def finish_repair(
        self, file_id: int, fingerprint: str, task_id: str, kind: str, execution_ok: bool | None, now: datetime
    ) -> None:
        if kind == "projection" and execution_ok is None:
            await self.state.finish_repair(file_id, fingerprint, task_id, None, now)
            return
        files = (await self.source._execute(select(KnowledgeFile).where(KnowledgeFile.id == file_id))).scalars().all()
        success = bool(execution_ok and files and files[0].status == 2 and files[0].deleted_at is None)
        if kind == "projection":
            success = success and files[0].projection_status == "ready"
        await self.state.finish_repair(file_id, fingerprint, task_id, success, now)
