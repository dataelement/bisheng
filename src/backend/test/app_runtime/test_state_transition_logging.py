"""T097 backend half — ``app.state_transition`` (design §7「关键日志 / 指标」).

The audit trail answers "who asked for what" (AC-65). It does **not** answer
"what did the state machine actually do", and the gap is exactly where the
expensive incidents live: a write that lost its compare-and-set and a transition
the table refuses both leave the app in its old state with nothing in the audit
table to explain it. This event closes that gap, so what is pinned here is the
**structured payload** (``record["extra"]``) rather than the sentence:

* one event per transition attempt, for all five actions;
* ``from`` / ``to`` / ``reason`` / ``actor`` always present (§7's field list);
* the two silent outcomes — ``lost_race`` and ``refused`` — are distinguishable
  from a successful write and from each other.
"""

from __future__ import annotations

import pytest
from loguru import logger as loguru_logger

from bisheng.app_runtime.domain.constants import AppState

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection")

EVENT = "app.state_transition"
#: §7 spells the field list as "from → to / reason / actor"; ``app_id`` and
#: ``result`` are what make a line greppable and actionable.
REQUIRED_FIELDS = ("app_id", "from_state", "to_state", "reason", "actor", "result")


@pytest.fixture()
def transition_events():
    """Collect the structured ``extra`` of every ``app.state_transition`` record.

    A loguru sink rather than ``caplog``: the project logger is loguru, and its
    ``bind()`` payload lives in ``record["extra"]`` — going through the stdlib
    interceptor would flatten exactly the fields under test into a string.
    """
    captured: list[dict] = []

    def sink(message) -> None:
        extra = message.record["extra"]
        if extra.get("event") == EVENT:
            captured.append(dict(extra))

    handler_id = loguru_logger.add(sink, level="DEBUG")
    try:
        yield captured
    finally:
        loguru_logger.remove(handler_id)


def _assert_contract(event: dict) -> None:
    missing = [name for name in REQUIRED_FIELDS if name not in event]
    assert not missing, f"app.state_transition emitted without {missing}"


@pytest.mark.parametrize(
    ("action", "source", "target"),
    (
        ("publish", AppState.DRAFT.value, AppState.ONLINE.value),
        ("manual_publish", AppState.PENDING_CAPACITY.value, AppState.ONLINE.value),
        ("resume", AppState.STOPPED.value, AppState.ONLINE.value),
        ("stop", AppState.ONLINE.value, AppState.STOPPED.value),
        ("delete", AppState.STOPPED.value, AppState.DELETED.value),
    ),
)
async def test_state_transition_logged_for_all_five_actions(
    app_factory, app_owner, transition_events, action, source, target
):
    """Every action that moves the column leaves one event with the §7 fields."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    app, _ = await app_factory(state=source)

    await getattr(AppStateService, action)(app.id, actor=app_owner.payload)

    applied = [event for event in transition_events if event["result"] == "applied"]
    assert len(applied) == 1, f"{action} should log exactly one applied transition"
    event = applied[0]
    _assert_contract(event)
    assert event["app_id"] == app.id
    assert event["from_state"] == source
    assert event["to_state"] == target
    assert event["actor"] == app_owner.user_id, "who did it — an admin acting on someone else's app is the case"
    assert event["reason"], "a transition with no reason is not worth logging"


async def test_publish_and_resume_are_distinguishable_in_the_log(app_factory, app_owner, transition_events):
    """Three actions land on ``online``; only ``reason`` says which one ran."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    published, _ = await app_factory(state=AppState.DRAFT.value)
    resumed, _ = await app_factory(state=AppState.STOPPED.value)

    await AppStateService.publish(published.id, actor=app_owner.payload)
    await AppStateService.resume(resumed.id, actor=app_owner.payload)

    reasons = {event["app_id"]: event["reason"] for event in transition_events if event["result"] == "applied"}
    assert reasons[published.id] != reasons[resumed.id]


async def test_a_lost_compare_and_set_is_logged_as_such(app_db, app_factory, app_owner, transition_events, monkeypatch):
    """The outcome that never reaches the audit table.

    A concurrent action moves the app first, the loser writes nothing and raises
    16102 — and without this event the only trace is the exception in the
    caller's response.
    """
    from bisheng.app_runtime.domain.services import app_state_service
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.common.errcode.app_factory import AppStateConflictError
    from bisheng.database.models.app import AppDao

    app, _ = await app_factory(state=AppState.ONLINE.value)
    original = AppStateService._transition

    async def _steal_then_transition(app_id, **kwargs):
        async with app_state_service.get_async_db_session() as session:
            await AppDao.aupdate_state_cas(
                session, app_id, from_states=(AppState.ONLINE.value,), to_state=AppState.STOPPED.value
            )
            await session.commit()
        return await original(app_id, **kwargs)

    monkeypatch.setattr(AppStateService, "_transition", staticmethod(_steal_then_transition))

    with pytest.raises(AppStateConflictError):
        await AppStateService.stop(app.id, actor=app_owner.payload)

    lost = [event for event in transition_events if event["result"] == "lost_race"]
    assert len(lost) == 1
    _assert_contract(lost[0])
    assert lost[0]["to_state"] == AppState.STOPPED.value


async def test_a_refused_edge_is_logged_and_writes_nothing(app_db, app_factory, app_owner, transition_events):
    """``online → pending_capacity`` is deliberately absent from the table.

    It is a programming error surfaced as a no-op, which means the log line is
    the only place it can be seen at all.
    """
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService
    from bisheng.database.models.app import AppDao

    app, _ = await app_factory(state=AppState.ONLINE.value)

    won = await AppStateService._transition(
        app.id,
        to_state=AppState.PENDING_CAPACITY,
        from_states=(AppState.ONLINE.value,),
        reason="capacity_exhausted",
        actor=app_owner.payload,
    )

    assert won is False
    refused = [event for event in transition_events if event["result"] == "refused"]
    assert len(refused) == 1
    _assert_contract(refused[0])
    assert refused[0]["reason"] == "capacity_exhausted"
    async with app_db() as session:
        assert (await AppDao.aget(session, app.id)).state == AppState.ONLINE.value


async def test_parking_a_failed_publish_is_logged_with_the_cause(
    app_factory, app_owner, fake_orchestrator, transition_events
):
    """AC-65's 「待上线 · 资源不足」 has a matching line on the operator's side."""
    from bisheng.app_runtime.domain.services.app_state_service import AppStateService

    fake_orchestrator.responses["admission"] = {
        "admitted": False,
        "reason": "insufficient_available_memory",
        "snapshot": {"mem_available_mb": 700, "committed_mb": 20480, "total_mb": 32768, "cpu": 8},
    }
    app, _ = await app_factory(state=AppState.DRAFT.value)

    result = await AppStateService.publish(app.id, actor=app_owner.payload)
    assert result.ok is False, "precondition: the capacity gate refused"

    parked = [event for event in transition_events if event["to_state"] == AppState.PENDING_CAPACITY.value]
    assert len(parked) == 1
    _assert_contract(parked[0])
    assert parked[0]["reason"] == "insufficient_available_memory"
