"""Bounded cumulative E+ reply streaming with ACK and quota enforcement."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from bisheng.eplus.domain.models.eplus import EPlusReplyStatus
from bisheng.eplus.infrastructure.protocol import MAX_STREAM_BYTES, build_stream_frame, truncate_utf8

DEFAULT_PLACEHOLDER = "处理中"
TIMEOUT_REPLY = "处理超时，请稍后重试"  # noqa: RUF001
CONTENT_TRUNCATED_SUFFIX = "\n\n[内容过长，已截断]"  # noqa: RUF001

_QUOTA_SCRIPT = """
local minute_count = tonumber(redis.call('GET', KEYS[1]) or '0')
local hour_count = tonumber(redis.call('GET', KEYS[2]) or '0')
if minute_count >= tonumber(ARGV[1]) or hour_count >= tonumber(ARGV[2]) then
  return 0
end
minute_count = redis.call('INCR', KEYS[1])
hour_count = redis.call('INCR', KEYS[2])
if minute_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[3]) end
if hour_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[4]) end
return 1
"""


class EPlusReplyError(RuntimeError):
    """Base error for an E+ reply stream."""


class EPlusReplyAckError(EPlusReplyError):
    """The E+ service did not accept a reply frame."""


class EPlusReplyQuotaExceeded(EPlusReplyError):
    """No E+ send slot remains for the requested frame."""


class EPlusReplyDeadlineExceeded(EPlusReplyError):
    """The reply stream reached its hard execution deadline."""


class EPlusFrameSender(Protocol):
    async def send_with_ack(self, frame: dict[str, Any]) -> Mapping[str, Any] | None: ...


class EPlusReplyQuota(Protocol):
    async def reserve(self, *, terminal: bool) -> bool: ...


class EPlusReplyStateRecorder(Protocol):
    async def record(self, status: EPlusReplyStatus, *, error_code: str | None = None) -> None: ...


class RedisReplyQuota:
    """Atomic fixed-window E+ send quota stored in Redis.

    Non-terminal frames can consume at most 29/minute and 999/hour so one
    protocol slot remains available for ``finish=true``.
    """

    def __init__(
        self,
        *,
        redis_client: Any,
        tenant_id: int,
        conversation_id: str,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis = redis_client
        self._tenant_id = int(tenant_id)
        self._conversation_id = str(conversation_id)
        self._wall_clock = wall_clock

    async def reserve(self, *, terminal: bool) -> bool:
        now = int(self._wall_clock())
        slot = f"{{{self._tenant_id}:{self._conversation_id}}}"
        minute_key = f"eplus:reply_quota:{slot}:minute:{now // 60}"
        hour_key = f"eplus:reply_quota:{slot}:hour:{now // 3600}"
        minute_cap = 30 if terminal else 29
        hour_cap = 1000 if terminal else 999
        await self._redis.acluster_nodes(minute_key)
        result = await self._redis.async_connection.eval(
            _QUOTA_SCRIPT,
            2,
            minute_key,
            hour_key,
            minute_cap,
            hour_cap,
            120,
            7200,
        )
        return bool(result)


class EPlusReplyStream:
    """Aggregate model fragments into cumulative, acknowledged E+ frames."""

    def __init__(
        self,
        *,
        sender: EPlusFrameSender,
        quota: EPlusReplyQuota,
        recorder: EPlusReplyStateRecorder,
        req_id: str,
        stream_id: str,
        clock: Callable[[], float] = time.monotonic,
        flush_interval_seconds: float = 1.5,
        flush_bytes: int = 512,
        deadline_seconds: float = 300,
    ) -> None:
        if flush_interval_seconds <= 0 or flush_bytes <= 0 or deadline_seconds <= 0:
            raise ValueError("reply stream timing and size limits must be positive")
        self._sender = sender
        self._quota = quota
        self._recorder = recorder
        self._req_id = req_id
        self._stream_id = stream_id
        self._clock = clock
        self._flush_interval = float(flush_interval_seconds)
        self._flush_bytes = int(flush_bytes)
        self._deadline_seconds = float(deadline_seconds)
        self._answer = ""
        self._started_at: float | None = None
        self._last_flush_at: float | None = None
        self._last_flushed_bytes = 0
        self._finished = False
        self._send_lock = asyncio.Lock()

    @property
    def answer(self) -> str:
        return self._answer

    @property
    def finished(self) -> bool:
        return self._finished

    async def start(self, placeholder: str = DEFAULT_PLACEHOLDER) -> None:
        if self._started_at is not None:
            raise EPlusReplyError("reply stream has already started")
        now = self._clock()
        await self._send(placeholder, finish=False, terminal=False, required=True)
        self._started_at = now
        self._last_flush_at = now
        await self._recorder.record(EPlusReplyStatus.STREAMING)

    async def append(self, fragment: str) -> bool:
        self._require_started()
        if self._finished:
            return False
        if self._deadline_reached():
            await self._finish_timeout()
            raise EPlusReplyDeadlineExceeded("E+ reply deadline exceeded")
        if not isinstance(fragment, str):
            raise TypeError("reply fragment must be a string")
        if not fragment:
            return False

        candidate = self._answer + fragment
        suffix_bytes = len(CONTENT_TRUNCATED_SUFFIX.encode("utf-8"))
        truncated, did_truncate = truncate_utf8(candidate, MAX_STREAM_BYTES - suffix_bytes)
        if did_truncate:
            self._answer = truncated + CONTENT_TRUNCATED_SUFFIX
            sent = await self._send(self._answer, finish=True, terminal=True, required=True)
            self._finished = True
            await self._recorder.record(EPlusReplyStatus.FINISHED)
            return sent

        self._answer = candidate
        answer_bytes = len(self._answer.encode("utf-8"))
        now = self._clock()
        last_flush_at = self._last_flush_at if self._last_flush_at is not None else now
        interval_elapsed = now - last_flush_at >= self._flush_interval
        threshold_reached = answer_bytes - self._last_flushed_bytes >= self._flush_bytes
        if not interval_elapsed and not threshold_reached:
            return False
        return await self._flush_nonterminal(now=now, answer_bytes=answer_bytes)

    async def finish(self) -> None:
        self._require_started()
        if self._finished:
            return
        if self._deadline_reached():
            await self._finish_timeout()
            raise EPlusReplyDeadlineExceeded("E+ reply deadline exceeded")
        await self._send(self._answer, finish=True, terminal=True, required=True)
        self._finished = True
        await self._recorder.record(EPlusReplyStatus.FINISHED)

    async def _flush_nonterminal(self, *, now: float, answer_bytes: int) -> bool:
        sent = await self._send(self._answer, finish=False, terminal=False, required=False)
        if sent:
            self._last_flush_at = now
            self._last_flushed_bytes = answer_bytes
        return sent

    async def _finish_timeout(self) -> None:
        await self._send(TIMEOUT_REPLY, finish=True, terminal=True, required=True)
        self._finished = True
        await self._recorder.record(EPlusReplyStatus.FINISHED, error_code="ASSISTANT_TIMEOUT")

    async def _send(self, content: str, *, finish: bool, terminal: bool, required: bool) -> bool:
        async with self._send_lock:
            return await self._send_locked(content, finish=finish, terminal=terminal, required=required)

    async def _send_locked(self, content: str, *, finish: bool, terminal: bool, required: bool) -> bool:
        if not await self._quota.reserve(terminal=terminal):
            if not required:
                return False
            await self._mark_send_failed("EPLUS_REPLY_RATE_LIMIT")
            raise EPlusReplyQuotaExceeded("E+ reply quota exhausted")

        frame = build_stream_frame(self._req_id, self._stream_id, content, finish=finish)
        try:
            ack = await self._sender.send_with_ack(frame)
        except TimeoutError as exc:
            await self._mark_send_failed("EPLUS_ACK_TIMEOUT")
            raise EPlusReplyAckError("E+ reply ACK timeout") from exc
        except Exception as exc:
            await self._mark_send_failed("EPLUS_SEND_ERROR")
            raise EPlusReplyAckError("E+ reply send failed") from exc

        if ack is not None and int(ack.get("errcode", -1)) != 0:
            error_code = ack.get("errcode")
            await self._mark_send_failed("EPLUS_ACK_REJECTED")
            raise EPlusReplyAckError(f"E+ rejected reply frame with errcode={error_code}")
        return True

    async def _mark_send_failed(self, error_code: str) -> None:
        self._finished = True
        await self._recorder.record(EPlusReplyStatus.SEND_FAILED, error_code=error_code)

    def _deadline_reached(self) -> bool:
        return self._started_at is not None and self._clock() - self._started_at >= self._deadline_seconds

    def _require_started(self) -> None:
        if self._started_at is None:
            raise EPlusReplyError("reply stream has not started")
