"""Durable tenant-scoped SQL-to-OpenFGA projection protocol."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from hashlib import sha256
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
from bisheng.permission.domain.services.projection_diagnostics import emit_projection_alert, reason_from_exception
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

    async def is_failed_closed_recovery_scope(
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


@dataclass(frozen=True, slots=True)
class FailedClosedRecoveryPreview:
    """Exact terminal-state correction proposed for one fenced resource."""

    operation_id: int
    tenant_id: int
    operation_type: str
    scope_type: str
    scope_key: str
    expected_version: int
    target_version: int
    store_id: str
    model_id: str
    operation_status: str
    request_checksum: str
    after_checksum: str
    observed_state: str
    target_tuple_count: int
    correction_deltas: tuple[ProjectionTupleDelta, ...]
    confirmation_checksum: str


MAINTENANCE_TYPES = frozenset({"DEPARTMENT_RECONCILE", "DEPARTMENT_CURRENT_REPAIR"})


def reject_department_maintenance(operation):
    if operation.operation_type in MAINTENANCE_TYPES:
        raise PermissionPublishNotReadyError(msg="Use the dedicated department reconciliation CLI")


def restore_projection_plan(
    operation: PermissionProjectionOperation,
    tuple_rows,
) -> ProjectionPlan:
    """Rebuild and checksum-verify one projection plan from durable rows."""

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
        self._department_write_gate = ContextVar(f"department_write_gate_{id(self)}", default=None)
        self._department_guard = ContextVar(f"department_guard_{id(self)}", default=None)

    async def execute(self, plan: ProjectionPlan) -> ProjectionOutcome:
        """Prepare, project, verify, and finalize one idempotent plan."""

        reject_department_maintenance(plan)
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

        reject_department_maintenance(plan)
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

        reject_department_maintenance(plan)
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

        reject_department_maintenance(plan)
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
        reject_department_maintenance(operation)
        tuple_rows = await self._repository.aget_operation_tuples(
            operation_id,
        )
        plan = restore_projection_plan(operation, tuple_rows)
        return await self.reconcile(plan)

    async def inspect_failed_closed_recovery(
        self,
        operation_id: int,
    ) -> FailedClosedRecoveryPreview:
        """Build a read-only, checksum-bound forward recovery proposal."""

        operation, plan = await self._load_operation_plan(operation_id)
        status = str(operation.status)
        if status not in {
            ProjectionOperationStatus.FAILED_CLOSED.value,
            ProjectionOperationStatus.COMMITTED.value,
        }:
            raise PermissionPublishNotReadyError(
                msg=f"Projection operation is not recoverable from status {status}",
            )
        if plan.scope_type != "resource":
            raise PermissionPublishNotReadyError(
                msg="FAILED_CLOSED forward recovery only supports resource scopes",
            )

        correction = await self._terminal_correction(plan.deltas)
        observed_state = "AFTER" if not correction else await self._classify(plan.deltas)
        confirmation_checksum = self._recovery_confirmation_checksum(
            operation=operation,
            correction=correction,
        )
        return FailedClosedRecoveryPreview(
            operation_id=int(operation.id),
            tenant_id=plan.tenant_id,
            operation_type=plan.operation_type,
            scope_type=plan.scope_type,
            scope_key=plan.scope_key,
            expected_version=plan.expected_version,
            target_version=plan.target_version,
            store_id=plan.store_id,
            model_id=plan.model_id,
            operation_status=status,
            request_checksum=operation.request_checksum,
            after_checksum=operation.after_checksum,
            observed_state=observed_state,
            target_tuple_count=len(
                projection_state_expectations(plan.deltas, after=True),
            ),
            correction_deltas=correction,
            confirmation_checksum=confirmation_checksum,
        )

    async def recover_failed_closed_operation(
        self,
        operation_id: int,
        *,
        confirmation_checksum: str,
    ) -> ProjectionOutcome:
        """Forward-complete one fenced resource to its frozen AFTER state."""

        operation, plan = await self._load_operation_plan(operation_id)
        request_checksum = projection_request_checksum(plan)
        status = str(operation.status)
        if status == ProjectionOperationStatus.FINALIZED.value:
            return self._outcome(
                plan,
                operation,
                request_checksum=request_checksum,
                idempotent=True,
                reconciled=True,
            )

        preview = await self.inspect_failed_closed_recovery(operation_id)
        if preview.confirmation_checksum != confirmation_checksum:
            raise PermissionVersionConflictError(
                msg="FAILED_CLOSED recovery confirmation checksum changed",
            )
        if len(preview.correction_deltas) > MAX_ATOMIC_TUPLES:
            raise PermissionPublishNotReadyError(
                msg=(f"FAILED_CLOSED recovery requires more than {MAX_ATOMIC_TUPLES} atomic tuple corrections"),
            )
        if not await self._scope_guard.is_failed_closed_recovery_scope(
            plan,
            int(operation.id),
        ):
            raise PermissionPublishNotReadyError(
                msg="FAILED_CLOSED resource scope no longer owns the operation fence",
            )

        if status == ProjectionOperationStatus.COMMITTED.value:
            if preview.correction_deltas:
                raise PermissionProjectionFailedError(
                    msg="Committed recovery operation no longer has its full AFTER state",
                )
            return await self._finalize(
                plan,
                operation,
                request_checksum=request_checksum,
                reconciled=True,
            )

        if not await self._marker.is_ready():
            raise PermissionPublishNotReadyError(
                msg="Permission recent-change marker sentinel is not ready",
            )
        try:
            await self._marker.arm(plan)
            commit_checksum = (
                await self._write(preview.correction_deltas) if preview.correction_deltas else operation.after_checksum
            )
        except Exception as exc:
            if not await self._is_after(plan.deltas):
                await self._emit(plan, operation, "FAILED_CLOSED_RECOVERY_FAILED", exc)
                raise PermissionProjectionFailedError(exception=exc) from exc
            commit_checksum = operation.after_checksum

        if not await self._is_after(plan.deltas):
            error = PermissionProjectionFailedError(
                msg="FAILED_CLOSED recovery did not reach the frozen AFTER state",
            )
            await self._emit(plan, operation, "FAILED_CLOSED_RECOVERY_FAILED", error)
            raise error
        await self._transition(
            operation,
            expected=ProjectionOperationStatus.FAILED_CLOSED.value,
            target=ProjectionOperationStatus.COMMITTED.value,
            commit_checksum=commit_checksum,
        )
        return await self._finalize(
            plan,
            operation,
            request_checksum=request_checksum,
            reconciled=True,
        )

    @asynccontextmanager
    async def department_uow(self, session, *, guard=None, write_gate=None):
        """Borrow the Owner's session so ledger and department finalize together."""
        token = self._department_guard.set(guard)
        write_token = self._department_write_gate.set(write_gate)
        try:
            async with self._repository.bind_session(session):
                yield
        finally:
            self._department_write_gate.reset(write_token)
            self._department_guard.reset(token)

    async def department_active_ids(self, department_id):
        return await self._repository.adepartment_active_ids(department_id)

    async def department_needs_recovery(self, operation_id):
        metadata = await self._repository.aget_bound_operation_metadata([operation_id])
        operation = metadata.get(operation_id)
        return operation is None or operation["status"] != "FINALIZED"

    async def department_plan(self, operation_id):
        operation = await self._repository.aget_operation(operation_id)
        if operation is None:
            raise PermissionPublishNotReadyError(msg="Department operation missing")
        reject_department_maintenance(operation)
        if (
            getattr(self._repository, "_active_session", None) is not None
            and self._repository._active_session.get() is not None
        ):
            operation = await self._repository.alock_recovery_operation(operation_id)
        rows = await self._repository.aget_operation_tuples(operation_id, limit=91)
        if len(rows) > 90:
            raise PermissionPublishNotReadyError(msg="Original department scope exceeds 90")
        return operation, restore_projection_plan(operation, rows)

    async def recover_department_operation(self, operation_id, *, verify_owner):
        """Original intent only. The Owner must hold its SQL lock and lease.

        verify_owner checks current model, binding and the ENTIRE owned tuple
        target, including unrelated members. It runs before and after mutation.
        This entry deliberately does not extend generic resource recovery.
        """
        operation, plan = await self._load_operation_plan(operation_id)
        if plan.scope_type != "department" or any(d.phase != "COMMIT" for d in plan.deltas):
            raise PermissionPublishNotReadyError(msg="Unsupported original department projection")
        observed = await verify_owner(plan, operation)
        if observed is None:
            correction = await self._terminal_correction(plan.deltas)
        else:
            expected = projection_state_expectations(plan.deltas, after=True)
            representatives = {d.key: d for d in plan.deltas}
            correction = tuple(
                replace(representatives[key], sequence=index, action="WRITE" if present else "DELETE")
                for index, (key, present) in enumerate(sorted(expected.items()))
                if (key in observed) != present
            )
        status = str(operation.status)
        if status in {"COMMITTED", "FINALIZED"} and correction:
            raise PermissionPublishNotReadyError(msg="COMMITTED_AFTER_STATE_MISSING")
        if status == "FINALIZED":
            return self._outcome(plan, operation, request_checksum=operation.request_checksum, idempotent=True)
        if status not in {"PREPARED", "STAGING", "COMMIT_UNKNOWN", "FAILED_CLOSED", "COMMITTED"}:
            raise PermissionPublishNotReadyError(msg="Unsupported original operation status")
        if not await self._marker.is_ready():
            raise PermissionPublishNotReadyError(msg="Permission marker unavailable")
        await self._marker.arm(plan)
        if correction:
            try:
                await self._write(correction)
            except Exception:
                after = await verify_owner(plan, operation)
                if after is None:
                    if not await self._is_after(plan.deltas):
                        raise
                elif any(
                    (key in after) != present
                    for key, present in projection_state_expectations(plan.deltas, after=True).items()
                ):
                    raise
        after = await verify_owner(plan, operation)
        if after is None and not await self._is_after(plan.deltas):
            raise PermissionPublishNotReadyError(msg="Original department AFTER not verified")
        if after is not None and any(
            (key in after) != present for key, present in projection_state_expectations(plan.deltas, after=True).items()
        ):
            raise PermissionPublishNotReadyError(msg="Original department AFTER not verified")
        if status != "COMMITTED":
            await self._transition(
                operation, expected=status, target="COMMITTED", commit_checksum=operation.after_checksum
            )
        return await self._finalize(plan, operation, request_checksum=operation.request_checksum, reconciled=True)

    async def _load_operation_plan(
        self,
        operation_id: int,
    ) -> tuple[PermissionProjectionOperation, ProjectionPlan]:
        operation = await self._repository.aget_operation(operation_id)
        if operation is None:
            raise PermissionPublishNotReadyError(
                msg="Projection operation does not exist",
            )
        reject_department_maintenance(operation)
        if (
            getattr(self._repository, "_active_session", None) is not None
            and self._repository._active_session.get() is not None
        ):
            operation = await self._repository.alock_recovery_operation(operation_id)
        tuple_rows = await self._repository.aget_operation_tuples(operation_id)
        return operation, restore_projection_plan(operation, tuple_rows)

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
            pending_stage = await self._pending_stage_deltas(stage_deltas)
            for offset in range(0, len(pending_stage), self._stage_batch_size):
                batch = pending_stage[offset : offset + self._stage_batch_size]
                await self._write(batch)
                applied_stage.extend(batch)
            if stage_deltas and not await self._is_after(stage_deltas):
                raise RuntimeError("staged tuple verification did not observe full after state")
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
        if plan.scope_type == "department" and self._department_guard.get() is None:
            raise PermissionPublishNotReadyError(msg="Department projections require the Owner execution adapter")
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
        guard = self._department_guard.get()
        if guard is not None:
            await guard()
        write_gate = self._department_write_gate.get()
        if write_gate is not None:
            await write_gate()
        writes = tuple(delta for delta in deltas if delta.action == "WRITE")
        deletes = tuple(delta for delta in deltas if delta.action == "DELETE")
        return await self._fga.write_atomic(writes=writes, deletes=deletes)

    async def _pending_stage_deltas(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> tuple[ProjectionTupleDelta, ...]:
        """Return only STAGE mutations whose exact tuple is not already after."""

        if not deltas:
            return ()
        present = await self._fga.read_present(
            deltas,
            consistency=HIGHER_CONSISTENCY,
        )
        return tuple(delta for delta in deltas if (delta.key in present) != (delta.action == "WRITE"))

    async def _terminal_correction(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
    ) -> tuple[ProjectionTupleDelta, ...]:
        """Return one exact mutation for every tuple not at terminal AFTER."""

        expected = projection_state_expectations(deltas, after=True)
        representatives: dict[tuple[str, str, str], ProjectionTupleDelta] = {}
        for delta in deltas:
            representatives[delta.key] = delta
        present = await self._fga.read_present(
            tuple(representatives[key] for key in sorted(representatives)),
            consistency=HIGHER_CONSISTENCY,
        )
        correction: list[ProjectionTupleDelta] = []
        for sequence, (key, should_exist) in enumerate(sorted(expected.items())):
            if (key in present) == should_exist:
                continue
            correction.append(
                replace(
                    representatives[key],
                    phase="COMMIT",
                    sequence=sequence,
                    action="WRITE" if should_exist else "DELETE",
                )
            )
        return tuple(correction)

    @staticmethod
    def _recovery_confirmation_checksum(
        *,
        operation: PermissionProjectionOperation,
        correction: tuple[ProjectionTupleDelta, ...],
    ) -> str:
        payload = {
            "after_checksum": operation.after_checksum,
            "correction": [
                {
                    "action": delta.action,
                    "object": delta.object,
                    "relation": delta.relation,
                    "user": delta.user,
                }
                for delta in correction
            ],
            "operation_id": int(operation.id),
            "operation_status": str(operation.status),
            "request_checksum": operation.request_checksum,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()

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
            guard = self._department_guard.get()
            if guard is not None:
                await guard()
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
        if status in {"FAILED_CLOSED", "COMMIT_UNKNOWN", "MARKER_FAILED", "FAILED_CLOSED_RECOVERY_FAILED"}:
            emit_projection_alert(
                "FAILED",
                reason_code=reason_from_exception(error) if error else "UNKNOWN_WRITE_OUTCOME",
                tenant_id=plan.tenant_id,
                operation_id=operation.id,
                scope_type=plan.scope_type,
                scope_key=plan.scope_key,
                details={
                    "operation_status": status,
                    "expected_version": plan.expected_version,
                    "target_version": plan.target_version,
                    "store_id": plan.store_id,
                    "model_id": plan.model_id,
                    "phase": "projection_engine",
                    "commit_state": "not_proven",
                },
            )
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
