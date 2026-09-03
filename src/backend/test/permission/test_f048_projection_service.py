"""Durable F048 projection-ledger contracts.

覆盖 AC: AC-15, AC-16, AC-54, AC-66, AC-67, AC-68, AC-69, AC-70,
AC-143, AC-164, AC-166, AC-167, AC-170
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from bisheng.common.errcode.permission import (
    PermissionMutationTooLargeError,
    PermissionProjectionFailedError,
    PermissionPublishNotReadyError,
    PermissionVersionConflictError,
)
from bisheng.permission.domain.models import ProjectionOperationStatus
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.projection_plan import (
    projection_state_expectations,
)
from bisheng.permission.domain.services.projection_service import (
    ProjectionCommitUnknownError,
    ProjectionPlan,
    ProjectionService,
    ProjectionTupleDelta,
)
from bisheng.permission.domain.services.resource_lifecycle_policy import (
    build_move_plan,
)


def _key(delta: ProjectionTupleDelta) -> tuple[str, str, str]:
    return (delta.user, delta.relation, delta.object)


class FakeProjectionRepository:
    def __init__(self) -> None:
        self.operation = None
        self.tuples = []
        self.next_id = 1
        self.log: list[str] = []

    async def aget_operation_by_idempotency(
        self,
        idempotency_key: str,
        *,
        for_update: bool = False,
    ):
        if self.operation and self.operation.idempotency_key == idempotency_key:
            return self.operation
        return None

    async def aget_operation(self, operation_id: int):
        if self.operation and self.operation.id == operation_id:
            return self.operation
        return None

    async def acreate_operation(self, operation, tuples):
        self.log.append("prepare")
        if self.operation is not None:
            if self.operation.request_checksum != operation.request_checksum:
                raise PermissionVersionConflictError()
            return self.operation
        operation.id = self.next_id
        self.next_id += 1
        for row in tuples:
            row.operation_id = operation.id
        self.operation = operation
        self.tuples = tuples
        return operation

    async def aupdate_operation_status_cas(
        self,
        *,
        operation_id: int,
        expected_status: str,
        target_status: str,
        commit_checksum: str | None = None,
        error_code: int | None = None,
        error_message: str | None = None,
    ) -> bool:
        if self.operation.id != operation_id or self.operation.status != expected_status:
            return False
        self.log.append(target_status)
        self.operation.status = target_status
        if commit_checksum is not None:
            self.operation.commit_checksum = commit_checksum
        self.operation.error_code = error_code
        self.operation.error_message = error_message
        return True

    async def aget_operation_tuples(self, operation_id: int):
        assert operation_id == self.operation.id
        return self.tuples


class FakeRecentMarker:
    def __init__(self) -> None:
        self.ready = True
        self.fail_arm = False
        self.log: list[str] = []

    async def is_ready(self) -> bool:
        return self.ready

    async def arm(self, plan: ProjectionPlan) -> None:
        self.log.append("recent")
        if self.fail_arm:
            raise RuntimeError("redis unavailable")


class FakeScopeGuard:
    def __init__(self) -> None:
        self.current = True
        self.fenced = False
        self.recoverable = True
        self.reserve_error: Exception | None = None
        self.reservations: list[tuple[str, int]] = []

    async def reserve(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> None:
        self.reservations.append((plan.idempotency_key, operation_id))
        if self.reserve_error is not None:
            raise self.reserve_error

    async def is_expected_version(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool:
        assert operation_id > 0
        return self.current

    async def is_failed_closed_recovery_scope(
        self,
        plan: ProjectionPlan,
        operation_id: int,
    ) -> bool:
        assert plan.scope_type == "resource"
        assert operation_id > 0
        return self.recoverable

    async def fail_closed(self, plan: ProjectionPlan, reason: str) -> None:
        assert reason
        self.fenced = True


class FakeFGAProjection:
    def __init__(self, initial: set[tuple[str, str, str]]) -> None:
        self.present = set(initial)
        self.calls: list[tuple[tuple, tuple]] = []
        self.fail_call: int | None = None
        self.timeout_mode: str | None = None
        self.timeout_call: int | None = None
        self.reject_existing_writes = False

    async def write_atomic(self, *, writes: tuple, deletes: tuple) -> str:
        self.calls.append((writes, deletes))
        call_number = len(self.calls)
        if self.fail_call == call_number:
            raise RuntimeError("definite stage failure")
        if self.reject_existing_writes and any(_key(row) in self.present for row in writes):
            raise RuntimeError("cannot write a tuple which already exists")
        if self.timeout_mode is not None and (self.timeout_call is None or self.timeout_call == call_number):
            mode = self.timeout_mode
            self.timeout_mode = None
            if mode == "after":
                self.present.difference_update(_key(row) for row in deletes)
                self.present.update(_key(row) for row in writes)
            elif mode == "mixed":
                if writes:
                    self.present.add(_key(writes[0]))
            raise ProjectionCommitUnknownError("OpenFGA timeout")
        self.present.difference_update(_key(row) for row in deletes)
        self.present.update(_key(row) for row in writes)
        return "c" * 64

    async def read_present(
        self,
        deltas: tuple[ProjectionTupleDelta, ...],
        *,
        consistency: str,
    ) -> frozenset[tuple[str, str, str]]:
        assert consistency == "HIGHER_CONSISTENCY"
        keys = {_key(delta) for delta in deltas}
        return frozenset(keys & self.present)


class FakeFinalizer:
    def __init__(self) -> None:
        self.calls = 0

    async def finalize(self, plan: ProjectionPlan, operation_id: int) -> None:
        self.calls += 1


class FakeEvents:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []

    async def emit(self, name: str, fields: dict) -> None:
        self.rows.append((name, fields))


def _delta(
    sequence: int,
    *,
    action: str = "WRITE",
    phase: str = "COMMIT",
) -> ProjectionTupleDelta:
    return ProjectionTupleDelta(
        phase=phase,
        sequence=sequence,
        action=action,
        user=f"user:{sequence}",
        relation="assignee",
        object="permission_grant:1",
    )


def _plan(
    *deltas: ProjectionTupleDelta,
    idempotency_key: str = "op-1",
    change_item_count: int = 1,
) -> ProjectionPlan:
    return ProjectionPlan(
        tenant_id=7,
        idempotency_key=idempotency_key,
        operation_type="GRANT_MUTATION",
        scope_type="resource",
        scope_key="workflow:42",
        expected_version=3,
        target_version=4,
        store_id="store",
        model_id="model",
        operator_id=9,
        change_item_count=change_item_count,
        deltas=tuple(deltas or (_delta(1),)),
    )


def _move_plan() -> ProjectionPlan:
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_file",
        resource_id="42",
        resource_version=3,
        parent_type="folder",
        parent_id="20",
        context_version="ctx-3",
    )
    return build_move_plan(
        target,
        old_parent=("knowledge_space", "10"),
        new_parent=("folder", "20"),
        mode="INHERIT",
        store_id="store",
        model_id="model",
        operator_id=9,
        idempotency_key="move-42",
    )


def _service(plan: ProjectionPlan):
    initial = {_key(delta) for delta in plan.deltas if delta.action == "DELETE"}
    repository = FakeProjectionRepository()
    marker = FakeRecentMarker()
    scope = FakeScopeGuard()
    fga = FakeFGAProjection(initial)
    finalizer = FakeFinalizer()
    events = FakeEvents()
    service = ProjectionService(
        repository=repository,
        marker=marker,
        scope_guard=scope,
        fga=fga,
        finalizer=finalizer,
        events=events,
        stage_batch_size=1,
    )
    return service, repository, marker, scope, fga, finalizer, events


@pytest.mark.asyncio
async def test_prepare_stage_recent_commit_verify_and_finalize_order() -> None:
    plan = _plan(_delta(1, phase="STAGE"), _delta(2))
    service, repository, marker, scope, fga, finalizer, events = _service(plan)
    outcome = await service.execute(plan)
    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert repository.log == [
        "prepare",
        "STAGING",
        "COMMITTED",
        "FINALIZED",
    ]
    assert marker.log == ["recent"]
    assert len(fga.calls) == 2
    assert scope.reservations == [("op-1", outcome.operation_id)]
    assert finalizer.calls == 1
    assert scope.fenced is False
    assert events.rows[-1][0] == "permission_projection"


@pytest.mark.asyncio
async def test_action_and_single_slot_visible_are_one_atomic_commit() -> None:
    plan = _plan(
        ProjectionTupleDelta(
            phase="COMMIT",
            sequence=0,
            action="WRITE",
            user="user:100",
            relation="ordinary_assignee",
            object="permission_grant:g-viewer",
        ),
        ProjectionTupleDelta(
            phase="COMMIT",
            sequence=1,
            action="WRITE",
            user="user:100",
            relation="visible",
            object="workflow:42",
        ),
    )
    service, repository, marker, scope, fga, finalizer, _ = _service(plan)

    outcome = await service.execute(plan)

    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert marker.log == ["recent"]
    assert scope.fenced is False
    assert finalizer.calls == 1
    assert len(fga.calls) == 1
    writes, deletes = fga.calls[0]
    assert deletes == ()
    assert {row.relation for row in writes} == {
        "ordinary_assignee",
        "visible",
    }
    assert all("slot" not in row.relation and not row.relation.endswith(("_a", "_b")) for row in writes)


@pytest.mark.asyncio
async def test_move_plan_verifies_final_state_when_enabled_is_restored() -> None:
    plan = _move_plan()
    service, repository, _, scope, fga, finalizer, _ = _service(plan)

    outcome = await service.execute(plan)

    enabled = ("user:*", "permission_enabled", "knowledge_file:42")
    old_parent = ("knowledge_space:10", "parent", "knowledge_file:42")
    new_parent = ("folder:20", "parent", "knowledge_file:42")
    before = projection_state_expectations(plan.deltas, after=False)
    after = projection_state_expectations(plan.deltas, after=True)
    assert before[enabled] is True
    assert after[enabled] is True
    assert before[old_parent] is True
    assert after[old_parent] is False
    assert before[new_parent] is False
    assert after[new_parent] is True
    assert fga.present == {enabled, new_parent}
    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert finalizer.calls == 1
    assert scope.fenced is False


@pytest.mark.asyncio
async def test_idempotency_checksum_reuses_final_result_and_rejects_collision() -> None:
    plan = _plan(_delta(1))
    service, repository, _, _, fga, _, _ = _service(plan)
    first = await service.execute(plan)
    second = await service.execute(plan)
    assert first.operation_id == second.operation_id
    assert second.idempotent is True
    assert len(fga.calls) == 1

    collision = replace(plan, deltas=(_delta(2),))
    with pytest.raises(PermissionVersionConflictError):
        await service.execute(collision)
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED


@pytest.mark.asyncio
async def test_marker_not_ready_or_arm_failure_never_writes_openfga() -> None:
    plan = _plan(_delta(1))
    service, repository, marker, _, fga, _, _ = _service(plan)
    marker.ready = False
    with pytest.raises(PermissionPublishNotReadyError):
        await service.execute(plan)
    assert repository.operation is None
    assert fga.calls == []

    marker.ready = True
    marker.fail_arm = True
    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)
    assert repository.operation.status == ProjectionOperationStatus.PREPARED
    assert fga.calls == []


@pytest.mark.asyncio
async def test_durable_operation_can_be_rebuilt_and_resumed_by_id() -> None:
    plan = _plan(
        _delta(1, phase="STAGE"),
        _delta(2),
        change_item_count=17,
    )
    service, repository, marker, _, fga, finalizer, _ = _service(plan)
    marker.fail_arm = True

    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)

    marker.fail_arm = False
    outcome = await service.reconcile_operation(
        int(repository.operation.id),
    )

    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert len(fga.calls) == 2
    assert finalizer.calls == 1


@pytest.mark.asyncio
async def test_prepared_reconcile_reuses_existing_stage_tuples_and_writes_only_missing() -> None:
    first_stage = _delta(1, phase="STAGE")
    missing_stage = _delta(2, phase="STAGE")
    commit = _delta(3)
    plan = _plan(
        first_stage,
        missing_stage,
        commit,
        change_item_count=3,
    )
    service, repository, _, _, fga, finalizer, _ = _service(plan)
    operation = await service.prepare(plan)
    fga.present.add(_key(first_stage))
    fga.reject_existing_writes = True

    outcome = await service.reconcile_operation(int(operation.id))

    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert len(fga.calls) == 2
    stage_writes, stage_deletes = fga.calls[0]
    assert tuple(_key(row) for row in stage_writes) == (_key(missing_stage),)
    assert stage_deletes == ()
    assert finalizer.calls == 1


@pytest.mark.asyncio
async def test_scope_reservation_failure_precedes_marker_and_openfga() -> None:
    plan = _plan(_delta(1))
    service, repository, marker, scope, fga, _, _ = _service(plan)
    scope.reserve_error = PermissionVersionConflictError(msg="competing department mutation")

    with pytest.raises(PermissionVersionConflictError):
        await service.execute(plan)

    assert scope.reservations == [("op-1", 1)]
    assert marker.log == []
    assert fga.calls == []
    assert repository.operation.status == ProjectionOperationStatus.FAILED_CLOSED


@pytest.mark.asyncio
async def test_commit_timeout_after_write_is_confirmed_and_finalized() -> None:
    plan = _plan(_delta(1))
    service, repository, _, _, fga, finalizer, _ = _service(plan)
    fga.timeout_mode = "after"
    outcome = await service.execute(plan)
    assert outcome.reconciled is True
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert finalizer.calls == 1
    assert len(fga.calls) == 1


@pytest.mark.asyncio
async def test_move_commit_timeout_after_write_observes_terminal_state() -> None:
    plan = _move_plan()
    service, repository, _, scope, fga, finalizer, _ = _service(plan)
    fga.timeout_mode = "after"
    fga.timeout_call = 2

    outcome = await service.execute(plan)

    assert outcome.reconciled is True
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert finalizer.calls == 1
    assert len(fga.calls) == 2
    assert scope.fenced is False


@pytest.mark.asyncio
async def test_commit_timeout_before_write_retries_only_when_version_is_current() -> None:
    plan = _plan(_delta(1))
    service, repository, _, _scope, fga, _, _ = _service(plan)
    fga.timeout_mode = "before"
    outcome = await service.execute(plan)
    assert outcome.reconciled is True
    assert len(fga.calls) == 2
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED

    service2, repository2, _, scope2, fga2, _, _ = _service(plan)
    fga2.timeout_mode = "before"
    scope2.current = False
    with pytest.raises(PermissionProjectionFailedError):
        await service2.execute(plan)
    assert repository2.operation.status == ProjectionOperationStatus.FAILED_CLOSED
    assert scope2.fenced is True


@pytest.mark.asyncio
async def test_move_commit_timeout_before_write_retries_from_staged_state() -> None:
    plan = _move_plan()
    service, repository, marker, scope, fga, finalizer, _ = _service(plan)
    fga.timeout_mode = "before"
    fga.timeout_call = 2

    outcome = await service.execute(plan)

    assert outcome.reconciled is True
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    assert finalizer.calls == 1
    assert len(fga.calls) == 3
    assert marker.log == ["recent", "recent"]
    assert scope.fenced is False


@pytest.mark.asyncio
async def test_mixed_commit_result_is_failed_closed() -> None:
    plan = _plan(_delta(1), _delta(2))
    service, repository, _, scope, fga, _, _ = _service(plan)
    fga.timeout_mode = "mixed"
    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)
    assert repository.operation.status == ProjectionOperationStatus.FAILED_CLOSED
    assert scope.fenced is True


@pytest.mark.asyncio
async def test_failed_closed_recovery_writes_only_terminal_difference() -> None:
    new_manager = ProjectionTupleDelta(
        phase="COMMIT",
        sequence=0,
        action="WRITE",
        user="user:841",
        relation="ordinary_assignee",
        object="permission_grant:g-manager",
    )
    old_editor = ProjectionTupleDelta(
        phase="COMMIT",
        sequence=1,
        action="DELETE",
        user="user:841",
        relation="ordinary_assignee",
        object="permission_grant:g-editor",
    )
    existing_visible = ProjectionTupleDelta(
        phase="COMMIT",
        sequence=2,
        action="WRITE",
        user="user:841",
        relation="visible",
        object="knowledge_space:4166",
    )
    plan = _plan(
        new_manager,
        old_editor,
        existing_visible,
        idempotency_key="recover-4166",
        change_item_count=1,
    )
    service, repository, _, _, fga, finalizer, _ = _service(plan)
    fga.present.add(_key(existing_visible))
    fga.timeout_mode = "before"

    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)
    assert repository.operation.status == ProjectionOperationStatus.FAILED_CLOSED

    preview = await service.inspect_failed_closed_recovery(int(repository.operation.id))
    assert preview.scope_key == "workflow:42"
    assert preview.observed_state == "MIXED"
    assert {_key(row) for row in preview.correction_deltas} == {
        _key(new_manager),
        _key(old_editor),
    }

    fga.reject_existing_writes = True
    outcome = await service.recover_failed_closed_operation(
        int(repository.operation.id),
        confirmation_checksum=preview.confirmation_checksum,
    )

    assert outcome.status == ProjectionOperationStatus.FINALIZED
    assert repository.operation.status == ProjectionOperationStatus.FINALIZED
    writes, deletes = fga.calls[-1]
    assert tuple(_key(row) for row in writes) == (_key(new_manager),)
    assert tuple(_key(row) for row in deletes) == (_key(old_editor),)
    assert _key(existing_visible) in fga.present
    assert finalizer.calls == 1


@pytest.mark.asyncio
async def test_failed_closed_recovery_rejects_stale_confirmation() -> None:
    plan = _plan(_delta(1), _delta(2))
    service, repository, _, _, fga, _, _ = _service(plan)
    fga.timeout_mode = "mixed"
    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)

    preview = await service.inspect_failed_closed_recovery(int(repository.operation.id))
    fga.present.add(_key(_delta(2)))

    with pytest.raises(PermissionVersionConflictError, match="confirmation checksum"):
        await service.recover_failed_closed_operation(
            int(repository.operation.id),
            confirmation_checksum=preview.confirmation_checksum,
        )

    assert repository.operation.status == ProjectionOperationStatus.FAILED_CLOSED


@pytest.mark.asyncio
async def test_definite_stage_failure_applies_inverse_compensation() -> None:
    plan = _plan(
        _delta(1, phase="STAGE"),
        _delta(2, phase="STAGE"),
        _delta(3),
    )
    service, repository, _, scope, fga, _, _ = _service(plan)
    fga.fail_call = 2
    with pytest.raises(PermissionProjectionFailedError):
        await service.execute(plan)
    assert len(fga.calls) == 3
    inverse_writes, inverse_deletes = fga.calls[-1]
    assert inverse_writes == ()
    assert [_key(row) for row in inverse_deletes] == [_key(_delta(1))]
    assert repository.operation.status == ProjectionOperationStatus.PREPARED
    assert scope.fenced is False


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [50])
async def test_change_item_limit_accepts_fifty(count: int) -> None:
    plan = _plan(_delta(1), change_item_count=count)
    service, _, _, _, _, _, _ = _service(plan)
    await service.execute(plan)


@pytest.mark.asyncio
async def test_change_item_limit_rejects_fifty_one() -> None:
    plan = _plan(_delta(1), change_item_count=51)
    service, repository, _, _, _, _, _ = _service(plan)
    with pytest.raises(PermissionMutationTooLargeError):
        await service.execute(plan)
    assert repository.operation is None


@pytest.mark.asyncio
async def test_atomic_tuple_limit_accepts_ninety_and_rejects_ninety_one() -> None:
    accepted = _plan(*(_delta(index) for index in range(1, 91)))
    service, _, _, _, fga, _, _ = _service(accepted)
    await service.execute(accepted)
    assert len(fga.calls[0][0]) == 90

    rejected = _plan(*(_delta(index) for index in range(1, 92)))
    service2, repository2, _, _, _, _, _ = _service(rejected)
    with pytest.raises(PermissionMutationTooLargeError):
        await service2.execute(rejected)
    assert repository2.operation is None
