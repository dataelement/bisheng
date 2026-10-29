"""Columns added to realtime QA detail exports.

The fact index counts one successful question. Question text, answers, and
feedback opinions live on the expert-QA tables and on chat messages, and can
change after the question is counted, so they are read when the sheet is built.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from bisheng.database.models.message import ChatMessageDao
from bisheng.database.models.qa_expert import ANSWER_STATUS_DELETED
from bisheng.qa_expert.domain.identity import should_reveal_name
from bisheng.qa_expert.domain.repositories import AnonymousAliasRepository, AnswerRepository, QuestionRepository

QA_DETAIL_DATASET = "mid_realtime_qa_question_fact"
QA_DETAIL_COLUMNS = (
    ("asked_at_text", "提问时间"),
    ("question_text", "问题描述"),
    ("answer_text", "回答"),
    ("feedback_text", "反馈"),
)
QA_DETAIL_FIELDS = {field for field, _label in QA_DETAIL_COLUMNS}
QA_DETAIL_SOURCE_FIELDS = ("question_id", "qa_type", "conversation_id", "user_id")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MATCH_WINDOW_SECONDS = 10 * 60
_IGNORED_REMARKS = {"break_answer", "inaction"}
_ANONYMOUS_FALLBACK = "匿名同事"
# Stored ChatMessage.category values. Compare the literal, not MessageCategory:
# the test harness replaces bisheng.database.constants with a mock.
_QUESTION_CATEGORY = "question"
_ANSWER_CATEGORY = "answer"


def visible_detail_columns(
    columns: list[Any],
    rows: list[dict[str, Any]],
    keep_fields: set[str],
) -> list[Any]:
    """Drop columns that are empty on every row, except columns the sheet must keep."""
    populated = [
        column
        for column in columns
        if column.field in keep_fields or any(row.get(column.field) not in (None, "") for row in rows)
    ]
    return populated or columns


def format_asked_at(timestamp: Any) -> str:
    """Chart axis clock: Asia/Shanghai, to the second."""
    epoch = _epoch_seconds(timestamp)
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch, _SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


def apply_qa_detail(
    rows: list[dict[str, Any]],
    *,
    questions: list[Any],
    answers: list[Any],
    aliases: list[Any],
    messages: list[Any],
) -> None:
    """Fill the four columns in place. Missing sources leave the agreed cells blank."""
    questions_by_id = {
        int(question.id): question for question in questions if getattr(question, "id", None) is not None
    }
    answers_by_question: dict[int, list[Any]] = {}
    for answer in answers:
        answers_by_question.setdefault(int(answer.question_id), []).append(answer)
    aliases_by_asker = {
        (int(alias.question_id), int(alias.user_id)): str(alias.alias_label or "")
        for alias in aliases
        if getattr(alias, "question_id", None) is not None and getattr(alias, "user_id", None) is not None
    }
    turns_by_chat = _turns_by_chat(messages)

    for row in rows:
        row["asked_at_text"] = format_asked_at(row.get("timestamp"))
        row["question_text"] = ""
        row["answer_text"] = ""
        row["feedback_text"] = ""
        if str(row.get("qa_type") or "") == "expert":
            _apply_expert_row(row, questions_by_id, answers_by_question, aliases_by_asker)
            continue
        if str(row.get("qa_type") or "") in {"smart", "document"}:
            _apply_chat_row(row, turns_by_chat)


async def enrich_qa_detail_rows(rows: list[dict[str, Any]]) -> None:
    """Load expert questions and chat turns once, then fill every exported row."""
    question_ids = sorted(
        {
            question_id
            for row in rows
            if str(row.get("qa_type") or "") == "expert" and (question_id := _optional_int(row.get("question_id")))
        }
    )
    chat_ids = sorted(
        {
            str(row.get("conversation_id")).strip()
            for row in rows
            if str(row.get("qa_type") or "") in {"smart", "document"} and str(row.get("conversation_id") or "").strip()
        }
    )
    questions = await QuestionRepository().get_by_ids(question_ids) if question_ids else []
    answer_rows = await AnswerRepository().list_all_by_question_ids(question_ids) if question_ids else []
    aliases = await AnonymousAliasRepository().list_by_question_ids(question_ids) if question_ids else []
    messages = await ChatMessageDao.get_all_message_by_chat_ids(chat_ids) if chat_ids else []
    apply_qa_detail(rows, questions=questions, answers=answer_rows, aliases=aliases, messages=messages)


def _apply_expert_row(
    row: dict[str, Any],
    questions_by_id: dict[int, Any],
    answers_by_question: dict[int, list[Any]],
    aliases_by_asker: dict[tuple[int, int], str],
) -> None:
    question_id = _optional_int(row.get("question_id"))
    question = questions_by_id.get(question_id) if question_id is not None else None
    if question is None:
        return
    row["question_text"] = _join_text(getattr(question, "title", None), getattr(question, "description", None))
    kept = [
        answer
        for answer in answers_by_question.get(question_id, [])
        if int(getattr(answer, "status", 0) or 0) != ANSWER_STATUS_DELETED
    ]
    kept.sort(key=lambda answer: (_epoch_seconds(getattr(answer, "created_at", None)) or 0, int(answer.id or 0)))
    row["answer_text"] = _join_text(*(getattr(answer, "content", None) for answer in kept))
    _mask_asker(row, question, aliases_by_asker)


def _mask_asker(
    row: dict[str, Any],
    question: Any,
    aliases_by_asker: dict[tuple[int, int], str],
) -> None:
    anonymous = bool(int(getattr(question, "asker_anonymous", 0) or 0))
    if should_reveal_name(
        anonymous=anonymous,
        question_type=str(getattr(question, "question_type", "") or ""),
        reveal_on_public=getattr(question, "asker_reveal_on_public", None),
    ):
        return
    asker_id = _optional_int(getattr(question, "user_id", None))
    label = aliases_by_asker.get((int(question.id), asker_id)) if asker_id is not None else ""
    row["user_name"] = label or _ANONYMOUS_FALLBACK


def _apply_chat_row(row: dict[str, Any], turns_by_chat: dict[str, list[tuple[Any, Any | None]]]) -> None:
    chat_id = str(row.get("conversation_id") or "").strip()
    fact_time = _epoch_seconds(row.get("timestamp"))
    turn = _select_turn(turns_by_chat.get(chat_id, []), fact_time)
    if turn is None:
        return
    question_message, answer_message = turn
    row["question_text"] = _json_text(question_message, "query")
    row["answer_text"] = _json_text(answer_message, "content") if answer_message is not None else ""
    row["feedback_text"] = _feedback_text(answer_message)


def _turns_by_chat(messages: list[Any]) -> dict[str, list[tuple[Any, Any | None]]]:
    grouped: dict[str, list[Any]] = {}
    for message in messages:
        chat_id = str(getattr(message, "chat_id", "") or "").strip()
        if chat_id:
            grouped.setdefault(chat_id, []).append(message)
    return {chat_id: _pair_turns(chat_messages) for chat_id, chat_messages in grouped.items()}


def _pair_turns(messages: list[Any]) -> list[tuple[Any, Any | None]]:
    ordered = sorted(
        messages,
        key=lambda message: (
            _epoch_seconds(getattr(message, "create_time", None)) or 0,
            int(getattr(message, "id", 0) or 0),
        ),
    )
    turns: list[tuple[Any, Any | None]] = []
    pending: Any | None = None
    for message in ordered:
        if _is_question(message):
            if pending is not None:
                turns.append((pending, None))
            pending = message
            continue
        if _is_answer(message) and pending is not None:
            turns.append((pending, message))
            pending = None
    if pending is not None:
        turns.append((pending, None))
    return turns


def _select_turn(
    turns: list[tuple[Any, Any | None]],
    fact_time: int | None,
) -> tuple[Any, Any | None] | None:
    if fact_time is None:
        return None
    scored: list[tuple[int, tuple[Any, Any | None]]] = []
    for turn in turns:
        question_time = _epoch_seconds(getattr(turn[0], "create_time", None))
        if question_time is None:
            continue
        scored.append((abs(question_time - fact_time), turn))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    if scored[0][0] > _MATCH_WINDOW_SECONDS:
        return None
    return scored[0][1]


def _is_question(message: Any) -> bool:
    return str(getattr(message, "category", "") or "") == _QUESTION_CATEGORY and not bool(
        getattr(message, "is_bot", False)
    )


def _is_answer(message: Any) -> bool:
    return str(getattr(message, "category", "") or "") == _ANSWER_CATEGORY and bool(getattr(message, "is_bot", False))


def _json_text(message: Any | None, key: str) -> str:
    if message is None:
        return ""
    raw = getattr(message, "message", None)
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get(key) or "").strip()


def _feedback_text(message: Any | None) -> str:
    if message is None:
        return ""
    remark = str(getattr(message, "remark", "") or "").strip()
    if not remark or remark in _IGNORED_REMARKS:
        return ""
    return remark


def _join_text(*parts: Any) -> str:
    return "\n".join(text for part in parts if (text := str(part or "").strip()))


def _optional_int(value: Any) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _epoch_seconds(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=_SHANGHAI)
        return int(value.timestamp())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return int(number)
    text = str(value).strip()
    if text.isdigit():
        return _epoch_seconds(int(text))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _epoch_seconds(parsed)
