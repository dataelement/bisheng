"""Wave 3 worker contract: broker messages wake up durable, tenant-scoped work."""

from types import SimpleNamespace
from unittest.mock import AsyncMock


def target(state, attempt=1):
    return SimpleNamespace(
        tenant_id=17,
        space_id=29,
        operation_id="dept-b",
        provider_instance_id=7,
        remote_kb_id="frozen-uuid",
        generation=2,
        operation_epoch=4,
        revision=9,
        lease_token="worker-b",
        state=state,
        attempt=attempt,
        phase="create",
    )


async def test_broker_failure_keeps_same_operation_eligible_for_next_scan():
    from bisheng.worker.knowledge.provider_dispatch import dispatch_due

    candidate = target("pending")
    due = AsyncMock(return_value=[candidate])
    publish = AsyncMock(side_effect=[ConnectionError("broker unavailable"), None])
    # The scan is a wake-up only. No execution lease or business state is consumed.
    for expected in (0, 1):
        assert await dispatch_due(tenant_id=17, limit=1, due=due, publish=publish) == expected
    assert publish.await_count == 2
    assert publish.await_args_list[0] == publish.await_args_list[1]
    publish.assert_awaited_with(operation_id="dept-b", expected_revision=9, headers={"tenant_id": 17})
    assert candidate.state == "pending"


def step_deps(row):
    return {
        "claim": AsyncMock(return_value=row),
        "send": AsyncMock(),
        "reconcile": AsyncMock(),
        "project": AsyncMock(),
        "advance": AsyncMock(return_value=True),
    }


async def step(deps, budget=4):
    from bisheng.worker.knowledge.provider_operations import advance_one

    await advance_one(tenant_id=17, operation_id="dept-b", expected_revision=8, attempt_budget=budget, **deps)


async def test_duplicate_wakeup_without_lease_never_sends_or_projects():
    deps = step_deps(None)
    await step(deps)
    for name in ("send", "reconcile", "project", "advance"):
        deps[name].assert_not_awaited()


async def test_takeover_queries_original_target_then_finishes_local_projection_only():
    reclaimed = target("reconciling")
    deps = step_deps(reclaimed)
    deps["reconcile"].return_value = "confirmed"
    await step(deps)
    deps["reconcile"].assert_awaited_once_with(reclaimed)
    deps["advance"].assert_awaited_once_with(reclaimed, state="applying")
    deps["project"].assert_not_awaited()
    applying = target("applying")
    deps["claim"].return_value = applying
    deps["project"].return_value = "confirmed"
    await step(deps)
    deps["project"].assert_awaited_once_with(applying)
    deps["advance"].assert_awaited_with(applying, state="succeeded")
    deps["send"].assert_not_awaited()


async def test_exhausted_unknown_result_stops_automatic_writes():
    row = target("reconciling", attempt=4)
    deps = step_deps(row)
    deps["reconcile"].return_value = "unknown"
    await step(deps, budget=4)
    deps["advance"].assert_awaited_once_with(row, state="manual_review")
    deps["send"].assert_not_awaited()
    deps["project"].assert_not_awaited()
