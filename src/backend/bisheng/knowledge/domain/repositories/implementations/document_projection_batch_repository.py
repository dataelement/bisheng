"""批量领取、读取和条件写回; 复用现有持久化租约和重试次数。"""

from datetime import datetime, timedelta

from sqlalchemy import case, or_, update
from sqlmodel import select

from bisheng.knowledge.domain.contracts.document_projection_batch import ProjectionBatchContext
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.interfaces.document_projection_batch_repository import (
    DocumentProjectionBatchRepository as BatchRepositoryContract,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_lifecycle_hook import (
    KnowledgeFulltextFileRef,
    request_file_sync_intents,
)


class DocumentProjectionBatchRepository(KnowledgeFileRepositoryImpl, BatchRepositoryContract):
    async def find_by_ids(self, entity_ids: list[int]) -> list[KnowledgeFile]:
        rows = []
        for offset in range(0, len(entity_ids), 500):
            rows.extend(await super().find_by_ids(entity_ids[offset : offset + 500]))
        return rows

    async def find_by_ids_for_update(self, entity_ids: list[int]) -> list[KnowledgeFile]:
        rows = []
        ids = sorted(set(entity_ids))
        for offset in range(0, len(ids), 500):
            rows.extend(await super().find_by_ids_for_update(ids[offset : offset + 500]))
        return rows

    async def claim_batch(
        self,
        ids: list[int],
        owner: str,
        max_attempts: int,
        *,
        handoff_owner: str | None = None,
    ) -> ProjectionBatchContext:
        now = datetime.now()
        # 先锁文档再锁入口, 批量任务之间按同一顺序取得文档处理权。
        requested = await self.find_by_ids(ids)
        document_ids = sorted({int(row.reference_document_id) for row in requested if row.reference_document_id})
        if not document_ids:
            return ProjectionBatchContext()
        documents = list(
            (
                await self.session.exec(
                    select(KnowledgeDocument)
                    .where(KnowledgeDocument.id.in_(document_ids))
                    .order_by(KnowledgeDocument.id)
                    .with_for_update()
                )
            ).all()
        )
        entries = list(
            (
                await self.session.exec(
                    select(KnowledgeFile)
                    .where(KnowledgeFile.reference_document_id.in_(document_ids))
                    .order_by(KnowledgeFile.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        blocked = {
            row.reference_document_id
            for row in entries
            if row.projection_lease_owner
            and row.projection_lease_owner not in {owner, handoff_owner}
            and row.projection_lease_until
            and row.projection_lease_until > now
        }
        eligible_ids = [row.id for row in requested if row.reference_document_id not in blocked]
        if not eligible_ids:
            return ProjectionBatchContext()
        predicate = or_(
            self._projection_candidate_predicate(now, max_attempts),
            KnowledgeFile.projection_lease_owner.in_([value for value in (owner, handoff_owner) if value])
            & (KnowledgeFile.projection_retry_count < max_attempts)
            & KnowledgeFile.entry_status.in_(["active", "deleting", "invalid"]),
        )
        for offset in range(0, len(eligible_ids), 500):
            await self.session.execute(
                update(KnowledgeFile)
                .where(KnowledgeFile.id.in_(eligible_ids[offset : offset + 500]), predicate)
                .values(
                    projection_status="processing",
                    projection_lease_owner=owner,
                    projection_lease_until=now + timedelta(seconds=180),
                )
                .execution_options(synchronize_session=False)
            )
        claimed = []
        for offset in range(0, len(eligible_ids), 500):
            claimed.extend(
                (
                    await self.session.exec(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.id.in_(eligible_ids[offset : offset + 500]),
                            KnowledgeFile.projection_lease_owner == owner,
                        )
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
        versions = list(
            (
                await self.session.exec(
                    select(KnowledgeDocumentVersion).where(
                        KnowledgeDocumentVersion.id.in_(
                            [row.primary_version_id for row in documents if row.primary_version_id]
                        ),
                    )
                )
            ).all()
        )
        files = await self.find_by_ids([row.knowledge_file_id for row in versions])
        context = ProjectionBatchContext(
            claimed=[row.model_copy(deep=True) for row in claimed],
            entries=[row.model_copy(deep=True) for row in entries],
            documents={row.id: row.model_copy(deep=True) for row in documents},
            versions={row.id: row.model_copy(deep=True) for row in versions},
            files={row.id: row.model_copy(deep=True) for row in files},
        )
        await self.session.commit()
        return context

    async def renew(self, owner: str, expected_ids: list[int] | None = None) -> None:
        now = datetime.now()
        if expected_ids:
            for offset in range(0, len(expected_ids), 500):
                ids = expected_ids[offset : offset + 500]
                owned = (
                    await self.session.exec(
                        select(KnowledgeFile.id).where(
                            KnowledgeFile.id.in_(ids),
                            KnowledgeFile.projection_lease_owner == owner,
                            KnowledgeFile.projection_lease_until > now,
                        )
                    )
                ).all()
                if set(owned) != set(ids):
                    raise RuntimeError("projection batch ownership changed")
        # 已过期的租约不能由旧执行者复活。
        expired = (
            await self.session.exec(
                select(KnowledgeFile.id)
                .where(
                    KnowledgeFile.projection_lease_owner == owner,
                    KnowledgeFile.projection_lease_until <= now,
                )
                .limit(1)
            )
        ).first()
        if expired is not None:
            raise RuntimeError("projection batch lease expired")
        await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.projection_lease_owner == owner,
            )
            .values(projection_lease_until=now + timedelta(seconds=180))
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()

    async def settle(
        self,
        snapshots: list[KnowledgeFile],
        owner: str,
        errors: dict[int, str],
        max_attempts: int,
        *,
        finalizing: bool = False,
        rebuild_ids: set[int] | None = None,
        rebuild_owner: str | None = None,
    ) -> dict[int, str]:
        if rebuild_ids and not rebuild_owner:
            raise ValueError("content rebuild handoff requires a reservation owner")
        current = {row.id: row for row in await self.find_by_ids_for_update([row.id for row in snapshots])}
        changes = {}
        results = {}
        refs = []
        for expected in snapshots:
            row = current.get(expected.id)
            if row is None:
                results[expected.id] = "cleaned" if finalizing else "missing"
                continue
            if (
                row.projection_lease_owner != owner
                or not row.projection_lease_until
                or row.projection_lease_until <= datetime.now()
            ):
                results[row.id] = "not_claimed"
                continue
            if (
                row.reference_document_id,
                row.desired_content_generation,
                row.desired_entry_generation,
                row.entry_status,
            ) != (
                expected.reference_document_id,
                expected.desired_content_generation,
                expected.desired_entry_generation,
                expected.entry_status,
            ):
                changes[row.id] = {
                    "projection_status": "pending",
                    "projection_lease_owner": None,
                    "projection_lease_until": None,
                }
                results[row.id] = "stale"
                continue
            error = errors.get(row.id)
            cleanup = row.entry_status in {"deleting", "invalid"} or row.entry_type == "projection_tombstone"
            if row.id in (rebuild_ids or ()) and not error:
                # 先持久化交接租约再投递; 接收者原子换成独立执行租约。
                changes[row.id] = {
                    "projection_status": "pending",
                    "projection_last_error": "content_rebuild_pending",
                    "projection_next_retry_at": None,
                    "projection_lease_owner": rebuild_owner,
                    "projection_lease_until": datetime.now() + timedelta(seconds=180),
                }
                results[row.id] = "rebuild_pending"
            elif error:
                attempts = int(row.projection_retry_count or 0) + 1
                exhausted = attempts >= max_attempts
                changes[row.id] = {
                    "projection_status": "failed",
                    "projection_retry_count": attempts,
                    "projection_last_error": (("retry_exhausted:" if exhausted else "") + error)[:3500],
                    "projection_next_retry_at": datetime.now(),
                    "projection_lease_owner": None if exhausted else owner,
                    "projection_lease_until": None if exhausted else datetime.now() + timedelta(seconds=180),
                }
                results[row.id] = "exhausted" if exhausted else "failed"
            else:
                keep = cleanup and not finalizing
                changes[row.id] = {
                    "projection_status": "ready",
                    "applied_content_generation": expected.desired_content_generation,
                    "applied_entry_generation": expected.desired_entry_generation,
                    "projection_retry_count": row.projection_retry_count if keep else 0,
                    "projection_last_error": row.projection_last_error if keep else None,
                    "projection_next_retry_at": None,
                    "projection_lease_owner": owner if keep else None,
                    "projection_lease_until": row.projection_lease_until if keep else None,
                }
                if not keep:
                    changes[row.id]["projection_previous_file_id"] = None
                results[row.id] = "finalizing" if keep else "ready"
                refs.append(
                    KnowledgeFulltextFileRef(file_id=row.id, knowledge_id=row.knowledge_id, tenant_id=row.tenant_id)
                )
        change_ids = list(changes)
        for offset in range(0, len(change_ids), 50):
            page = {entry_id: changes[entry_id] for entry_id in change_ids[offset : offset + 50]}
            fields = {field for values in page.values() for field in values}
            values = {
                field: case(
                    {key: value[field] for key, value in page.items() if field in value},
                    value=KnowledgeFile.id,
                    else_=getattr(KnowledgeFile, field),
                )
                for field in fields
            }
            await self.session.execute(
                update(KnowledgeFile)
                .where(
                    KnowledgeFile.id.in_(list(page)),
                    KnowledgeFile.projection_lease_owner == owner,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
        if refs:
            await request_file_sync_intents(self.session, refs, trigger_type="document_projection_batch_applied")
        await self.session.commit()
        return results

    async def release(self, owner: str) -> None:
        await self.session.execute(
            update(KnowledgeFile)
            .where(
                KnowledgeFile.projection_lease_owner == owner,
            )
            .values(projection_lease_owner=None, projection_lease_until=None)
            .execution_options(synchronize_session=False)
        )
        await self.session.commit()
