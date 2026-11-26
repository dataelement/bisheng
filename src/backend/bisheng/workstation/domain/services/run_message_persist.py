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
   answer events kept at the last park (``parked_answer``) and the accumulated
   text in the Redis snapshot.

3. **Who a direct run answers for.** ``remember_direct_run`` keeps the few
   values such a row needs (user, model display name, model id, tenant).

Redis contract (same hash tag ``{<cid>}`` as every key of the conversation)
---------------------------------------------------------------------------

``bisheng:run:steer:{<cid>}`` -- HASH, field = inbox ``message_id``.
    ``{"id": <row id>, "run_id": ...}``  the row is written and still queued;
    ``read``                             the run read the message before the row
                                         was bound.
    ``discarded``                        the user stopped the run before it read
                                         the message, and the row was not bound
                                         yet (``discard_unread``).
    A field is removed once the row is settled.

``bisheng:run:relay_read:{<cid>}`` -- STRING, JSON ``{"run_id", "message_ids"}``.
    The inbox messages a planned relay run took as its input. The worker that
    created the run record writes it; the worker that executes the run (maybe
    another node) takes it right after ``run_started`` and emits ``steer_read``
    for each message, which clears the "queued" mark of its row.

``bisheng:run:direct:{<cid>}`` -- HASH of the conversation's latest direct run:
    ``run_id user_id tenant_id sender model_id``, plus ``answer_saved`` once a
    row was written here for that run (so two recoveries write one row), plus
    ``parked_answer`` (JSON ``{"msg", "events"}``) once the run asked the user:
    the answer row as the parking execution had it, written once per question
    by that execution's projector (``save_parked_answer``). The execution that
    resumes the run starts its projector from it (``seed_parked_answer``) and
    keeps it on the hash (``remember_direct_run(parked_answer=...)``).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from bisheng.linsight.domain.schemas import run_events
from bisheng.workstation.domain.services.run_lease import STATE_TTL_SECONDS

STEER_KEY_PREFIX = "bisheng:run:steer:"
RELAY_READ_KEY_PREFIX = "bisheng:run:relay_read:"
DIRECT_RUN_KEY_PREFIX = "bisheng:run:direct:"
KEY_TTL_SECONDS = STATE_TTL_SECONDS
PARKED_ANSWER_FIELD = "parked_answer"
READ_MARK = "read"
DISCARD_MARK = "discarded"
# How many of the newest rows are checked for an answer row of the same run.
RECENT_ROWS = 50

EventHook = Callable[[dict], Awaitable[None]]


def steer_key(conversation_id: str) -> str:
    return f"{STEER_KEY_PREFIX}{{{conversation_id}}}"


def relay_read_key(conversation_id: str) -> str:
    return f"{RELAY_READ_KEY_PREFIX}{{{conversation_id}}}"


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
    mark = _s(await redis.hget(key, message_id))
    await redis.hdel(key, message_id)
    if mark == DISCARD_MARK:
        # The run was stopped before it read the message: the text went back to
        # the client, so the row written a moment ago must not stay in the history.
        from bisheng.database.models.message import ChatMessageDao

        await ChatMessageDao.adelete_by_id_in_chat(row_id, conversation_id)
        return False
    # ``mark_steer_read`` came first and left its mark.
    await _clear_queued(row_id, run_id, message_id)
    return False


async def discard_unread(dispatch: Any, conversation_id: str, *, redis: Any = None) -> list[dict]:
    """The user stopped the run: take the unread inbox messages back (design §7 item 6).

    The messages leave the inbox (no relay run answers them) and their question
    rows are deleted, because the client puts the text back into the input box
    and the user sends it again or drops it. Returns the ``unread_messages``
    list of the ``run_stopped`` event and of the stop response:
    ``[{message_id, text, files}]``.

    Deleting a row is best effort: the messages are already out of the inbox, so
    a failure is logged and the list is still returned (the row then stays in
    the history with its "queued" mark).
    """
    messages = await dispatch.discard_inbox(conversation_id)
    if not messages:
        return []
    return await forget_steer_rows(conversation_id, messages, redis=redis)


async def forget_steer_rows(conversation_id: str, messages: list[dict], *, redis: Any = None) -> list[dict]:
    """Delete the question rows of inbox messages no run will answer; return them as ``unread_messages``.

    ``messages`` were already taken out of the inbox by the caller.
    """
    from bisheng.workstation.domain.services.run_dispatch import unread_view

    redis = redis if redis is not None else await _redis()
    key = steer_key(conversation_id)
    for message in messages:
        message_id = str(message.get("message_id") or "")
        if not message_id:
            continue
        try:
            if await redis.hsetnx(key, message_id, DISCARD_MARK):
                # The row is not bound yet; ``bind_steer_row`` finds this mark and deletes it.
                await redis.expire(key, KEY_TTL_SECONDS)
                continue
            value = _s(await redis.hget(key, message_id))
            await redis.hdel(key, message_id)
            if value and value not in (READ_MARK, DISCARD_MARK):
                from bisheng.database.models.message import ChatMessageDao

                await ChatMessageDao.adelete_by_id_in_chat(int(json.loads(value)["id"]), conversation_id)
        except Exception:
            logger.exception(
                "could not delete the question row of discarded message {} in conversation={}",
                message_id,
                conversation_id,
            )
    return unread_view(messages)


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
# Planned relay run: the inbox messages it answers
# --------------------------------------------------------------------------- #


async def remember_relay_messages(redis: Any, conversation_id: str, run_id: str, message_ids: list[str]) -> None:
    await redis.set(
        relay_read_key(conversation_id),
        json.dumps({"run_id": run_id, "message_ids": [m for m in message_ids if m]}),
        ex=KEY_TTL_SECONDS,
    )


async def take_relay_messages(redis: Any, conversation_id: str, run_id: str) -> list[str]:
    """The message ids ``remember_relay_messages`` stored for ``run_id``, taken once."""
    key = relay_read_key(conversation_id)
    raw = _s(await redis.get(key))
    if not raw:
        return []
    stored = json.loads(raw)
    if stored.get("run_id") != run_id:
        # Left by a relay run that never executed; a newer value replaces it.
        return []
    await redis.delete(key)
    return [str(m) for m in stored.get("message_ids") or []]


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
    storage_partition: str | None = None,
    parked_answer: str | None = None,
) -> None:
    """``storage_partition``: the caller's file partition (Open API); empty = the user's own.

    ``parked_answer``: the raw ``parked_answer`` of the run, kept by a resumed
    execution (``parked_answer_raw``); the hash is rewritten otherwise.
    """
    key = direct_run_key(conversation_id)
    mapping = {
        "run_id": run_id,
        "user_id": str(user_id),
        "tenant_id": str(tenant_id or ""),
        "sender": sender or "",
        "model_id": "" if model_id is None else str(model_id),
        "storage_partition": storage_partition or "",
    }
    if parked_answer:
        mapping[PARKED_ANSWER_FIELD] = parked_answer
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, _parked_ttl() if parked_answer else KEY_TTL_SECONDS)
        await pipe.execute()


def _parked_ttl() -> int:
    """At least as long as the parked run's event stream lives (design §5 #26)."""
    from bisheng.linsight.domain.services.run_event_stream import PARKED_TTL_SECONDS

    return max(KEY_TTL_SECONDS, PARKED_TTL_SECONDS)


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
        "storage_partition": info.get("storage_partition") or None,
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
        storage_partition=previous.get("storage_partition"),
    )
    projector = DirectRunProjector(
        run_id=run_id,
        conversation_id=conversation_id,
        user_id=int(item["user_id"]),
        sender=sender,
        storage_partition=previous.get("storage_partition"),
        on_parked=lambda state: save_parked_answer(redis, conversation_id, run_id, state),
    )
    return [projector.on_event, steer_read_hook(conversation_id, redis=redis)], model_id


# --------------------------------------------------------------------------- #
# Direct run: questions the user answered
# --------------------------------------------------------------------------- #

ASK_USER_TOOL_NAME = "ask_user"
# ``extra`` key of the question row that answers a question of a run.
ASKED_QUESTION_KEY = "ask_user"


def answer_extra(run_id: str, pending_question: dict | None) -> dict:
    """``extra`` of the question row that answers the parked question of ``run_id``.

    The row keeps the question, so the answer row can show the question and its
    answer in place and the history can leave the row out of the message list.
    """
    return {"run_id": run_id, ASKED_QUESTION_KEY: dict(pending_question or {})}


def asked_question_event(question: dict, answer: str) -> dict:
    """One answered ``ask_user`` as the answer row stores a tool call."""
    return {
        "type": "tool_call",
        "tool_call_id": str(question.get("call_id") or ""),
        "tool_name": ASK_USER_TOOL_NAME,
        "display_name": ASK_USER_TOOL_NAME,
        "tool_type": "tool",
        "args": question,
        "results": answer,
        "error": None,
    }


async def answered_question_events(conversation_id: str, run_id: str) -> list[dict]:
    """The answered questions of ``run_id``, oldest first, as stored tool calls.

    Read from the question rows marked by ``answer_extra``: a run that asks more
    than once keeps every question and answer on its single answer row.
    """
    from bisheng.database.models.message import ChatMessageDao

    events = []
    for row in await ChatMessageDao.aget_messages_by_chat_id(conversation_id, limit=RECENT_ROWS):
        if row.is_bot or not row.extra:
            continue
        try:
            extra = json.loads(row.extra)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(extra, dict) or extra.get("run_id") != run_id:
            continue
        question = extra.get(ASKED_QUESTION_KEY)
        if not isinstance(question, dict):
            continue
        events.append(asked_question_event(question, _question_text(row.message)))
    return events


async def save_parked_answer(redis: Any, conversation_id: str, run_id: str, state: dict) -> bool:
    """Keep the answer row of ``run_id`` as it is when the run parks (``DirectRunProjector.parked_state``).

    Written once per question, by the projector of the execution that asked, in
    whichever process it runs; the answer may reach another process. Returns
    False when the hash belongs to another run (nothing is written).
    """
    key = direct_run_key(conversation_id)
    if _s(await redis.hget(key, "run_id")) != run_id:
        logger.warning(
            "direct run={} conversation={} parked, but the direct-run record names another run; "
            "its answer events are not kept",
            run_id,
            conversation_id,
        )
        return False
    await redis.hset(key, PARKED_ANSWER_FIELD, json.dumps(state, ensure_ascii=False))
    await redis.expire(key, _parked_ttl())
    return True


async def parked_answer_raw(redis: Any, conversation_id: str, run_id: str) -> str | None:
    """The ``parked_answer`` of ``run_id`` as stored, or None."""
    key = direct_run_key(conversation_id)
    run_field, raw = await redis.hmget(key, ["run_id", PARKED_ANSWER_FIELD])
    if _s(run_field) != run_id or not raw:
        return None
    return _s(raw)


async def seed_parked_answer(projector: Any, conversation_id: str, run_id: str, text: str, raw: str | None) -> None:
    """Start ``projector`` from what the run showed before it parked.

    ``text`` is the run's accumulated text in the snapshot. With a kept
    ``parked_answer`` (``raw``) the row keeps the thinking, tool calls and text
    before each question, and each question gets the answer of its question row
    in place; a question nobody answered (the run was stopped while parked) is
    left out, as before. Text the run wrote after its last park is appended.
    Without one (a run parked before the upgrade, or the save failed) the row
    is the text followed by the answered questions.
    """
    answered = await answered_question_events(conversation_id, run_id)
    state = _load_parked(raw, run_id)
    if state is None:
        if text:
            projector.final_msg = text
            projector.events.append({"type": "text", "content": text})
        projector.events.extend(answered)
        return

    answers = {event["tool_call_id"]: event for event in answered}
    events = []
    for entry in state["events"]:
        if entry.get("type") == "tool_call" and entry.get("tool_name") == ASK_USER_TOOL_NAME and "results" not in entry:
            answer = answers.get(str(entry.get("tool_call_id") or ""))
            if answer is None:
                continue
            entry = {**entry, **answer}
        events.append(entry)

    msg = state["msg"]
    tail = ""
    if text.startswith(msg):
        tail = text[len(msg) :]
    elif text:
        logger.warning(
            "direct run={} conversation={}: the kept answer text is not a prefix of the snapshot text; "
            "the row keeps the kept events and the snapshot text as its message",
            run_id,
            conversation_id,
        )
    if tail:
        if events and events[-1].get("type") == "text":
            events[-1] = {**events[-1], "content": events[-1].get("content", "") + tail}
        else:
            events.append({"type": "text", "content": tail})
    projector.seed_events(events, text or msg)


def _load_parked(raw: str | None, run_id: str) -> dict | None:
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("direct run={}: the kept answer events are not JSON; ignored", run_id)
        return None
    if not isinstance(state, dict) or not isinstance(state.get("events"), list):
        return None
    return {"msg": str(state.get("msg") or ""), "events": copy.deepcopy(state["events"])}


def _question_text(message: Any) -> str:
    """The text the user sent, from a stored question row (``serialize_user_question``)."""
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return message
    if isinstance(message, dict):
        return str(message.get("query") or "")
    return str(message or "")


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
            run_id=run_id,
            conversation_id=conversation_id,
            user_id=info["user_id"],
            sender=info["sender"],
            storage_partition=info.get("storage_partition"),
        )
        # Their question rows stay out of the history list; the answer row shows them.
        await seed_parked_answer(
            projector, conversation_id, run_id, text, await parked_answer_raw(redis, conversation_id, run_id)
        )
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
    """A direct run parked on a question was stopped: save what it had written, marked ``stopped``."""
    redis = redis if redis is not None else await _redis()
    return await _persist_from_snapshot(
        redis,
        conversation_id,
        run_id,
        text,
        {"type": run_events.RUN_STOPPED, "run_id": run_id, "data": run_events.stopped_data()},
    )
