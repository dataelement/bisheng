"""F004 (T055 leftover): a ``resync`` event says whether its run has ended, and how.

Before this the client had to guess the end of a run from empty connections.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services.run_event_stream import RunEventStream

CID = "conv-resync"
RUN = "run-resync"


def _ev(event_type: str, **data) -> dict:
    return run_events.make_event(event_type, data, run_id=RUN)


async def _trimmed_run(terminal: dict | None) -> tuple[RunEventStream, str]:
    """A run whose first entries were trimmed; returns the stream and a stale cursor."""
    stream = RunEventStream(fakeredis.aioredis.FakeRedis(), maxlen=2)
    first = await stream.append(CID, _ev("run_started"))
    for piece in ("a", "b", "c"):
        await stream.append(CID, _ev("text", text=piece))
    if terminal is not None:
        await stream.append(CID, terminal)
    return stream, first


async def test_resync_of_a_running_run_is_not_ended():
    stream, cursor = await _trimmed_run(None)

    resync = [e async for e in stream.read(CID, cursor)][0]

    assert resync["type"] == "resync"
    assert resync["data"]["ended"] is False
    assert "status" not in resync["data"]
    run_events.ResyncData.model_validate(resync["data"])


@pytest.mark.parametrize(
    ("terminal", "status"),
    [
        (_ev("run_finished"), "finished"),
        (_ev("run_stopped", reason="user"), "stopped"),
        (_ev("run_failed", code=11090, reason="unknown", detail="boom", reference_id=None), "failed"),
    ],
)
async def test_resync_of_an_ended_run_carries_the_terminal_status(terminal, status):
    stream, cursor = await _trimmed_run(terminal)

    events = [e async for e in stream.read(CID, cursor, follow=True, block_ms=10)]

    # The reader gets the state once and is told the run is over: nothing follows.
    assert [e["type"] for e in events] == ["resync"]
    assert events[0]["data"]["ended"] is True
    assert events[0]["data"]["status"] == status
    assert events[0]["data"]["text"] == "abc"
    assert run_events.ResyncData.model_validate(events[0]["data"]).status == status
    assert (await stream.snapshot(CID))["status"] == status


async def test_ended_snapshot_without_recorded_status_has_no_status():
    """A snapshot written by a node that ran the older script has ``ended`` only."""
    redis = fakeredis.aioredis.FakeRedis()
    stream = RunEventStream(redis, maxlen=2)
    first = await stream.append(CID, _ev("run_started"))
    for piece in ("a", "b", "c"):
        await stream.append(CID, _ev("text", text=piece))
    await redis.hset("bisheng:run:snapshot:{%s}" % CID, "ended", "1")

    resync = [e async for e in stream.read(CID, first)][0]

    assert resync["data"]["ended"] is True
    assert "status" not in resync["data"]


async def test_new_run_clears_the_ended_state():
    stream, _ = await _trimmed_run(_ev("run_finished"))

    await stream.append(CID, _ev("run_started"))

    snapshot = await stream.snapshot(CID)
    assert snapshot["ended"] is False and "status" not in snapshot
