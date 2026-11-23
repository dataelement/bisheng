"""Daily mode: a turn blocked by content safety ends its memory turn without consolidation (F132 T051, AC-41)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bisheng.workstation.domain.services import chat_service


async def test_ac41_content_safety_blocked_turn_is_never_consolidated(monkeypatch):
    """AC-41 / AC-18: a turn blocked by content safety moves the watermark past itself."""
    end_turn = AsyncMock()
    monkeypatch.setattr(chat_service.MemoryActivity, "end_turn", end_turn)
    monkeypatch.setattr(chat_service.ChatMessageDao, "ainsert_one", AsyncMock(return_value=SimpleNamespace(id=42)))
    monkeypatch.setattr(chat_service, "iter_blocked_sse", lambda **kw: iter(["data: x\n\n"]))
    # 3.1: a blocked turn also flags the session row (MessageSession.sensitive_status).
    mark_violation = MagicMock()
    monkeypatch.setattr(chat_service, "mark_session_content_violation", mark_violation)
    conversation = SimpleNamespace(chat_id="blocked-chat", user_id=101)
    data = SimpleNamespace(text="违规内容", files=[])
    response = chat_service._respond_blocked_workbench(
        conversation, SimpleNamespace(id=41), SimpleNamespace(displayName="m"), data, "已拦截"
    )
    _ = [chunk async for chunk in response.body_iterator]
    end_turn.assert_awaited_once_with("blocked-chat", 42, False)
    mark_violation.assert_called_once_with("blocked-chat")
