"""Execution values shared by the E+ transport and assistant adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bisheng.assistant.domain.schemas.execution import AssistantMessageContent, AssistantRobotScope
from bisheng.eplus.domain.services.conversation_scheduler import EPlusHistoryTurn
from bisheng.eplus.domain.services.message_service import EPlusAdmissionContext
from bisheng.eplus.domain.services.reply_stream import EPlusFrameSender


@dataclass(frozen=True, slots=True)
class EPlusBotRuntimeContext:
    """Per-connection values needed after a callback has been admitted."""

    admission: EPlusAdmissionContext
    sender: EPlusFrameSender


@dataclass(frozen=True, slots=True)
class EPlusAssistantHistoryItem:
    content: AssistantMessageContent
    answer: str


@dataclass(frozen=True, slots=True)
class EPlusAssistantRequest:
    assistant_id: str
    conversation_id: str
    user_id: int
    external_user_id: str
    content: AssistantMessageContent
    history: tuple[EPlusAssistantHistoryItem, ...]
    robot_scope: AssistantRobotScope


@dataclass(frozen=True, slots=True)
class EPlusTurnDelivery:
    tenant_id: int
    assistant_id: str
    conversation_id: str
    turn_id: str
    inbound_message_id: int
    req_id: str
    stream_id: str
    sender_user_id: int
    sender_external_id: str
    content_manifest: tuple[dict[str, Any], ...]
    scope_version: int
    space_ids: tuple[int, ...]
    history: tuple[EPlusHistoryTurn, ...]
