"""轮次和异常进度在同一事务中保存, 未完成轮次优先恢复。"""

from collections import Counter
from datetime import datetime, timedelta
from uuid import uuid4

from sqlmodel import col, or_, select, update

from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileIssue as Issue
from bisheng.knowledge.domain.models.knowledge_fulltext_reconcile import FulltextReconcileRun as Run


class FulltextReconcileStateRepository:
    def __init__(self, session):
        self.session = session

    async def _rows(self, query):
        return list((await self.session.execute(query)).scalars())

    async def load_or_create(self, now: datetime, upper: int, *, create: bool = True) -> Run | None:
        active = await self._rows(
            select(Run).where(col(Run.status).in_(["scanning", "waiting", "paused"])).order_by(Run.started_at).limit(1)
        )
        if active:
            return active[0]
        if not create:
            return None
        today = await self._rows(select(Run).where(Run.day == now.date().isoformat()).limit(1))
        if today:
            return today[0]
        run = Run(id=uuid4().hex, day=now.date().isoformat(), upper_id=upper, started_at=now, updated_at=now)
        self.session.add(run)
        await self.session.flush()
        return run

    async def checkpoint(
        self, run_id: str, phase: str, cursor: int, failures: dict[int, str], successes: dict[int, str], now: datetime
    ) -> None:
        run = (await self._rows(select(Run).where(Run.id == run_id).with_for_update()))[0]
        ids = sorted(set(failures) | set(successes))
        existing = (
            {
                i.file_id: i
                for i in await self._rows(
                    select(Issue).where(Issue.run_id == run_id, col(Issue.file_id).in_(ids)).with_for_update()
                )
            }
            if ids
            else {}
        )
        for file_id, reason in failures.items():
            item = existing.get(file_id) or Issue(run_id=run_id, file_id=file_id, updated_at=now)
            item.reason = reason[:128]
            waiting = reason.startswith(("waiting", "busy", "repair_pending", "source_changed"))
            if not waiting:
                item.attempts += 1
            item.status = (
                "exhausted"
                if item.attempts >= 8 or reason.startswith(("repair_exhausted", "invalid_es_identity"))
                else "pending"
            )
            item.next_retry_at = now + timedelta(seconds=min(1800, 300 * 2 ** min(item.attempts, 3)))
            item.updated_at = now
            self.session.add(item)
        for file_id, reason in successes.items():
            item = existing.get(file_id)
            if item is not None and reason != "reverse_existing":
                item.status = "resolved"
                item.updated_at = now
                self.session.add(item)
        counts = Counter(run.counters or {})
        counts.update(successes.values())
        counts["failed_observations"] += len(failures)
        if phase != "retry":
            counts["scanned"] += len(ids)
            run.phase, run.cursor = phase, cursor
        run.counters, run.updated_at = dict(counts), now
        self.session.add(run)
        await self.session.flush()

    async def transition(self, run_id: str, phase: str, now: datetime) -> None:
        await self.session.execute(update(Run).where(Run.id == run_id).values(phase=phase, cursor=0, updated_at=now))

    async def due(self, run_id: str, now: datetime, limit: int = 200) -> list[Issue]:
        return await self._rows(
            select(Issue)
            .where(
                Issue.run_id == run_id,
                Issue.status == "pending",
                or_(Issue.next_retry_at.is_(None), Issue.next_retry_at <= now),
            )
            .order_by(Issue.next_retry_at, Issue.file_id)
            .limit(limit)
        )

    async def finish_scan(self, run_id: str, now: datetime) -> str:
        run = (await self._rows(select(Run).where(Run.id == run_id)))[0]
        if now - run.started_at >= timedelta(hours=24):
            await self.session.execute(
                update(Issue)
                .where(Issue.run_id == run_id, Issue.status == "pending")
                .values(status="exhausted", reason="round_wait_budget_exhausted", updated_at=now)
            )
        pending = await self._rows(select(Issue).where(Issue.run_id == run_id, Issue.status == "pending").limit(1))
        exhausted = await self._rows(select(Issue).where(Issue.run_id == run_id, Issue.status == "exhausted").limit(1))
        status = "waiting" if pending else "completed_with_errors" if exhausted else "completed"
        await self.session.execute(update(Run).where(Run.id == run_id).values(status=status, updated_at=now))
        return status

    async def has_issue(self, run_id: str, file_id: int) -> bool:
        return await self.session.get(Issue, (run_id, file_id)) is not None

    async def request_repair(self, file_id: int, fingerprint: str, kind: str, now: datetime) -> Issue:
        rows = await self._rows(
            select(Issue).where(Issue.run_id == "repair", Issue.file_id == file_id).with_for_update()
        )
        row = rows[0] if rows else Issue(run_id="repair", file_id=file_id, updated_at=now)
        if row.fingerprint != fingerprint:
            if row.status == "processing":
                return row
            row.fingerprint, row.reason = fingerprint, kind
            row.status, row.attempts, row.task_id = "pending", 0, uuid4().hex
            row.next_retry_at = now
            row.updated_at = now
        self.session.add(row)
        await self.session.flush()
        return row

    async def claim_repair(self, file_id: int, fingerprint: str, task_id: str, now: datetime) -> bool:
        result = await self.session.execute(
            update(Issue)
            .where(
                Issue.run_id == "repair",
                Issue.file_id == file_id,
                Issue.fingerprint == fingerprint,
                Issue.task_id == task_id,
                Issue.status == "pending",
                Issue.attempts == 0,
            )
            .values(status="processing", attempts=1, updated_at=now)
        )
        await self.session.flush()
        return bool(result.rowcount)

    async def finish_repair(self, file_id: int, fingerprint: str, task_id: str, success: bool, now: datetime) -> None:
        await self.session.execute(
            update(Issue)
            .where(
                Issue.run_id == "repair",
                Issue.file_id == file_id,
                Issue.fingerprint == fingerprint,
                Issue.task_id == task_id,
                Issue.status == "processing",
            )
            .values(status="resolved" if success else "exhausted", updated_at=now)
        )

    async def pending_repairs(self, now: datetime, limit: int = 100) -> list[Issue]:
        # 超时进程结果不明时禁止再次解析; 记录耗尽, 交由后续对账/人工处理。
        await self.session.execute(
            update(Issue)
            .where(Issue.run_id == "repair", Issue.status == "processing", Issue.updated_at < now - timedelta(hours=2))
            .values(status="exhausted", updated_at=now)
        )
        return await self._rows(
            select(Issue)
            .where(
                Issue.run_id == "repair",
                Issue.status == "pending",
                or_(Issue.next_retry_at.is_(None), Issue.next_retry_at <= now),
            )
            .order_by(Issue.updated_at)
            .limit(limit)
        )

    async def repair_published(self, row: Issue, now: datetime) -> None:
        await self.session.execute(
            update(Issue)
            .where(
                Issue.run_id == "repair",
                Issue.file_id == row.file_id,
                Issue.task_id == row.task_id,
                Issue.status == "pending",
            )
            .values(next_retry_at=now + timedelta(minutes=10))
        )
