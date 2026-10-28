"""回答过程失败的判定. 失败时会标记会话."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from bisheng.database.models.answer_failure import (
    message_has_answer_failure,
    node_failure_should_persist,
    note_answer_failure,
    payload_has_answer_failure,
    tool_output_error,
)


def _message(**kwargs):
    defaults = {"is_bot": True, "category": "answer", "extra": "{}", "message": "好的"}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_plain_answer_is_not_abnormal():
    assert message_has_answer_failure(_message()) is False


def test_extra_error_timeout_and_unfinished_are_abnormal():
    assert message_has_answer_failure(_message(extra='{"error": true, "error_msg": "回答超时"}'))
    assert message_has_answer_failure(_message(extra='{"unfinished": true}'))
    assert message_has_answer_failure(_message(extra='{"error": false}')) is False
    assert message_has_answer_failure(_message(extra='{"error": ""}')) is False


def test_tool_call_failure_inside_answer_events_is_abnormal():
    body = '{"msg": "部分结果", "events": [{"type": "tool_call", "error": "网络中断"}]}'
    assert message_has_answer_failure(_message(category="agent_answer", message=body))
    empty = '{"events": [{"type": "tool_call", "error": null}]}'
    assert message_has_answer_failure(_message(category="agent_answer", message=empty)) is False


def test_unused_tool_prep_failure_is_not_abnormal():
    body = (
        '{"msg": "你好", "events": [{"type": "tool_call", "tool_call_id": "init_fail_abc", '
        '"tool_name": "web_search", "error": "联网搜索未配置"}]}'
    )
    assert message_has_answer_failure(_message(category="agent_answer", message=body)) is False
    mixed = (
        '{"msg": "部分结果", "events": ['
        '{"type": "tool_call", "tool_call_id": "init_fail_abc", "error": "联网搜索未配置"},'
        '{"type": "tool_call", "tool_call_id": "call_1", "error": "网络中断"}]}'
    )
    assert message_has_answer_failure(_message(category="agent_answer", message=mixed))


def test_node_failure_counts_and_user_stop_does_not():
    assert payload_has_answer_failure(
        is_bot=True,
        category="node_run",
        extra="{}",
        message='{"name": "检索", "reason": "连接超时"}',
    )
    assert (
        payload_has_answer_failure(
            is_bot=True,
            category="node_run",
            extra="{}",
            message='{"name": "检索", "reason": "stop by user"}',
        )
        is False
    )
    assert node_failure_should_persist("连接超时")
    assert node_failure_should_persist("workflow stop by user") is False
    assert node_failure_should_persist("") is False
    assert node_failure_should_persist(None) is False


def test_tool_status_and_error_category_are_abnormal():
    assert payload_has_answer_failure(
        is_bot=True,
        category="tool_result",
        extra="{}",
        message='{"status": "error"}',
    )
    assert payload_has_answer_failure(
        is_bot=False,
        category="error",
        extra="{}",
        message="workflow failed",
    )
    assert payload_has_answer_failure(
        is_bot=False,
        category="question",
        extra='{"error": true}',
        message="用户问题",
    )


def test_tool_output_error_follows_status_not_the_word_error():
    ok = SimpleNamespace(status="success", content="请解释 error")
    failed = SimpleNamespace(status="error", content="网络中断")
    assert tool_output_error(ok) is None
    assert tool_output_error(failed) == "网络中断"
    assert tool_output_error({"status": "error"}) == "工具调用失败"
    assert tool_output_error({"content": "error"}) is None


def test_user_answer_text_containing_error_word_is_not_abnormal():
    assert message_has_answer_failure(_message(message="请解释 error 这个词")) is False


def test_note_marks_failed_session_and_skips_success(monkeypatch):
    marked = []
    dao = MagicMock()
    dao.mark_answer_abnormal.side_effect = lambda chat_id: marked.append(chat_id)
    monkeypatch.setattr("bisheng.database.models.session.MessageSessionDao", dao)

    note_answer_failure(_message(chat_id="c-ok"))
    note_answer_failure(_message(chat_id="c-bad", extra='{"error": true}'))
    note_answer_failure(_message(chat_id="", extra='{"error": true}'))

    assert marked == ["c-bad"]
