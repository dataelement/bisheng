"""F004 T032: the send entry and the event subscription of the unified runtime.

Design: features/v3.1.0-beta2/004-unified-agent-runtime/design.md, 决策 3, 4, 9 and
§4.3 / §4.4. ``chat_service.stream_chat_completion`` calls ``unified_send`` for every
request of the login-state endpoint and for Open API daily chat.

Open API daily chat (``session_subject`` is set, AC-39) keeps its contract: the
response is always today's SSE stream with the answer of THIS message. So its
message never joins the inbox and never answers a waiting run: the send waits
until the conversation is free (``BUSY_WAIT_SECONDS``) and then starts a new run,
or fails with ``ConversationBusyError``. The run is unattended (no ``ask_user``),
the conversation is stamped and checked with the subject, files use the
subject's storage partition, and the department slot is taken before the
response starts, as the legacy loop did.

Send (``POST /chat/completions``)
---------------------------------

1. Permission (AC-06): ``task_mode=true`` needs the ``linsight_task_mode`` menu.
2. Input safety (AC-38): a blocked text never reaches ``run_dispatch``, so it
   cannot join the inbox. The turn is recorded with the auto-reply as today.
   Under ``X-BS-Run-Protocol: 2`` the answer is the JSON body
   ``{run_id: null, disposition: "blocked", message_id: null, conversation_id,
   content_safety: true, auto_reply, question_message_id, answer_message_id}``;
   no run exists and nothing is written to the event stream. Without the header
   it is today's SSE frames.
3. ``RunDispatchService.submit`` decides atomically (决策 9):

   * ``started`` / ``direct``  -> question row, then ``start_direct_run`` in this
     API process. The persistence projector is attached through ``on_event``.
   * ``started`` / ``planned`` -> the existing task submit core
     (``submit_task_turn``) creates the version and enqueues it. The worker finds
     the run through ``RunLeaseService.get_state(conversation_id).run_id``: the
     run state of record is the Redis state hash, nothing is passed in memory.
   * the message answers a parked ask_user -> the parked run is resumed
     (``direct`` here, ``planned`` through a resume item at the queue head).
   * ``queued`` -> the message is in the inbox. Its question row is written at
     once with a "queued" mark and ``steer_accepted`` goes to the run's event
     stream (AC-13); the mark is cleared when the run reads the message (AC-14,
     ``run_message_persist``).

Stop (``POST /conversations/{id}/stop``)
----------------------------------------

``stop_conversation_run`` asks the run that holds the conversation to stop, in
whichever process it executes. A run without a live coroutine (parked on a
question, or still waiting in the worker queue) is ended here.

A stopped run starts no relay run (design §7 item 6). The messages it never
read leave the inbox, their question rows are deleted, and the client gets them
back as ``unread_messages`` (``[{message_id, text, files}]``): in the ``data``
of the ``run_stopped`` event, written by whichever process ends the run, and in
the response of the stop request when the run was ended by that request. The
event stream keeps the list in the run snapshot, so a reader that receives a
``resync`` of the ended run instead of the event gets it in ``resync.data``.

4. Response: with ``X-BS-Run-Protocol: 2`` a JSON body
   ``{run_id, disposition, message_id, conversation_id}``; without it the
   response is today's SSE stream. For a ``direct`` run this module follows the
   run's event stream and translates it to today's frames; for a ``planned`` run
   it is today's hand-off frame.

Subscribe (``GET /conversations/{id}/events``)
----------------------------------------------

``follow_run_events`` wraps ``RunEventStream.read`` with the two things a
client connection needs: it waits when the run exists but has not written its
first event yet (the run state says "running"), and it ends when the
conversation is idle. A lapsed lease found on the way is reported through
``RunDispatchService.recover_expired`` (决策 3).

Nothing about a run is kept in this process (C8); the generators below only hold
the cursor of one HTTP response.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import StreamingResponse
from loguru import logger

from bisheng.api.v1.schemas import resp_200
from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum, BaseTelemetryTypeEnum
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode import BaseErrorCode
from bisheng.common.errcode.http_error import ServerError
from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.workstation import (
    ConversationBusyError,
    ConversationNotFoundError,
    DepartmentDailyChatConcurrentLimitError,
)
from bisheng.common.schemas.telemetry.event_data_schema import NewMessageSessionEventData
from bisheng.common.services import telemetry_service
from bisheng.common.services.failure_context import FailureContextAdapter
from bisheng.core.context.tenant import DEFAULT_TENANT_ID
from bisheng.core.logger import trace_id_var
from bisheng.core.storage.chat_attachment import promote_chat_attachments
from bisheng.database.models.flow import FlowType
from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.database.models.role_access import WebMenuResource
from bisheng.database.models.session import MessageSession, MessageSessionDao, SensitiveStatus
from bisheng.department.domain.services.department_flow_service import (
    DepartmentFlowService,
    SlotOutcome,
    lease_id_from_headers,
)
from bisheng.linsight.domain.schemas import run_events
from bisheng.linsight.domain.services.run_event_stream import HEARTBEAT_TYPE, RunEventStream
from bisheng.sensitive_word.domain.services.sensitive_word_policy_service import SensitiveWordPolicyService
from bisheng.workstation.domain.schemas.chat import APIChatCompletion
from bisheng.workstation.domain.services import chat_service, direct_run_turn, run_message_persist
from bisheng.workstation.domain.services.chat_helpers import _memory_sse, _sse_resp, gen_title, user_message
from bisheng.workstation.domain.services.content_safety import workbench_tenant_id
from bisheng.workstation.domain.services.daily_memory import (
    MemoryRegister,
    redact_args,
    redact_error,
    redact_results,
    register_session,
)
from bisheng.workstation.domain.services.direct_run import DirectRunContext, start_direct_run
from bisheng.workstation.domain.services.run_dispatch import (
    KIND_ANSWER,
    KIND_BUSY,
    KIND_NEW_RUN,
    PROFILE_PLANNED,
    RunDispatchService,
    SubmitResult,
)
from bisheng.workstation.domain.services.run_lease import (
    STATUS_IDLE,
    STATUS_RUNNING,
    STATUS_WAITING,
    RunLeaseService,
    stop_key,
)
from bisheng.workstation.domain.services.run_projector_direct import DirectRunProjector

RUN_PROTOCOL_HEADER = "X-BS-Run-Protocol"
RUN_PROTOCOL_V2 = "2"
# ``disposition`` of the send response when input content safety blocked the message.
DISPOSITION_BLOCKED = "blocked"
TASK_MODE_MENU = WebMenuResource.LINSIGHT_TASK_MODE.value

# How long one blocking read waits before the run state is checked again.
FOLLOW_BLOCK_MS = 1000
# First pause between two looks when the conversation is held by a run but the
# Stream does not exist: the run has not written its first event yet (it waits
# in the worker queue, possibly for hours), or the Stream of a parked run is
# gone. The pause doubles up to ``NO_STREAM_POLL_MAX_SECONDS``, so a subscriber
# that waits long costs one look a second instead of twenty.
FIRST_EVENT_POLL_SECONDS = 0.05
NO_STREAM_POLL_MAX_SECONDS = 1.0
# SSE comment interval of the subscribe endpoint.
HEARTBEAT_SECONDS = 15.0
# How long the legacy stream waits for the projector to save the answer row.
PERSIST_WAIT_SECONDS = 15.0

_SSE = "text/event-stream"
# Open API (AC-39): how long a send waits for a busy conversation to become free.
BUSY_WAIT_SECONDS = 60.0
BUSY_POLL_SECONDS = 0.5


# --------------------------------------------------------------------------- #
# Services
# --------------------------------------------------------------------------- #


@dataclass
class RunServices:
    stream: RunEventStream
    lease: RunLeaseService
    dispatch: RunDispatchService
    redis: Any = None


async def _redis() -> Any:
    from bisheng.core.cache.redis_manager import get_redis_client

    return (await get_redis_client()).async_connection


def _dispatch_wiring() -> dict[str, Any]:
    """Relay queue, expiry handler and queue-position probe of this deployment."""
    from bisheng.workstation.domain.services.direct_run import production_dispatch_wiring

    return production_dispatch_wiring()


async def run_services() -> RunServices:
    redis = await _redis()
    return RunServices(
        stream=RunEventStream(redis),
        lease=RunLeaseService(redis),
        dispatch=RunDispatchService(redis, **_dispatch_wiring()),
        redis=redis,
    )


def wants_run_protocol(request: Any) -> bool:
    headers = getattr(request, "headers", None)
    if not hasattr(headers, "get"):
        return False
    return str(headers.get(RUN_PROTOCOL_HEADER) or "").strip() == RUN_PROTOCOL_V2


# --------------------------------------------------------------------------- #
# Subscribe
# --------------------------------------------------------------------------- #


async def _run_active(svc: RunServices, conversation_id: str) -> bool:
    """Whether more events can still arrive for this conversation.

    A run whose lease lapsed is reported here (决策 3): the dispatcher appends
    ``run_failed`` and frees the conversation, and the caller reads once more to
    deliver that event.
    """
    state = await svc.lease.get_state(conversation_id)
    if state.status == STATUS_IDLE:
        return False
    if state.status == STATUS_RUNNING and state.lease_until_ms <= int(time.time() * 1000):
        try:
            await svc.dispatch.recover_expired(conversation_id)
        except Exception:
            # The relay run could not be queued. The dead run was already reported
            # (run_failed is on the stream); the next access retries the relay.
            logger.exception("could not recover the lapsed run of conversation={}", conversation_id)
            return False
    return True


async def follow_run_events(svc: RunServices, conversation_id: str, cursor: str | None = None) -> AsyncIterator[dict]:
    """Yield the events after ``cursor`` until the conversation is idle.

    Yields ``{"type": "heartbeat"}`` while it waits. A relay run that takes the
    conversation right after a run ended is followed too.
    """
    cur = cursor
    pause = FIRST_EVENT_POLL_SECONDS
    while True:
        async for event in svc.stream.read(conversation_id, cur, follow=True, block_ms=FOLLOW_BLOCK_MS, heartbeat=True):
            # The Stream exists: the reader itself waits between two looks.
            pause = FIRST_EVENT_POLL_SECONDS
            if event.get("type") == HEARTBEAT_TYPE:
                if not await _run_active(svc, conversation_id):
                    return
                yield event
                continue
            cur = event["id"]
            yield event
        # The reader stopped: a run ended, or the Stream does not exist (yet).
        if not await _run_active(svc, conversation_id):
            # Events appended between the last read and the state check.
            async for event in svc.stream.read(conversation_id, cur):
                yield event
            return
        yield {"type": HEARTBEAT_TYPE}
        await asyncio.sleep(pause)
        pause = min(pause * 2, NO_STREAM_POLL_MAX_SECONDS)


def event_frame(event: dict) -> str:
    """One unified event as an SSE frame; ``id`` is the cursor for ``Last-Event-ID``."""
    return f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def _get_session(conversation_id: str) -> Any:
    return await MessageSessionDao.async_get_one(conversation_id)


async def owns_conversation(conversation_id: str, login_user: UserPayload) -> bool:
    session = await _get_session(conversation_id)
    return session is not None and session.user_id == login_user.user_id


async def _queue_index(version_id: str) -> int:
    """1-based position of a deep-research version in the worker queue; 0 = not queued."""
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.linsight.worker import LinsightQueue

    queue = LinsightQueue("queue", namespace="linsight", redis=await get_redis_client())
    return int(await queue.index(version_id) or 0)


async def queue_position(conversation_id: str) -> dict:
    """AC-36: where the deep-research run of the conversation waits in the worker queue.

    ``{"run_id", "position"}``; ``position`` is None when the conversation has
    no planned run that waits in the queue (no run, a direct run, a run the
    worker already took, or a run that waits for the conversation itself). The
    caller has checked ownership.
    """
    svc = await run_services()
    state = await svc.lease.get_state(conversation_id)
    if state.status != STATUS_RUNNING or state.profile != PROFILE_PLANNED or not state.run_id:
        return {"run_id": state.run_id or None, "position": None}
    record = await _planned_run_record(conversation_id, state.run_id)
    if record is None:
        return {"run_id": state.run_id, "position": None}
    index = await _queue_index(record.id)
    return {"run_id": state.run_id, "position": index if index > 0 else None}


async def subscribe_response(conversation_id: str, last_event_id: str | None) -> StreamingResponse:
    """SSE of the conversation's run events. The caller has checked ownership."""
    svc = await run_services()

    async def body():
        last_beat = time.monotonic()
        async for event in follow_run_events(svc, conversation_id, last_event_id or None):
            if event.get("type") == HEARTBEAT_TYPE:
                if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                    last_beat = time.monotonic()
                    yield ": heartbeat\n\n"
                continue
            last_beat = time.monotonic()
            yield event_frame(event)

    return StreamingResponse(body(), media_type=_SSE, headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# Send: database helpers (the test suite replaces exactly these)
# --------------------------------------------------------------------------- #


async def _open_conversation(
    data: APIChatCompletion, login_user: UserPayload, session_subject: SessionSubject | None = None
) -> tuple[Any, bool]:
    """Fetch the conversation, or create it for a first message. Owner only.

    The conversation must exist before ``run_dispatch.submit``: its id is the key
    of the run state. With ``session_subject`` (Open API) a new conversation is
    stamped with the subject and an existing one must match it; a mismatch is
    HTTP 404, as the legacy Open API loop answered.
    """
    conversation_id = data.conversationId
    is_new = not conversation_id
    if is_new:
        conversation_id = uuid4().hex
        new_session = MessageSession(
            chat_id=conversation_id,
            name="New Chat",
            flow_type=FlowType.WORKSTATION.value,
            user_id=login_user.user_id,
        )
        if session_subject is not None:
            new_session = session_subject.stamp(new_session)
        if data.project_id is not None:
            from bisheng.chat_session.domain.chat import ChatSessionService

            if session_subject is not None:
                from bisheng.common.errcode.chat import ProjectInputError

                raise ProjectInputError()
            await ChatSessionService.create_owned_project_session(new_session, login_user, data.project_id)
        else:
            await MessageSessionDao.async_insert_one(new_session)
        await telemetry_service.log_event(
            user_id=login_user.user_id,
            event_type=BaseTelemetryTypeEnum.NEW_MESSAGE_SESSION,
            trace_id=trace_id_var.get(),
            event_data=NewMessageSessionEventData(
                session_id=conversation_id,
                app_id=ApplicationTypeEnum.DAILY_CHAT.value,
                source="platform",
                app_name=ApplicationTypeEnum.DAILY_CHAT.value,
                app_type=ApplicationTypeEnum.DAILY_CHAT,
            ),
        )
    if session_subject is not None:
        from bisheng.chat_session.domain.chat import ChatSessionService

        conversation = await ChatSessionService.get_subject_session(conversation_id, session_subject)
    else:
        conversation = await MessageSessionDao.async_get_one(conversation_id)
        if conversation is None or conversation.user_id != login_user.user_id:
            raise ConversationNotFoundError()
    if not is_new:
        await MessageSessionDao.touch_session(conversation_id)
    return conversation, is_new


def _question_row(data: Any, login_user: Any, conversation_id: str, extra: dict | None = None) -> ChatMessage:
    """The question row of one sent message; ``extra`` is empty for a normal turn."""
    return ChatMessage(
        user_id=login_user.user_id,
        chat_id=conversation_id,
        flow_id="",
        type="over",
        is_bot=False,
        sender="User",
        files=json.dumps(data.files) if data.files else None,
        extra=json.dumps(extra, ensure_ascii=False) if extra else "{}",
        message=json.dumps({"query": data.text or "", "files": data.files or []}, ensure_ascii=False),
        category="question",
        source=0,
        sensitive_status=SensitiveStatus.PASS.value,
    )


async def _insert_question_row(
    data: APIChatCompletion,
    login_user: UserPayload,
    conversation_id: str,
    memory_register: MemoryRegister | None,
    storage_partition: str | None = None,
) -> Any:
    """The question row daily chat writes today (``_agent_initialize_chat``), same order of steps."""
    # F132: registration precedes this turn's question row (AC-40 of F132).
    await register_session(memory_register, conversation_id)
    await promote_chat_attachments(data.files, login_user.user_id, storage_partition=storage_partition)
    return await ChatMessageDao.ainsert_one(_question_row(data, login_user, conversation_id))


async def _insert_steer_row(
    data: APIChatCompletion,
    login_user: UserPayload,
    conversation_id: str,
    result: SubmitResult,
    memory_register: MemoryRegister | None,
) -> Any:
    """Question row of a message that joined the inbox (AC-13).

    Same steps and structure as ``_insert_question_row``; ``extra`` names the run
    that will read the message and carries the "queued" mark.
    """
    await register_session(memory_register, conversation_id)
    await promote_chat_attachments(data.files, login_user.user_id)
    extra = run_message_persist.steer_extra(result.run_id, result.message_id, queued=True)
    return await ChatMessageDao.ainsert_one(_question_row(data, login_user, conversation_id, extra))


async def _model_display_name(data: APIChatCompletion, login_user: UserPayload) -> str:
    """Validate the picked model like today's entry and return the answer row's ``sender``."""
    from bisheng.dsh.domain.services.model_catalog import user_workbench_models

    models = await user_workbench_models(login_user.user_id)
    model_info = next((m for m in models if m.id == data.model), None)
    if not model_info:
        raise ValueError(f"Model with id '{data.model}' not found.")
    return model_info.displayName


def _spawn_title(request: Any, data: APIChatCompletion, login_user: UserPayload, conversation: Any) -> None:
    """Name a still-unnamed conversation from the question, in the background (as task mode does)."""
    if getattr(conversation, "name", None) not in (None, "", "New Chat"):
        return

    async def name_it() -> None:
        from bisheng.llm.domain import LLMService

        llm = await LLMService.get_bisheng_llm(
            model_id=data.model,
            app_id=ApplicationTypeEnum.DAILY_CHAT.value,
            app_name=ApplicationTypeEnum.DAILY_CHAT.value,
            app_type=ApplicationTypeEnum.DAILY_CHAT,
            user_id=login_user.user_id,
        )
        await gen_title(data.text or "", llm, conversation.chat_id, login_user, request)

    _background(name_it(), f"title:{conversation.chat_id}")


async def _submit_task_turn(data: APIChatCompletion, login_user: UserPayload, **kwargs: Any) -> tuple[Any, Any]:
    from bisheng.workstation.domain.services.task_submit_service import submit_task_turn

    return await submit_task_turn(data, login_user, **kwargs)


async def _relay_model(conversation_id: str, redis: Any) -> str:
    """The model a planned relay run answers with.

    An inbox message carries no model (switching models is disabled while a run
    is in progress), so the relay run uses the model of the conversation's last
    deep-research run, else of its last direct run. Empty = the tenant's
    deep-research default, as for a send without a model.
    """
    from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersionDao

    versions = await LinsightSessionVersionDao.get_session_versions_by_session_id(conversation_id)
    if versions and versions[0].model:
        return str(versions[0].model)
    previous = await run_message_persist.direct_run_info(redis, conversation_id) or {}
    return str(previous.get("model_id") or "")


async def start_planned_relay(item: dict, messages: list[dict], *, redis: Any = None) -> Any:
    """Create and queue the deep-research run that answers unread inbox messages (design §7 item 1).

    Called by the Linsight worker for a ``planned_relay`` queue item, after it
    took ``messages`` out of the inbox. The run record is created and queued by
    ``submit_task_turn``, the code of a normal deep-research send; only these
    differ:

    * the question is the text of all unread messages, oldest first, and the
      settings (tools, skills, knowledge) are those of the first one;
    * no question row is written: every message got its row when it joined the
      inbox, and ``steer_read`` clears that row's "queued" mark when the run starts;
    * the queue item carries ``item["run_id"]``, the id the conversation is
      already reserved for.

    Returns the new session version. Raises what ``submit_task_turn`` raises.
    """
    from bisheng.workstation.domain.schemas.chat import ToolPayload, UseKnowledgeBaseParam

    redis = redis if redis is not None else await _redis()
    conversation_id, run_id = item["conversation_id"], item["run_id"]
    head = messages[0]
    texts = [str(message.get("text") or "") for message in messages if message.get("text")]
    files = [f for message in messages for f in (message.get("files") or [])]
    knowledge = head.get("knowledge")
    data = APIChatCompletion(
        clientTimestamp=str(int(time.time() * 1000)),
        conversationId=conversation_id,
        model=await _relay_model(conversation_id, redis),
        text="\n\n".join(texts),
        tools=[ToolPayload(**tool) for tool in (head.get("tools") or []) if isinstance(tool, dict)] or None,
        task_mode=True,
        skills=list(head.get("skills") or []) or None,
        use_knowledge_base=UseKnowledgeBaseParam(**knowledge) if isinstance(knowledge, dict) and knowledge else None,
        files=files or None,
    )
    login_user = await UserPayload.init_login_user(
        user_id=int(item["user_id"]), user_name="", tenant_id=int(item["tenant_id"])
    )
    # Before the run is queued: the worker that executes it reads this at ``run_started``.
    await run_message_persist.remember_relay_messages(
        redis, conversation_id, run_id, [str(message.get("message_id") or "") for message in messages]
    )
    _session, version = await _submit_task_turn(data, login_user, run_id=run_id, persist_user_turn=False)
    return version


async def _enqueue_planned_resume(conversation_id: str, run_id: str, answer: str, tenant_id: int) -> Any:
    """Wake the parked deep-research run ``run_id`` of this conversation with the user's answer.

    Same queue item as ``/linsight/workbench/user-input``; the worker resumes
    from the item alone.

    The run record is the one of the parked run (its id is the run id, or it
    stores the run id), never "the newest record of the conversation": an entry
    that does not go through the send entry (Open API, ``/workbench/*``) can add
    a newer record while this run waits, and that record has no question to
    answer. A parked run without a record is an error, not a reason to guess.
    """
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.linsight.domain import task_exec
    from bisheng.linsight.worker import LinsightQueue, encode_queue_item

    version = await task_exec._find_run_record(conversation_id, run_id)
    if version is None:
        raise RuntimeError(
            f"conversation {conversation_id} waits for an answer to run {run_id}, but that run has no run record"
        )

    queue = LinsightQueue("queue", namespace="linsight", redis=await get_redis_client())
    await queue.put_head(encode_queue_item(version.id, resume=True, user_input=answer, tenant_id=tenant_id))
    return version


async def _blocked_response(
    data: APIChatCompletion,
    login_user: UserPayload,
    blocked: Any,
    memory_register: MemoryRegister | None,
    negotiated: bool = False,
    session_subject: SessionSubject | None = None,
) -> Any:
    """Answer to a blocked input: the turn is recorded with the auto-reply, no run starts.

    ``negotiated`` (``X-BS-Run-Protocol: 2``): a JSON body with
    ``disposition="blocked"`` (see the module docstring). Otherwise today's SSE frames.
    """
    try:
        _cfg, conversation, message, _llm, model_info, _new = await chat_service._agent_initialize_chat(
            data,
            login_user,
            session_subject,
            skip_llm=True,
            memory_register=None if data.task_mode else memory_register,
        )
    except (BaseErrorCode, ValueError) as exc:
        if negotiated:
            if isinstance(exc, BaseErrorCode):
                raise
            raise ServerError(exception=exc) from exc
        error = exc if isinstance(exc, BaseErrorCode) else ServerError()
        return _error_stream(error, exc)
    auto_reply = blocked.auto_reply or ""
    if not negotiated:
        return chat_service._respond_blocked_workbench(conversation, message, model_info, data, auto_reply)
    answer = await chat_service.persist_blocked_workbench_answer(conversation, model_info, auto_reply)
    return resp_200(
        data={
            "run_id": None,
            "disposition": DISPOSITION_BLOCKED,
            "message_id": None,
            "conversation_id": conversation.chat_id,
            "content_safety": True,
            "auto_reply": auto_reply,
            "question_message_id": message.id,
            "answer_message_id": answer.id,
        }
    )


# --------------------------------------------------------------------------- #
# Send
# --------------------------------------------------------------------------- #

_TASKS: set[asyncio.Task] = set()


def _background(coro: Any, name: str) -> None:
    """Run a coroutine that must outlive the request; a failure is logged, never lost."""
    task = asyncio.create_task(coro, name=name)
    _TASKS.add(task)

    def done(finished: asyncio.Task) -> None:
        _TASKS.discard(finished)
        if not finished.cancelled() and finished.exception() is not None:
            logger.opt(exception=finished.exception()).error("background task {} failed", finished.get_name())

    task.add_done_callback(done)


def _error_stream(error: Any, cause: BaseException | None = None) -> StreamingResponse:
    return StreamingResponse(iter([FailureContextAdapter.public_sse_text(error, cause=cause)]), media_type=_SSE)


def _json(result: SubmitResult, conversation_id: str) -> Any:
    return resp_200(data={**result.as_response(), "conversation_id": conversation_id})


def _closing_frames(conversation_id: str, answer_message_id: Any = None) -> list[str]:
    final: dict[str, Any] = {"final": True, "conversation": {"conversationId": conversation_id}}
    if answer_message_id is not None:
        final["responseMessage"] = {"messageId": answer_message_id, "conversationId": conversation_id}
    return [
        _sse_resp("processing", "close", "", conversation_id),
        f"data: {json.dumps(final, ensure_ascii=False)}\n\n",
    ]


def _handoff_stream(session_version: Any) -> StreamingResponse:
    payload = {
        "event": "linsight_task_handoff",
        "data": {"session_version_id": session_version.id, "chat_id": session_version.session_id},
    }
    return StreamingResponse(iter([f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"]), media_type=_SSE)


async def _abandon_run(svc: RunServices, conversation_id: str, run_id: str) -> None:
    """A run that was granted but could not be started gives the conversation back."""
    try:
        await svc.dispatch.on_run_finished(conversation_id, run_id)
    except Exception:
        logger.exception(
            "could not release conversation={} after run={} failed to start; its lease will lapse",
            conversation_id,
            run_id,
        )


async def unified_send(
    request: Request,
    data: APIChatCompletion,
    login_user: UserPayload,
    *,
    memory_register: MemoryRegister | None = None,
    session_subject: SessionSubject | None = None,
):
    """``POST /chat/completions`` on the unified runtime.

    ``session_subject`` is set by the Open API daily-chat entry (see the module
    docstring); that caller always gets today's SSE stream.
    """
    negotiated = wants_run_protocol(request) and session_subject is None

    # 1. AC-06: deep research needs its menu permission; a rejected request
    #    creates no conversation, no run and no inbox entry.
    if data.task_mode:
        await UserPayload.assert_effective_web_menu_contains(login_user.user_id, TASK_MODE_MENU)

    # 2. AC-38: input safety runs before the message can reach the inbox.
    tenant_id = workbench_tenant_id(login_user)
    blocked = SensitiveWordPolicyService.evaluate_workbench_user_text(tenant_id, data.text or "")
    if blocked:
        logger.warning(
            "workbench content safety hit tenant_id={} mode=input chat_id={}", tenant_id, data.conversationId or ""
        )
        return await _blocked_response(data, login_user, blocked, memory_register, negotiated, session_subject)

    try:
        if data.task_mode:
            return await _send_planned(request, data, login_user, negotiated, memory_register)
        if session_subject is not None:
            return await _send_open_api(request, data, login_user, session_subject)
        return await _send(request, data, login_user, negotiated, memory_register)
    except DepartmentDailyChatConcurrentLimitError:
        if negotiated:
            raise
        return chat_service._department_limit_stream_response()
    except BaseErrorCode as exc:
        if negotiated:
            raise
        return _error_stream(exc)
    except ValueError as exc:
        # Today's entry answers an unknown model id like this.
        logger.warning("unified send rejected: {}", exc)
        if negotiated:
            raise ServerError(exception=exc) from exc
        return _error_stream(ServerError(), exc)


async def _send_planned(request, data, login_user, negotiated, memory_register):
    """Deep research holds the department execution slot for the submit, as today."""
    page_lease_id = lease_id_from_headers(getattr(request, "headers", None))
    if page_lease_id is not None:
        outcome, _ = await DepartmentFlowService.ensure_lease(login_user, page_lease_id)
        if outcome is SlotOutcome.REJECTED:
            raise DepartmentDailyChatConcurrentLimitError()
        return await _send(request, data, login_user, negotiated, memory_register)
    async with DepartmentFlowService.hold_execution_lease(login_user) as (outcome, _lease):
        if outcome is SlotOutcome.REJECTED:
            raise DepartmentDailyChatConcurrentLimitError()
        return await _send(request, data, login_user, negotiated, memory_register)


async def _send_open_api(
    request, data: APIChatCompletion, login_user: UserPayload, session_subject: SessionSubject
) -> Any:
    """Open API daily chat: the department slot is taken before the response starts.

    A rejection is one error frame and no rows, as in the legacy Open API loop.
    The run takes the lease over and releases it when it ends; every path that
    does not start a run releases it here.
    """
    outcome, lease = await DepartmentFlowService.ensure_lease(login_user)
    if outcome is SlotOutcome.REJECTED:
        raise DepartmentDailyChatConcurrentLimitError()
    # The send may wait for a busy conversation for up to BUSY_WAIT_SECONDS;
    # the slot is renewed meanwhile so it is still held when the run takes it over.
    renewal = DepartmentFlowService.start_renewal(lease) if lease is not None else None
    handed_over = False
    try:
        response = await _send(
            request,
            data,
            login_user,
            False,
            None,
            session_subject=session_subject,
            execution_lease_id=lease.lease_id if lease is not None else None,
        )
        handed_over = True
        return response
    finally:
        if renewal is not None:
            # Cancelled before any release, so a late renewal cannot put the slot back.
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
        if lease is not None and not handed_over:
            await DepartmentFlowService.release_lease(lease)


async def _submit_when_free(svc: RunServices, conversation_id: str, message: dict) -> SubmitResult:
    """Exclusive submit (Open API): wait until the conversation is free, then start a run."""
    deadline = time.monotonic() + BUSY_WAIT_SECONDS
    while True:
        result = await svc.dispatch.submit(conversation_id, message, exclusive=True)
        if result.kind != KIND_BUSY:
            return result
        if time.monotonic() >= deadline:
            logger.warning(
                "open api send: conversation={} still held by run={} after {}s",
                conversation_id,
                result.run_id,
                BUSY_WAIT_SECONDS,
            )
            raise ConversationBusyError()
        await asyncio.sleep(BUSY_POLL_SECONDS)


async def _send(
    request,
    data: APIChatCompletion,
    login_user: UserPayload,
    negotiated: bool,
    memory_register,
    *,
    session_subject: SessionSubject | None = None,
    execution_lease_id: str | None = None,
):
    tenant_id = int(workbench_tenant_id(login_user) or DEFAULT_TENANT_ID)
    task_mode = data.task_mode is True
    sender = "" if task_mode else await _model_display_name(data, login_user)
    conversation, _is_new = await _open_conversation(data, login_user, session_subject)
    conversation_id = conversation.chat_id
    # ``knowledge`` of a direct message is the resolved list the tool assembly
    # takes; a deep-research message keeps the raw selection for the task core.
    if task_mode:
        knowledge: Any = data.use_knowledge_base.model_dump(mode="json") if data.use_knowledge_base else []
    else:
        knowledge = await chat_service._resolve_user_kb_selection(data)
    tools = [tool.model_dump() for tool in (data.tools or [])]

    svc = await run_services()

    async def save_queued(queued: SubmitResult, _message: dict) -> None:
        row = await _insert_steer_row(data, login_user, conversation_id, queued, memory_register)
        # The run may already have read the message; then the mark is cleared here.
        await run_message_persist.bind_steer_row(svc.redis, conversation_id, queued.message_id, row.id, queued.run_id)

    message = {
        "text": data.text or "",
        "task_mode": task_mode,
        "tools": tools,
        # T053: a direct run mounts the selected skills too (AC-45).
        "skills": list(data.skills or []),
        "knowledge": knowledge,
        "files": data.files or [],
        "user_id": login_user.user_id,
        "tenant_id": tenant_id,
    }
    if session_subject is not None:
        result = await _submit_when_free(svc, conversation_id, message)
    else:
        result = await svc.dispatch.submit(conversation_id, message, on_queued=save_queued)

    if result.kind not in (KIND_NEW_RUN, KIND_ANSWER):
        # The message is in the inbox and its question row is written; the
        # running (or relay) run reads it.
        if negotiated:
            return _json(result, conversation_id)
        return StreamingResponse(iter(_closing_frames(conversation_id)), media_type=_SSE)

    try:
        if result.profile == PROFILE_PLANNED:
            return await _start_planned(
                request, data, login_user, conversation, result, negotiated, memory_register, tenant_id
            )
        return await _start_direct(
            svc,
            request,
            data,
            login_user,
            conversation,
            result,
            negotiated,
            memory_register,
            tenant_id=tenant_id,
            tools=tools,
            knowledge=knowledge if isinstance(knowledge, list) else [],
            sender=sender,
            session_subject=session_subject,
            execution_lease_id=execution_lease_id,
        )
    except BaseException:
        if result.kind == KIND_ANSWER:
            # The answer did not reach the run: it waits for the user again.
            await svc.lease.park(conversation_id, result.run_id)
        else:
            await _abandon_run(svc, conversation_id, result.run_id)
        raise


async def _start_planned(request, data, login_user, conversation, result, negotiated, memory_register, tenant_id):
    conversation_id = conversation.chat_id
    if result.kind == KIND_ANSWER:
        version = await _enqueue_planned_resume(conversation_id, result.run_id, data.text or "", tenant_id)
    else:

        async def register(session, _version):
            await register_session(memory_register, session.chat_id)

        # The conversation already exists, so the task core continues it.
        turn = data.model_copy(update={"conversationId": conversation_id, "project_id": None})
        _session, version = await _submit_task_turn(
            turn,
            login_user,
            on_session_created=register if memory_register is not None else None,
            # The worker claims the conversation under the id it was reserved with.
            run_id=result.run_id,
        )
        _spawn_title(request, data, login_user, conversation)
    logger.info(
        "unified send: planned run={} conversation={} version={} kind={}",
        result.run_id,
        conversation_id,
        version.id,
        result.kind,
    )
    return _json(result, conversation_id) if negotiated else _handoff_stream(version)


async def _start_direct(
    svc: RunServices,
    request,
    data: APIChatCompletion,
    login_user: UserPayload,
    conversation,
    result: SubmitResult,
    negotiated: bool,
    memory_register,
    *,
    tenant_id: int,
    tools: list,
    knowledge: list,
    sender: str,
    session_subject: SessionSubject | None = None,
    execution_lease_id: str | None = None,
):
    conversation_id = conversation.chat_id
    is_resume = result.kind == KIND_ANSWER
    storage_partition = session_subject.storage_partition if session_subject is not None else None
    question = await _insert_question_row(data, login_user, conversation_id, memory_register, storage_partition)

    persisted = asyncio.Event()

    async def on_persisted(row: Any) -> None:
        try:
            # F132: bind this turn's memory records to the answer row and end the
            # turn, as the legacy stream does right after it saves the row.
            projector.memory_signal = await direct_run_turn.finish_memory_turn(result.run_id, row.id)
        finally:
            persisted.set()

    projector = DirectRunProjector(
        run_id=result.run_id,
        conversation_id=conversation_id,
        user_id=conversation.user_id,
        sender=sender,
        storage_partition=storage_partition,
        # The sources this execution's tools registered (T059).
        citation_items=lambda: direct_run_turn.collected_citations(result.run_id),
        on_persisted=on_persisted,
    )
    if is_resume:
        # The hooks of this execution do not see what the run wrote before it
        # parked; the accumulated text of the run is in the Redis snapshot.
        parked = (await svc.stream.snapshot(conversation_id)) or {}
        earlier = parked.get("text") or ""
        if earlier:
            projector.final_msg = earlier
            projector.events.append({"type": "text", "content": earlier})
        # T055: files written before the park belong to the same answer row.
        projector.seed_files(parked.get("files"))

    ctx = DirectRunContext(
        conversation_id=conversation_id,
        run_id=result.run_id,
        tenant_id=tenant_id,
        user_id=login_user.user_id,
        message_id=result.message_id,
        text=data.text or "",
        model_id=data.model,
        tools=tools,
        skills=list(data.skills or []),
        knowledge=knowledge,
        files=data.files or [],
        question_message_id=question.id,
        # The department slot of the page, when the page holds one (AC-22).
        page_lease_id=lease_id_from_headers(getattr(request, "headers", None)),
        # Only a login-state endpoint passes ``memory_register`` (F132 AC-10).
        memory_registered=memory_register is not None,
        is_resume=is_resume,
        answer=(data.text or "") if is_resume else None,
        initial_events=list(result.events),
        # Open API (AC-39): nobody answers a question; files in the subject's partition.
        unattended=session_subject is not None,
        storage_partition=storage_partition,
        execution_lease_id=execution_lease_id,
    )
    # What a process without this projector needs to write the run's answer row:
    # the worker (relay run), or whoever closes the run after this process died.
    await run_message_persist.remember_direct_run(
        svc.redis,
        conversation_id,
        result.run_id,
        user_id=conversation.user_id,
        tenant_id=tenant_id,
        sender=sender,
        model_id=data.model,
        storage_partition=storage_partition,
    )
    # The only attachment of these hooks: no process-wide hook factory is
    # registered in the API process, or every row would be written twice.
    start_direct_run(
        ctx, on_event=[projector.on_event, run_message_persist.steer_read_hook(conversation_id, redis=svc.redis)]
    )
    logger.info(
        "unified send: direct run={} conversation={} resume={} negotiated={}",
        result.run_id,
        conversation_id,
        is_resume,
        negotiated,
    )
    if not is_resume:
        _spawn_title(request, data, login_user, conversation)
    if negotiated:
        return _json(result, conversation_id)
    return StreamingResponse(_legacy_direct_stream(svc, ctx, question.id, data, projector, persisted), media_type=_SSE)


# --------------------------------------------------------------------------- #
# Unified events -> today's daily-chat SSE frames
# --------------------------------------------------------------------------- #


class LegacyFrameTranslator:
    """Translate the unified events of ONE direct run to today's SSE frames.

    Only bookkeeping of one HTTP response lives here (open thinking segment,
    start frames of running tools); it is rebuilt from the stream on demand.
    """

    def __init__(self, conversation_id: str):
        self.cid = conversation_id
        self._thinking_call: Any = None
        self._thinking_started: int | None = None
        self._tools: dict[str, dict] = {}
        self._sent_text = 0

    def feed(self, event: dict) -> list[str]:
        kind, data = event.get("type"), event.get("data") or {}
        now_ms = int(event.get("ts") or time.time() * 1000)
        if kind == run_events.THINKING:
            return self._thinking(data, now_ms)
        if kind == run_events.TEXT:
            text = str(data.get("text") or "")
            if not text:
                return []
            self._sent_text += len(text)
            return [*self._close_thinking(now_ms), _sse_resp("agent_answer", "stream", {"msg": text}, self.cid)]
        if kind == run_events.TOOL_CALL:
            return self._tool_call(data, now_ms)
        if kind == run_events.RESYNC:
            # This reader fell behind the Stream's MAXLEN: send the text it missed.
            text = str(data.get("text") or "")[self._sent_text :]
            self._sent_text += len(text)
            return [_sse_resp("agent_answer", "stream", {"msg": text}, self.cid)] if text else []
        if kind in run_events.TERMINAL_EVENT_TYPES or kind == run_events.ASK_USER:
            return self._close_thinking(now_ms)
        # plan / file / queued / steer_* have no frame in today's daily stream.
        return []

    def _thinking(self, data: dict, now_ms: int) -> list[str]:
        if data.get("namespace"):
            return []
        frames: list[str] = []
        if self._thinking_started is not None and data.get("call_id") != self._thinking_call:
            frames += self._close_thinking(now_ms)
        if self._thinking_started is None:
            self._thinking_started = now_ms
            self._thinking_call = data.get("call_id")
        frames.append(_sse_resp("agent_thinking", "stream", {"content": str(data.get("text") or "")}, self.cid))
        return frames

    def _close_thinking(self, now_ms: int) -> list[str]:
        if self._thinking_started is None:
            return []
        duration = max(0, now_ms - self._thinking_started)
        self._thinking_started = None
        self._thinking_call = None
        return [_sse_resp("agent_thinking", "end", {"duration_ms": duration}, self.cid)]

    def _tool_call(self, data: dict, now_ms: int) -> list[str]:
        extra_info = data.get("extra_info") or {}
        if extra_info.get("namespace"):
            return []
        call_id, name = str(data.get("call_id") or ""), str(data.get("name") or "")
        frames = self._close_thinking(now_ms)
        if data.get("status") != "end":
            start = {
                "tool_call_id": call_id,
                "tool_name": name,
                # The runner puts the tool's display data on the event.
                "display_name": extra_info.get("display_name") or name,
                "tool_type": extra_info.get("tool_type") or "tool",
                "args": redact_args(name, data.get("params") or {}),
                "started_at": now_ms,
            }
            self._tools[call_id] = start
            return [*frames, _sse_resp("agent_tool_call", "start", start, self.cid)]

        start = self._tools.pop(call_id, None)
        if start is None:
            start = {
                "tool_call_id": call_id,
                "tool_name": name,
                "display_name": extra_info.get("display_name") or name,
                "tool_type": extra_info.get("tool_type") or "tool",
                "args": {},
                "started_at": now_ms,
            }
            if extra_info.get("init_failed"):
                # Today a tool that failed to initialise shows as start + end.
                frames.append(
                    _sse_resp(
                        "agent_tool_call", "start", {k: v for k, v in start.items() if k != "started_at"}, self.cid
                    )
                )
        output = data.get("output")
        results = redact_results(name, output, chat_service._parse_tool_results)
        payload = {
            **start,
            "results": results,
            "error": redact_error(name, chat_service._extract_tool_error(output)),
            "ended_at": now_ms,
            "duration_ms": max(0, now_ms - start["started_at"]),
        }
        info = extra_info.get("failure_info") or FailureContextAdapter.from_payload(results)
        if info:
            payload["failure_info"] = info
        return [*frames, _sse_resp("agent_tool_call", "end", payload, self.cid)]


def _failure_frame(data: dict) -> str:
    """``run_failed`` as today's ``event: error`` frame (same envelope keys)."""
    payload = {
        key: value
        for key, value in {
            "error_code": data.get("code"),
            "error_type": data.get("reason"),
            "detail": data.get("detail"),
            "reference_id": data.get("reference_id"),
            "failure_info": data.get("failure_info"),
        }.items()
        if value is not None
    }
    envelope = {
        "status_code": data.get("code") or ServerError.Code,
        "status_message": data.get("detail") or ServerError.Msg,
        "data": payload,
    }
    return f"event: error\ndata: {json.dumps(envelope, ensure_ascii=False)}\n\n"


async def _legacy_direct_stream(
    svc: RunServices,
    ctx: DirectRunContext,
    question_id: Any,
    data: APIChatCompletion,
    projector: DirectRunProjector,
    persisted: asyncio.Event,
) -> AsyncIterator[str]:
    """Today's daily-chat stream, produced from the event stream of the run.

    Closing this response stops the run, as closing today's stream does: the
    unmodified client has no other way to stop a direct answer.
    """
    cid = ctx.conversation_id
    translator = LegacyFrameTranslator(cid)
    terminal: dict | None = None
    done = False
    try:
        yield user_message(question_id, cid, "User", data.text or "")
        yield _sse_resp("processing", "begin", "", cid)
        yield _sse_resp(
            "question",
            "over",
            {"query": data.text or "", "files": data.files or []},
            cid,
            message_id=question_id,
            is_bot=False,
        )
        async for event in follow_run_events(svc, cid):
            if event.get("type") == HEARTBEAT_TYPE or event.get("run_id") != ctx.run_id:
                # Heartbeats, and what is left on the Stream of the run before this one.
                continue
            for frame in translator.feed(event):
                yield frame
            if event["type"] in run_events.TERMINAL_EVENT_TYPES:
                terminal = event
                break
            if event["type"] == run_events.ASK_USER:
                # The run is parked; the next message of the user is its answer.
                done = True
                break

        if terminal is None:
            if not done:
                logger.warning(
                    "direct run={} conversation={}: the event stream ended without a result", ctx.run_id, cid
                )
            done = True
            for frame in _closing_frames(cid):
                yield frame
            return

        done = True
        row = None
        try:
            await asyncio.wait_for(persisted.wait(), PERSIST_WAIT_SECONDS)
            row = projector.answer_row
        except TimeoutError:
            logger.error("direct run={} conversation={}: the answer row was not saved in time", ctx.run_id, cid)
        if row is None:
            yield FailureContextAdapter.public_sse_text(ServerError())
            for frame in _closing_frames(cid):
                yield frame
            return
        if terminal["type"] == run_events.RUN_FAILED:
            yield _failure_frame(terminal.get("data") or {})
        content = json.loads(row.message)
        files = json.loads(row.files) if getattr(row, "files", None) else []
        if projector.memory_signal:
            yield _memory_sse(projector.memory_signal, cid, message_id=row.id)
        yield _sse_resp(
            "agent_answer",
            "end",
            {**content, "files": files},
            cid,
            message_id=row.id,
            citations=projector.citations,
        )
        for frame in _closing_frames(cid, row.id):
            yield frame
    finally:
        if not done:
            logger.warning("direct run={} conversation={}: the client closed the stream; stopping", ctx.run_id, cid)
            _background(svc.lease.request_stop(ctx.run_id, cid), f"stop:{ctx.run_id}")


# --------------------------------------------------------------------------- #
# Stop
# --------------------------------------------------------------------------- #

STOP_NO_RUN = "idle"
STOP_REQUESTED = "stopping"
STOP_ENDED = "stopped"
STOP_EXPIRED = "expired"


async def _planned_run_record(conversation_id: str, run_id: str) -> Any:
    """The run record of the planned run that holds the conversation, or None.

    The record's id is the run id, or the record stores the run id:
    ``submit_task_turn`` writes it before the run is queued, so a run that is
    still in the worker queue is found too. None = the record does not exist
    (yet); the newest record of the conversation is never taken instead, because
    it can belong to a run of another entry.
    """
    from bisheng.linsight.domain import task_exec

    return await task_exec._find_run_record(conversation_id, run_id)


async def _terminate_planned_record(record: Any) -> None:
    """What the deep-research stop does today: leave the queue, mark the record, tell the legacy subscribers."""
    from bisheng.linsight.domain.models.linsight_session_version import SessionVersionStatusEnum
    from bisheng.linsight.domain.services.workbench_impl import LinsightWorkbenchImpl

    if record.status in (SessionVersionStatusEnum.COMPLETED, SessionVersionStatusEnum.TERMINATED):
        return
    await LinsightWorkbenchImpl.terminate(record)


async def _planned_run_is_driven(svc: RunServices, record: Any) -> bool:
    """Whether a worker is executing the run right now (it holds the 30 s driver key)."""
    from bisheng.linsight.domain.task_exec import LINSIGHT_RUN_LOCK_KEY_PREFIX

    return bool(await svc.redis.exists(f"{LINSIGHT_RUN_LOCK_KEY_PREFIX}{record.id}"))


async def _append_run_stopped(
    svc: RunServices, conversation_id: str, run_id: str, unread: list[dict] | None = None
) -> None:
    """``run_stopped`` for a run without a coroutine, unless its stream is gone or already closed."""
    snapshot = await svc.stream.snapshot(conversation_id)
    if snapshot is None or snapshot.get("run_id") != run_id or snapshot.get("ended"):
        return
    await svc.stream.append(
        conversation_id,
        run_events.make_event(run_events.RUN_STOPPED, run_events.stopped_data(unread), run_id=run_id),
    )


async def _promote_waiting_run(svc: RunServices, conversation_id: str) -> None:
    """After a release that skipped the finish script: start a run that waits for the conversation."""
    try:
        await svc.dispatch.promote_pending(conversation_id)
    except Exception:
        # The run stays in the pending list; the worker's sweep starts it.
        logger.exception("stop: could not start the waiting run of conversation={}", conversation_id)


async def stop_conversation_run(
    conversation_id: str,
    *,
    session_version_id: str | None = None,
    terminate_record: bool = True,
    svc: RunServices | None = None,
) -> dict:
    """Stop the run that holds the conversation (AC-29).

    Returns ``{run_id, status, unread_messages}``. ``unread_messages`` are the
    inbox messages this call took back (design §7 item 6); for ``"stopping"``
    the list is empty here and arrives in the run's ``run_stopped`` event.

    * a running run sees the stop flag within a second, in whichever process it
      executes, writes ``run_stopped`` and releases the conversation itself
      (``status="stopping"``);
    * a run parked on a question has no coroutine: it is ended here and the
      conversation is idle when this returns (``"stopped"``);
    * a deep-research run still waiting in the worker queue is taken out of the
      queue and the conversation is released (``"stopped"``);
    * a run whose lease lapsed is reported as failed (``"expired"``);
    * no run: ``"idle"``.

    ``session_version_id`` restricts the stop to that deep-research run (the
    legacy terminate endpoint); ``terminate_record=False`` leaves the run record
    to the caller.
    """
    svc = svc or await run_services()
    state = await svc.lease.get_state(conversation_id)
    run_id = state.run_id
    if state.status == STATUS_IDLE or not run_id:
        return {"run_id": None, "status": STOP_NO_RUN, "unread_messages": []}

    planned = state.profile == PROFILE_PLANNED
    record = None
    if planned:
        record = await _planned_run_record(conversation_id, run_id)
        if session_version_id is not None and (record is None or record.id != session_version_id):
            # The conversation is held by another run than the one being terminated.
            return {"run_id": None, "status": STOP_NO_RUN, "unread_messages": []}
    elif session_version_id is not None:
        return {"run_id": None, "status": STOP_NO_RUN, "unread_messages": []}

    if state.status == STATUS_RUNNING and state.lease_until_ms <= int(time.time() * 1000):
        # Nothing is executing it any more: report it instead of flagging a dead run.
        await svc.dispatch.recover_expired(conversation_id)
        return {"run_id": run_id, "status": STOP_EXPIRED, "unread_messages": []}

    # Read before the conversation is released: afterwards a new run may clear it.
    parked_text = ""
    if state.status == STATUS_WAITING and not planned:
        snapshot = await svc.stream.snapshot(conversation_id)
        if snapshot is not None and snapshot.get("run_id") == run_id:
            parked_text = snapshot.get("text") or ""

    # A run with no live coroutine is ended by this call, so this call takes its
    # unread messages back (design §7 item 6). Before the conversation is
    # released: afterwards a new send would start a relay run for them. A
    # running run takes them back itself when it sees the stop flag.
    queued_planned = (
        state.status == STATUS_RUNNING
        and planned
        and record is not None
        and not await _planned_run_is_driven(svc, record)
    )
    unread: list[dict] = []
    if state.status == STATUS_WAITING or queued_planned:
        unread = await run_message_persist.discard_unread(svc.dispatch, conversation_id, redis=svc.redis)

    result = await svc.lease.request_stop(run_id, conversation_id)
    status = STOP_REQUESTED

    if result.parked_run_released:
        status = STOP_ENDED
        # Nobody consumes the flag of a parked run, and a later execution under
        # the same run id must not be stopped by it.
        await svc.redis.delete(stop_key(run_id))
        if not planned:
            await run_message_persist.persist_stopped_direct_answer(
                conversation_id, run_id, parked_text, redis=svc.redis
            )
        await _append_run_stopped(svc, conversation_id, run_id, unread)
        await _promote_waiting_run(svc, conversation_id)
    elif queued_planned:
        # Still in the worker queue: no worker will see the flag.
        status = STOP_ENDED
        if terminate_record:
            await _terminate_planned_record(record)
        await svc.redis.delete(stop_key(run_id))
        await svc.dispatch.on_run_finished(conversation_id, run_id)
        logger.info("stop: queued planned run={} conversation={} left the queue", run_id, conversation_id)
        return {"run_id": run_id, "status": status, "unread_messages": unread}

    if planned and record is not None and terminate_record:
        # A running deep-research run also stops through its record, as today.
        await _terminate_planned_record(record)
    logger.info(
        "stop: run={} conversation={} profile={} status={} unread_returned={}",
        run_id,
        conversation_id,
        state.profile,
        status,
        len(unread),
    )
    return {"run_id": run_id, "status": status, "unread_messages": unread}
