"""Pure compilation of F048 projection plans into durable ledger rows."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256

from bisheng.common.errcode.permission import PermissionMutationTooLargeError
from bisheng.permission.domain.models import (
    PermissionProjectionOperation,
    PermissionProjectionTuple,
    ProjectionOperationStatus,
    ProjectionTupleStatus,
)

MAX_CHANGE_ITEMS = 50
MAX_ATOMIC_TUPLES = 90
HIGHER_CONSISTENCY = "HIGHER_CONSISTENCY"
_PHASE_ORDER = {"STAGE": 0, "COMMIT": 1}


class ProjectionCommitUnknownError(RuntimeError):
    """The OpenFGA atomic write outcome cannot be inferred from transport."""


@dataclass(frozen=True, slots=True)
class ProjectionTupleDelta:
    phase: str
    sequence: int
    action: str
    user: str
    relation: str
    object: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.user, self.relation, self.object)


@dataclass(frozen=True, slots=True)
class ProjectionPlan:
    tenant_id: int
    idempotency_key: str
    operation_type: str
    scope_type: str
    scope_key: str
    expected_version: int
    target_version: int
    store_id: str
    model_id: str
    operator_id: int
    change_item_count: int
    deltas: tuple[ProjectionTupleDelta, ...]


@dataclass(frozen=True, slots=True)
class ProjectionOutcome:
    operation_id: int
    target_version: int
    status: str
    request_checksum: str
    idempotent: bool = False
    reconciled: bool = False


def projection_state_expectations(
    deltas: tuple[ProjectionTupleDelta, ...],
    *,
    after: bool,
) -> dict[tuple[str, str, str], bool]:
    """Resolve one observable tuple state from a multi-phase projection plan.

    A tuple may be changed in both phases, for example resource moves temporarily
    delete ``permission_enabled`` during STAGE and restore it during COMMIT. The
    state before the operation is therefore defined by the first action for each
    tuple key, while the state after the operation is defined by its final action.
    """

    ordered = sorted(
        deltas,
        key=lambda row: (
            _PHASE_ORDER.get(row.phase.upper(), len(_PHASE_ORDER)),
            row.sequence,
            row.user,
            row.relation,
            row.object,
            row.action,
        ),
    )
    expected: dict[tuple[str, str, str], bool] = {}
    for delta in ordered:
        if after:
            expected[delta.key] = delta.action.upper() == "WRITE"
        elif delta.key not in expected:
            expected[delta.key] = delta.action.upper() == "DELETE"
    return dict(sorted(expected.items()))


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def normalize_projection_plan(plan: ProjectionPlan) -> ProjectionPlan:
    if plan.tenant_id <= 0:
        raise ValueError("projection tenant_id must be positive")
    if not plan.idempotency_key.strip():
        raise ValueError("projection idempotency_key must not be empty")
    if plan.change_item_count < 0 or plan.change_item_count > MAX_CHANGE_ITEMS:
        raise PermissionMutationTooLargeError(msg=f"Projection accepts at most {MAX_CHANGE_ITEMS} change items")
    if not plan.deltas:
        raise ValueError("projection plan must contain tuple deltas")

    by_phase_key: dict[
        tuple[str, tuple[str, str, str]],
        ProjectionTupleDelta,
    ] = {}
    for delta in plan.deltas:
        phase = delta.phase.upper()
        action = delta.action.upper()
        if phase not in {"STAGE", "COMMIT"}:
            raise ValueError(f"unsupported projection phase: {delta.phase}")
        if action not in {"WRITE", "DELETE"}:
            raise ValueError(f"unsupported tuple action: {delta.action}")
        if delta.sequence < 0:
            raise ValueError("projection tuple sequence must be non-negative")
        if not delta.user or not delta.relation or not delta.object:
            raise ValueError("projection tuple identity must be complete")
        normalized = replace(delta, phase=phase, action=action)
        identity = (phase, normalized.key)
        previous = by_phase_key.get(identity)
        if previous is not None and previous.action != action:
            raise ValueError("projection plan contains conflicting actions for one tuple")
        if previous is None or normalized.sequence < previous.sequence:
            by_phase_key[identity] = normalized

    deltas = tuple(
        sorted(
            by_phase_key.values(),
            key=lambda row: (
                _PHASE_ORDER[row.phase],
                row.sequence,
                row.user,
                row.relation,
                row.object,
                row.action,
            ),
        )
    )
    commit_count = sum(delta.phase == "COMMIT" for delta in deltas)
    if commit_count > MAX_ATOMIC_TUPLES:
        raise PermissionMutationTooLargeError(msg=f"Projection atomic commit exceeds {MAX_ATOMIC_TUPLES} tuples")
    if commit_count == 0:
        raise ValueError("projection plan requires an atomic COMMIT phase")
    return replace(plan, deltas=deltas)


def projection_request_checksum(plan: ProjectionPlan) -> str:
    return _checksum(
        {
            "change_item_count": plan.change_item_count,
            "deltas": [
                {
                    "action": delta.action,
                    "object": delta.object,
                    "phase": delta.phase,
                    "relation": delta.relation,
                    "sequence": delta.sequence,
                    "user": delta.user,
                }
                for delta in plan.deltas
            ],
            "expected_version": plan.expected_version,
            "idempotency_key": plan.idempotency_key,
            "model_id": plan.model_id,
            "operation_type": plan.operation_type,
            "operator_id": plan.operator_id,
            "scope_key": plan.scope_key,
            "scope_type": plan.scope_type,
            "store_id": plan.store_id,
            "target_version": plan.target_version,
            "tenant_id": plan.tenant_id,
        }
    )


def _state_checksum(
    deltas: tuple[ProjectionTupleDelta, ...],
    *,
    after: bool,
) -> str:
    expected = projection_state_expectations(deltas, after=after)
    return _checksum(
        [
            {
                "key": key,
                "present": present,
            }
            for key, present in expected.items()
        ]
    )


def build_projection_operation(
    plan: ProjectionPlan,
    *,
    request_checksum: str,
) -> tuple[PermissionProjectionOperation, list[PermissionProjectionTuple]]:
    operation = PermissionProjectionOperation(
        tenant_id=plan.tenant_id,
        idempotency_key=plan.idempotency_key,
        request_checksum=request_checksum,
        operation_type=plan.operation_type,
        scope_type=plan.scope_type,
        scope_key=plan.scope_key,
        expected_version=plan.expected_version,
        target_version=plan.target_version,
        store_id=plan.store_id,
        model_id=plan.model_id,
        status=ProjectionOperationStatus.PREPARED.value,
        before_checksum=_state_checksum(plan.deltas, after=False),
        after_checksum=_state_checksum(plan.deltas, after=True),
        operator_id=plan.operator_id,
    )
    rows = [
        PermissionProjectionTuple(
            tenant_id=plan.tenant_id,
            phase=delta.phase,
            sequence=delta.sequence,
            action=delta.action,
            fga_user=delta.user,
            relation=delta.relation,
            fga_object=delta.object,
            tuple_fingerprint=_checksum(
                {
                    "object": delta.object,
                    "relation": delta.relation,
                    "user": delta.user,
                }
            ),
            inverse_action=("DELETE" if delta.action == "WRITE" else "WRITE"),
            status=ProjectionTupleStatus.PENDING.value,
        )
        for delta in plan.deltas
    ]
    return operation, rows
