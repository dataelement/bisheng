"""F004 T043: message rows of the unified runtime that no live HTTP request writes.

Three cases, all needed in more than one process (API node and Linsight
worker), so nothing here lives in process memory (C8):

1. **Steer rows.** A message sent while a run holds the conversation gets its
   question row at once, with ``extra = {run_id, steer_message_id, queued}``
   (AC-13). When the run reads the message it emits ``steer_read`` and the
   ``queued`` key is removed (AC-14). The run may execute in another process
   than the one that wrote the row, and it may read the message before the row
   exists; ``bind_steer_row`` / ``mark_steer_read`` settle both orders through
   one Redis hash.

2. **Answer row of a direct run that has no projector of its own.** A relay run
   executes in the worker (``relay_run_hooks``); a run whose process died is
   closed by whoever notices the lapsed lease (``persist_expired_direct_answer``);
   a run parked on a question is closed by the stop request
   (``persist_stopped_direct_answer``). The last two rebuild the row from the
   accumulated text in the Redis snapshot.

3. **Who a direct run answers for.** ``remember_direct_run`` keeps the few
   values such a row needs (user, model display name, model id, tenant).

Redis contract (same hash tag ``{<cid>}`` as every key of the conversation)
---------------------------------------------------------------------------

``bisheng:run:steer:{<cid>}`` -- HASH, field = inbox ``message_id``.
    ``{"id": <row id>, "run_id": ...}``  the row is written and still queued;
    ``read``                             the run read the message before the row
                                         was bound.
    A field is removed once the row is settled.

``bisheng:run:direct:{<cid>}`` -- HASH of the conversation's latest direct run:
    ``run_id user_id tenant_id sender model_id``, plus ``answer_saved`` once a
    row was written here for that run (so two recoveries write one row).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from bisheng.linsight.domain.schemas import run_events
from bisheng.workstation.domain.services.run_lease import STATE_TTL_SECONDS

STEER_KEY_PREFIX = "bisheng:run:steer:"
DIRECT_RUN_KEY_PREFIX = "bisheng:run:direct:"
KEY_TTL_SECONDS = STATE_TTL_SECONDS
READ_MARK = "read"
# How many of the newest rows are checked for an answer row of the same run.
RECENT_ROWS = 50

EventHook = Callable[[dict], Awaitable[None]]


def steer_key(conversation_id: str) -> str:
    return f"{STEER_KEY_PREFIX}{{{conversation_id}}}"


def direct_run_key(conversation_id: str) -> str:
    return f"{DIRECT_RUN_KEY_PREFIX}{{{conversation_id}}}"


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


async def _redis() -> Any:
    from bisheng.core.cache.redis_manager import get_redis_client

    return (await get_redis_client()).async_connection


# --------------------------------------------------------------------------- #
# Steer rows
# --------------------------------------------------------------------------- #


def steer_extra(run_id: str, message_id: str, *, queued: bool) -> dict:
    """``extra`` of a steer question row. ``queued`` is present only while unread."""
    extra: dict[str, Any] = {"run_id": run_id, "steer_message_id": message_id}
    if queued:
        extra["queued"] = True
    return extra


async def _clear_queued(row_id: int, run_id: str, message_id: str) -> None:
    from bisheng.database.models.message import ChatMessageDao

    # The row's ``extra`` was written by ``steer_extra`` and nothing else edits
    # it, so the new value is known without reading the row back.
    await ChatMessageDao.update_fields_by_id(
        row_id, extra=json.dumps(steer_extra(run_id, message_id, queued=False), ensure_ascii=False)
    )


async def bind_steer_row(redis: Any, conversation_id: str, message_id: str, row_id: int, run_id: str) -> bool:
    """Tell the reader which row belongs to ``message_id``. Returns whether it is still queued.

    When the run read the message before this call, the mark is cleared here.
    """
    key = steer_key(conversation_id)
    value = json.dumps({"id": row_id, "run_id": run_id})
    if await redis.hsetnx(key, message_id, value):
        await redis.expire(key, KEY_TTL_SECONDS)
        return True
    # ``mark_steer_read`` came first and left its mark.
    await _clear_queued(row_id, run_id, message_id)
    await redis.hdel(key, message_id)
    return False


async def mark_steer_read(conversation_id: str, message_id: str, *, redis: Any = None) -> bool:
    """The run read ``message_id``: remove the "queued" mark of its row. Returns whether a row changed."""
    if not message_id:
        return False
    redis = redis if redis is not None else await _redis()
    key = steer_key(conversation_id)
    if await redis.hsetnx(key, message_id, READ_MARK):
        # The row is not bound yet; ``bind_steer_row`` finds this mark.
        await redis.expire(key, KEY_TTL_SECONDS)
        return False
    value = _s(await redis.hget(key, message_id))
    if not value or value == READ_MARK:
        return False
    bound = json.loads(value)
    await _clear_queued(int(bound["id"]), str(bound.get("run_id") or ""), message_id)
    await redis.hdel(key, message_id)
    logger.info(
        "steer message {} of conversation={} was read; row {} updated", message_id, conversation_id, bound["id"]
    )
    return True


def steer_read_hook(conversation_id: str, *, redis: Any = None) -> EventHook:
    """Event hook of a direct run (``DirectRunner`` logs a hook that raises)."""

    async def on_event(event: dict) -> None:
        if event.get("type") == run_events.STEER_READ:
            await mark_steer_read(conversation_id, str((event.get("data") or {}).get("message_id") or ""), redis=redis)

    return on_event


async def on_run_event(conversation_id: str, event: dict, *, redis: Any = None) -> None:
    """For an event sink without hooks (the planned run in the worker). Never raises."""
    if event.get("type") != run_events.STEER_READ:
        return
    message_id = str((event.get("data") or {}).get("message_id") or "")
    try:
        await mark_steer_read(conversation_id, message_id, redis=redis)
    except Exception:
        # The message reached the model; only the "queued" label of its row is
        # stale until the next read of the history.
        logger.exception(
            "could not clear the queued mark of steer message {} in conversation={}", message_id, conversation_id
        )


# --------------------------------------------------------------------------- #
# Direct run: who it answers for
# --------------------------------------------------------------------------- #


async def remember_direct_run(
    redis: Any,
    conversation_id: str,
    run_id: str,
    *,
    user_id: int,
    tenant_id: int | None,
    sender: str,
    model_id: Any = None,
) -> None:
    key = direct_run_key(conversation_id)
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.hset(
            key,
            mapping={
                "run_id": run_id,
                "user_id": str(user_id),
                "tenant_id": str(tenant_id or ""),
                "sender": sender or "",
                "model_id": "" if model_id is None else str(model_id),
            },
        )
        pipe.expire(key, KEY_TTL_SECONDS)
        await pipe.execute()


async def direct_run_info(redis: Any, conversation_id: str) -> dict | None:
    raw = await redis.hgetall(direct_run_key(conversation_id))
    if not raw:
        return None
    info = {_s(k): _s(v) for k, v in raw.items()}
    return {
        "run_id": info.get("run_id") or "",
        "user_id": int(info["user_id"]) if info.get("user_id") else None,
        "tenant_id": int(info["tenant_id"]) if info.get("tenant_id") else None,
        "sender": info.get("sender") or "",
        "model_id": info.get("model_id") or None,
    }


# --------------------------------------------------------------------------- #
# Answer rows written outside the request that started the run
# --------------------------------------------------------------------------- #


async def relay_run_hooks(item: dict, *, redis: Any = None) -> tuple[list[EventHook], str | None]:
    """Hooks of a direct relay run executed by the worker, and the model it should use.

    A relay item carries no model: the run answers with the model of the
    conversation's previous direct run, and its row shows that model's name.
    Returns ``(hooks, model_id)``; ``model_id`` is None when nothing is known.
    """
    from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

    redis = redis if redis is not None else await _redis()
    conversation_id, run_id = item["conversation_id"], item["run_id"]
    previous = await direct_run_info(redis, conversation_id) or {}
    model_id = item.get("model_id") or previous.get("model_id")
    sender = previous.get("sender") or ""
    await remember_direct_run(
        redis,
        conversation_id,
        run_id,
        user_id=item["user_id"],
        tenant_id=item.get("tenant_id"),
        sender=sender,
        model_id=model_id,
    )
    projector = DirectRunProjector(
        run_id=run_id, conversation_id=conversation_id, user_id=int(item["user_id"]), sender=sender
    )
    return [projector.on_event, steer_read_hook(conversation_id, redis=redis)], model_id


async def _answer_row_exists(conversation_id: str, run_id: str) -> bool:
    from bisheng.database.models.message import ChatMessageDao

    for row in await ChatMessageDao.aget_messages_by_chat_id(conversation_id, limit=RECENT_ROWS):
        if not row.is_bot or not row.extra:
            continue
        try:
            extra = json.loads(row.extra)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(extra, dict) and extra.get("run_id") == run_id:
            return True
    return False


async def _persist_from_snapshot(
    redis: Any, conversation_id: str, run_id: str, text: str, terminal_event: dict
) -> Any | None:
    """Write the answer row of a direct run nobody else will write. At most one row per run."""
    from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id, set_current_tenant_id
    from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

    info = await direct_run_info(redis, conversation_id)
    if info is None or info["run_id"] != run_id or info["user_id"] is None:
        # Not a direct run this module knows (a planned run keeps its own record).
        return None
    if not await redis.hsetnx(direct_run_key(conversation_id), "answer_saved", run_id):
        return None

    token = None
    if get_current_tenant_id() is None and info["tenant_id"]:
        # A worker may notice the lapsed lease outside any tenant context.
        token = set_current_tenant_id(info["tenant_id"])
    try:
        if await _answer_row_exists(conversation_id, run_id):
            # The run saved its row and died before it released the conversation.
            return None
        projector = DirectRunProjector(
            run_id=run_id, conversation_id=conversation_id, user_id=info["user_id"], sender=info["sender"]
        )
        if text:
            projector.final_msg = text
            projector.events.append({"type": "text", "content": text})
        await projector.on_event(terminal_event)
        return projector.answer_row
    finally:
        if token is not None:
            current_tenant_id.reset(token)


async def _snapshot_text(redis: Any, conversation_id: str, run_id: str) -> str:
    from bisheng.linsight.domain.services.run_event_stream import RunEventStream

    snapshot = await RunEventStream(redis).snapshot(conversation_id)
    if snapshot is None or snapshot.get("run_id") != run_id:
        # The stream still holds an earlier run: this run wrote nothing.
        return ""
    return snapshot.get("text") or ""


async def persist_expired_direct_answer(
    conversation_id: str, run_id: str, failure: dict, *, redis: Any = None
) -> Any | None:
    """A direct run stopped renewing its lease: save what it had written as a failed answer.

    Call this BEFORE ``run_failed`` is appended for the run (the snapshot must
    still belong to it). ``failure`` is the ``data`` of that ``run_failed``.
    Best effort: a failure is logged and never raised, and never writes a second row.
    """
    try:
        redis = redis if redis is not None else await _redis()
        text = await _snapshot_text(redis, conversation_id, run_id)
        row = await _persist_from_snapshot(
            redis,
            conversation_id,
            run_id,
            text,
            {"type": run_events.RUN_FAILED, "run_id": run_id, "data": dict(failure)},
        )
    except Exception:
        logger.exception(
            "could not save the answer row of expired direct run={} conversation={}", run_id, conversation_id
        )
        return None
    if row is not None:
        logger.warning(
            "expired direct run={} conversation={}: saved a failed answer row {} with {} characters",
            run_id,
            conversation_id,
            row.id,
            len(text),
        )
    return row


async def persist_stopped_direct_answer(
    conversation_id: str, run_id: str, text: str, *, redis: Any = None
) -> Any | None:
    """A direct run parked on a question was stopped: save what it had written (marked like a stopped turn)."""
    redis = redis if redis is not None else await _redis()
    return await _persist_from_snapshot(
        redis,
        conversation_id,
        run_id,
        text,
        {"type": run_events.RUN_STOPPED, "run_id": run_id, "data": {"reason": "user"}},
    )
