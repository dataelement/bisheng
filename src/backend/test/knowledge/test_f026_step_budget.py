"""A leased step must be able to finish one full round of remote probes."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.worker.knowledge import provider_operations as operations


def test_a_step_budget_covers_a_probe_round(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(weknora=None), raising=False)
    # Default probe budget 180s + overhead; the old fixed 120s lease could not host it.
    assert operations.step_timeout_seconds() == 300
    assert operations.lease_seconds() == 360


def test_an_operator_budget_stretches_the_step_and_its_lease(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(weknora_probe_timeout_seconds=420),
        raising=False,
    )
    assert operations.step_timeout_seconds() == 540
    # The lease always outlives the step, otherwise a peer reclaims running work.
    assert operations.lease_seconds() > operations.step_timeout_seconds()


def test_a_step_never_gets_less_than_the_previous_budget(monkeypatch):
    from bisheng.common.services import config_service

    monkeypatch.setattr(
        config_service,
        "settings",
        SimpleNamespace(weknora_probe_timeout_seconds=1),
        raising=False,
    )
    assert operations.step_timeout_seconds() >= 120


def _row():
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
        state="reconciling",
        attempt=1,
        phase="create",
        remote_task_id=None,
    )


async def test_a_slow_send_is_no_longer_cut_off_at_the_old_lease():
    """A send that legitimately outlives the old 120s budget must still complete."""
    current = _row()
    current.state = "sending"
    seen = []

    async def slow_send(_row):
        await asyncio.sleep(0.05)
        seen.append("completed")
        return "accepted"

    deps = {
        "claim": AsyncMock(return_value=current),
        "send": slow_send,
        "reconcile": AsyncMock(),
        "project": AsyncMock(),
        "advance": AsyncMock(return_value=True),
    }
    await operations.advance_one(
        tenant_id=17,
        operation_id="dept-b",
        expected_revision=8,
        attempt_budget=4,
        step_timeout=0.2,
        **deps,
    )
    assert seen == ["completed"]
    deps["reconcile"].assert_not_awaited()


async def test_a_step_that_exceeds_its_budget_is_still_reported_unknown(monkeypatch):
    """Raising the budget must not turn a genuine timeout into a silent success."""
    current = _row()
    warnings = []
    monkeypatch.setattr(operations.logger, "warning", lambda message, *a, **k: warnings.append((message, a)))

    async def stuck(_row):
        await asyncio.sleep(5)

    deps = {
        "claim": AsyncMock(return_value=current),
        "send": AsyncMock(),
        "reconcile": stuck,
        "project": AsyncMock(),
        "advance": AsyncMock(return_value=True),
    }
    await operations.advance_one(
        tenant_id=17,
        operation_id="dept-b",
        expected_revision=8,
        attempt_budget=4,
        step_timeout=0.05,
        **deps,
    )
    deps["advance"].assert_awaited_once_with(current, state="reconciling")
    assert any(a[-1] == "TimeoutError" for _message, a in warnings)
