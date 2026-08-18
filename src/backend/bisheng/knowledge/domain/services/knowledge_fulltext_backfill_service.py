"""存量全文回填的候选判定、Outbox 请求与目标 revision 分类。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutboxStatus,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_outbox_repository import (
    KnowledgeFulltextOutboxRepository,
)
from bisheng.knowledge.domain.repositories.interfaces.knowledge_fulltext_source_repository import (
    KnowledgeFulltextSourceRepository,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_document_service import (
    KnowledgeFulltextDocumentService,
    KnowledgeFulltextProjectionAction,
)


@dataclass(frozen=True)
class KnowledgeFulltextBackfillCandidate:
    file_id: int
    knowledge_id: int


@dataclass(frozen=True)
class KnowledgeFulltextBackfillTarget:
    file_id: int
    outbox_id: int
    target_revision: int


@dataclass(frozen=True)
class KnowledgeFulltextBackfillPage:
    scanned_count: int
    candidates: tuple[KnowledgeFulltextBackfillCandidate, ...]
    excluded_counts: dict[str, int]
    next_start_after_id: int


class KnowledgeFulltextBackfillService:
    def __init__(
        self,
        *,
        source_repository: KnowledgeFulltextSourceRepository,
        outbox_repository: KnowledgeFulltextOutboxRepository,
        max_retries: int,
    ):
        self.source_repository = source_repository
        self.outbox_repository = outbox_repository
        self.max_retries = max_retries

    async def inspect_page(
        self,
        *,
        after_file_id: int,
        limit: int,
        knowledge_id: int | None,
        file_id: int | None,
    ) -> KnowledgeFulltextBackfillPage:
        file_ids = await self.source_repository.list_backfill_file_ids(
            after_file_id=after_file_id,
            limit=limit,
            knowledge_id=knowledge_id,
            file_id=file_id,
        )
        candidates: list[KnowledgeFulltextBackfillCandidate] = []
        excluded: Counter[str] = Counter()
        for current_file_id in file_ids:
            snapshot = await self.source_repository.get_current_snapshot(current_file_id)
            if snapshot is None:
                excluded["missing"] += 1
                continue
            action = KnowledgeFulltextDocumentService.decide(snapshot)
            if action is KnowledgeFulltextProjectionAction.UPSERT:
                candidates.append(
                    KnowledgeFulltextBackfillCandidate(
                        file_id=snapshot.file_id,
                        knowledge_id=snapshot.knowledge_id,
                    )
                )
            else:
                excluded[action.value] += 1
        return KnowledgeFulltextBackfillPage(
            scanned_count=len(file_ids),
            candidates=tuple(candidates),
            excluded_counts=dict(excluded),
            next_start_after_id=file_ids[-1] if file_ids else after_file_id,
        )

    async def request_target(
        self,
        candidate: KnowledgeFulltextBackfillCandidate,
    ) -> KnowledgeFulltextBackfillTarget:
        row = await self.outbox_repository.request_sync(
            aggregate_type=KnowledgeFulltextAggregateType.FILE,
            aggregate_id=candidate.file_id,
            knowledge_id=candidate.knowledge_id,
            desired_action=KnowledgeFulltextDesiredAction.SYNC_CURRENT,
            trigger_type="historical_backfill",
            tenant_id=1,
            max_retries=self.max_retries,
        )
        if row.id is None:
            raise RuntimeError("backfill outbox row has no persisted id")
        return KnowledgeFulltextBackfillTarget(
            file_id=candidate.file_id,
            outbox_id=int(row.id),
            target_revision=int(row.desired_revision),
        )

    async def classify_targets(
        self,
        targets: list[KnowledgeFulltextBackfillTarget],
    ) -> dict[str, int]:
        counts = {"success": 0, "failed": 0, "processing": 0, "pending": 0}
        if not targets:
            return counts
        states = await self.classify_target_states(targets)
        for state in states.values():
            counts[state] += 1
        return counts

    async def classify_target_states(
        self,
        targets: list[KnowledgeFulltextBackfillTarget],
    ) -> dict[int, str]:
        if not targets:
            return {}
        rows = await self.outbox_repository.list_by_ids([target.outbox_id for target in targets])
        rows_by_id = {int(row.id): row for row in rows if row.id is not None}
        states: dict[int, str] = {}
        for target in targets:
            row = rows_by_id.get(target.outbox_id)
            if row is None:
                states[target.outbox_id] = "failed"
            elif int(row.applied_revision) >= target.target_revision:
                states[target.outbox_id] = "success"
            elif (
                row.status == KnowledgeFulltextOutboxStatus.FAILED.value
                and int(row.retry_count) >= int(row.max_retries)
            ):
                states[target.outbox_id] = "failed"
            elif row.status == KnowledgeFulltextOutboxStatus.PROCESSING.value:
                states[target.outbox_id] = "processing"
            else:
                states[target.outbox_id] = "pending"
        return states
