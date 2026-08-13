"""History replay must name the attachments of past turns.

``get_chat_history`` parsed a question row as ``{"query": ...}`` and dropped the
sibling ``files`` list, so nothing in the replayed history said a file had ever
been attached. Combined with a code interpreter that cannot see the upload
either, the model had no signal that a document was in play — and a production
turn answered "KASAMA 与 NAKONDE 的培训是否相同" with zero tool calls, quoting
"Table 11-3, PDF 第 448-450 页" purely from its own earlier summary.

Only NAMES are replayed. The extracted text was already truncated into that
turn's prompt and replaying it would blow ``history_max_tokens`` (default 8000);
the point is that the model knows a file exists so it can say it cannot re-read
it, not that it gets the content a second time.

``ChatMessageDao.aget_messages_by_chat_id`` is patched; the unit under test is
``WorkStationService.get_chat_history``.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from langchain_core.messages import HumanMessage

from bisheng.database.models.message import ChatMessage, ChatMessageDao
from bisheng.workstation.domain.services.workstation_service import WorkStationService


def _question(message: str, extra: str = "{}") -> ChatMessage:
    return ChatMessage(
        id=1,
        is_bot=False,
        chat_id="chat-1",
        user_id=1,
        flow_id="",
        type="over",
        category="question",
        message=message,
        extra=extra,
        tenant_id=1,
        create_time=datetime(2026, 8, 12, 15, 49, 49),
        update_time=datetime(2026, 8, 12, 15, 49, 49),
    )


@pytest.fixture
def patch_messages(monkeypatch: pytest.MonkeyPatch):
    state: dict = {"rows": []}

    async def _fake(_cls, chat_id, categories=None, size=4):
        return list(state["rows"])

    monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", classmethod(_fake))
    return state


def _human(history) -> str:
    return "\n".join(str(m.content) for m in history if isinstance(m, HumanMessage))


async def test_attachment_names_are_replayed(patch_messages):
    payload = json.dumps(
        {
            "query": "帮我拆析标书里的 FAT 费用",
            "files": [
                {"file_id": "a", "file_name": "ZTIP_RfB_NAKONDE.pdf"},
                {"file_id": "b", "file_name": "Part 2-Employer's Requirements.pdf"},
            ],
        },
        ensure_ascii=False,
    )
    patch_messages["rows"] = [_question(payload)]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert "帮我拆析标书里的 FAT 费用" in content
    assert "ZTIP_RfB_NAKONDE.pdf" in content
    assert "Part 2-Employer's Requirements.pdf" in content


async def test_no_attachments_adds_no_noise(patch_messages):
    patch_messages["rows"] = [_question(json.dumps({"query": "你好", "files": []}, ensure_ascii=False))]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert content == "你好"


@pytest.mark.parametrize(
    "file_item,expected",
    [
        ({"file_name": "a.pdf", "filename": "b.pdf", "name": "c.pdf"}, "a.pdf"),
        ({"filename": "b.pdf", "name": "c.pdf"}, "b.pdf"),
        ({"name": "c.pdf"}, "c.pdf"),
        # Task-mode ingest rows carry the original under yet another key.
        ({"original_filename": "d.xlsx"}, "d.xlsx"),
    ],
)
async def test_name_key_fallback_chain(patch_messages, file_item, expected):
    """Daily uploads and task-mode ingests disagree on the key; try each in turn."""
    payload = json.dumps({"query": "q", "files": [file_item]}, ensure_ascii=False)
    patch_messages["rows"] = [_question(payload)]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert expected in content


@pytest.mark.parametrize(
    "files",
    [
        "not-a-list",
        [None, 42, "x"],
        [{"file_id": "a"}],  # present but nameless
        [{"file_name": "   "}],  # whitespace only
    ],
)
async def test_malformed_file_entries_do_not_break_history(patch_messages, files):
    payload = json.dumps({"query": "q", "files": files}, ensure_ascii=False)
    patch_messages["rows"] = [_question(payload)]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert content == "q"


async def test_legacy_plain_text_question_is_unaffected(patch_messages):
    """Pre-2.5 rows hold bare text, not JSON — they must still replay verbatim."""
    patch_messages["rows"] = [_question("老格式的纯文本提问")]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert content == "老格式的纯文本提问"


async def test_rewritten_prompt_still_wins_but_keeps_attachments(patch_messages):
    """``extra.prompt`` overrides the query text; the attachment list survives it."""
    payload = json.dumps(
        {"query": "原始提问", "files": [{"file_name": "tender.pdf"}]},
        ensure_ascii=False,
    )
    patch_messages["rows"] = [_question(payload, extra=json.dumps({"prompt": "被改写的提问"}))]

    content = _human(await WorkStationService.get_chat_history("chat-1", max_tokens=None))

    assert "被改写的提问" in content
    assert "原始提问" not in content
    assert "tender.pdf" in content
