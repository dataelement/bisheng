"""Workbench content-safety SSE / persistence helpers.

Evaluate lives on SensitiveWordPolicyService so linsight can call it without
importing workstation (avoids a workstation ↔ linsight cycle).
"""

from __future__ import annotations

import json
from collections.abc import Iterator

from bisheng.database.models.message import ChatMessage
from bisheng.workstation.domain.services.chat_helpers import _sse_resp, user_message


def blocked_answer_payload(auto_reply: str) -> dict:
    return {"msg": auto_reply, "events": [{"type": "text", "content": auto_reply}]}


def blocked_answer_extra() -> str:
    return json.dumps({"content_safety": True})


def build_blocked_answer_row(
    *,
    user_id: int,
    conversation_id: str,
    sender: str,
    auto_reply: str,
) -> ChatMessage:
    return ChatMessage(
        user_id=user_id,
        chat_id=conversation_id,
        flow_id="",
        type="end",
        is_bot=True,
        message=json.dumps(blocked_answer_payload(auto_reply), ensure_ascii=False),
        category="agent_answer",
        sender=sender,
        extra=blocked_answer_extra(),
        source=0,
    )


def iter_blocked_sse(
    *,
    conversation_id: str,
    user_message_id: int,
    user_text: str,
    files: list | None,
    auto_reply: str,
    answer_message_id: int,
) -> Iterator[str]:
    payload = blocked_answer_payload(auto_reply)
    yield user_message(user_message_id, conversation_id, "User", user_text or "")
    yield _sse_resp("processing", "begin", "", conversation_id)
    yield _sse_resp(
        "question",
        "over",
        {"query": user_text or "", "files": files or []},
        conversation_id,
        message_id=user_message_id,
        is_bot=False,
    )
    yield _sse_resp(
        "agent_answer",
        "end",
        payload,
        conversation_id,
        message_id=answer_message_id,
    )
    yield _sse_resp("processing", "close", "", conversation_id)
    final_payload = {
        "final": True,
        "conversation": {"conversationId": conversation_id},
        "responseMessage": {
            "messageId": answer_message_id,
            "conversationId": conversation_id,
        },
    }
    yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"


def workbench_tenant_id(login_user) -> int:
    from bisheng.core.context.tenant import get_current_tenant_id

    return get_current_tenant_id() or getattr(login_user, "tenant_id", None) or 0
