"""F004 T011: run event Stream (design 决策 4, §4.3) — covers AC-31.

All state lives in a fakeredis instance (Lua enabled); no real middleware.
"""

import asyncio

import fakeredis.aioredis
import pytest

from bisheng.linsight.domain.services import run_event_stream as res
from bisheng.linsight.domain.services.run_event_stream import EventWriter, RunEventStream

CID = "conv-1"
RUN = "run-1"


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _never_sleep(_seconds: float) -> None:
    """Coalescing timer that never fires: only events close the window."""
    await asyncio.Event().wait()


@pytest.fixture()
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.flushall()
    await r.aclose()


def _ev(typ, run_id=RUN, **data):
    return {"type": typ, "run_id": run_id, "data": data}


async def _collect(stream, cid=CID, cursor=None, **kw):
    return [ev async for ev in stream.read(cid, cursor, **kw)]


def test_keys_share_conversation_hash_tag():
    assert res.events_key("abc") == "bisheng:run:events:{abc}"
    assert res.snapshot_key("abc") == "bisheng:run:snapshot:{abc}"


async def test_append_and_read_from_cursor(redis):
    stream = RunEventStream(redis)
    ids = [
        await stream.append(CID, _ev("run_started")),
        await stream.append(CID, _ev("text", text="hello")),
        await stream.append(CID, _ev("tool_call", name="search")),
    ]
    parsed = [res._parse_id(i) for i in ids]
    assert parsed == sorted(parsed) and len(set(parsed)) == 3

    after_first = await _collect(stream, cursor=ids[0])
    assert [e["id"] for e in after_first] == ids[1:]
    assert [e["type"] for e in after_first] == ["text", "tool_call"]
    assert after_first[0]["data"] == {"text": "hello"}
    assert after_first[0]["run_id"] == RUN
    assert [e["seq"] for e in after_first] == [2, 3]
    assert all(isinstance(e["ts"], int) and e["ts"] > 0 for e in after_first)

    everything = await _collect(stream)
    assert [e["id"] for e in everything] == ids
    assert await _collect(stream, cursor=ids[-1]) == []
    # Another conversation is isolated.
    assert await _collect(stream, cid="conv-2") == []


async def test_maxlen_trims(redis):
    stream = RunEventStream(redis, maxlen=5)
    await stream.append(CID, _ev("run_started"))
    for i in range(7):
        await stream.append(CID, _ev("tool_call", n=i))
    assert await redis.xlen(res.events_key(CID)) == 5
    kept = await redis.xrange(res.events_key(CID))
    assert [int(f[b"seq"]) for _, f in kept] == [4, 5, 6, 7, 8]
    snap = await stream.snapshot(CID)
    assert snap["seq"] == 8


async def test_stale_cursor_gets_resync(redis):
    stream = RunEventStream(redis, maxlen=3)
    first = await stream.append(CID, _ev("run_started"))
    await stream.append(CID, _ev("text", text="Hel"))
    await stream.append(CID, _ev("thinking", text="hmm"))
    await stream.append(CID, _ev("plan", items=[{"id": "1", "content": "a", "status": "pending"}]))
    await stream.append(CID, _ev("text", text="lo"))
    await stream.append(CID, _ev("file", file_id="f1", name="a.md", path="output/a.md", size=3, source="agent"))
    await stream.append(CID, _ev("file", file_id="f2", name="b.md", path="output/b.md", size=4, source="agent"))
    last = await stream.append(CID, _ev("ask_user", call_id="c1", questions=[{"question": "q?", "options": []}]))

    events = await _collect(stream, cursor=first)
    assert len(events) == 1
    resync = events[0]
    assert resync["type"] == "resync"
    assert resync["id"] == last
    assert resync["run_id"] == RUN
    assert resync["data"] == {
        "text": "Hello",
        "thinking": "hmm",
        "plan": [{"id": "1", "content": "a", "status": "pending"}],
        "files": [
            {"file_id": "f1", "name": "a.md", "path": "output/a.md", "size": 3, "source": "agent"},
            {"file_id": "f2", "name": "b.md", "path": "output/b.md", "size": 4, "source": "agent"},
        ],
        "pending_question": {"call_id": "c1", "questions": [{"question": "q?", "options": []}]},
        # The run is still in progress (F004 T055).
        "ended": False,
    }
    snap = await stream.snapshot(CID)
    assert {k: snap[k] for k in resync["data"]} == resync["data"]

    # An answered question leaves the accumulated state; increments follow resync.
    nxt = await stream.append(CID, _ev("ask_user_answered", call_id="c1"))
    events = await _collect(stream, cursor="0")
    assert [e["type"] for e in events] == ["resync"]
    assert "pending_question" not in events[0]["data"]
    assert events[0]["id"] == nxt

    # A cursor inside the kept window gets plain increments, no resync.
    kept = await redis.xrange(res.events_key(CID))
    cursor = kept[0][0].decode()
    events = await _collect(stream, cursor=cursor)
    assert [e["type"] for e in events] == [kept[1][1][b"type"].decode(), kept[2][1][b"type"].decode()]


async def test_reader_falling_behind_gets_resync(redis):
    stream = RunEventStream(redis, maxlen=3)
    await stream.append(CID, _ev("run_started"))
    await stream.append(CID, _ev("text", text="a"))
    reader = stream.read(CID, None, count=1)
    assert (await reader.__anext__())["type"] == "run_started"
    for ch in "bcdef":
        await stream.append(CID, _ev("text", text=ch))
    rest = [ev async for ev in reader]
    assert rest[0]["type"] == "resync"
    assert rest[0]["data"]["text"] == "abcdef"
    assert len(rest) == 1


async def test_new_run_resets_stream_and_snapshot(redis):
    stream = RunEventStream(redis)
    await stream.append(CID, _ev("run_started"))
    await stream.append(CID, _ev("text", text="old"))
    await stream.append(CID, _ev("run_finished"))
    await stream.append(CID, _ev("run_started", run_id="run-2"))
    snap = await stream.snapshot(CID)
    assert snap["run_id"] == "run-2" and snap["text"] == "" and snap["seq"] == 1 and not snap["ended"]
    events = await _collect(stream)
    assert [(e["type"], e["run_id"]) for e in events] == [("run_started", "run-2")]
    assert await redis.ttl(res.events_key(CID)) > res.ENDED_TTL_SECONDS


async def test_text_coalescing(redis):
    stream = RunEventStream(redis)
    clock = FakeClock()
    writer = EventWriter(stream, CID, RUN, clock=clock, sleep=_never_sleep)
    await writer.emit({"type": "run_started"})
    for ch in "abc":
        await writer.emit({"type": "text", "data": {"text": ch}})
        clock.advance(0.01)
    # Still inside the 50 ms window: nothing but run_started reached Redis.
    assert await redis.xlen(res.events_key(CID)) == 1
    clock.advance(0.03)  # 60 ms since the first delta
    await writer.emit({"type": "text", "data": {"text": "d"}})
    await writer.emit({"type": "thinking", "data": {"text": "t1"}})
    await writer.emit({"type": "thinking", "data": {"text": "t2"}})
    await writer.emit({"type": "tool_call", "data": {"name": "x"}})
    await writer.emit({"type": "text", "data": {"text": "e"}})
    await writer.aclose()

    events = await _collect(stream)
    assert [(e["type"], e["data"]) for e in events] == [
        ("run_started", {}),
        ("text", {"text": "abc"}),
        ("text", {"text": "d"}),
        ("thinking", {"text": "t1t2"}),
        ("tool_call", {"name": "x"}),
        ("text", {"text": "e"}),
    ]
    assert all(e["run_id"] == RUN for e in events)
    assert (await stream.snapshot(CID))["text"] == "abcde"


async def test_coalescing_same_segment_keeps_call_id_and_namespace(redis):
    stream = RunEventStream(redis)
    writer = EventWriter(stream, CID, RUN, clock=FakeClock(), sleep=_never_sleep)
    for ch in "abc":
        await writer.emit({"type": "thinking", "data": {"text": ch, "call_id": "seg-1", "namespace": "sub:r1"}})
    await writer.aclose()

    events = await _collect(stream)
    assert [(e["type"], e["data"]) for e in events] == [
        ("thinking", {"text": "abc", "call_id": "seg-1", "namespace": "sub:r1"}),
    ]
    assert (await stream.snapshot(CID))["thinking"] == "abc"


async def test_coalescing_does_not_merge_across_call_id_or_namespace(redis):
    stream = RunEventStream(redis)
    writer = EventWriter(stream, CID, RUN, clock=FakeClock(), sleep=_never_sleep)
    await writer.emit({"type": "thinking", "data": {"text": "a1", "call_id": "seg-1"}})
    await writer.emit({"type": "thinking", "data": {"text": "a2", "call_id": "seg-1"}})
    await writer.emit({"type": "thinking", "data": {"text": "b", "call_id": "seg-2"}})
    await writer.emit({"type": "thinking", "data": {"text": "c", "call_id": "seg-2", "namespace": "sub:r1"}})
    await writer.emit({"type": "thinking", "data": {"text": "d", "call_id": "seg-2"}})
    await writer.aclose()

    events = await _collect(stream)
    assert [(e["type"], e["data"]) for e in events] == [
        ("thinking", {"text": "a1a2", "call_id": "seg-1"}),
        ("thinking", {"text": "b", "call_id": "seg-2"}),
        ("thinking", {"text": "c", "call_id": "seg-2", "namespace": "sub:r1"}),
        ("thinking", {"text": "d", "call_id": "seg-2"}),
    ]
    # The snapshot accumulation is unchanged: every delta, in arrival order.
    assert (await stream.snapshot(CID))["thinking"] == "a1a2bcd"


async def test_coalescing_preserves_order_across_segments(redis):
    stream = RunEventStream(redis)
    writer = EventWriter(stream, CID, RUN, clock=FakeClock(), sleep=_never_sleep)
    await writer.emit({"type": "text", "data": {"text": "m1", "namespace": "sub:r1"}})
    await writer.emit({"type": "text", "data": {"text": "x"}})
    await writer.emit({"type": "text", "data": {"text": "m2", "namespace": "sub:r1"}})
    await writer.emit({"type": "text", "data": {"text": "m3", "namespace": "sub:r1"}})
    await writer.emit({"type": "thinking", "data": {"text": "t", "call_id": "seg-1"}})
    await writer.emit({"type": "text", "data": {"text": "y"}})
    await writer.aclose()

    events = await _collect(stream)
    assert [(e["type"], e["data"]) for e in events] == [
        ("text", {"text": "m1", "namespace": "sub:r1"}),
        ("text", {"text": "x"}),
        ("text", {"text": "m2m3", "namespace": "sub:r1"}),
        ("thinking", {"text": "t", "call_id": "seg-1"}),
        ("text", {"text": "y"}),
    ]
    snap = await stream.snapshot(CID)
    assert snap["text"] == "m1xm2m3y" and snap["thinking"] == "t"


async def test_text_coalescing_timer_flushes_idle_buffer(redis):
    stream = RunEventStream(redis)
    writer = EventWriter(stream, CID, RUN, window_seconds=0.002)
    await writer.emit({"type": "text", "data": {"text": "x"}})
    await writer.emit({"type": "text", "data": {"text": "y"}})
    for _ in range(50):
        if await redis.xlen(res.events_key(CID)):
            break
        await asyncio.sleep(0.001)
    events = await _collect(stream)
    assert [(e["type"], e["data"]) for e in events] == [("text", {"text": "xy"})]
    await writer.aclose()


async def test_stream_expires_after_run(redis):
    stream = RunEventStream(redis)
    await stream.append(CID, _ev("run_started"))
    await stream.append(CID, _ev("text", text="hi"))
    ek, sk = res.events_key(CID), res.snapshot_key(CID)
    assert await redis.ttl(ek) > res.ENDED_TTL_SECONDS
    assert await redis.ttl(sk) > res.ENDED_TTL_SECONDS

    await stream.append(CID, _ev("run_finished"))
    for key in (ek, sk):
        ttl = await redis.ttl(key)
        assert res.ENDED_TTL_SECONDS - 5 <= ttl <= res.ENDED_TTL_SECONDS
    assert (await stream.snapshot(CID))["ended"] is True

    # A late event does not stretch the expiry back to the live TTL.
    await stream.append(CID, _ev("tool_call"))
    assert await redis.ttl(ek) <= res.ENDED_TTL_SECONDS

    # Once Redis expires the keys, readers get nothing and fall back to the DB.
    await redis.delete(ek, sk)
    assert await _collect(stream, follow=True) == []
    assert await stream.snapshot(CID) is None


async def test_follow_reads_until_terminal(redis):
    stream = RunEventStream(redis)
    await stream.append(CID, _ev("run_started"))

    async def produce():
        await asyncio.sleep(0.005)
        await stream.append(CID, _ev("text", text="a"))
        await stream.append(CID, _ev("run_finished"))
        await stream.append(CID, _ev("tool_call"))  # after terminal: not delivered

    task = asyncio.create_task(produce())
    events = await asyncio.wait_for(_collect(stream, follow=True, block_ms=20), timeout=2)
    await task
    assert [e["type"] for e in events] == ["run_started", "text", "run_finished"]


async def test_follow_heartbeat_on_idle(redis):
    stream = RunEventStream(redis)
    first = await stream.append(CID, _ev("run_started"))
    reader = stream.read(CID, first, follow=True, block_ms=5, heartbeat=True)
    assert await asyncio.wait_for(reader.__anext__(), timeout=2) == {"type": "heartbeat"}
    await reader.aclose()


async def test_follow_never_holds_a_connection_in_a_blocking_read(redis, monkeypatch):
    """Every open conversation page is one follower. With ``XREAD BLOCK`` each of
    them parks on a pooled connection; the shared pool is capped and raises when it
    runs out, which fails lease renewals and with them the running answers."""
    stream = RunEventStream(redis)
    first = await stream.append(CID, _ev("run_started"))
    calls: list[dict] = []
    real_xread = redis.xread

    async def spy(*args, **kwargs):
        calls.append(kwargs)
        return await real_xread(*args, **kwargs)

    monkeypatch.setattr(redis, "xread", spy)

    async def produce():
        await asyncio.sleep(0.03)
        await stream.append(CID, _ev("run_finished"))

    task = asyncio.create_task(produce())
    events = await asyncio.wait_for(_collect(stream, cursor=first, follow=True, block_ms=500), timeout=2)
    await task

    assert [e["type"] for e in events] == ["run_finished"]
    assert len(calls) >= 2  # it polled while it waited
    assert all(not call.get("block") for call in calls)


async def test_append_rejects_reader_only_types(redis):
    stream = RunEventStream(redis)
    with pytest.raises(ValueError):
        await stream.append(CID, {"type": "resync", "data": {}})
    with pytest.raises(ValueError):
        await stream.append(CID, {"data": {}})


async def test_update_snapshot_overrides_fields(redis):
    stream = RunEventStream(redis)
    await stream.append(CID, _ev("run_started"))
    await stream.update_snapshot(CID, text="seed", plan=[{"id": "1"}], pending_question={"call_id": "c"})
    snap = await stream.snapshot(CID)
    assert snap["text"] == "seed" and snap["plan"] == [{"id": "1"}] and snap["pending_question"] == {"call_id": "c"}
    await stream.update_snapshot(CID, pending_question=None)
    assert "pending_question" not in await stream.snapshot(CID)


async def test_parked_run_keeps_its_stream_for_the_parked_ttl(redis):
    """A pending question stretches the expiry; the answer or the end of the run puts it back."""
    stream = RunEventStream(redis)
    ek, sk = res.events_key(CID), res.snapshot_key(CID)
    await stream.append(CID, _ev("run_started"))
    await stream.append(CID, _ev("text", text="先问一句"))
    for key in (ek, sk):
        assert await redis.ttl(key) <= res.LIVE_TTL_SECONDS

    await stream.append(CID, _ev("ask_user", call_id="c1", questions=[{"question": "要哪一种？"}]))
    for key in (ek, sk):
        assert res.LIVE_TTL_SECONDS < await redis.ttl(key) <= res.PARKED_TTL_SECONDS

    # The answer resumes the run: an ordinary live run again.
    await stream.append(CID, _ev("ask_user_answered", call_id="c1", answer="第一种"))
    for key in (ek, sk):
        assert res.ENDED_TTL_SECONDS < await redis.ttl(key) <= res.LIVE_TTL_SECONDS

    # A parked run that is stopped ends like any other run.
    await stream.append(CID, _ev("ask_user", call_id="c2", questions=[{"question": "再问一次"}]))
    await stream.append(CID, _ev("run_stopped"))
    for key in (ek, sk):
        assert await redis.ttl(key) <= res.ENDED_TTL_SECONDS


async def test_writer_discard_drops_buffered_text(redis):
    stream = RunEventStream(redis)
    writer = EventWriter(stream, CID, RUN, sleep=_never_sleep)
    await writer.emit(_ev("run_started"))
    await writer.emit(_ev("text", text="不该写出"))

    writer.discard()
    await writer.aclose()

    assert [ev["type"] for ev in await _collect(stream)] == ["run_started"]
    assert (await stream.snapshot(CID))["text"] == ""
