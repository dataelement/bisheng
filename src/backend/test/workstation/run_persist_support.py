"""Shared fakes of the F004 message-persistence tests (T042 and its neighbours).

``MessageTable`` replaces the ``ChatMessageDao`` methods the unified runtime
uses with an in-memory table, so the real row builders, the real projector and
the real history formatter run against it.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from bisheng.database.models.message import ChatMessage, ChatMessageDao


class MessageTable:
    def __init__(self) -> None:
        self.rows: list[ChatMessage] = []
        self.updates: list[tuple[int, dict]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> MessageTable:
        monkeypatch.setattr(ChatMessageDao, "ainsert_one", self.ainsert_one)
        monkeypatch.setattr(ChatMessageDao, "update_fields_by_id", self.update_fields_by_id)
        monkeypatch.setattr(ChatMessageDao, "aget_messages_by_chat_id", self.aget_messages_by_chat_id)
        return self

    async def ainsert_one(self, row: ChatMessage) -> ChatMessage:
        row.id = 1000 + len(self.rows)
        if row.create_time is None:
            row.create_time = datetime(2026, 11, 18, 10, 0, 0)
        self.rows.append(row)
        return row

    async def update_fields_by_id(self, message_id: int, **fields: Any) -> None:
        self.updates.append((message_id, fields))
        for row in self.rows:
            if row.id == message_id:
                for key, value in fields.items():
                    setattr(row, key, value)

    async def aget_messages_by_chat_id(
        self, chat_id: str, category_list: list | None = None, limit: int = 10, offset: int = 0
    ) -> list[ChatMessage]:
        rows = [r for r in self.rows if r.chat_id == chat_id]
        if category_list:
            rows = [r for r in rows if r.category in category_list]
        return rows[-limit:]

    # -- views ---------------------------------------------------------------

    def questions(self) -> list[ChatMessage]:
        return [r for r in self.rows if r.category == "question"]

    def answers(self) -> list[ChatMessage]:
        return [r for r in self.rows if r.category == "agent_answer"]

    @staticmethod
    def extra(row: ChatMessage) -> dict:
        return json.loads(row.extra or "{}")
