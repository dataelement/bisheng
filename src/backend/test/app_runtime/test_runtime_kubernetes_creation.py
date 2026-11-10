"""覆盖 AC: AC-13、AC-14、AC-48、AC-49、AC-52. Durable create rejection with real SQL."""

from datetime import timedelta
from uuid import uuid4

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation, RuntimeOperation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import ADMISSION, MANAGER, REF, register, short_hash
from test.app_runtime.test_runtime_kubernetes_service import control as control


async def observe(control, action, **detail):
    svc, _, _ = control
    return await svc.observe_resource(
        MANAGER, REF, {"action": action, "holder_id": "controller-a", "controller_epoch": 1, **detail}
    )


def evidence(**changes):
    return {
        "evidence_kind": "not_created",
        "namespace": "namespace-a",
        "name": "app-" + short_hash("app-a"),
        "observed_at": NOW.isoformat() + "Z",
        "api_status": 404,
        **changes,
    }


async def begin(control):
    await register(control)
    attempt = str(uuid4())
    await observe(control, "create_begin", create_attempt_id=attempt)
    return attempt


@pytest.mark.parametrize("attempted", [False, True])
async def test_new_fenced_absence_is_not_same_uid_stop(control, attempted):
    svc, repository, op = control
    await register(control)
    assert not (await svc.admission_plan(ADMISSION, REF))["allow_create"]
    if attempted:
        attempt = str(uuid4())
        row = await observe(control, "create_begin", create_attempt_id=attempt)
        assert row["observed_state"]["creation"]["state"] == "started"
        assert (await svc.admission_plan(ADMISSION, REF))["allow_create"]
        await observe(control, "create_rejected", create_attempt_id=attempt, http_status=403)
    row = await observe(control, "create_fence")
    assert row["observed_state"]["creation"]["state"] == "fenced"
    assert not (await svc.admission_plan(ADMISSION, REF))["allow_create"]
    op = await repository.get(RuntimeOperation, op.id)
    op.status = "failed"
    await repository.save(op)
    row = await observe(control, "not_created", evidence=evidence())
    assert row["uid"] is None and row["stop_state"] == "confirmed"
    assert row["stop_evidence"]["evidence_kind"] == "not_created"
    assert row["observed_state"]["creation"]["state"] == "not_created"
    assert (await observe(control, "cleanup", uid=None))["cleanup_state"] == "complete"
    assert (await observe(control, "not_created", evidence=evidence()))["stop_state"] == "confirmed"
    assert (await repository.find(RuntimeCapacityReservation, operation_id=op.id))[0].state == "released"


async def test_unknown_started_and_legacy_cannot_be_closed_by_404(control):
    _, repository, _ = control
    await begin(control)
    for action, detail in [("create_fence", {}), ("not_created", {"evidence": evidence()}), ("cleanup", {"uid": None})]:
        with pytest.raises(RuntimeConflict):
            await observe(control, action, **detail)
    row = await repository.get(RuntimeExecutionResource, REF)
    row.observed_state = {}
    await repository.save(row)
    for action, detail in [("create_fence", {}), ("create_begin", {"create_attempt_id": str(uuid4())})]:
        with pytest.raises(RuntimeConflict):
            await observe(control, action, **detail)


async def test_begin_is_single_use_even_after_explicit_rejection(control):
    attempt = await begin(control)
    for value in [attempt, str(uuid4())]:
        with pytest.raises(RuntimeConflict):
            await observe(control, "create_begin", create_attempt_id=value)
    await observe(control, "create_rejected", create_attempt_id=attempt, http_status=403)
    await observe(control, "create_fence")
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_begin", create_attempt_id=str(uuid4()))


@pytest.mark.parametrize("status", [True, 400, 401, 409, 429, 500, 503, "403", None])
async def test_only_403_ends_a_started_attempt(control, status):
    attempt = await begin(control)
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_rejected", create_attempt_id=attempt, http_status=status)
    assert (await observe(control, "stop"))["stop_state"] != "confirmed"


async def test_wrong_attempt_or_bound_uid_cannot_be_not_created(control):
    attempt = await begin(control)
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_rejected", create_attempt_id=str(uuid4()), http_status=403)
    await observe(control, "bind", uid=UID, node_name="worker-a")
    for action, detail in [
        ("create_rejected", {"create_attempt_id": attempt, "http_status": 403}),
        ("create_fence", {}),
        ("not_created", {"evidence": evidence()}),
    ]:
        with pytest.raises(RuntimeConflict):
            await observe(control, action, **detail)


@pytest.mark.parametrize(
    "change",
    [
        {"namespace": "foreign"},
        {"name": "foreign"},
        {"api_status": 403},
        {"api_status": True},
        {"evidence_kind": "never_scheduled"},
        {"uid": UID},
        {"observed_at": (NOW - timedelta(minutes=2)).isoformat() + "Z"},
        {"observed_at": (NOW + timedelta(minutes=2)).isoformat() + "Z"},
    ],
)
async def test_proof_needs_exact_fenced_scope_and_fresh_404(control, change):
    await register(control)
    await observe(control, "create_fence")
    with pytest.raises(RuntimeConflict):
        await observe(control, "not_created", evidence=evidence(**change))
    assert (await observe(control, "create_fence"))["stop_state"] != "confirmed"


async def test_normal_stopped_still_requires_uid_and_late_binding_is_refused(control):
    await register(control)
    await observe(control, "create_fence")
    with pytest.raises(RuntimeConflict, match="stop_uid"):
        await observe(control, "stopped", evidence=evidence())
    await observe(control, "not_created", evidence=evidence())
    with pytest.raises(RuntimeConflict):
        await observe(control, "bind", uid=UID, node_name="worker-a")


@pytest.mark.parametrize("change", [{"holder_id": "foreign"}, {"controller_epoch": 2}])
async def test_creation_respects_controller_cas(control, change):
    await register(control)
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_begin", create_attempt_id=str(uuid4()), **change)


async def test_creation_fields_cannot_be_smuggled_into_bind(control):
    await register(control)
    with pytest.raises(RuntimeConflict):
        await observe(control, "bind", uid=UID, node_name="worker-a", create_attempt_id=str(uuid4()))


async def test_rejected_receipt_survives_restart_but_late_old_epoch_response_does_not(control):
    svc, repository, _ = control
    attempt = await begin(control)
    await observe(control, "create_rejected", create_attempt_id=attempt, http_status=403)
    later = NOW + timedelta(seconds=31)
    await repository.claim_controller("node-a", holder_id="controller-b", expected_epoch=1, now=later)
    svc.clock = lambda: later
    auth = {"holder_id": "controller-b", "controller_epoch": 2}
    await observe(control, "create_fence", **auth)
    row = await observe(control, "not_created", evidence=evidence(observed_at=later.isoformat() + "Z"), **auth)
    assert row["stop_state"] == "confirmed" and row["uid"] is None


async def test_new_epoch_cannot_turn_an_unknown_old_attempt_into_rejected(control):
    svc, repository, _ = control
    attempt = await begin(control)
    later = NOW + timedelta(seconds=31)
    await repository.claim_controller("node-a", holder_id="controller-b", expected_epoch=1, now=later)
    svc.clock = lambda: later
    auth = {"holder_id": "controller-b", "controller_epoch": 2}
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_rejected", create_attempt_id=attempt, http_status=403, **auth)
    with pytest.raises(RuntimeConflict):
        await observe(control, "create_fence", **auth)
    assert (await repository.get(RuntimeExecutionResource, REF)).observed_state["creation"]["state"] == "started"


async def test_one_unknown_writer_keeps_capacity_despite_another_not_created_proof(control):
    from test.app_runtime.test_runtime_kubernetes_repository import resource

    _, repository, op = control
    await register(control)
    other = await repository.create_resource_intent(
        resource(op, name="second-position", purpose="probe"), holder_id="controller-a", controller_epoch=1, now=NOW
    )
    await repository.observe_resource_creation(
        other.id,
        action="create_begin",
        create_attempt_id=str(uuid4()),
        holder_id="controller-a",
        controller_epoch=1,
        now=NOW,
    )
    await observe(control, "create_fence")
    op = await repository.get(RuntimeOperation, op.id)
    op.status = "failed"
    await repository.save(op)
    await observe(control, "not_created", evidence=evidence())
    assert (await repository.find(RuntimeCapacityReservation, operation_id=op.id))[0].state == "held"
    with pytest.raises(RuntimeConflict):
        await repository.release_resources(op.id)
