from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from inspect import isawaitable
from typing import Any

from loguru import logger
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus, ApprovalOutboxStatus
from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
from bisheng.approval.domain.services.approval_outbox_service import ApprovalOutboxService, Deferred
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
from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import UploadExecutionStepCode

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
    instance_id: int
    outbox_id: int
    execution_token: str

    def __post_init__(self) -> None:
        if min(self.tenant_id, self.request_id, self.instance_id, self.outbox_id) <= 0:
            raise ValueError("F046 execution identity ids must be positive")
        if not self.execution_token or len(self.execution_token) > 64:
            raise ValueError("F046 execution token must contain 1 to 64 characters")


@dataclass(frozen=True, slots=True)
class ExecutionStepContext:
    tenant_id: int
    request_id: int
    instance_id: int
    outbox_id: int
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
OutboxLoader = Callable[[int], Awaitable[Any]]
InstanceOutboxesLoader = Callable[[int], Awaitable[list[Any]]]


class KnowledgeSpaceFileChangeExecutionCoordinator:
    """Drive durable F046 steps without treating queue receipts as success.

    Every callback is bound to tenant/request/instance/outbox/token. A repeated
    dispatch in the same generation intentionally reuses the durable
    idempotency key, while a callback from an older generation is ignored
    before any external verification is attempted.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = get_async_db_session,
        approval_outbox_service: ApprovalOutboxService | None = None,
        deadline_factory: Callable[[], datetime] | None = None,
        mutation_cutover: MutationCutover | None = None,
        delete_purge: MutationCutover | None = None,
        outbox_loader: OutboxLoader | None = None,
        instance_outboxes_loader: InstanceOutboxesLoader | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.approval_outbox_service = approval_outbox_service or ApprovalOutboxService(
            instance_repository=ApprovalInstanceRepository
        )
        self.deadline_factory = deadline_factory or (lambda: datetime.now(UTC) + timedelta(hours=24))
        self.mutation_cutover = mutation_cutover or self._cutover_verified_mutation
        self.delete_purge = delete_purge or self._purge_delete
        self.outbox_loader = outbox_loader or ApprovalInstanceRepository.get_outbox
        self.instance_outboxes_loader = instance_outboxes_loader or ApprovalInstanceRepository.list_outbox

    async def load_identity(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        execution_token: str,
    ) -> ExecutionIdentity | None:
        """Resolve a worker callback without exposing Approval ORM reads."""

        self._require_matching_tenant(tenant_id)
        outbox = await self.outbox_loader(int(outbox_id))
        if (
            outbox is None
            or int(outbox.tenant_id or 0) != int(tenant_id)
            or int(outbox.id or 0) != int(outbox_id)
            or outbox.status != ApprovalOutboxStatus.DEFERRED
            or outbox.execution_token != str(execution_token)
        ):
            return None
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_approval_instance_id(
                tenant_id=int(tenant_id),
                approval_instance_id=int(outbox.instance_id),
            )
        identity = (
            ExecutionIdentity(
                tenant_id=int(tenant_id),
                request_id=int(request.id) if request is not None else 0,
                instance_id=int(outbox.instance_id),
                outbox_id=int(outbox_id),
                execution_token=str(execution_token),
            )
            if request is not None
            else None
        )
        if identity is None or not self._matches_identity(request, identity):
            return None
        return identity

    async def load_identity_by_request(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
    ) -> ExecutionIdentity | None:
        """Bind a knowledge-worker callback that predates outbox persistence."""

        self._require_matching_tenant(tenant_id)
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=int(tenant_id),
                request_id=int(request_id),
            )
        if request is None or request.approval_instance_id is None or request.execution_token != str(execution_token):
            return None
        outboxes = await self.instance_outboxes_loader(int(request.approval_instance_id))
        current = next(
            (
                row
                for row in reversed(outboxes)
                if int(row.tenant_id or 0) == int(tenant_id)
                and int(row.instance_id) == int(request.approval_instance_id)
                and row.status == ApprovalOutboxStatus.DEFERRED
                and row.execution_token == str(execution_token)
            ),
            None,
        )
        if current is None:
            return None
        identity = ExecutionIdentity(
            tenant_id=int(tenant_id),
            request_id=int(request_id),
            instance_id=int(request.approval_instance_id),
            outbox_id=int(current.id),
            execution_token=str(execution_token),
        )
        return identity if self._matches_identity(request, identity) else None

    async def acknowledge_upload_pipeline(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
        step_code: str,
        verifier: StepVerifier,
        acknowledgement: Any = None,
    ) -> ExecutionReconcileStatus:
        identity = await self.load_identity_by_request(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
        if identity is None:
            return ExecutionReconcileStatus.IGNORED
        return await self.acknowledge_step(
            identity=identity,
            step_code=step_code,
            verifier=verifier,
            acknowledgement=acknowledgement,
        )

    async def acknowledge_upload_terminal(
        self,
        *,
        tenant_id: int,
        request_id: int,
        execution_token: str,
        file_id: int,
    ) -> ExecutionReconcileStatus:
        """Accept a legacy parser callback without coupling parsing to approval.

        New upload jobs do not carry F046 callback context. This path only
        upgrades an already-dispatched legacy parse step to the scheduler
        handoff acknowledgement required by the current business boundary.
        The file's parse result is intentionally not inspected.
        """

        identity = await self.load_identity_by_request(
            tenant_id=tenant_id,
            request_id=request_id,
            execution_token=execution_token,
        )
        if identity is None:
            return ExecutionReconcileStatus.IGNORED
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=int(tenant_id),
                    request_id=int(request_id),
                    for_update=True,
                )
                if (
                    not self._matches_identity(request, identity)
                    or request.action != KnowledgeSpaceFileChangeAction.UPLOAD
                    or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING
                    or int(request.executed_resource_id or 0) != int(file_id)
                ):
                    return ExecutionReconcileStatus.IGNORED
                parse_step = await KnowledgeSpaceFileChangeExecutionStepRepository(session).lock_step(
                    tenant_id=int(tenant_id),
                    request_id=int(request_id),
                    step_code=UploadExecutionStepCode.PARSE,
                )
                if (
                    parse_step is None
                    or parse_step.attempt_token != str(execution_token)
                    or parse_step.state
                    not in {
                        KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                        KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
                        KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                    }
                ):
                    return ExecutionReconcileStatus.IGNORED
                marked = await KnowledgeSpaceFileChangeExecutionStepRepository(session).mark_succeeded(
                    tenant_id=int(tenant_id),
                    request_id=int(request_id),
                    step_code=UploadExecutionStepCode.PARSE,
                    attempt_token=str(execution_token),
                    result_digest=f"legacy-parser-handoff:file:{int(file_id)}",
                )
                if not marked:
                    return ExecutionReconcileStatus.IGNORED
        return await self.reconcile(identity=identity)

    async def coordinate_outbox_execution(
        self,
        *,
        tenant_id: int,
        outbox_id: int,
        execution_token: str,
        dispatcher: StepDispatcher,
    ) -> ExecutionReconcileStatus:
        identity = await self.load_identity(
            tenant_id=tenant_id,
            outbox_id=outbox_id,
            execution_token=execution_token,
        )
        if identity is None:
            return ExecutionReconcileStatus.IGNORED
        await self.dispatch_ready_steps(identity=identity, dispatcher=dispatcher)
        return await self.reconcile(identity=identity)

    async def dispatch_ready_steps(
        self,
        *,
        identity: ExecutionIdentity,
        dispatcher: StepDispatcher,
        step_codes: Sequence[str] | None = None,
    ) -> list[str]:
        """Dispatch unfinished steps; DISPATCHED is safe to redeliver.

        The row is marked only after enqueue returns. A crash in that gap causes
        a same-generation redelivery with the same idempotency key, which is the
        required recovery behavior.
        """

        request, rows = await self._load_current(identity=identity)
        if request is None or request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLYING:
            return []
        selected = set(step_codes or self._required_step_codes(request.action))
        ready_codes = set(self._ready_dispatch_step_codes(request.action, rows))
        dispatched: list[str] = []
        for row in rows:
            if (
                row.step_code not in selected
                or row.step_code not in ready_codes
                or row.state
                in {
                    KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED,
                    KnowledgeSpaceFileChangeExecutionStepState.COMPENSATING,
                    KnowledgeSpaceFileChangeExecutionStepState.COMPENSATED,
                }
            ):
                continue
            context = self._step_context(identity=identity, request=request, row=row)
            task_id = dispatcher(context)
            if isawaitable(task_id):
                task_id = await task_id
            async with self.session_factory() as session:
                async with session.begin():
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
        if row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
            return await self.reconcile(identity=identity)
        if row.state not in {
            KnowledgeSpaceFileChangeExecutionStepState.PENDING,
            KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
        }:
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

        async with self.session_factory() as session:
            async with session.begin():
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
        """Project durable truth into the F025 Deferred state machine."""

        return await self._reconcile(identity=identity, allow_cutover=True)

    async def _reconcile(
        self,
        *,
        identity: ExecutionIdentity,
        allow_cutover: bool,
    ) -> ExecutionReconcileStatus:

        result = ExecutionReconcileStatus.RUNNING
        failure_reason: str | None = None
        should_cutover = False
        should_purge_delete = False
        async with self.session_factory() as session:
            async with session.begin():
                request_repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await request_repository.get_by_id(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                    for_update=True,
                )
                if not self._matches_identity(request, identity):
                    return ExecutionReconcileStatus.IGNORED
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                    for_update=True,
                )
                required_codes = self._required_step_codes(request.action)
                required = {row.step_code: row for row in steps if row.step_code in required_codes}

                if request.execution_state == KnowledgeSpaceFileChangeExecutionState.COMPENSATING:
                    result = ExecutionReconcileStatus.COMPENSATING
                elif request.execution_state == KnowledgeSpaceFileChangeExecutionState.FAILED:
                    result = ExecutionReconcileStatus.FAILED
                    failure_reason = self._failure_reason(request, "business execution failed")
                elif request.action == KnowledgeSpaceFileChangeAction.UPLOAD:
                    if self._upload_business_handoff_succeeded(required):
                        request.execution_state = KnowledgeSpaceFileChangeExecutionState.APPLIED
                        checkpoint = dict(request.execution_checkpoint or {})
                        checkpoint.pop("failure_reason", None)
                        checkpoint["formalized_at"] = datetime.now(UTC).isoformat()
                        request.execution_checkpoint = checkpoint
                        await request_repository.save(request)
                        result = ExecutionReconcileStatus.COMPLETED
                elif request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED and self._all_succeeded(
                    required, required_codes
                ):
                    # Delete completion belongs to its atomic DB cutover. Its
                    # purge steps are durable post-completion cleanup and must
                    # never regress the approval instance.
                    result = ExecutionReconcileStatus.COMPLETED
                elif (
                    allow_cutover
                    and request.action
                    in {
                        KnowledgeSpaceFileChangeAction.RENAME,
                        KnowledgeSpaceFileChangeAction.MOVE,
                    }
                    and self._all_succeeded(required, self._external_step_codes(request.action))
                ):
                    should_cutover = True
                elif request.action == KnowledgeSpaceFileChangeAction.DELETE and self._all_succeeded(
                    required, ("delete.db_cutover",)
                ):
                    should_purge_delete = True
                elif (
                    allow_cutover
                    and request.action == KnowledgeSpaceFileChangeAction.DELETE
                    and self._all_succeeded(required, ("delete.prepare",))
                ):
                    should_cutover = True
                elif any(row.state == KnowledgeSpaceFileChangeExecutionStepState.FAILED for row in required.values()):
                    failure_reason = "business execution step failed"
                    self._mark_request_failed(request, failure_reason)
                    await request_repository.save(request)
                    result = ExecutionReconcileStatus.FAILED

        if should_cutover:
            try:
                cutover = self.mutation_cutover(identity)
                if isawaitable(cutover):
                    cutover = await cutover
            except Exception as exc:
                await self.fail(identity=identity, error_summary=str(exc))
                return ExecutionReconcileStatus.FAILED
            if not cutover:
                return ExecutionReconcileStatus.IGNORED
            return await self._reconcile(identity=identity, allow_cutover=False)
        if should_purge_delete:
            try:
                purged = self.delete_purge(identity)
                if isawaitable(purged):
                    purged = await purged
            except Exception:
                logger.exception(
                    "F046 delete purge failed: request_id={} token={}",
                    identity.request_id,
                    identity.execution_token,
                )
                return ExecutionReconcileStatus.FAILED
            if not purged:
                return ExecutionReconcileStatus.RUNNING
            async with self.session_factory() as session:
                request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                )
                steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                )
            by_code = {row.step_code: row for row in steps}
            if (
                self._matches_identity(request, identity)
                and request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED
                and self._all_succeeded(by_code, self._required_step_codes(KnowledgeSpaceFileChangeAction.DELETE))
            ):
                return ExecutionReconcileStatus.COMPLETED
            raise RuntimeError("F046 delete purge reported success without durable terminal state")
        if result == ExecutionReconcileStatus.FAILED:
            await self.fail(identity=identity, error_summary=failure_reason or "business execution failed")
            return result
        if result == ExecutionReconcileStatus.COMPLETED:
            # Delete and rename/move complete F025 in the same caller-owned
            # cutover UoW as their formal DB visibility switch.
            if request.action == KnowledgeSpaceFileChangeAction.UPLOAD:
                await self.approval_outbox_service.complete_deferred_execution(
                    tenant_id=identity.tenant_id,
                    instance_id=identity.instance_id,
                    outbox_id=identity.outbox_id,
                    execution_token=identity.execution_token,
                )
            return result
        await self.heartbeat(identity=identity)
        return result

    async def heartbeat(self, *, identity: ExecutionIdentity, now: datetime | None = None) -> bool:
        return await self.approval_outbox_service.heartbeat_deferred_execution(
            tenant_id=identity.tenant_id,
            instance_id=identity.instance_id,
            outbox_id=identity.outbox_id,
            execution_token=identity.execution_token,
            now=now,
        )

    async def fail(
        self,
        *,
        identity: ExecutionIdentity,
        error_summary: str,
        watchdog: bool = False,
        heartbeat_timeout_seconds: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        failed = await self.approval_outbox_service.fail_deferred_execution(
            tenant_id=identity.tenant_id,
            instance_id=identity.instance_id,
            outbox_id=identity.outbox_id,
            execution_token=identity.execution_token,
            error_summary=str(error_summary)[:2000],
            watchdog=watchdog,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            now=now,
        )
        async with self.session_factory() as session:
            async with session.begin():
                repository = KnowledgeSpaceFileChangeRequestRepository(session)
                request = await repository.get_by_id(
                    tenant_id=identity.tenant_id,
                    request_id=identity.request_id,
                    for_update=True,
                )
                if (
                    self._matches_identity(request, identity)
                    and request.execution_state != KnowledgeSpaceFileChangeExecutionState.APPLIED
                ):
                    self._mark_request_failed(request, error_summary)
                    await repository.save(request)
        return failed

    async def prepare_resume_in_uow(
        self,
        *,
        session: AsyncSession,
        request_id: int,
        new_token: str,
    ) -> Deferred:
        """Restore the F046 request inside F025's locked resume transaction."""

        tenant_id = self._require_tenant_id()
        request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
            tenant_id=tenant_id,
            request_id=int(request_id),
            for_update=True,
        )
        if request is None:
            raise LookupError(f"F046 request not found: {request_id}")

        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        executor = KnowledgeSpaceMutationExecutor(deadline_factory=self.deadline_factory)
        if request.action == KnowledgeSpaceFileChangeAction.UPLOAD:
            return await executor.prepare_upload_resume_in_uow(
                session=session,
                request_id=int(request_id),
                new_token=str(new_token),
            )
        if request.action in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
        }:
            return await executor.prepare_mutation_resume_in_uow(
                session=session,
                request_id=int(request_id),
                new_token=str(new_token),
            )
        prepare_delete = getattr(executor, "prepare_delete_resume_in_uow", None)
        if prepare_delete is None:
            raise RuntimeError("F046 delete resume is not available")
        return await prepare_delete(
            session=session,
            request_id=int(request_id),
            new_token=str(new_token),
        )

    async def get_business_status_projection(
        self,
        *,
        instance,
        request: KnowledgeSpaceFileChangeRequest | None = None,
    ) -> dict:
        tenant_id = int(instance.tenant_id)
        self._require_matching_tenant(tenant_id)
        request_id = self._request_id(instance)
        if (
            request is not None
            and request.executed_resource_id is None
            and request.execution_state
            in {
                KnowledgeSpaceFileChangeExecutionState.NOT_STARTED,
                KnowledgeSpaceFileChangeExecutionState.FAILED,
            }
        ):
            return self.project_business_status(
                instance_status=str(instance.status),
                request=request,
                file_status=None,
                steps=(),
            )
        async with self.session_factory() as session:
            repository = KnowledgeSpaceFileChangeRequestRepository(session)
            current = request or await repository.get_by_id(
                tenant_id=tenant_id,
                request_id=request_id,
            )
            if current is None:
                return {}
            file_status = await repository.get_executed_file_status(
                tenant_id=tenant_id,
                request=current,
            )
            steps = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=tenant_id,
                request_id=request_id,
            )
        return self.project_business_status(
            instance_status=str(instance.status),
            request=current,
            file_status=file_status,
            steps=steps,
        )

    @classmethod
    def project_business_status(
        cls,
        *,
        instance_status: str,
        request: KnowledgeSpaceFileChangeRequest,
        file_status: int | None,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> dict:
        checkpoint = dict(request.execution_checkpoint or {})
        failure_reason = checkpoint.get("failure_reason")
        required_codes = cls._required_step_codes(request.action)
        required = {row.step_code: row for row in steps if row.step_code in required_codes}
        complete = request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED and cls._all_succeeded(
            required,
            required_codes,
        )
        if request.action == KnowledgeSpaceFileChangeAction.UPLOAD:
            complete = request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLIED and (
                cls._upload_business_handoff_succeeded(required)
            )

        if complete:
            status = "published"
        elif instance_status == ApprovalInstanceStatus.EXECUTED:
            status = "execute_failed"
            failure_reason = failure_reason or "business execution is incomplete"
        elif (
            request.execution_state
            in {
                KnowledgeSpaceFileChangeExecutionState.FAILED,
                KnowledgeSpaceFileChangeExecutionState.COMPENSATING,
            }
            or instance_status == ApprovalInstanceStatus.EXECUTE_FAILED
        ):
            status = "execute_failed"
        elif request.execution_state == KnowledgeSpaceFileChangeExecutionState.APPLYING:
            status = "executing"
        else:
            status = "pending"
        return {
            "status": status,
            "action": request.action,
            "execution_state": request.execution_state,
            "failure_reason": failure_reason,
            "cleanup_state": request.cleanup_state,
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
            rows = await KnowledgeSpaceFileChangeExecutionStepRepository(session).list_by_request(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
            )
        return request, rows

    @staticmethod
    def _matches_identity(request, identity: ExecutionIdentity) -> bool:
        return bool(
            request is not None
            and int(request.approval_instance_id or 0) == identity.instance_id
            and request.execution_token == identity.execution_token
        )

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
            instance_id=identity.instance_id,
            outbox_id=identity.outbox_id,
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
            return ("rename.index_shadow", "rename.verify", "rename.db_cutover")
        if action == KnowledgeSpaceFileChangeAction.MOVE:
            return (
                "move.parent_prepare",
                "move.tags_prepare",
                "move.storage_prepare",
                "move.index_prepare",
                "move.verify",
                "move.db_cutover",
            )
        if action == KnowledgeSpaceFileChangeAction.DELETE:
            return (
                "delete.prepare",
                "delete.db_cutover",
                "delete.fga_purge",
                "delete.minio_purge",
                "delete.es_purge",
                "delete.milvus_purge",
            )
        raise ValueError(f"unsupported F046 action: {action}")

    @staticmethod
    def _upload_business_handoff_succeeded(
        required: dict[str, KnowledgeSpaceFileChangeExecutionStep],
    ) -> bool:
        fga = required.get(UploadExecutionStepCode.FGA)
        parse_handoff = required.get(UploadExecutionStepCode.PARSE)
        return bool(
            fga is not None
            and fga.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
            and parse_handoff is not None
            and parse_handoff.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED
        )

    @classmethod
    def _ready_dispatch_step_codes(
        cls,
        action: str,
        steps: Sequence[KnowledgeSpaceFileChangeExecutionStep],
    ) -> tuple[str, ...]:
        """Return at most one dependency-safe broker step.

        Upload index/vector acknowledgements are emitted by the authoritative
        parser pipeline; they are not independent tasks. Database cutovers are
        internal owner operations and are never placed on the generic broker.
        """

        by_code = {row.step_code: row for row in steps}
        if action == KnowledgeSpaceFileChangeAction.UPLOAD:
            chain = ("upload.fga", "upload.parse")
        elif action in {
            KnowledgeSpaceFileChangeAction.RENAME,
            KnowledgeSpaceFileChangeAction.MOVE,
        }:
            chain = cls._external_step_codes(action)
        else:
            return ()
        for step_code in chain:
            row = by_code.get(step_code)
            if row is None:
                return ()
            if row.state == KnowledgeSpaceFileChangeExecutionStepState.SUCCEEDED:
                continue
            if row.state in {
                KnowledgeSpaceFileChangeExecutionStepState.PENDING,
                KnowledgeSpaceFileChangeExecutionStepState.DISPATCHED,
            }:
                return (step_code,)
            return ()
        return ()

    @staticmethod
    def _external_step_codes(action: str) -> tuple[str, ...]:
        if action == KnowledgeSpaceFileChangeAction.RENAME:
            return ("rename.index_shadow", "rename.verify")
        if action == KnowledgeSpaceFileChangeAction.MOVE:
            return (
                "move.parent_prepare",
                "move.tags_prepare",
                "move.storage_prepare",
                "move.index_prepare",
                "move.verify",
            )
        return ()

    async def _cutover_verified_mutation(self, identity: ExecutionIdentity) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        executor = KnowledgeSpaceMutationExecutor()
        async with self.session_factory() as session:
            request = await KnowledgeSpaceFileChangeRequestRepository(session).get_by_id(
                tenant_id=identity.tenant_id,
                request_id=identity.request_id,
            )
        if not self._matches_identity(request, identity):
            return False
        cutover_name = (
            "cutover_delete" if request.action == KnowledgeSpaceFileChangeAction.DELETE else "cutover_verified_mutation"
        )
        cutover = getattr(executor, cutover_name, None)
        if cutover is None:
            raise RuntimeError(f"F046 owner cutover is not available: {cutover_name}")
        return bool(
            await cutover(
                instance_id=identity.instance_id,
                request_id=identity.request_id,
                execution_token=identity.execution_token,
            )
        )

    async def _purge_delete(self, identity: ExecutionIdentity) -> bool:
        from bisheng.knowledge.domain.services.knowledge_space_mutation_executor import (
            KnowledgeSpaceMutationExecutor,
        )

        return await KnowledgeSpaceMutationExecutor().purge_delete(
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
    def _failure_reason(request: KnowledgeSpaceFileChangeRequest, fallback: str) -> str:
        return str((request.execution_checkpoint or {}).get("failure_reason") or fallback)

    @staticmethod
    def _mark_request_failed(request: KnowledgeSpaceFileChangeRequest, reason: str) -> None:
        checkpoint = dict(request.execution_checkpoint or {})
        checkpoint["failure_reason"] = str(reason)[:1000]
        request.execution_checkpoint = checkpoint
        request.execution_state = KnowledgeSpaceFileChangeExecutionState.FAILED

    @staticmethod
    def _request_id(instance) -> int:
        payload = instance.payload_snapshot or {}
        value = payload.get("change_request_id") or instance.business_resource_id
        if value is None or int(value) <= 0:
            raise ValueError("F046 instance has no positive change_request_id")
        return int(value)

    @staticmethod
    def _require_tenant_id() -> int:
        tenant_id = get_current_tenant_id()
        if tenant_id is None or int(tenant_id) <= 0:
            raise RuntimeError("tenant context is required for F046 execution")
        return int(tenant_id)

    @classmethod
    def _require_matching_tenant(cls, tenant_id: int) -> None:
        if cls._require_tenant_id() != int(tenant_id):
            raise RuntimeError("a matching tenant context is required for F046 execution")
