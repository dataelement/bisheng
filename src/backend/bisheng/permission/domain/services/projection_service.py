"""Durable tenant-scoped SQL-to-OpenFGA projection protocol."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.permission import (
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    ProjectionOperationStatus,
)
from bisheng.permission.domain.repositories.interfaces import (
    PermissionProjectionRepositoryPort,
)
from bisheng.permission.domain.services import projection_plan as projection_plan_types
from bisheng.permission.domain.services.projection_plan import (
    HIGHER_CONSISTENCY,
    MAX_ATOMIC_TUPLES,
    ProjectionOutcome,
    ProjectionPlan,
    ProjectionTupleDelta,
    build_projection_operation,
    normalize_projection_plan,
    projection_request_checksum,
    projection_state_expectations,
)

ProjectionCommitUnknownError = projection_plan_types.ProjectionCommitUnknownError


class ProjectionMarkerPort(Protocol):
    async def is_ready(self) -> bool: ...

    async def arm(self, plan: ProjectionPlan) -> None: ...


class ProjectionScopeGuardPort(Protocol):
    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None: ...

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool: ...

    async def fail_closed(self, plan: ProjectionPlan, reason: str) -> None: ...


class ProjectionFGAPort(Protocol):
    async def write_atomic(
        self,
        *,
        writes: tuple[ProjectionTupleDelta, ...],
        deletes: tuple[ProjectionTupleDelta, ...],
    ) -> str: ...

    async def read_present(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
        *,
        consistency: str,
    ) -> frozenset[tuple[str, str, str]]: ...


class ProjectionFinalizerPort(Protocol):
    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None: ...


class ProjectionEventPort(Protocol):
    async def emit(self, name: str, fields: dict) -> None: ...


class _NullFinalizer:
    async def finalize(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        return None


class _NullEvents:
    async def emit(self, name: str, fields: dict) -> None:
        return None


class ProjectionService:
    """Execute and reconcile one atomic permission projection operation."""

    def __init__(
        self,
        *,
        repository: PermissionProjectionRepositoryPort,
        marker: ProjectionMarkerPort,
        scope_guard: ProjectionScopeGuardPort,
        fga: ProjectionFGAPort,
        finalizer: ProjectionFinalizerPort | None = None,
        events: ProjectionEventPort | None = None,
        stage_batch_size: int = MAX_ATOMIC_TUPLES,
    ) -> None:
        if not 1 <= stage_batch_size <= MAX_ATOMIC_TUPLES:
            raise ValueError("stage_batch_size must be between 1 and 90")
        self._repository = repository
        self._marker = marker
        self._scope_guard = scope_guard
        self._fga = fga
        self._finalizer = finalizer or _NullFinalizer()
        self._events = events or _NullEvents()
        self._stage_batch_size = stage_batch_size

    async def execute(self, plan: ProjectionPlan) -> ProjectionOutcome:
        """Prepare, project, verify, and finalize one idempotent plan."""

        normalized = normalize_projection_plan(plan)
        request_checksum = projection_request_checksum(normalized)
        operation = await self.prepare(normalized)
        return await self._resume(
            normalized,
            operation,
            request_checksum=request_checksum,
        )

    async def prepare(
        self,
        plan: ProjectionPlan,
    ) -> PermissionProjectionOperation:
        """Persist the durable operation before any permission mirror changes."""

        normalized = normalize_projection_plan(plan)
        request_checksum = projection_request_checksum(normalized)
        existing = await self._repository.aget_operation_by_idempotency(normalized.idempotency_key)
        if existing is not None:
            if existing.request_checksum != request_checksum:
                raise PermissionVersionConflictError(msg="Idempotency key is bound to another projection request")
            return existing
        if not await self._marker.is_ready():
            raise PermissionPublishNotReadyError(msg="Permission recent-change marker sentinel is not ready")
        operation, tuple_rows = build_projection_operation(
            normalized,
            request_checksum=request_checksum,
        )
        operation = await self._repository.acreate_operation(
            operation,
            tuple_rows,
        )
        if operation.request_checksum != request_checksum:
            raise PermissionVersionConflictError(msg="Idempotency key checksum changed during projection prepare")
        return operation

    async def abandon_prepared(
        self,
        plan: ProjectionPlan,
        error: Exception,
    ) -> None:
        """Close an operation whose SQL mirror prepare transaction was rejected."""

        normalized = normalize_projection_plan(plan)
        request_checksum = projection_request_checksum(normalized)
        operation = await self._repository.aget_operation_by_idempotency(normalized.idempotency_key)
        if operation is None or operation.request_checksum != request_checksum:
            raise PermissionVersionConflictError(msg="Projection prepare cannot be abandoned from this request")
        if str(operation.status) != ProjectionOperationStatus.PREPARED.value:
            return
        await self._transition(
            operation,
            expected=ProjectionOperationStatus.PREPARED.value,
            target=ProjectionOperationStatus.FAILED_CLOSED.value,
            error=error,
        )
        await self._emit(
            normalized,
            operation,
            ProjectionOperationStatus.FAILED_CLOSED.value,
            error,
        )

    async def reconcile(self, plan: ProjectionPlan) -> ProjectionOutcome:
        """Resume a durable operation using its original request checksum."""

        normalized = normalize_projection_plan(plan)
        request_checksum = projection_request_checksum(normalized)
        operation = await self._repository.aget_operation_by_idempotency(normalized.idempotency_key)
        if operation is None or operation.request_checksum != request_checksum:
            raise PermissionVersionConflictError(msg="Projection operation cannot be reconciled from this request")
        return await self._resume(
            normalized,
            operation,
            request_checksum=request_checksum,
        )

    async def reconcile_operation(
        self,
        operation_id: int,
    ) -> ProjectionOutcome:
        """Rebuild and resume a projection using only its durable ledger rows.

        Business services persist the operation ID before committing their SQL
        mutation.  Retried requests can therefore resume the exact projection
        even when the original in-memory plan was lost.
        """

        operation = await self._repository.aget_operation(operation_id)
        if operation is None:
            raise PermissionPublishNotReadyError(
                msg="Projection operation does not exist",
            )
        tuple_rows = await self._repository.aget_operation_tuples(
            operation_id,
        )
        plan = self._restore_plan(operation, tuple_rows)
        return await self.reconcile(plan)

    @staticmethod
    def _restore_plan(
        operation: PermissionProjectionOperation,
        tuple_rows,
    ) -> ProjectionPlan:
        if operation.id is None or operation.tenant_id is None or not tuple_rows:
            raise PermissionPublishNotReadyError(
                msg="Projection ledger is incomplete",
            )
        deltas = tuple(
            ProjectionTupleDelta(
                phase=row.phase,
                sequence=int(row.sequence),
                action=row.action,
                user=row.fga_user,
                relation=row.relation,
                object=row.fga_object,
            )
            for row in tuple_rows
        )
        for change_item_count in range(0, 51):
            candidate = ProjectionPlan(
                tenant_id=int(operation.tenant_id),
                idempotency_key=operation.idempotency_key,
                operation_type=operation.operation_type,
                scope_type=operation.scope_type,
                scope_key=operation.scope_key,
                expected_version=int(operation.expected_version),
                target_version=int(operation.target_version),
                store_id=operation.store_id,
                model_id=operation.model_id,
                operator_id=int(operation.operator_id),
                change_item_count=change_item_count,
                deltas=deltas,
            )
            normalized = normalize_projection_plan(candidate)
            if projection_request_checksum(normalized) == operation.request_checksum:
                return normalized
        raise PermissionVersionConflictError(
            msg="Projection ledger checksum cannot be reconstructed",
        )

    async def _run_prepared(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        request_checksum: str,
    ) -> ProjectionOutcome:
        try:
            await self._scope_guard.reserve(plan, int(operation.id))
        except Exception as exc:
            await self.abandon_prepared(plan, exc)
            raise
        try:
            await self._marker.arm(plan)
        except Exception as exc:
            await self._emit(plan, operation, "MARKER_FAILED", exc)
            raise PermissionProjectionFailedError(exception=exc) from exc

        await self._transition(
            operation,
            expected=ProjectionOperationStatus.PREPARED.value,
            target=ProjectionOperationStatus.STAGING.value,
        )
        stage_deltas = tuple(delta for delta in plan.deltas if delta.phase == "STAGE")
        applied_stage: list[ProjectionTupleDelta] = []
        try:
            for offset in range(0, len(stage_deltas), self._stage_batch_size):
                batch = stage_deltas[offset : offset + self._stage_batch_size]
                await self._write(batch)
                applied_stage.extend(batch)
        except Exception as exc:
            await self._compensate_stage(
                plan,
                operation,
                tuple(applied_stage),
                cause=exc,
            )
            raise PermissionProjectionFailedError(exception=exc) from exc

        commit_deltas = tuple(delta for delta in plan.deltas if delta.phase == "COMMIT")
        try:
            commit_checksum = await self._write(commit_deltas)
        except Exception as exc:
            await self._transition(
                operation,
                expected=ProjectionOperationStatus.STAGING.value,
                target=ProjectionOperationStatus.COMMIT_UNKNOWN.value,
                error=exc,
            )
            return await self._resolve_commit(
                plan,
                operation,
                request_checksum=request_checksum,
                allow_retry=True,
            )

        if not await self._is_after(plan.deltas):
            await self._mark_failed_closed(
                plan,
                operation,
                reason="higher-consistency verification did not observe full after state",
            )
        await self._transition(
            operation,
            expected=ProjectionOperationStatus.STAGING.value,
            target=ProjectionOperationStatus.COMMITTED.value,
            commit_checksum=commit_checksum,
        )
        return await self._finalize(
            plan,
            operation,
            request_checksum=request_checksum,
            reconciled=False,
        )

    async def _resume(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        request_checksum: str,
    ) -> ProjectionOutcome:
        status = str(operation.status)
        if status == ProjectionOperationStatus.FINALIZED.value:
            return self._outcome(
                plan,
                operation,
                request_checksum=request_checksum,
                idempotent=True,
            )
        if status == ProjectionOperationStatus.PREPARED.value:
            if not await self._marker.is_ready():
                raise PermissionPublishNotReadyError()
            return await self._run_prepared(
                plan,
                operation,
                request_checksum=request_checksum,
            )
        if status in {
            ProjectionOperationStatus.STAGING.value,
            ProjectionOperationStatus.COMMIT_UNKNOWN.value,
        }:
            return await self._resolve_commit(
                plan,
                operation,
                request_checksum=request_checksum,
                allow_retry=True,
            )
        if status == ProjectionOperationStatus.COMMITTED.value:
            return await self._finalize(
                plan,
                operation,
                request_checksum=request_checksum,
                reconciled=True,
            )
        raise PermissionProjectionFailedError(msg=f"Projection operation is fail closed: {operation.id}")

    async def _resolve_commit(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        request_checksum: str,
        allow_retry: bool,
    ) -> ProjectionOutcome:
        stage_deltas = tuple(delta for delta in plan.deltas if delta.phase == "STAGE")
        commit_deltas = tuple(delta for delta in plan.deltas if delta.phase == "COMMIT")
        commit_state = await self._classify(commit_deltas)
        if commit_state == "AFTER":
            if not await self._is_after(plan.deltas):
                await self._mark_failed_closed(
                    plan,
                    operation,
                    reason="projection commit after state is incomplete",
                )
            await self._transition(
                operation,
                expected=str(operation.status),
                target=ProjectionOperationStatus.COMMITTED.value,
                commit_checksum=operation.after_checksum,
            )
            return await self._finalize(
                plan,
                operation,
                request_checksum=request_checksum,
                reconciled=True,
            )

        if commit_state == "BEFORE" and allow_retry:
            if stage_deltas and not await self._is_after(stage_deltas):
                await self._mark_failed_closed(
                    plan,
                    operation,
                    reason="staged tuple set is partial during reconciliation",
                )
            if not await self._scope_guard.is_expected_version(
                plan,
                int(operation.id),
            ):
                await self._mark_failed_closed(
                    plan,
                    operation,
                    reason="projection scope version changed before retry",
                )
            try:
                await self._marker.arm(plan)
                commit_checksum = await self._write(commit_deltas)
            except Exception:
                if await self._classify(commit_deltas) != "AFTER":
                    await self._mark_failed_closed(
                        plan,
                        operation,
                        reason="projection retry outcome is not full after state",
                    )
                commit_checksum = operation.after_checksum
            if not await self._is_after(plan.deltas):
                await self._mark_failed_closed(
                    plan,
                    operation,
                    reason="projection retry verification is incomplete",
                )
            await self._transition(
                operation,
                expected=str(operation.status),
                target=ProjectionOperationStatus.COMMITTED.value,
                commit_checksum=commit_checksum,
            )
            return await self._finalize(
                plan,
                operation,
                request_checksum=request_checksum,
                reconciled=True,
            )

        await self._mark_failed_closed(
            plan,
            operation,
            reason=f"projection commit state is {commit_state}",
        )
        raise AssertionError("unreachable")

    async def _write(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> str:
        writes = tuple(delta for delta in deltas if delta.action == "WRITE")
        deletes = tuple(delta for delta in deltas if delta.action == "DELETE")
        return await self._fga.write_atomic(writes=writes, deletes=deletes)

    async def _classify(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> str:
        representatives: dict[tuple[str, str, str], ProjectionTupleDelta] = {}
        for delta in deltas:
            representatives.setdefault(delta.key, delta)
        present = await self._fga.read_present(
            tuple(representatives.values()),
            consistency=HIGHER_CONSISTENCY,
        )
        after_state = projection_state_expectations(deltas, after=True)
        after = all((key in present) == expected for key, expected in after_state.items())
        if after:
            return "AFTER"
        before_state = projection_state_expectations(deltas, after=False)
        before = all((key in present) == expected for key, expected in before_state.items())
        return "BEFORE" if before else "MIXED"

    async def _is_after(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> bool:
        return await self._classify(deltas) == "AFTER"

    async def _compensate_stage(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        applied: tuple[ProjectionTupleDelta, ...],
        *,
        cause: Exception,
    ) -> None:
        inverse = tuple(
            replace(
                delta,
                action="DELETE" if delta.action == "WRITE" else "WRITE",
            )
            for delta in reversed(applied)
        )
        try:
            if inverse:
                await self._write(inverse)
            if applied and await self._classify(applied) != "BEFORE":
                raise RuntimeError("stage compensation verification failed")
            await self._transition(
                operation,
                expected=ProjectionOperationStatus.STAGING.value,
                target=ProjectionOperationStatus.PREPARED.value,
                error=cause,
            )
        except Exception as compensation_error:
            await self._mark_failed_closed(
                plan,
                operation,
                reason=f"stage compensation failed: {compensation_error}",
            )

    async def _finalize(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        request_checksum: str,
        reconciled: bool,
    ) -> ProjectionOutcome:
        try:
            await self._finalizer.finalize(plan, int(operation.id))
            await self._transition(
                operation,
                expected=ProjectionOperationStatus.COMMITTED.value,
                target=ProjectionOperationStatus.FINALIZED.value,
            )
        except Exception as exc:
            await self._emit(plan, operation, "COMMITTED_NOT_FINALIZED", exc)
            raise PermissionProjectionFailedError(exception=exc) from exc
        await self._emit(plan, operation, "FINALIZED")
        return self._outcome(
            plan,
            operation,
            request_checksum=request_checksum,
            reconciled=reconciled,
        )

    async def _mark_failed_closed(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        reason: str,
    ) -> None:
        await self._transition(
            operation,
            expected=str(operation.status),
            target=ProjectionOperationStatus.FAILED_CLOSED.value,
            error=PermissionProjectionFailedError(msg=reason),
        )
        await self._scope_guard.fail_closed(plan, reason)
        await self._emit(
            plan,
            operation,
            ProjectionOperationStatus.FAILED_CLOSED.value,
            PermissionProjectionFailedError(msg=reason),
        )
        raise PermissionProjectionFailedError(msg=reason)

    async def _transition(
        self,
        operation: PermissionProjectionOperation,
        *,
        expected: str,
        target: str,
        commit_checksum: str | None = None,
        error: Exception | None = None,
    ) -> None:
        changed = await self._repository.aupdate_operation_status_cas(
            operation_id=int(operation.id),
            expected_status=expected,
            target_status=target,
            commit_checksum=commit_checksum,
            error_code=(PermissionProjectionFailedError.Code if error is not None else None),
            error_message=str(error) if error is not None else None,
        )
        if not changed:
            raise PermissionVersionConflictError(msg=f"Projection status changed concurrently from {expected}")
        operation.status = target
        if commit_checksum is not None:
            operation.commit_checksum = commit_checksum

    async def _emit(
        self,
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        status: str,
        error: Exception | None = None,
    ) -> None:
        fields = {
            "operation_id": operation.id,
            "operation_type": plan.operation_type,
            "scope_type": plan.scope_type,
            "status": status,
            "tenant_id": plan.tenant_id,
            "tuple_count": len(plan.deltas),
        }
        if error is not None:
            fields["error"] = type(error).__name__
        try:
            await self._events.emit("permission_projection", fields)
        except Exception:
            logger.exception("Failed to emit the F048 projection event")
            return

    @staticmethod
    def _outcome(
        plan: ProjectionPlan,
        operation: PermissionProjectionOperation,
        *,
        request_checksum: str,
        idempotent: bool = False,
        reconciled: bool = False,
    ) -> ProjectionOutcome:
        return ProjectionOutcome(
            operation_id=int(operation.id),
            target_version=plan.target_version,
            status=str(operation.status),
            request_checksum=request_checksum,
            idempotent=idempotent,
            reconciled=reconciled,
        )
