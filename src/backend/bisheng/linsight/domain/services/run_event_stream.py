"""F004 T012: per-conversation run event log on a Redis Stream (design 决策 4, §4.3).

One Redis Stream per conversation holds the events of the run in progress.
Readers follow it with a cursor (the Stream entry id, sent back by the client as
``Last-Event-ID``). Next to the Stream a hash keeps the accumulated state of the
run (text, thinking, plan, files, pending question). A reader whose cursor is
older than the oldest entry that ``MAXLEN`` kept first receives one ``resync``
event built from that hash, then the increments after it.

Layout (both keys share the hash tag ``{conversation_id}``, design K8):

* ``bisheng:run:events:{<cid>}``   Stream, entry fields ``run_id seq type data ts``
* ``bisheng:run:snapshot:{<cid>}`` Hash, fields ``run_id seq last_id ended status
  text thinking plan files pending_question unread_messages`` (``status`` is the
  type of the terminal event, set together with ``ended``; ``unread_messages``
  is the JSON list a terminal event gave back, kept so that a reader who gets a
  ``resync`` instead of that event still receives the messages)

Rules this module owns:

* ``append`` runs one Lua script: it adds the entry with exact ``MAXLEN``,
  updates the snapshot and sets the expiry. The snapshot therefore always
  describes exactly the entries up to ``last_id``.
* A ``run_started`` event clears the Stream and the snapshot first: the Stream
  only holds the current run, history comes from the database.
* A terminal event (``run_finished`` / ``run_failed`` / ``run_stopped``) sets
  both keys to expire after ``ended_ttl_seconds`` (1 hour). While a run is live
  the keys carry a long safety TTL so a crashed writer cannot leak them.
* ``EventWriter`` merges ``text`` / ``thinking`` events within a 50 ms window
  into one entry before they reach Redis.

Events are plain dicts ``{type, data, run_id?, ts?}`` here; the pydantic schema
for them lives elsewhere. Only Redis 5.0 core commands are used (K8).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from loguru import logger

EVENTS_KEY = "bisheng:run:events:{{{cid}}}"
SNAPSHOT_KEY = "bisheng:run:snapshot:{{{cid}}}"

DEFAULT_MAXLEN = 2000
ENDED_TTL_SECONDS = 3600
LIVE_TTL_SECONDS = 24 * 3600
COALESCE_WINDOW_SECONDS = 0.05

COALESCED_TYPES = frozenset({"text", "thinking"})
TERMINAL_TYPES = frozenset({"run_finished", "run_failed", "run_stopped"})
# Terminal event type -> ``status`` of a ``resync`` event.
TERMINAL_STATUS = {"run_finished": "finished", "run_failed": "failed", "run_stopped": "stopped"}
RESYNC_TYPE = "resync"
HEARTBEAT_TYPE = "heartbeat"
# Field of ``data`` that carries the text delta of ``text`` / ``thinking``.
TEXT_FIELD = "text"
# Field of a terminal event's ``data`` (and of an ended ``resync``) that carries
# the inbox messages given back to the client.
UNREAD_FIELD = "unread_messages"

# Fields of ``data`` that identify a segment of ``text`` / ``thinking`` deltas
# (see ``run_events.TextData``). Deltas merge only when these are all equal, and
# the merged event keeps them.
SEGMENT_FIELDS = ("call_id", "namespace")

# Snapshot operations computed in Python and applied atomically by the script.
_OP_NONE = "none"
_OP_APPEND_TEXT = "append_text"  # arg: delta string, field = event type
_OP_SET_PLAN = "set_plan"  # arg: JSON array of plan items
_OP_PUSH_FILE = "push_file"  # arg: JSON object of one file
_OP_SET_QUESTION = "set_question"  # arg: JSON object of the question
_OP_CLEAR_QUESTION = "clear_question"

# KEYS[1] stream, KEYS[2] snapshot
# ARGV: 1 maxlen, 2 type, 3 run_id, 4 data json, 5 ts, 6 live ttl, 7 ended ttl,
#       8 is_terminal ('1'/'0'), 9 snapshot op, 10 op arg,
#       11 unread_messages json of a terminal event ('' when it has none)
_APPEND_LUA = """
local stream, snap = KEYS[1], KEYS[2]
local typ = ARGV[2]
if typ == 'run_started' then
  redis.call('DEL', stream, snap)
end
local seq = redis.call('HINCRBY', snap, 'seq', 1)
local id = redis.call('XADD', stream, 'MAXLEN', ARGV[1], '*',
  'run_id', ARGV[3], 'seq', tostring(seq), 'type', typ, 'data', ARGV[4], 'ts', ARGV[5])
redis.call('HSET', snap, 'last_id', id, 'run_id', ARGV[3])
local op, arg = ARGV[9], ARGV[10]
if op == 'append_text' then
  local cur = redis.call('HGET', snap, typ)
  if not cur then cur = '' end
  redis.call('HSET', snap, typ, cur .. arg)
elseif op == 'set_plan' then
  redis.call('HSET', snap, 'plan', arg)
elseif op == 'push_file' then
  local cur = redis.call('HGET', snap, 'files')
  if (not cur) or cur == '' or cur == '[]' then
    cur = '[' .. arg .. ']'
  else
    cur = string.sub(cur, 1, -2) .. ',' .. arg .. ']'
  end
  redis.call('HSET', snap, 'files', cur)
elseif op == 'set_question' then
  redis.call('HSET', snap, 'pending_question', arg)
elseif op == 'clear_question' then
  redis.call('HDEL', snap, 'pending_question')
end
if ARGV[8] == '1' then
  redis.call('HSET', snap, 'ended', '1', 'status', typ)
  if ARGV[11] and ARGV[11] ~= '' then
    redis.call('HSET', snap, 'unread_messages', ARGV[11])
  end
end
local ttl = ARGV[6]
if redis.call('HEXISTS', snap, 'ended') == 1 then
  ttl = ARGV[7]
end
redis.call('EXPIRE', stream, ttl)
redis.call('EXPIRE', snap, ttl)
return id
"""

RedisFactory = Callable[[], Awaitable[Any]]


def events_key(conversation_id: str) -> str:
    return EVENTS_KEY.format(cid=conversation_id)


def snapshot_key(conversation_id: str) -> str:
    return SNAPSHOT_KEY.format(cid=conversation_id)


def _parse_id(entry_id: Any) -> tuple[int, int]:
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode()
    ms, _, sq = str(entry_id).partition("-")
    return int(ms), int(sq or 0)


def _s(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _snapshot_op(event: dict) -> tuple[str, str]:
    """Map one event to the change it makes to the accumulated state."""
    typ = event.get("type")
    data = event.get("data") or {}
    if typ in COALESCED_TYPES:
        return _OP_APPEND_TEXT, str(data.get(TEXT_FIELD) or "")
    if typ == "plan":
        return _OP_SET_PLAN, json.dumps(data.get("items") or [], ensure_ascii=False)
    if typ == "file":
        return _OP_PUSH_FILE, json.dumps(data, ensure_ascii=False)
    if typ == "ask_user":
        return _OP_SET_QUESTION, json.dumps(data, ensure_ascii=False)
    if typ in ("ask_user_answered", "run_started") or typ in TERMINAL_TYPES:
        return _OP_CLEAR_QUESTION, ""
    return _OP_NONE, ""


def _terminal_unread(typ: str, data: Any) -> str:
    """JSON of the ``unread_messages`` a terminal event gives back, '' when none.

    ``run_stopped`` (the user stopped the run) and ``run_failed`` (a relay run
    that could not be created) carry them. The snapshot keeps the list, so a
    ``resync`` of the ended run delivers it to a reader that missed the event.
    """
    if typ not in TERMINAL_TYPES or not isinstance(data, dict):
        return ""
    unread = data.get(UNREAD_FIELD)
    if not isinstance(unread, list) or not unread:
        return ""
    return json.dumps(unread, ensure_ascii=False)


def _latest_files(files: list) -> list:
    """One entry per ``file_id``: a file written again replaces its entry, in place."""
    latest: dict[str, Any] = {}
    for item in files:
        if not isinstance(item, dict) or not item.get("file_id"):
            continue
        latest[str(item["file_id"])] = item
    return list(latest.values())


async def _default_redis() -> Any:
    from bisheng.core.cache.redis_manager import get_redis_client

    client = await get_redis_client()
    return client.async_connection


class RunEventStream:
    """Read and write the run event Stream of a conversation.

    ``redis`` is a ``redis.asyncio`` style client (plain, Cluster, or
    ``fakeredis.aioredis`` in tests). When omitted the project client is
    resolved lazily via ``get_redis_client()``.
    """

    def __init__(
        self,
        redis: Any = None,
        *,
        maxlen: int = DEFAULT_MAXLEN,
        ended_ttl_seconds: int = ENDED_TTL_SECONDS,
        live_ttl_seconds: int = LIVE_TTL_SECONDS,
        wall_clock: Callable[[], float] = time.time,
    ):
        if maxlen < 1:
            raise ValueError("maxlen must be positive")
        self._redis = redis
        self.maxlen = maxlen
        self.ended_ttl_seconds = ended_ttl_seconds
        self.live_ttl_seconds = live_ttl_seconds
        self._wall_clock = wall_clock

    async def _client(self) -> Any:
        if self._redis is None:
            self._redis = await _default_redis()
        return self._redis

    def _now_ms(self) -> int:
        return int(self._wall_clock() * 1000)

    # ------------------------------------------------------------------ write

    async def append(self, conversation_id: str, event: dict) -> str:
        """Append one event; return its Stream entry id (strictly increasing)."""
        typ = event.get("type")
        if not typ:
            raise ValueError("event needs a type")
        if typ in (RESYNC_TYPE, HEARTBEAT_TYPE):
            raise ValueError(f"{typ} is produced by the reader, not appended")
        data = event.get("data")
        if data is None:
            data = {}
        ts = event.get("ts")
        if ts is None:
            ts = self._now_ms()
        op, arg = _snapshot_op({"type": typ, "data": data})
        client = await self._client()
        entry_id = await client.eval(
            _APPEND_LUA,
            2,
            events_key(conversation_id),
            snapshot_key(conversation_id),
            str(self.maxlen),
            typ,
            str(event.get("run_id") or ""),
            json.dumps(data, ensure_ascii=False),
            str(int(ts)),
            str(self.live_ttl_seconds),
            str(self.ended_ttl_seconds),
            "1" if typ in TERMINAL_TYPES else "0",
            op,
            arg,
            _terminal_unread(typ, data),
        )
        return _s(entry_id)

    async def update_snapshot(
        self,
        conversation_id: str,
        *,
        text: str | None = None,
        thinking: str | None = None,
        plan: list | None = None,
        files: list | None = None,
        pending_question: Any = ...,
    ) -> None:
        """Overwrite fields of the accumulated state without adding an entry.

        Only for state that is not carried by an event (for example seeding a
        relay run). ``pending_question=None`` clears the pending question.
        """
        mapping: dict[str, str] = {}
        if text is not None:
            mapping["text"] = text
        if thinking is not None:
            mapping["thinking"] = thinking
        if plan is not None:
            mapping["plan"] = json.dumps(plan, ensure_ascii=False)
        if files is not None:
            mapping["files"] = json.dumps(files, ensure_ascii=False)
        if pending_question is not ... and pending_question is not None:
            mapping["pending_question"] = json.dumps(pending_question, ensure_ascii=False)
        key = snapshot_key(conversation_id)
        client = await self._client()
        if mapping:
            await client.hset(key, mapping=mapping)
        if pending_question is None:
            await client.hdel(key, "pending_question")

    # ------------------------------------------------------------------- read

    @staticmethod
    def _decode_snapshot(raw: dict) -> dict | None:
        if not raw:
            return None
        h = {_s(k): _s(v) for k, v in raw.items()}
        snap: dict[str, Any] = {
            "run_id": h.get("run_id") or "",
            "seq": int(h.get("seq") or 0),
            "last_id": h.get("last_id"),
            "ended": h.get("ended") == "1",
            "text": h.get("text") or "",
            "thinking": h.get("thinking") or "",
            "plan": json.loads(h["plan"]) if h.get("plan") else [],
            "files": _latest_files(json.loads(h["files"]) if h.get("files") else []),
        }
        if snap["ended"]:
            # ``run_finished`` -> ``finished``. None for a snapshot written before
            # the status was recorded.
            snap["status"] = TERMINAL_STATUS.get(h.get("status") or "")
            if h.get(UNREAD_FIELD):
                snap[UNREAD_FIELD] = json.loads(h[UNREAD_FIELD])
        if h.get("pending_question"):
            snap["pending_question"] = json.loads(h["pending_question"])
        return snap

    async def snapshot(self, conversation_id: str) -> dict | None:
        """Accumulated state of the current run, or None when nothing is live."""
        client = await self._client()
        return self._decode_snapshot(await client.hgetall(snapshot_key(conversation_id)))

    async def _read_state(self, conversation_id: str) -> tuple[dict | None, int, str | None]:
        """Snapshot, Stream length and oldest entry id, read in one transaction."""
        client = await self._client()
        async with client.pipeline(transaction=True) as pipe:
            pipe.hgetall(snapshot_key(conversation_id))
            pipe.xlen(events_key(conversation_id))
            pipe.xrange(events_key(conversation_id), "-", "+", count=1)
            raw, length, first = await pipe.execute()
        first_id = _s(first[0][0]) if first else None
        return self._decode_snapshot(raw), int(length or 0), first_id

    def _resync_event(self, snap: dict) -> dict:
        data: dict[str, Any] = {
            "text": snap["text"],
            "thinking": snap["thinking"],
            "plan": snap["plan"],
            "files": snap["files"],
            # The run this state belongs to is over: the reader must not wait for
            # more events of it. ``status`` says how it ended, when known.
            "ended": bool(snap.get("ended")),
        }
        if snap.get("ended") and snap.get("status"):
            data["status"] = snap["status"]
        if snap.get("ended") and snap.get(UNREAD_FIELD):
            # The terminal event gave these messages back; a reader that only
            # gets this resync must receive them too (same shape as the event).
            data[UNREAD_FIELD] = snap[UNREAD_FIELD]
        if "pending_question" in snap:
            data["pending_question"] = snap["pending_question"]
        return {
            "id": snap["last_id"],
            "run_id": snap["run_id"],
            "seq": snap["seq"],
            "type": RESYNC_TYPE,
            "data": data,
            "ts": self._now_ms(),
        }

    @staticmethod
    def _decode_entry(entry_id: Any, fields: dict) -> dict:
        f = {_s(k): _s(v) for k, v in fields.items()}
        try:
            data = json.loads(f.get("data") or "{}")
        except ValueError:
            logger.warning("run event {} carries non-JSON data, passing it as a string", _s(entry_id))
            data = f.get("data")
        return {
            "id": _s(entry_id),
            "run_id": f.get("run_id") or "",
            "seq": int(f.get("seq") or 0),
            "type": f.get("type"),
            "data": data,
            "ts": int(f.get("ts") or 0),
        }

    @staticmethod
    def _normalize_cursor(cursor: str | None) -> str:
        if cursor in (None, "", "0"):
            return "0-0"
        try:
            ms, sq = _parse_id(cursor)
        except ValueError:
            logger.warning("run event cursor {!r} is malformed, reading from the start", cursor)
            return "0-0"
        return f"{ms}-{sq}"

    async def read(
        self,
        conversation_id: str,
        cursor: str | None = None,
        *,
        follow: bool = False,
        block_ms: int = 15000,
        count: int = 200,
        heartbeat: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield the events after ``cursor`` (exclusive).

        * If entries between ``cursor`` and the oldest kept entry were trimmed,
          the first yielded event is ``resync`` (the accumulated state, ``id`` =
          the entry it covers up to) and reading continues after it.
        * ``follow=False`` stops at the end of the Stream. ``follow=True`` blocks
          for new entries and stops after a terminal event, or when the Stream
          no longer exists (expired or never started).
        * ``heartbeat=True`` yields ``{"type": "heartbeat"}`` after each block
          timeout so an SSE layer can keep the connection alive.
        """
        key = events_key(conversation_id)
        cur = self._normalize_cursor(cursor)
        client = await self._client()

        snap, length, first_id = await self._read_state(conversation_id)
        if first_id is None and snap is None:
            return
        last_seq: int | None = None
        # MAXLEN trimmed something (seq counts every entry of the run, the Stream
        # holds fewer) and the cursor is older than the oldest kept entry: the
        # reader may have missed entries, so hand it the accumulated state.
        if snap is not None and first_id is not None and snap["seq"] > length and _parse_id(cur) < _parse_id(first_id):
            yield self._resync_event(snap)
            cur = snap["last_id"]
            last_seq = snap["seq"]
            if follow and snap["ended"]:
                return

        while True:
            if follow:
                resp = await client.xread({key: cur}, count=count, block=block_ms)
            else:
                resp = await client.xread({key: cur}, count=count)
            entries = resp[0][1] if resp else []
            if not entries:
                if not follow:
                    return
                if not await client.exists(key):
                    return
                if heartbeat:
                    yield {"type": HEARTBEAT_TYPE}
                continue
            gap = False
            for entry_id, fields in entries:
                ev = self._decode_entry(entry_id, fields)
                if last_seq is not None and ev["seq"] != 1 and ev["seq"] != last_seq + 1:
                    gap = True
                    break
                last_seq = ev["seq"]
                cur = ev["id"]
                yield ev
                if follow and ev["type"] in TERMINAL_TYPES:
                    return
            if gap:
                # The reader fell behind MAXLEN while reading: replace with the
                # accumulated state and continue after it.
                snap, _, _ = await self._read_state(conversation_id)
                if snap is None:
                    return
                logger.info(
                    "run event reader of {} fell behind at seq {}, sending resync up to seq {}",
                    conversation_id,
                    last_seq,
                    snap["seq"],
                )
                yield self._resync_event(snap)
                cur = snap["last_id"]
                last_seq = snap["seq"]
                if follow and snap["ended"]:
                    return
            elif not follow and len(entries) < count:
                return


class EventWriter:
    """Write the events of one run, merging ``text`` / ``thinking`` deltas.

    Consecutive deltas of the same type, ``call_id`` and ``namespace`` are
    buffered and written as one entry that keeps those fields. The buffer is
    written when the window (50 ms from the first buffered delta) has passed,
    when an event of another type or another segment arrives, or when
    ``flush()`` is called. A background
    timer flushes a buffer that no later event closes. The buffer only lives
    for the window; the run state itself is in Redis.
    """

    def __init__(
        self,
        stream: RunEventStream,
        conversation_id: str,
        run_id: str,
        *,
        window_seconds: float = COALESCE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ):
        self.stream = stream
        self.conversation_id = conversation_id
        self.run_id = run_id
        self.window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._buf_type: str | None = None
        self._buf_parts: list[str] = []
        # call_id / namespace of the buffered segment (only the fields that are set).
        self._buf_segment: dict[str, str] = {}
        self._buf_started: float = 0.0
        self._timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def emit(self, event: dict) -> str | None:
        """Accept one event. Returns the entry id when something was written."""
        typ = event.get("type")
        async with self._lock:
            if typ in COALESCED_TYPES:
                data = event.get("data") or {}
                segment = {k: data[k] for k in SEGMENT_FIELDS if data.get(k) is not None}
                written = None
                if self._buf_type is not None and (
                    self._buf_type != typ
                    or self._buf_segment != segment
                    or self._clock() - self._buf_started >= self.window_seconds
                ):
                    written = await self._flush_locked()
                if self._buf_type is None:
                    self._buf_type = typ
                    self._buf_segment = segment
                    self._buf_started = self._clock()
                    self._start_timer()
                self._buf_parts.append(str(data.get(TEXT_FIELD) or ""))
                return written
            await self._flush_locked()
            return await self.stream.append(self.conversation_id, {**event, "run_id": self.run_id})

    async def flush(self) -> str | None:
        async with self._lock:
            return await self._flush_locked()

    async def aclose(self) -> None:
        await self.flush()
        self._cancel_timer()

    async def _flush_locked(self) -> str | None:
        if self._buf_type is None:
            return None
        typ, text, segment = self._buf_type, "".join(self._buf_parts), self._buf_segment
        self._buf_type, self._buf_parts, self._buf_segment = None, [], {}
        self._cancel_timer()
        return await self.stream.append(
            self.conversation_id, {"type": typ, "run_id": self.run_id, "data": {TEXT_FIELD: text, **segment}}
        )

    def _start_timer(self) -> None:
        self._cancel_timer()
        self._timer = asyncio.get_running_loop().create_task(self._timer_flush())

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task() and not timer.done():
            timer.cancel()

    async def _timer_flush(self) -> None:
        try:
            await self._sleep(self.window_seconds)
            async with self._lock:
                if self._timer is asyncio.current_task():
                    self._timer = None
                    await self._flush_locked()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("run event writer of {} failed to flush its text buffer", self.conversation_id)
