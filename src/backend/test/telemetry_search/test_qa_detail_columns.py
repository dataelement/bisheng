"""Realtime QA detail columns: one question row, filled from the live sources."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from bisheng.telemetry_search.domain.services.dashboard_export_detail import DetailColumn
from bisheng.telemetry_search.domain.services.qa_detail_columns import (
    QA_DETAIL_FIELDS,
    apply_qa_detail,
    format_asked_at,
    visible_detail_columns,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _epoch(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=_SHANGHAI).timestamp())


def _question(**overrides):
    values = {
        "id": 7,
        "user_id": 3,
        "title": "轧辊寿命",
        "description": "多久更换",
        "asker_anonymous": 0,
        "question_type": "public",
        "asker_reveal_on_public": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _answer(answer_id: int, content: str, minute: int, status: int = 1):
    return SimpleNamespace(
        id=answer_id,
        question_id=7,
        content=content,
        status=status,
        created_at=datetime(2026, 7, 27, 9, minute, tzinfo=_SHANGHAI),
    )


def _message(
    message_id: int,
    chat_id: str,
    category: str,
    is_bot: bool,
    body: str,
    minute: int,
    remark: str = "",
    hour: int = 10,
):
    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        category=category,
        is_bot=is_bot,
        message=body,
        remark=remark,
        create_time=datetime(2026, 7, 27, hour, minute, tzinfo=_SHANGHAI),
    )


def test_asked_at_uses_shanghai_clock_to_the_second():
    assert format_asked_at(_epoch(2026, 7, 27, 9, 5, 6)) == "2026-07-27 09:05:06"


def test_expert_row_keeps_every_live_answer_and_blank_feedback():
    row = {
        "qa_type": "expert",
        "question_id": "7",
        "user_name": "王五",
        "timestamp": _epoch(2026, 7, 27, 9, 0),
    }

    apply_qa_detail(
        [row],
        questions=[_question()],
        answers=[
            _answer(2, "后写的", 12),
            _answer(1, "先写的", 5),
            _answer(3, "已删除", 8, status=3),
        ],
        aliases=[],
        messages=[],
    )

    assert row["asked_at_text"] == "2026-07-27 09:00:00"
    assert row["question_text"] == "轧辊寿命\n多久更换"
    assert row["answer_text"] == "先写的\n后写的"
    assert row["feedback_text"] == ""
    assert row["user_name"] == "王五"


def test_anonymous_expert_uses_existing_alias_and_does_not_invent_one():
    hidden = {
        "qa_type": "expert",
        "question_id": 7,
        "user_name": "王五",
        "timestamp": _epoch(2026, 7, 27, 9, 0),
    }
    missing_alias = {**hidden, "question_id": 8}
    revealed = {**hidden, "question_id": 9}

    apply_qa_detail(
        [hidden, missing_alias, revealed],
        questions=[
            _question(asker_anonymous=1),
            _question(id=8, asker_anonymous=1),
            _question(id=9, asker_anonymous=1, asker_reveal_on_public=1),
        ],
        answers=[],
        aliases=[SimpleNamespace(question_id=7, user_id=3, alias_label="匿名同事A")],
        messages=[],
    )

    assert hidden["user_name"] == "匿名同事A"
    assert missing_alias["user_name"] == "匿名同事"
    assert revealed["user_name"] == "王五"


def test_anonymous_without_an_alias_row_uses_the_fallback_label():
    row = {
        "qa_type": "expert",
        "question_id": "8",
        "user_name": "王五",
        "timestamp": _epoch(2026, 7, 27, 9, 0),
    }

    apply_qa_detail(
        [row],
        questions=[_question(id=8, asker_anonymous=1, question_type="directed")],
        answers=[],
        aliases=[],
        messages=[],
    )

    assert row["user_name"] == "匿名同事"
    assert row["question_text"] == "轧辊寿命\n多久更换"


def test_chat_turn_uses_the_nearest_question_and_its_opinion():
    fact_time = _epoch(2026, 7, 27, 10, 5)
    row = {
        "qa_type": "smart",
        "conversation_id": "chat-1",
        "timestamp": fact_time,
    }
    earlier = _message(1, "chat-1", "question", False, '{"query": "上一问"}', 0)
    earlier_answer = _message(2, "chat-1", "answer", True, '{"content": "上一答"}', 1, remark="旧意见")
    current = _message(3, "chat-1", "question", False, '{"query": "这一问"}', 5)
    current_answer = _message(4, "chat-1", "answer", True, '{"content": "这一答"}', 6, remark="说得太长")

    apply_qa_detail(
        [row],
        questions=[],
        answers=[],
        aliases=[],
        messages=[earlier, earlier_answer, current, current_answer],
    )

    assert row["question_text"] == "这一问"
    assert row["answer_text"] == "这一答"
    assert row["feedback_text"] == "说得太长"


def test_chat_feedback_ignores_like_placeholders_and_unmatched_turns():
    fact_time = _epoch(2026, 7, 27, 10, 5)
    near = {
        "qa_type": "document",
        "conversation_id": "chat-2",
        "timestamp": fact_time,
    }
    tied = {"qa_type": "document", "conversation_id": "chat-3", "timestamp": fact_time}
    far = {"qa_type": "smart", "conversation_id": "chat-4", "timestamp": fact_time}
    broken = {"qa_type": "smart", "conversation_id": "chat-5", "timestamp": fact_time}

    apply_qa_detail(
        [near, tied, far, broken],
        questions=[],
        answers=[],
        aliases=[],
        messages=[
            _message(1, "chat-2", "question", False, '{"query": "问"}', 5),
            _message(2, "chat-2", "answer", True, '{"content": "答"}', 6, remark="break_answer"),
            _message(3, "chat-3", "question", False, '{"query": "甲"}', 4),
            _message(4, "chat-3", "answer", True, '{"content": "甲答"}', 4),
            _message(5, "chat-3", "question", False, '{"query": "乙"}', 6),
            _message(6, "chat-3", "answer", True, '{"content": "乙答"}', 6),
            _message(7, "chat-4", "question", False, '{"query": "太早"}', 0, hour=9),
            _message(8, "chat-4", "answer", True, '{"content": "太早的答"}', 1, hour=9, remark="不该配上"),
            _message(9, "chat-5", "question", False, "不是 JSON", 5),
            _message(10, "chat-5", "answer", True, "也不是", 6, remark="inaction"),
        ],
    )

    assert near["question_text"] == "问"
    assert near["answer_text"] == "答"
    assert near["feedback_text"] == ""
    assert tied["question_text"] == ""
    assert tied["answer_text"] == ""
    assert far["question_text"] == ""
    assert broken["question_text"] == ""
    assert broken["feedback_text"] == ""


def test_blank_feedback_column_is_kept_for_realtime_qa():
    columns = [
        DetailColumn(field="user_name", label="提问人"),
        DetailColumn(field="feedback_text", label="反馈"),
    ]
    rows = [{"user_name": "王五", "feedback_text": ""}]

    visible = visible_detail_columns(columns, rows, QA_DETAIL_FIELDS)

    assert [column.label for column in visible] == ["提问人", "反馈"]
