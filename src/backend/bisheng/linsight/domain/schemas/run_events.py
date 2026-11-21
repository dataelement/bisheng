"""F004 unified run events (design §4.3).

One event model for both answer modes. Daily chat (``direct``) and deep research
(``planned``) publish the same event types on one channel, the Redis Stream
written by ``run_event_stream.RunEventStream.append``. A stored event has the
outer shape ``{id, run_id, seq, type, data, ts}``; ``id``, ``seq`` and ``ts`` are
assigned by the stream, so the builders here return only ``{type, data}`` (plus
``run_id`` when the caller passes one).

This module is pure data: no Redis, no database, no agent framework.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# -- event types ----------------------------------------------------------

RUN_STARTED = "run_started"
RUN_FINISHED = "run_finished"
RUN_FAILED = "run_failed"
RUN_STOPPED = "run_stopped"
QUEUED = "queued"
TEXT = "text"
THINKING = "thinking"
TOOL_CALL = "tool_call"
PLAN = "plan"
STEER_ACCEPTED = "steer_accepted"
STEER_READ = "steer_read"
ASK_USER = "ask_user"
ASK_USER_ANSWERED = "ask_user_answered"
FILE = "file"
# Produced by the reader (``RunEventStream.read``), never appended by a run.
RESYNC = "resync"

RunEventType = Literal[
    "run_started",
    "run_finished",
    "run_failed",
    "run_stopped",
    "queued",
    "text",
    "thinking",
    "tool_call",
    "plan",
    "steer_accepted",
    "steer_read",
    "ask_user",
    "ask_user_answered",
    "file",
    "resync",
]

TERMINAL_EVENT_TYPES = frozenset({RUN_FINISHED, RUN_FAILED, RUN_STOPPED})

# Optional field of a terminal event's ``data`` (a ``direct`` run): the ``files``
# of the answer row this run stores, as the history returns them. Each item's
# ``file_id`` is the answer's own copy and ``workspace_file_id`` the id the live
# ``file`` events used (absent when the copy failed; ``file_id`` is then the
# live id). Lets the client show the finished answer's files with the row's ids
# before it reloads the history (design §7 item 11). Absent when the run stored
# no generated file.
ANSWER_FILES_FIELD = "answer_files"

PlanItemStatus = Literal["pending", "in_progress", "completed", "cancelled"]
PLAN_PENDING: PlanItemStatus = "pending"
PLAN_IN_PROGRESS: PlanItemStatus = "in_progress"
PLAN_COMPLETED: PlanItemStatus = "completed"
PLAN_CANCELLED: PlanItemStatus = "cancelled"


# -- data payloads --------------------------------------------------------


class PlanItem(BaseModel):
    """One row of the plan. ``id`` stays the same when the row is reworded."""

    id: str
    content: str
    # Wording before the most recent rewrite of this row (AC-10). Absent when the
    # row was never reworded.
    previous_content: str | None = None
    status: PlanItemStatus = PLAN_PENDING


class PlanData(BaseModel):
    """``plan``: always the complete plan, never a delta."""

    items: list[PlanItem] = Field(default_factory=list)


class TextData(BaseModel):
    """``text`` / ``thinking``: one delta. The stream concatenates ``text``."""

    text: str
    # ``thinking`` only: id of the contiguous thinking segment, and the subagent
    # namespace when the reasoning is a subagent's.
    call_id: str | None = None
    namespace: str | None = None


class ToolCallData(BaseModel):
    """``tool_call``: the start frame and the end frame share ``call_id``."""

    call_id: str
    name: str
    status: Literal["start", "end"]
    # ``tool`` / ``knowledge`` / ``subagent`` (a delegation to a subagent).
    step_type: str = "tool"
    call_reason: str = ""
    params: Any = None
    # Present on the end frame only.
    output: str | None = None
    extra_info: dict[str, Any] = Field(default_factory=dict)


class AskUserQuestion(BaseModel):
    question: str
    options: list[str] = Field(default_factory=list)
    multiple: bool = False
    # Id of this question inside the card (``q_0``, ``q_1`` ...), which the answer
    # endpoint uses to pair answers with questions.
    id: str | None = None


class AskUserData(BaseModel):
    """``ask_user``: same structure as today's ``user_input`` card."""

    call_id: str
    reason: str = ""
    questions: list[AskUserQuestion] = Field(default_factory=list)


class AskUserAnsweredData(BaseModel):
    call_id: str | None = None
    answer: Any = None


class SteerData(BaseModel):
    """``steer_accepted`` / ``steer_read``."""

    message_id: str


class FileData(BaseModel):
    """``file``: one deliverable became available (AC-24)."""

    file_id: str
    name: str
    path: str
    size: int | None = None
    source: str | None = None


class QueuedData(BaseModel):
    position: int


class RunFailedData(BaseModel):
    """``run_failed``: the structure of deep research's existing error card."""

    # Platform error code (11090 / 11091 umbrella codes or a business code).
    code: int
    # Stable failure class the client picks its copy from (``error_type``).
    reason: str
    # Redacted exception type and message for the "view details" disclosure.
    detail: str
    # Identifier support uses to find the failure in the logs. None when a
    # registered business error code already tells the user what to do.
    reference_id: str | None = None
    failure_info: dict[str, Any] | None = None


class UnreadMessage(BaseModel):
    """A message that was still in the inbox when the user stopped the run."""

    message_id: str
    text: str = ""
    files: list[Any] = Field(default_factory=list)


class RunStoppedData(BaseModel):
    """``run_stopped``: the user stopped the run. Not a failure.

    ``status`` is always ``"stopped"``; the answer row of the run stores the same
    value in ``extra.status``. ``unread_messages`` are the messages sent during
    the run that it never read: they were removed from the inbox, their question
    rows were deleted, and no run will answer them. The client puts their text
    back into the input box. Always present, empty when there were none.
    """

    reason: str = "user"
    status: Literal["stopped"] = "stopped"
    unread_messages: list[UnreadMessage] = Field(default_factory=list)


STATUS_STOPPED = "stopped"


def stopped_data(unread_messages: list[dict[str, Any]] | None = None, *, reason: str = "user") -> dict[str, Any]:
    """``data`` of a ``run_stopped`` event."""
    return RunStoppedData(
        reason=reason,
        unread_messages=[
            UnreadMessage(
                message_id=str(message.get("message_id") or ""),
                text=message.get("text") or "",
                files=message.get("files") or [],
            )
            for message in unread_messages or []
        ],
    ).model_dump()


class ResyncData(BaseModel):
    text: str = ""
    thinking: str = ""
    plan: list[PlanItem] = Field(default_factory=list)
    files: list[FileData] = Field(default_factory=list)
    pending_question: AskUserData | None = None
    # True when the run this state belongs to has ended: no more events follow.
    ended: bool = False
    # How it ended (``finished`` / ``failed`` / ``stopped``). Present only when
    # ``ended`` is true and the terminal event was recorded.
    status: Literal["finished", "failed", "stopped"] | None = None
    # With ``ended``: the messages the terminal event gave back (``run_stopped``,
    # or a ``run_failed`` of a relay run that could not be created). Absent when
    # there were none.
    unread_messages: list[UnreadMessage] | None = None


class RunEvent(BaseModel):
    """Outer shape of an event as a reader receives it."""

    id: str | None = None
    run_id: str | None = None
    seq: int | None = None
    type: RunEventType
    data: dict[str, Any] = Field(default_factory=dict)
    ts: int | None = None


# -- builders -------------------------------------------------------------


def make_event(
    event_type: str, data: BaseModel | dict[str, Any] | None = None, *, run_id: str | None = None
) -> dict[str, Any]:
    """Build the plain dict ``RunEventStream.append`` takes.

    Optional fields that are unset are left out of ``data``. ``run_failed`` is the
    exception: its four contract fields are always present.
    """
    if isinstance(data, RunFailedData):
        payload = data.model_dump(exclude={"failure_info"} if data.failure_info is None else None)
    elif isinstance(data, BaseModel):
        payload = data.model_dump(exclude_none=True)
    else:
        payload = dict(data or {})
    event: dict[str, Any] = {"type": event_type, "data": payload}
    if run_id is not None:
        event["run_id"] = run_id
    return event


def plan_progress(items: list[dict[str, Any]] | list[PlanItem]) -> tuple[int, int]:
    """``(completed, total)`` of a ``plan`` event's items (AC-08).

    A cancelled row is no longer part of the work, so it counts in neither number.
    """
    statuses = [item.status if isinstance(item, PlanItem) else item.get("status") for item in items]
    live = [status for status in statuses if status != PLAN_CANCELLED]
    return sum(1 for status in live if status == PLAN_COMPLETED), len(live)
