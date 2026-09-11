from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)


@dataclass(frozen=True, slots=True)
class ExecutionStepDispatchClaim:
    task_id: str
    attempt_count: int


class KnowledgeSpaceFileChangeExecutionStepRepository:
    """Caller-transaction-owned durable step primitives."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_request(
        self,
        *,
        tenant_id: int,
        request_id: int,
        for_update: bool = False,
    ) -> list[KnowledgeSpaceFileChangeExecutionStep]:
        statement = (
            select(KnowledgeSpaceFileChangeExecutionStep)
            .where(
                KnowledgeSpaceFileChangeExecutionStep.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeExecutionStep.request_id == int(request_id),
            )
            .order_by(KnowledgeSpaceFileChangeExecutionStep.id.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        return list((await self.session.exec(statement)).all())

    async def ensure_steps(
        self,
        *,
        tenant_id: int,
        request_id: int,
        attempt_token: str,
        step_codes: Sequence[str],
    ) -> list[KnowledgeSpaceFileChangeExecutionStep]:
        rows = await self.list_by_request(
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=True,
        )
        by_code = {row.step_code: row for row in rows}
        for step_code in step_codes:
            if step_code in by_code:
                continue
            row = KnowledgeSpaceFileChangeExecutionStep(
                tenant_id=int(tenant_id),
                request_id=int(request_id),
                step_code=str(step_code),
                attempt_token=str(attempt_token),
                idempotency_key=f"f046:{int(request_id)}:{step_code}",
            )
            self.session.add(row)
            by_code[step_code] = row
        await self.session.flush()
        return [by_code[code] for code in step_codes]

    async def lock_step(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
    ) -> KnowledgeSpaceFileChangeExecutionStep | None:
        statement = (
            select(KnowledgeSpaceFileChangeExecutionStep)
            .where(
                KnowledgeSpaceFileChangeExecutionStep.tenant_id == int(tenant_id),
                KnowledgeSpaceFileChangeExecutionStep.request_id == int(request_id),
                KnowledgeSpaceFileChangeExecutionStep.step_code == str(step_code),
            )
            .with_for_update()
        )
        return (await self.session.exec(statement)).first()

    async def claim_dispatch(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        now: datetime,
        lease_until: datetime,
        max_attempts: int,
    ) -> ExecutionStepDispatchClaim | None:
        """Atomically lease one due step before publishing its broker task."""

        if lease_until <= now:
            raise ValueError("F046 dispatch lease must expire after it starts")
        if max_attempts <= 0:
            raise ValueError("F046 dispatch attempt budget must be positive")
        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return None
        if row.state not in {
            KnowledgeSpaceFileChangeExecutionStepState.PENDING,
            KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
        }:
            return None
        if (
            row.state == KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
            and row.next_retry_at is not None
            and row.next_retry_at > now
        ):
            return None
        if row.attempt_count >= max_attempts:
            row.state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
            row.next_retry_at = None
            row.error_summary = f"step gave up after {row.attempt_count} dispatch attempts"
            self.session.add(row)
            await self.session.flush()
            return None

        row.attempt_count += 1
        task_id = f"{row.idempotency_key}:attempt:{row.attempt_count}"
        row.state = KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
        row.task_id = task_id
        row.next_retry_at = lease_until
        row.error_summary = None
        self.session.add(row)
        await self.session.flush()
        return ExecutionStepDispatchClaim(task_id=task_id, attempt_count=row.attempt_count)

    async def mark_dispatched(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        task_id: str | None,
    ) -> bool:
        """Mark an inline owner step dispatched without creating a broker lease."""

        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return False
        if row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
            return True
        row.state = KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
        row.attempt_count += 1
        row.task_id = task_id
        row.error_summary = None
        self.session.add(row)
        await self.session.flush()
        return True

    async def release_dispatch_claim(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        task_id: str,
        error_summary: str,
    ) -> bool:
        """Release only the exact claim whose broker publication failed."""

        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if (
            row is None
            or row.attempt_token != attempt_token
            or row.state != KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED
            or row.task_id != task_id
        ):
            return False
        row.state = KnowledgeSpaceFileChangeExecutionStepState.PENDING
        row.next_retry_at = None
        row.error_summary = str(error_summary)[:2000]
        self.session.add(row)
        await self.session.flush()
        return True

    async def mark_succeeded(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        result_digest: str | None,
    ) -> bool:
        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return False
        row.state = KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
        row.result_digest = result_digest
        row.error_summary = None
        row.next_retry_at = None
        row.acked_at = datetime.utcnow()
        self.session.add(row)
        await self.session.flush()
        return True

    async def mark_failed(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        error_summary: str,
    ) -> bool:
        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return False
        if row.state in {
            KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
            KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED,
        }:
            return True
        row.state = KnowledgeSpaceFileChangeExecutionStepState.FAILED
        row.error_summary = str(error_summary)[:2000]
        row.next_retry_at = None
        self.session.add(row)
        await self.session.flush()
        return True

    async def mark_compensating(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
    ) -> bool:
        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return False
        if row.state == KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED:
            return True
        if row.state not in {
            KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
            KnowledgeSpaceFileChangeExecutionStepState.FAILED,
        }:
            return False
        row.state = KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING
        self.session.add(row)
        await self.session.flush()
        return True

    async def mark_compensated(
        self,
        *,
        tenant_id: int,
        request_id: int,
        step_code: str,
        attempt_token: str,
        result_digest: str | None,
    ) -> bool:
        row = await self.lock_step(tenant_id=tenant_id, request_id=request_id, step_code=step_code)
        if row is None or row.attempt_token != attempt_token:
            return False
        if row.state == KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED:
            return True
        if row.state != KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING:
            return False
        row.state = KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED
        row.result_digest = result_digest
        row.error_summary = None
        row.acked_at = datetime.utcnow()
        self.session.add(row)
        await self.session.flush()
        return True

    async def reset_incomplete_for_resume(
        self,
        *,
        tenant_id: int,
        request_id: int,
        new_token: str,
        reset_succeeded_step_codes: Sequence[str] = (),
    ) -> list[KnowledgeSpaceFileChangeExecutionStep]:
        rows = await self.list_by_request(
            tenant_id=tenant_id,
            request_id=request_id,
            for_update=True,
        )
        force_reset = {str(step_code) for step_code in reset_succeeded_step_codes}
        for row in rows:
            if row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED and row.step_code not in force_reset:
                continue
            row.attempt_token = str(new_token)
            row.state = KnowledgeSpaceFileChangeExecutionStepState.PENDING
            row.attempt_count = 0
            row.task_id = None
            row.error_summary = None
            row.next_retry_at = None
            self.session.add(row)
        await self.session.flush()
        return rows
