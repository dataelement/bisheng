from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from bisheng.common.constants.enums.knowledge_parse_priority import KnowledgeParsePriority


class KnowledgeParseStage(str, Enum):
    """Legacy queue-stage values kept only for rolling-message compatibility."""

    TITLE = "title"
    PARSE = "parse"
    RETRY = "retry"


class KnowledgeParseAttemptKind(str, Enum):
    INITIAL = "initial"
    RETRY = "retry"

    @classmethod
    def from_legacy_stage(cls, stage: KnowledgeParseStage | str) -> KnowledgeParseAttemptKind:
        parsed_stage = KnowledgeParseStage(stage)
        return cls.RETRY if parsed_stage is KnowledgeParseStage.RETRY else cls.INITIAL


class KnowledgeParseTicketState(str, Enum):
    PUBLISHING = "publishing"
    QUEUED = "queued"
    PROCESSING = "processing"


class KnowledgeParsePositionState(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NOT_QUEUED = "not_queued"
    UNAVAILABLE = "unavailable"


class KnowledgeParseQueueTicket(BaseModel):
    queue_ticket_id: str
    tenant_id: int
    knowledge_id: int
    file_id: int
    attempt_kind: KnowledgeParseAttemptKind
    priority: KnowledgeParsePriority
    sequence: int = 0
    state: KnowledgeParseTicketState = KnowledgeParseTicketState.PUBLISHING


class KnowledgeParseTicketSnapshot(KnowledgeParseQueueTicket):
    ahead_waiting_count: int | None = None
    active_attempt_count: int = 0


class KnowledgeParseQueuePositionItem(BaseModel):
    file_id: int
    state: KnowledgeParsePositionState
    stage: KnowledgeParseStage | None = Field(default=None, deprecated=True)
    ahead_waiting_count: int | None = Field(default=None, ge=0)


class KnowledgeParseQueuePositionsResponse(BaseModel):
    items: list[KnowledgeParseQueuePositionItem]
    active_count: int = Field(ge=0)
    waiting_count: int | None = Field(default=None, ge=0)
    approximate: bool = True
    as_of: datetime


def normalize_parse_queue_file_ids(knowledge_id: int, file_ids: list[int]) -> list[int]:
    normalized_ids = list(dict.fromkeys(file_ids))
    if (
        knowledge_id <= 0
        or not normalized_ids
        or len(normalized_ids) > 100
        or any(file_id <= 0 for file_id in normalized_ids)
    ):
        raise ValueError("file_ids must contain 1 to 100 positive integers")
    return normalized_ids
