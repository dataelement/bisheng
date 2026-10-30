"""Reading daily history hides inline thinking without rewriting stored rows."""

import json

import pytest

from bisheng.database.models.message import ChatMessage
from bisheng.workstation.domain.services.chat_helpers import _convert_legacy_message, _format_new_message


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("text", ["<think>secret</think>Answer", "Answer<think>unfinished secret"])
def test_history_hides_inline_thinking(legacy, text):
    raw = text if legacy else json.dumps({"msg": text, "events": [{"type": "thinking", "content": "Plan"}]})
    row = ChatMessage(is_bot=True, type="end", category="answer" if legacy else "agent_answer", flow_id="", message=raw)
    result = (_convert_legacy_message if legacy else _format_new_message)(row)
    assert result["message"]["msg"] == "Answer"
    assert row.message == raw
    if not legacy:
        assert result["message"]["events"] == [{"type": "thinking", "content": "Plan"}]


def test_user_question_is_not_filtered():
    row = ChatMessage(is_bot=False, type="over", category="question", flow_id="", message="Explain <think> tags")
    assert _convert_legacy_message(row)["message"]["query"] == "Explain <think> tags"
