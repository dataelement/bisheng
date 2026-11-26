"""A replay proven safe by absence must actually re-send, not die before the step."""

from types import SimpleNamespace
from unittest.mock import AsyncMock


def row(state, attempt=1):
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


def deps_for(current):
    return {
        "claim": AsyncMock(return_value=current),
        "send": AsyncMock(return_value="accepted"),
        "reconcile": AsyncMock(return_value="confirmed"),
        "project": AsyncMock(return_value="confirmed"),
        "advance": AsyncMock(return_value=True),
    }


async def step(current, deps, budget=4):
    from bisheng.worker.knowledge.provider_operations import advance_one

    return await advance_one(tenant_id=17, operation_id="dept-b", expected_revision=8, attempt_budget=budget, **deps)


async def test_pending_replays_the_send_and_never_the_read():
    """`pending` is produced by verified_safe_replay, whose whole point is a new send."""
    from bisheng.worker.knowledge.provider_operations import StepResult

    current = row("pending")
    deps = deps_for(current)
    deps["send"].return_value = StepResult("accepted", remote_task_id="remote-task")
    await step(current, deps)

    deps["send"].assert_awaited_once_with(current)
    deps["reconcile"].assert_not_awaited()
    # An accepted send waits for the remote receipt instead of claiming success.
    deps["advance"].assert_awaited_once_with(current, state="waiting_remote", remote_task_id="remote-task")


async def test_verified_absence_returns_the_operation_to_pending():
    current = row("reconciling")
    deps = deps_for(current)
    deps["reconcile"].return_value = "verified_safe_replay"
    await step(current, deps)

    deps["advance"].assert_awaited_once_with(current, state="pending")
    deps["send"].assert_not_awaited()
