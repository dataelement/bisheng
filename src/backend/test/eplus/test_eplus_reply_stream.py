from __future__ import annotations

import asyncio
from collections import deque

import pytest

from bisheng.eplus.domain.models.eplus import EPlusReplyStatus
from bisheng.eplus.domain.services.reply_stream import (
    CONTENT_TRUNCATED_SUFFIX,
    EPlusReplyAckError,
    EPlusReplyDeadlineExceeded,
    EPlusReplyStream,
    RedisReplyQuota,
)
from bisheng.eplus.infrastructure.protocol import MAX_STREAM_BYTES


class FakeClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeSender:
    def __init__(self, outcomes=None) -> None:
        self.frames: list[dict] = []
        self.outcomes = deque(outcomes or [])

    async def send_with_ack(self, frame: dict) -> dict:
        self.frames.append(frame)
        if not self.outcomes:
            return {"errcode": 0, "errmsg": "ok"}
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeQuota:
    def __init__(self, *, nonterminal_allowances: int = 100, terminal_allowances: int = 1) -> None:
        self.nonterminal_allowances = nonterminal_allowances
        self.terminal_allowances = terminal_allowances
        self.calls: list[bool] = []

    async def reserve(self, *, terminal: bool) -> bool:
        self.calls.append(terminal)
        if terminal:
            self.terminal_allowances -= 1
            return self.terminal_allowances >= 0
        self.nonterminal_allowances -= 1
        return self.nonterminal_allowances >= 0


class FakeRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[EPlusReplyStatus, str | None]] = []

    async def record(self, status: EPlusReplyStatus, *, error_code: str | None = None) -> None:
        self.events.append((status, error_code))


def _stream(*, sender=None, quota=None, recorder=None, clock=None, flush_bytes=512):
    return EPlusReplyStream(
        sender=sender or FakeSender(),
        quota=quota or FakeQuota(),
        recorder=recorder or FakeRecorder(),
        req_id="callback-1",
        stream_id="stream-1",
        clock=clock or FakeClock(),
        flush_interval_seconds=1.5,
        flush_bytes=flush_bytes,
        deadline_seconds=300,
    )


async def test_first_frame_ack_failure_records_send_failure_and_blocks_downstream() -> None:
    sender = FakeSender([TimeoutError()])
    recorder = FakeRecorder()
    stream = _stream(sender=sender, recorder=recorder)
    assistant_started = False

    with pytest.raises(EPlusReplyAckError, match="timeout"):
        await stream.start()
        assistant_started = True

    assert assistant_started is False
    assert recorder.events == [(EPlusReplyStatus.SEND_FAILED, "EPLUS_ACK_TIMEOUT")]
    assert sender.frames[0]["body"]["stream"] == {
        "id": "stream-1",
        "finish": False,
        "content": "处理中",
    }


async def test_fragments_are_coalesced_and_each_refresh_sends_cumulative_text() -> None:
    sender = FakeSender()
    clock = FakeClock()
    stream = _stream(sender=sender, clock=clock, flush_bytes=100)

    await stream.start()
    assert await stream.append("你") is False
    clock.advance(1.4)
    assert await stream.append("好") is False
    clock.advance(0.1)
    assert await stream.append("!") is True
    assert await stream.append("继续") is False
    await stream.finish()

    payloads = [frame["body"]["stream"] for frame in sender.frames]
    assert [payload["content"] for payload in payloads] == ["处理中", "你好!", "你好!继续"]
    assert [payload["finish"] for payload in payloads] == [False, False, True]
    assert {frame["headers"]["req_id"] for frame in sender.frames} == {"callback-1"}
    assert {payload["id"] for payload in payloads} == {"stream-1"}


async def test_flush_threshold_does_not_send_each_token() -> None:
    sender = FakeSender()
    stream = _stream(sender=sender, flush_bytes=4)

    await stream.start()
    assert await stream.append("a") is False
    assert await stream.append("b") is False
    assert await stream.append("cd") is True

    assert [frame["body"]["stream"]["content"] for frame in sender.frames] == ["处理中", "abcd"]


async def test_flush_interval_works_when_monotonic_clock_starts_at_zero() -> None:
    sender = FakeSender()
    clock = FakeClock()
    clock.value = 0
    stream = _stream(sender=sender, clock=clock, flush_bytes=100)

    await stream.start()
    assert await stream.append("a") is False
    clock.advance(1.5)
    assert await stream.append("b") is True


async def test_utf8_limit_adds_suffix_and_finishes_safely() -> None:
    sender = FakeSender()
    stream = _stream(sender=sender, flush_bytes=MAX_STREAM_BYTES + 1)

    await stream.start()
    sent = await stream.append("中" * MAX_STREAM_BYTES)

    final = sender.frames[-1]["body"]["stream"]
    assert sent is True
    assert final["finish"] is True
    assert final["content"].endswith(CONTENT_TRUNCATED_SUFFIX)
    assert len(final["content"].encode("utf-8")) <= MAX_STREAM_BYTES
    assert stream.finished is True


async def test_negative_ack_stops_stream_and_records_classification() -> None:
    sender = FakeSender([{"errcode": 0}, {"errcode": 45009, "errmsg": "rate limited"}])
    recorder = FakeRecorder()
    stream = _stream(sender=sender, recorder=recorder, flush_bytes=1)

    await stream.start()
    with pytest.raises(EPlusReplyAckError, match="45009"):
        await stream.append("answer")

    assert recorder.events == [
        (EPlusReplyStatus.STREAMING, None),
        (EPlusReplyStatus.SEND_FAILED, "EPLUS_ACK_REJECTED"),
    ]


async def test_same_stream_waits_for_previous_ack_before_sending_next_frame() -> None:
    class BlockingSender(FakeSender):
        def __init__(self) -> None:
            super().__init__()
            self.first_answer_started = asyncio.Event()
            self.release_first_answer = asyncio.Event()
            self.active_sends = 0
            self.overlapped = False

        async def send_with_ack(self, frame: dict) -> dict:
            self.frames.append(frame)
            content = frame["body"]["stream"]["content"]
            self.active_sends += 1
            self.overlapped = self.overlapped or self.active_sends > 1
            if content == "a":
                self.first_answer_started.set()
                await self.release_first_answer.wait()
            self.active_sends -= 1
            return {"errcode": 0}

    sender = BlockingSender()
    stream = _stream(sender=sender, flush_bytes=1)
    await stream.start()

    first = asyncio.create_task(stream.append("a"))
    await sender.first_answer_started.wait()
    second = asyncio.create_task(stream.append("b"))
    await asyncio.sleep(0)
    sender.release_first_answer.set()
    await asyncio.gather(first, second)

    assert sender.overlapped is False
    assert [frame["body"]["stream"]["content"] for frame in sender.frames] == ["处理中", "a", "ab"]


async def test_hard_deadline_sends_explicit_terminal_frame_and_raises() -> None:
    sender = FakeSender()
    recorder = FakeRecorder()
    clock = FakeClock()
    stream = _stream(sender=sender, recorder=recorder, clock=clock)

    await stream.start()
    clock.advance(300)
    with pytest.raises(EPlusReplyDeadlineExceeded):
        await stream.append("late model output")

    terminal = sender.frames[-1]["body"]["stream"]
    assert terminal == {
        "id": "stream-1",
        "finish": True,
        "content": "处理超时，请稍后重试",  # noqa: RUF001
    }
    assert recorder.events[-1] == (EPlusReplyStatus.FINISHED, "ASSISTANT_TIMEOUT")


async def test_nonterminal_quota_denial_coalesces_but_terminal_slot_is_reserved() -> None:
    sender = FakeSender()
    quota = FakeQuota(nonterminal_allowances=1, terminal_allowances=1)
    stream = _stream(sender=sender, quota=quota, flush_bytes=1)

    await stream.start()
    assert await stream.append("a") is False
    assert await stream.append("b") is False
    await stream.finish()

    assert quota.calls == [False, False, False, True]
    assert [frame["body"]["stream"]["content"] for frame in sender.frames] == ["处理中", "ab"]
    assert sender.frames[-1]["body"]["stream"]["finish"] is True


async def test_terminal_rejection_can_reply_without_starting_assistant_stream() -> None:
    sender = FakeSender()
    recorder = FakeRecorder()
    stream = _stream(sender=sender, recorder=recorder)

    await stream.send_terminal("无权限使用", error_code="NO_PERMISSION")

    assert sender.frames[-1]["body"]["stream"] == {
        "id": "stream-1",
        "finish": True,
        "content": "无权限使用",
    }
    assert recorder.events == [(EPlusReplyStatus.FINISHED, "NO_PERMISSION")]
    assert stream.answer == "无权限使用"


async def test_failure_replaces_partial_answer_with_safe_terminal_message() -> None:
    sender = FakeSender()
    recorder = FakeRecorder()
    stream = _stream(sender=sender, recorder=recorder, flush_bytes=100)
    await stream.start()
    await stream.append("partial secret detail")

    await stream.fail("处理失败，请稍后重试", error_code="ASSISTANT_ERROR")  # noqa: RUF001

    assert sender.frames[-1]["body"]["stream"] == {
        "id": "stream-1",
        "finish": True,
        "content": "处理失败，请稍后重试",  # noqa: RUF001
    }
    assert recorder.events[-1] == (EPlusReplyStatus.FINISHED, "ASSISTANT_ERROR")
    assert stream.answer == "处理失败，请稍后重试"  # noqa: RUF001


class FakeRedisConnection:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.calls: list[tuple] = []

    async def eval(self, script, numkeys, minute_key, hour_key, minute_cap, hour_cap, minute_ttl, hour_ttl):
        self.calls.append((numkeys, minute_key, hour_key, minute_cap, hour_cap, minute_ttl, hour_ttl))
        minute = self.counts.get(minute_key, 0)
        hour = self.counts.get(hour_key, 0)
        if minute >= int(minute_cap) or hour >= int(hour_cap):
            return 0
        self.counts[minute_key] = minute + 1
        self.counts[hour_key] = hour + 1
        return 1


class FakeRedisClient:
    def __init__(self) -> None:
        self.async_connection = FakeRedisConnection()

    async def acluster_nodes(self, key: str) -> None:
        return None


async def test_redis_quota_enforces_30_per_minute_and_1000_per_hour_with_terminal_reserve() -> None:
    redis = FakeRedisClient()
    quota = RedisReplyQuota(
        redis_client=redis,
        tenant_id=9,
        conversation_id="conversation-1",
        wall_clock=lambda: 3661,
    )

    for _ in range(29):
        assert await quota.reserve(terminal=False) is True
    assert await quota.reserve(terminal=False) is False
    assert await quota.reserve(terminal=True) is True
    assert await quota.reserve(terminal=True) is False

    minute_key = redis.async_connection.calls[0][1]
    hour_key = redis.async_connection.calls[0][2]
    assert "{9:conversation-1}" in minute_key
    assert redis.async_connection.counts[minute_key] == 30
    assert redis.async_connection.counts[hour_key] == 30

    redis.async_connection.counts[hour_key] = 999
    redis.async_connection.counts[minute_key] = 0
    assert await quota.reserve(terminal=False) is False
    assert await quota.reserve(terminal=True) is True
    assert redis.async_connection.counts[hour_key] == 1000
