from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from inspect import isawaitable
from typing import Any
from uuid import uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge_space_file_change_execution_step import (
    KnowledgeSpaceFileChangeExecutionStep,
    KnowledgeSpaceFileChangeExecutionStepState,
)
from bisheng.knowledge.domain.models.knowledge_space_file_change_request import (
    KnowledgeSpaceFileChangeAction,
    KnowledgeSpaceFileChangeExecutionState,
    KnowledgeSpaceFileChangeRequest,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_execution_step_repository import (
    KnowledgeSpaceFileChangeExecutionStepRepository,
)
from bisheng.knowledge.domain.repositories.knowledge_space_file_change_request_repository import (
    KnowledgeSpaceFileChangeRequestRepository,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
    DELETE_PHASE_CHECKPOINT_KEY,
    DELETE_PHASE_COMPLETED,
    DELETE_PHASE_PURGE_FAILED,
    DELETE_PHASE_PURGING,
    DeleteExecutionStepCode,
    MoveExecutionStepCode,
    RenameExecutionStepCode,
    UploadExecutionStepCode,
)
from bisheng.knowledge.domain.services.knowledge_space_mutation_read_projection_service import (
    MUTATION_TRANSITION_NEW_VIEW,
    MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ExecutionReconcileStatus(StrEnum):
    IGNORED = "ignored"
    RUNNING = "running"
    COMPENSATING = "compensating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExecutionIdentity:
    tenant_id: int
    request_id: int
    execution_token: str

    def __post_init__(self) -> None:
        if min(self.tenant_id, self.request_id) <= 0:
            raise ValueError("F046 execution identity ids must be positive")
        if not self.execution_token or len(self.execution_token) > 64:
            raise ValueError("F046 execution token must contain 1 to 64 characters")


@dataclass(frozen=True, slots=True)
class ExecutionStepContext:
    tenant_id: int
    request_id: int
    execution_token: str
    action: str
    step_code: str
    idempotency_key: str
    task_id: str | None
    acknowledgement: Any = None


@dataclass(frozen=True, slots=True)
class VerifiedExecutionStepResult:
    """A read-after-verified result, never a broker enqueue receipt."""

    result_digest: str

    def __post_init__(self) -> None:
        if not self.result_digest or len(self.result_digest) > 255:
            raise ValueError("verified F046 step digest must contain 1 to 255 characters")


StepDispatcher = Callable[[ExecutionStepContext], Awaitable[str | None] | str | None]
StepVerifier = Callable[
    [ExecutionStepContext],
    Awaitable[VerifiedExecutionStepResult] | VerifiedExecutionStepResult,
]
MutationCutover = Callable[[ExecutionIdentity], Awaitable[bool] | bool]


class KnowledgeSpaceFileChangeExecutionCoordinator:
    """Own F046 request generations and durable steps entirely in Knowledge."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        execution_token_factory: Callable[[], str] | None = None,
        mutation_cutover: MutationCutover | None = None,
        delete_cutover: MutationCutover | None = None,
        delete_purge: MutationCutover | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.execution_token_factory = execution_token_factory or (lambda: str(uuid4()))
        self.mutation_cutover = mutation_cutover or self._cutover_verified_mutation
        self.delete_cutover = delete_cutover or self._cutover_delete
        self.delete_purge = delete_purge or self._purge_delete

    async def begin_execution(self, *, tenant_id: int, request_id: int) -> ExecutionIdentity:
        """Claim one queued business request and enter its current generation."""

        tenant_id = self._require_matching_tenant(tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
                for_update=True,
            )
            if request is None:
                raise LookupError(f"F046 request not found: {request_id}")
            if request.execution_state != KnowledgeSpaceFileChangeExecutionState.QUEUED:
                raise RuntimeError("only queued F046 requests can begin execution")
            token = request.execution_token or self._new_token(previous=None)
            request.execution_token = token
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLYING
            checkpoint = dict(request.execution_checkpoint or {})
            checkpoint.pop("failure_reason", None)
            checkpoint["started_at"] = datetime.now(UTC).isoformat()
            request.execution_checkpoint = checkpoint
            await repository.save(request)
            step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
            await step_repository.ensure_steps(
                tenant_id=tenant_id,
                request_id=int(request.id),
                attempt_token=token,
                step_codes=self._required_step_codes(request.action),
            )
            await step_repository.reset_incomplete_for_resume(
                tenant_id=tenant_id,
                request_id=int(request.id),
                new_token=token,
            )
        return ExecutionIdentity(tenant_id=tenant_id, request_id=int(request_id), execution_token=token)

    async def queue_retry(self, *, tenant_id: int, request_id: int) -> ExecutionIdentity:
        """Queue a failed request with a new generation while retaining its binding."""

        tenant_id = self._require_matching_tenant(tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
                for_update=True,
            )
            if request is None:
                raise LookupError(f"F046 request not found: {request_id}")
            if request.execution_state != KnowledgeSpaceFileChangeExecutionState.FAILED:
                raise RuntimeError("only failed F046 requests can be queued for retry")
            token = self._new_token(previous=request.execution_token)
            request.execution_token = token
            request.execution_state = KnowledgeSpaceFileChangeExecutionState.QUEUED
            checkpoint = dict(request.execution_checkpoint or {})
            checkpoint.pop("failure_reason", None)
            checkpoint["retry_queued_at"] = datetime.now(UTC).isoformat()
            if request.action == KnowledgeSpaceFileChangeAction.DELETE:
                if checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) != DELETE_PHASE_PURGE_FAILED or not checkpoint.get(
                    "deletion_cutover_active"
                ):
                    raise RuntimeError("delete retry requires a failed post-cutover purge")
                checkpoint[DELETE_PHASE_CHECKPOINT_KEY] = DELETE_PHASE_PURGING
            request.execution_checkpoint = checkpoint
            await repository.save(request)
            step_repository = KnowledgeSpaceFileChangeExecutionStepRepository(session)
            reset_succeeded: tuple[str, ...] = ()
            if request.action == KnowledgeSpaceFileChangeAction.RENAME:
                reset_succeeded = (RenameExecutionStepCode.VERIFY,)
            elif request.action == KnowledgeSpaceFileChangeAction.MOVE:
                reset_succeeded = (MoveExecutionStepCode.VERIFY,)
            if request.action == KnowledgeSpaceFileChangeAction.DELETE:
                rows = await step_repository.list_by_request(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    for_update=True,
                )
                by_code = {row.step_code: row for row in rows}
                if any(code not in by_code for code in DeleteExecutionStepCode.ALL):
                    raise RuntimeError("delete retry requires its durable step set")
                if by_code[DeleteExecutionStepCode.DB_CUTOVER].state != (
                    KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                ):
                    raise RuntimeError("delete retry cannot precede DB cutover")
                for row in rows:
                    row.attempt_token = token
                    if row.step_code in DeleteExecutionStepCode.PURGE and row.state != (
                        KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
                    ):
                        row.state = KnowledgeSpaceFileChangeExecutionStepState.PENDING
                        row.task_id = None
                        row.error_summary = None
                        row.next_retry_at = None
                    session.add(row)
                await session.flush()
            else:
                await step_repository.reset_incomplete_for_resume(
                    tenant_id=tenant_id,
                    request_id=int(request.id),
                    new_token=token,
                    reset_succeeded_step_codes=reset_succeeded,
                )
        return ExecutionIdentity(tenant_id=tenant_id, request_id=int(request_id), execution_token=token)

    async def fail_execution(self, *, identity: ExecutionIdentity, error_summary: str) -> bool:
        self._require_matching_tenant(identity.tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            if not self._matches_identity(request, identity):
                return False
            if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
                return False
            self._mark_request_failed(request, error_summary)
            await repository.save(request)
        return True

    async def begin_compensation(self, *, identity: ExecutionIdentity) -> bool:
        return await self._set_generation_state(
            identity=identity,
            expected={KnowledgeSpaceFileChangeExecutionState.APPLYING},
            target=KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
        )

    async def finish_compensation(self, *, identity: ExecutionIdentity, recovered: bool) -> bool:
        self._require_matching_tenant(identity.tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            if not self._matches_identity(request, identity) or request.execution_state != (
                KnowledgeSpaceFileChangeExecutionState.COMPENSATING
            ):
                return False
            steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            request.execution_state = (
                KnowledgeSpaceFileChangeExecutionState.APPLIED
                if recovered and self.is_business_complete(request=request, steps=steps)
                else KnowledgeSpaceFileChangeExecutionState.FAILED
            )
            await repository.save(request)
        return True

    async def _set_generation_state(
        self,
        *,
        identity: ExecutionIdentity,
        expected: set[str],
        target: str,
    ) -> bool:
        self._require_matching_tenant(identity.tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            if not self._matches_identity(request, identity) or request.execution_state not in expected:
                return False
            request.execution_state = target
            await repository.save(request)
        return True

    async def load_identity_by_request(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
    ) -> ExecutionIdentity | None:
        tenant_id = self._require_matching_tenant(tenant_id)
        identity = ExecutionIdentity(
            tenant_id=tenant_id,
            request_id=int(request_id),
            execution_token=str(execution_token),
        )
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=tenant_id,
                request_id=int(request_id),
            )
        return identity if self._matches_identity(request, identity) else None

    async def dispatch_ready_steps(
        self,
        *,
        identity: ExecutionIdentity,
        dispatcher: StepDispatcher,
        step_codes: Sequence[str] | None = None,
    ) -> list[str]:
        request, rows = await self._load_current(identity=identity)
        if request is None or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING:
            return []
        selected = set(step_codes or self._required_step_codes(request.action))
        ready_codes = set(self._ready_dispatch_step_codes(request.action, rows))
        dispatched: list[str] = []
        for row in rows:
            if row.step_code not in selected or row.step_code not in ready_codes:
                continue
            context = self._step_context(identity=identity, request=request, row=row)
            task_id = dispatcher(context)
            if isawaitable(task_id):
                task_id = await task_id
            async with self.session_factory() as session, session.begin():
                current = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                    for_update=True,
                )
                if not self._matches_identity(current, identity):
                    continue
                marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_dispatched(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                    step_code=row.step_code,
                    attempt_token=identity.execution_token,
                    task_id=None if task_id is None else str(task_id),
                )
                if marked:
                    dispatched.append(row.step_code)
        return dispatched

    async def acknowledge_step(
        self,
        *,
        identity: ExecutionIdentity,
        step_code: str,
        verifier: StepVerifier,
        acknowledgement: Any = None,
    ) -> ExecutionReconcileStatus:
        request, rows = await self._load_current(identity=identity)
        if request is None or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING:
            return ExecutionReconcileStatus.IGNORED
        row = next((item for item in rows if item.step_code == str(step_code)), None)
        if row is None or row.attempt_token != identity.execution_token:
            return ExecutionReconcileStatus.IGNORED
        context = self._step_context(
            identity=identity,
            request=request,
            row=row,
            acknowledgement=acknowledgement,
        )
        verification = verifier(context)
        if isawaitable(verification):
            verification = await verification
        if not isinstance(verification, VerifiedExecutionStepResult):
            raise TypeError("F046 acknowledgement requires an authoritative read-after-verified result")
        async with self.session_factory() as session, session.begin():
            current = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            if not self._matches_identity(current, identity):
                return ExecutionReconcileStatus.IGNORED
            marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                step_code=str(step_code),
                attempt_token=identity.execution_token,
                result_digest=verification.result_digest,
            )
            if not marked:
                return ExecutionReconcileStatus.IGNORED
        return await self.reconcile(identity=identity)

    async def reconcile(self, *, identity: ExecutionIdentity) -> ExecutionReconcileStatus:
        request, steps = await self._load_current(identity=identity)
        if request is None:
            return ExecutionReconcileStatus.IGNORED
        if request.execution_state == KnowledgeSpaceFileChangeExecutionState.COMPENSATING:
            return ExecutionReconcileStatus.COMPENSATING
        if request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED:
            return ExecutionReconcileStatus.FAILED
        if request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED:
            return (
                ExecutionReconcileStatus.COMPLETED
                if self.is_business_complete(request=request, steps=steps)
                else ExecutionReconcileStatus.RUNNING
            )
        if request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING:
            return ExecutionReconcileStatus.IGNORED
        if any(step.state == KnowledgeSpaceFileChangeExecutionStepState.FAILED for step in steps):
            await self.fail_execution(identity=identity, error_summary="business execution step failed")
            return ExecutionReconcileStatus.FAILED

        by_code = {step.step_code: step for step in steps}
        if request.action in {KnowledgeSpaceFileChangeAction.RENAME, KnowledgeSpaceFileChangeAction.MOVE}:
            external = (
                RenameExecutionStepCode.EXTERNAL
                if request.action == KnowledgeSpaceFileChangeAction.RENAME
                else MoveExecutionStepCode.EXTERNAL
            )
            if self._all_succeeded(by_code, external):
                completed = self.mutation_cutover(identity)
                if isawaitable(completed):
                    completed = await completed
                return ExecutionReconcileStatus.COMPLETED if completed else ExecutionReconcileStatus.RUNNING
            await self.heartbeat(identity=identity)
            return ExecutionReconcileStatus.RUNNING
        if request.action == KnowledgeSpaceFileChangeAction.DELETE:
            if not self._all_succeeded(by_code, (DeleteExecutionStepCode.PREPARE,)):
                await self.heartbeat(identity=identity)
                return ExecutionReconcileStatus.RUNNING
            if not self._all_succeeded(by_code, (DeleteExecutionStepCode.DB_CUTOVER,)):
                cutover = self.delete_cutover(identity)
                if isawaitable(cutover):
                    cutover = await cutover
                if not cutover:
                    return ExecutionReconcileStatus.RUNNING
            purged = self.delete_purge(identity)
            if isawaitable(purged):
                purged = await purged
            return ExecutionReconcileStatus.COMPLETED if purged else ExecutionReconcileStatus.RUNNING
        if not self._all_succeeded(by_code, UploadExecutionStepCode.BUSINESS_REQUIRED):
            await self.heartbeat(identity=identity)
            return ExecutionReconcileStatus.RUNNING
        await self._set_generation_state(
            identity=identity,
            expected={KnowledgeSpaceFileChangeExecutionState.APPLYING},
            target=KnowledgeSpaceFileChangeExecutionState.APPLIED,
        )
        return ExecutionReconcileStatus.COMPLETED

    async def heartbeat(self, *, identity: ExecutionIdentity, now: datetime | None = None) -> bool:
        self._require_matching_tenant(identity.tenant_id)
        async with self.session_factory() as session, session.begin():
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            request = await repository.get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
                for_update=True,
            )
            if not self._matches_identity(request, identity):
                return False
            checkpoint = dict(request.execution_checkpoint or {})
            checkpoint["heartbeat_at"] = (now or datetime.now(UTC)).isoformat()
            request.execution_checkpoint = checkpoint
            await repository.save(request)
        return True

    async def fail(self, *, identity: ExecutionIdentity, error_summary: str, **_watchdog) -> bool:
        return await self.fail_execution(identity=identity, error_summary=error_summary)

    @classmethod
    def is_business_complete(
        cls,
        *,
        request: KnowledgeSpaceFileChangeRequest,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> bool:
        required_codes = cls._required_step_codes(request.action)
        by_code = {step.step_code: step for step in steps}
        if not cls._all_succeeded(by_code, required_codes):
            return False
        if request.action in {KnowledgeSpaceFileChangeAction.RENAME, KnowledgeSpaceFileChangeAction.MOVE}:
            checkpoint = request.execution_checkpoint or {}
            return checkpoint.get(MUTATION_TRANSITION_PHASE_CHECKPOINT_KEY) == MUTATION_TRANSITION_NEW_VIEW
        if request.action == KnowledgeSpaceFileChangeAction.DELETE:
            checkpoint = request.execution_checkpoint or {}
            return (
                checkpoint.get(DELETE_PHASE_CHECKPOINT_KEY) == DELETE_PHASE_COMPLETED
                and not checkpoint.get("deletion_cutover_active")
                and all(
                    step.attempt_token == request.execution_token for step in steps if step.step_code in required_codes
                )
            )
        return True

    @classmethod
    def is_publishable(
        cls,
        *,
        request: KnowledgeSpaceFileChangeRequest,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> bool:
        return request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED and cls.is_business_complete(
            request=request,
            steps=steps,
        )

    @classmethod
    def project_business_status(
        cls,
        *,
        request: KnowledgeSpaceFileChangeRequest,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> dict[str, Any]:
        checkpoint = dict(request.execution_checkpoint or {})
        return {
            "status": request.execution_state,
            "action": request.action,
            "execution_state": request.execution_state,
            "failure_reason": checkpoint.get("failure_reason"),
            "cleanup_state": request.cleanup_state,
            "publishable": cls.is_publishable(request=request, steps=steps),
        }

    async def _load_current(
        self,
        *,
        identity: ExecutionIdentity,
    ) -> tuple[KnowledgeSpaceFileChangeRequest | None, list[KnowledgeSpaceFileChangeExecutionStep]]:
        self._require_matching_tenant(identity.tenant_id)
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
            )
            if not self._matches_identity(request, identity):
                return None, []
            steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
            )
        return request, steps

    @staticmethod
    def _matches_identity(request, identity: ExecutionIdentity) -> bool:
        return bool(request is not None and request.execution_token == identity.execution_token)

    @staticmethod
    def _step_context(
        *,
        identity: ExecutionIdentity,
        request: KnowledgeSpaceFileChangeRequest,
        row: KnowledgeSpaceFileChangeExecutionStep,
        acknowledgement: Any = None,
    ) -> ExecutionStepContext:
        return ExecutionStepContext(
            tenant_id=identity.tenant_id,
            request_id=identity.request_id,
            execution_token=identity.execution_token,
            action=str(request.action),
            step_code=str(row.step_code),
            idempotency_key=str(row.idempotency_key),
            task_id=row.task_id,
            acknowledgement=acknowledgement,
        )

    @staticmethod
    def _required_step_codes(action: str) -> tuple[str, ...]:
        if action == KnowledgeSpaceFileChangeAction.UPLOAD:
            return UploadExecutionStepCode.BUSINESS_REQUIRED
        if action == KnowledgeSpaceFileChangeAction.RENAME:
            return RenameExecutionStepCode.ALL
        if action == KnowledgeSpaceFileChangeAction.MOVE:
            return MoveExecutionStepCode.ALL
        if action == KnowledgeSpaceFileChangeAction.DELETE:
            return DeleteExecutionStepCode.ALL
        raise ValueError(f"unsupported F046 action: {action}")

    @classmethod
    def _ready_dispatch_step_codes(
        cls,
        action: str,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> tuple[str, ...]:
        by_code = {step.step_code: step for step in steps}
        if action == KnowledgeSpaceFileChangeAction.UPLOAD:
            chain = UploadExecutionStepCode.BUSINESS_REQUIRED
        elif action == KnowledgeSpaceFileChangeAction.RENAME:
            chain = RenameExecutionStepCode.EXTERNAL
        elif action == KnowledgeSpaceFileChangeAction.MOVE:
            chain = MoveExecutionStepCode.EXTERNAL
        else:
            return ()
        for code in chain:
            row = by_code.get(code)
            if row is None:
                return ()
            if row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
                continue
            if row.state in {
                KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
            }:
                return (code,)
            return ()
        return ()

    async def _cutover_verified_mutation(self, identity: ExecutionIdentity) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        return await KnowledgeSpaceMutationExecutor().cutover_verified_mutation(
            request_id=identity.request_id,
            execution_token=identity.execution_token,
        )

    async def _purge_delete(self, identity: ExecutionIdentity) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        return await KnowledgeSpaceMutationExecutor().purge_delete(
            request_id=identity.request_id,
            execution_token=identity.execution_token,
        )

    async def _cutover_delete(self, identity: ExecutionIdentity) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        return await KnowledgeSpaceMutationExecutor().cutover_delete(
            request_id=identity.request_id,
            execution_token=identity.execution_token,
        )

    @staticmethod
    def _all_succeeded(
        by_code: dict[str, KnowledgeSpaceFileChangeExecutionStep],
        required_codes: Sequence[str],
    ) -> bool:
        return all(
            code in by_code and by_code[code].state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
            for code in required_codes
        )

    @staticmethod
    def _mark_request_failed(request: KnowledgeSpaceFileChangeRequest, reason: str) -> None:
        checkpoint = dict(request.execution_checkpoint or {})
        checkpoint["failure_reason"] = str(reason)[:2000]
        request.execution_checkpoint = checkpoint
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED

    def _new_token(self, *, previous: str | None) -> str:
        token = str(self.execution_token_factory())
        if not token or len(token) > 64 or token == previous:
            raise ValueError("F046 retry requires a distinct 1 to 64 character token")
        return token

    @staticmethod
    def _require_matching_tenant(tenant_id: int) -> int:
        tenant_id = int(tenant_id)
        current = get_current_tenant_id()
        if tenant_id <= 0 or current is None or int(current) != tenant_id:
            raise RuntimeError("F046 execution requires the matching tenant context")
        return tenant_id
