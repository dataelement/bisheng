"""F059 AC-07、AC-30、AC-31、AC-35、AC-40、AC-48、AC-49、AC-52、AC-55.

Real SQLite heartbeat/resource transitions; no mocked protection services or cluster.
"""

import copy
from datetime import timedelta

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeCapacityReservation, RuntimeNode, RuntimeOperation
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_kubernetes_coordination import coordination as coordination
from test.app_runtime.test_runtime_kubernetes_coordination import heartbeat, prepare_document
from test.app_runtime.test_runtime_kubernetes_repository import NOW, UID, evidence
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import MANAGER, REF
from test.app_runtime.test_runtime_kubernetes_service import control as control

BASELINE = "a" * 64
OTHER_BASELINE = "b" * 64
UNSET = object()


def report(state="current", *, digest=BASELINE, observation=UNSET):
    body = heartbeat()
    body.capabilities["protection_observation"] = (
        {"version": 1, "baseline_digest": digest, "state": state} if observation is UNSET else observation
    )
    if state != "current":
        body.probe_report["ready"] = False
        body.capabilities.update(status_protection=False, binding_protection=False)
    return body


async def bound(c, *, node_name="worker-a", adopt=True):
    if adopt:
        await c.svc.heartbeat(MANAGER, report())
    await c.control.register_resource(MANAGER, prepare_document(c.op))
    await c.control.observe_resource(
        MANAGER,
        REF,
        {"action": "bind", "uid": UID, "node_name": node_name, "holder_id": "controller-a", "controller_epoch": 1},
    )
    row = await c.repo.get(RuntimeExecutionResource, REF)
    assert row.protected_since_creation is True and row.binding_policy_verified is True
    return row


async def flags(c):
    row = await c.repo.get(RuntimeExecutionResource, REF)
    return row.protected_since_creation, row.binding_policy_verified


async def node(c):
    return await c.repo.get(RuntimeNode, c.op.node_id)


async def stop_request(c):
    return await c.repo.request_resource_stop(
        REF, operation_id=c.op.id, holder_id="controller-a", controller_epoch=1, now=NOW
    )


def proof(row, kind):
    return {**evidence(node_name=row.node_name, kind=kind), "namespace": row.namespace, "name": row.name}


async def confirm(c, row, kind):
    return await c.repo.confirm_resource_stop(
        REF, proof(row, kind), holder_id="controller-a", controller_epoch=1, now=NOW + timedelta(seconds=2)
    )


async def assert_held(c):
    row = await c.repo.get(RuntimeExecutionResource, REF)
    assert row.stop_state != "confirmed" and row.cleanup_state != "complete" and row.stop_evidence == {}
    assert (await c.repo.find(RuntimeCapacityReservation, operation_id=c.op.id))[0].state == "held"
    with pytest.raises(RuntimeConflict, match="stopped"):
        await c.repo.release_resources(c.op.id)


async def test_current_bootstraps_server_baseline_without_rewriting_legacy_history(coordination):
    c = coordination
    await bound(c, adopt=False)
    await c.svc.heartbeat(MANAGER, report())
    current = await node(c)
    assert current.status == "ready"
    assert current.capabilities["protection_contract_version"] == 1
    assert current.capabilities["protection_baseline_digest"] == BASELINE
    assert await flags(c) == (True, True)


async def test_legacy_positive_client_remains_compatible_without_new_markers(coordination):
    c = coordination
    await bound(c, adopt=False)
    await c.svc.heartbeat(MANAGER, heartbeat())
    current = await node(c)
    assert current.status == "ready" and await flags(c) == (True, True)
    assert "protection_contract_version" not in current.capabilities


@pytest.mark.parametrize("state", ["report_expired", "helper_changed"])
async def test_report_only_unknown_retains_same_baseline_history_but_blocks_current(coordination, state):
    c = coordination
    await bound(c)
    body = report(state)
    if state == "helper_changed":
        body.capabilities["helper_image"] = "example.invalid/new-helper@sha256:" + "d" * 64
    for _ in range(2):
        await c.svc.heartbeat(MANAGER, body)
        current = await node(c)
        assert current.status == "blocked" and current.probe_report["ready"] is False
        assert current.capabilities["status_protection"] is False
        assert current.capabilities["binding_protection"] is False
        assert current.capabilities["protection_contract_version"] == 1
        assert current.capabilities["protection_baseline_digest"] == BASELINE
        assert await flags(c) == (True, True)
    await c.svc.heartbeat(MANAGER, report())
    assert (await node(c)).status == "ready" and await flags(c) == (True, True)


@pytest.mark.parametrize("state", ["report_expired", "helper_changed"])
async def test_legacy_node_cannot_claim_report_only_continuity_without_baseline(coordination, state):
    c = coordination
    await bound(c, adopt=False)
    await c.svc.heartbeat(MANAGER, report(state))
    assert (await node(c)).status == "blocked" and await flags(c) == (False, False)


@pytest.mark.parametrize("state", ["unconfirmed", "current"])
async def test_unconfirmed_or_explicit_guard_failures_taint_history(coordination, state):
    c = coordination
    await bound(c)
    body = report(state)
    body.capabilities.update(status_protection=False, binding_protection=False)
    body.probe_report["ready"] = False
    await c.svc.heartbeat(MANAGER, body)
    assert await flags(c) == (False, False)
    await c.svc.heartbeat(MANAGER, report())
    assert (await node(c)).status == "ready" and await flags(c) == (False, False)


@pytest.mark.parametrize("guard,index", [("status_protection", 0), ("binding_protection", 1)])
@pytest.mark.parametrize("adopt", [True, False])
async def test_explicit_failure_is_irreversible_even_during_legacy_bootstrap(coordination, guard, index, adopt):
    c = coordination
    await bound(c, adopt=adopt)
    broken = report()
    broken.capabilities[guard] = False
    broken.probe_report["ready"] = False
    await c.svc.heartbeat(MANAGER, broken)
    expected = (False, True) if index == 0 else (True, False)
    assert await flags(c) == expected
    await c.svc.heartbeat(MANAGER, report("report_expired"))
    assert await flags(c) == expected
    await c.svc.heartbeat(MANAGER, report())
    assert (await node(c)).status == "ready" and await flags(c) == expected


@pytest.mark.parametrize("change", ["baseline", "policy"])
async def test_new_current_baseline_or_policy_taints_old_flags_despite_ready(coordination, change):
    c = coordination
    await bound(c)
    body = report(digest=OTHER_BASELINE if change == "baseline" else BASELINE)
    if change == "policy":
        body.capabilities["status_policy_revision"] = "v2"
    await c.svc.heartbeat(MANAGER, body)
    assert (await node(c)).status == "ready" and await flags(c) == (False, False)
    assert (await node(c)).capabilities["protection_baseline_digest"] == (
        OTHER_BASELINE if change == "baseline" else BASELINE
    )


@pytest.mark.parametrize("change", ["baseline", "policy", "report_ready", "status_true", "binding_true"])
async def test_report_only_exemption_requires_every_bound_condition(coordination, change):
    c = coordination
    await bound(c)
    body = report("report_expired")
    if change == "baseline":
        body.capabilities["protection_observation"]["baseline_digest"] = OTHER_BASELINE
    elif change == "policy":
        body.capabilities["status_policy_revision"] = "v2"
    elif change == "report_ready":
        body.probe_report["ready"] = True
    else:
        body.capabilities["status_protection" if change == "status_true" else "binding_protection"] = True
    await c.svc.heartbeat(MANAGER, body)
    assert (await node(c)).status == "blocked" and await flags(c) == (False, False)


@pytest.mark.parametrize(
    "observation",
    [
        None,
        {},
        {"version": True, "baseline_digest": BASELINE, "state": "current"},
        {"version": 2, "baseline_digest": BASELINE, "state": "current"},
        {"version": 1, "baseline_digest": "A" * 64, "state": "current"},
        {"version": 1, "baseline_digest": "bad", "state": "current"},
        {"version": 1, "baseline_digest": BASELINE, "state": "other"},
        {"version": 1, "baseline_digest": BASELINE, "state": "current", "extra": True},
    ],
)
async def test_malformed_observation_is_persisted_blocked_not_heartbeat_rejected(coordination, observation):
    c = coordination
    await bound(c)
    await c.svc.heartbeat(MANAGER, report(observation=observation))
    current = await node(c)
    assert current.status == "blocked" and await flags(c) == (False, False)
    assert current.capabilities["protection_contract_version"] == 1
    assert current.capabilities["protection_baseline_digest"] == BASELINE


@pytest.mark.parametrize("downgrade", ["missing", "malformed"])
async def test_new_to_unknown_to_fresh_legacy_never_erases_sticky_barrier(coordination, downgrade):
    c = coordination
    await bound(c)
    body = heartbeat() if downgrade == "missing" else report(observation={})
    body.capabilities.update(protection_contract_version=0, protection_baseline_digest=OTHER_BASELINE)
    await c.svc.heartbeat(MANAGER, body)
    for legacy in [heartbeat(), heartbeat()]:
        await c.svc.heartbeat(MANAGER, legacy)
        current = await node(c)
        assert current.status == "blocked" and await flags(c) == (False, False)
        assert current.capabilities["protection_contract_version"] == 1
        assert current.capabilities["protection_baseline_digest"] == BASELINE
    await c.svc.heartbeat(MANAGER, report())
    assert (await node(c)).status == "ready" and await flags(c) == (False, False)


async def test_first_malformed_adoption_cannot_fall_back_to_legacy_positive(coordination):
    c = coordination
    await bound(c, adopt=False)
    await c.svc.heartbeat(MANAGER, report(observation={}))
    await c.svc.heartbeat(MANAGER, heartbeat())
    current = await node(c)
    assert current.status == "blocked" and current.capabilities["protection_contract_version"] == 1
    assert await flags(c) == (False, False)


async def test_body_cannot_forge_prior_baseline_to_preserve_flags(coordination):
    c = coordination
    await bound(c)
    body = report("helper_changed", digest=OTHER_BASELINE)
    body.capabilities.update(protection_contract_version=1, protection_baseline_digest=OTHER_BASELINE)
    await c.svc.heartbeat(MANAGER, body)
    assert (await node(c)).status == "blocked" and await flags(c) == (False, False)


async def test_new_uid_binding_during_report_unknown_cannot_gain_protection(coordination):
    c = coordination
    await c.svc.heartbeat(MANAGER, report())
    await c.control.register_resource(MANAGER, prepare_document(c.op))
    await c.svc.heartbeat(MANAGER, report("report_expired"))
    await c.repo.bind_resource(
        REF, uid=UID, node_name="worker-a", holder_id="controller-a", controller_epoch=1, now=NOW
    )
    assert await flags(c) == (False, False)


@pytest.mark.parametrize(
    "kind,guard,node_name",
    [("kubelet_terminal", "status_protection", "worker-a"), ("never_scheduled", "binding_protection", "")],
)
@pytest.mark.parametrize("current", [False, None, 0, "true"])
async def test_first_stop_requires_exact_current_corresponding_guard(coordination, kind, guard, node_name, current):
    c = coordination
    row = await bound(c, node_name=node_name)
    await stop_request(c)
    current_node = await node(c)
    current_node.capabilities = {**current_node.capabilities, guard: current}
    await c.repo.save(current_node)
    assert await flags(c) == (True, True)
    with pytest.raises(RuntimeConflict, match="stop_protection_current_unconfirmed"):
        await confirm(c, row, kind)
    await assert_held(c)


@pytest.mark.parametrize("kind,node_name", [("kubelet_terminal", "worker-a"), ("never_scheduled", "")])
async def test_network_only_failure_does_not_block_protected_stop(coordination, kind, node_name):
    c = coordination
    row = await bound(c, node_name=node_name)
    await stop_request(c)
    body = report()
    body.capabilities["mandatory_isolation"] = False
    body.probe_report["ready"] = False
    await c.svc.heartbeat(MANAGER, body)
    assert (await node(c)).status == "blocked" and await flags(c) == (True, True)
    assert (await confirm(c, row, kind)).stop_state == "confirmed"


@pytest.mark.parametrize("kind,node_name", [("kubelet_terminal", "worker-a"), ("never_scheduled", "")])
async def test_confirmed_same_uid_remains_idempotent_after_current_guard_loss(coordination, kind, node_name):
    c = coordination
    row = await bound(c, node_name=node_name)
    await stop_request(c)
    confirmed = await confirm(c, row, kind)
    frozen = copy.deepcopy(confirmed.stop_evidence)
    await c.svc.heartbeat(MANAGER, report("unconfirmed"))
    again = await confirm(c, row, kind)
    assert again.stop_state == "confirmed" and again.stop_evidence == frozen
    with pytest.raises(RuntimeConflict, match="stop_uid"):
        await c.repo.confirm_resource_stop(
            REF, {**frozen, "uid": "different"}, holder_id="controller-a", controller_epoch=1, now=NOW
        )


async def test_not_created_independent_proof_remains_usable_without_current_protection(coordination):
    c = coordination
    await c.svc.heartbeat(MANAGER, report())
    await c.control.register_resource(MANAGER, prepare_document(c.op))
    auth = {"holder_id": "controller-a", "controller_epoch": 1}
    await c.control.observe_resource(MANAGER, REF, {"action": "create_fence", **auth})
    await c.svc.heartbeat(MANAGER, report("unconfirmed"))
    operation = await c.repo.get(RuntimeOperation, c.op.id)
    operation.status = "failed"
    await c.repo.save(operation)
    row = await c.repo.get(RuntimeExecutionResource, REF)
    evidence_doc = {
        "evidence_kind": "not_created",
        "namespace": row.namespace,
        "name": row.name,
        "observed_at": NOW.isoformat() + "Z",
        "api_status": 404,
    }
    result = await c.control.observe_resource(MANAGER, REF, {"action": "not_created", "evidence": evidence_doc, **auth})
    assert result["uid"] is None and result["stop_state"] == "confirmed"
    result = await c.control.observe_resource(MANAGER, REF, {"action": "cleanup", "uid": None, **auth})
    assert result["cleanup_state"] == "complete"
    assert (await c.repo.find(RuntimeCapacityReservation, operation_id=c.op.id))[0].state == "released"


async def test_legacy_body_cannot_bootstrap_server_owned_baseline_markers(coordination):
    c = coordination
    await bound(c, adopt=False)
    body = heartbeat()
    body.capabilities.update(protection_contract_version=1, protection_baseline_digest=BASELINE)
    await c.svc.heartbeat(MANAGER, body)
    current = await node(c)
    assert current.status == "ready"
    assert "protection_contract_version" not in current.capabilities
    assert "protection_baseline_digest" not in current.capabilities
    await c.svc.heartbeat(MANAGER, report("report_expired"))
    assert (await node(c)).status == "blocked" and await flags(c) == (False, False)


@pytest.mark.parametrize("kind,node_name", [("kubelet_terminal", "worker-a"), ("never_scheduled", "")])
async def test_report_only_unknown_rejects_first_stop_until_real_current_confirmation(coordination, kind, node_name):
    c = coordination
    row = await bound(c, node_name=node_name)
    await stop_request(c)
    await c.svc.heartbeat(MANAGER, report("report_expired"))
    assert await flags(c) == (True, True)
    with pytest.raises(RuntimeConflict, match="stop_protection_current_unconfirmed"):
        await confirm(c, row, kind)
    await assert_held(c)
    await c.svc.heartbeat(MANAGER, report())
    assert await flags(c) == (True, True)
    assert (await confirm(c, row, kind)).stop_state == "confirmed"
