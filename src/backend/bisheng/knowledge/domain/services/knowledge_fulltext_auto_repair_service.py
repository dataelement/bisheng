"""全文 Chunk 源数据自动修复策略。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import (
    KnowledgeFulltextAutoRepairSource,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_rebuild_service import (
    KnowledgeFulltextChunkCorruptedError,
    KnowledgeFulltextChunkNotReadyError,
)


class KnowledgeFulltextAutoRepairDecision(str, Enum):
    IGNORE = "ignore"
    RETRY_ONLY = "retry_only"
    REQUEST = "request"


class KnowledgeFulltextAutoRepairService:
    """只对白名单 Chunk 源错误作出确定性修复决策。"""

    @staticmethod
    def decide(exception: Exception, *, retry_count: int) -> KnowledgeFulltextAutoRepairDecision:
        return KnowledgeFulltextAutoRepairService.decide_error_type(
            type(exception).__name__,
            retry_count=retry_count,
        )

    @staticmethod
    def decide_error_type(error_type: str, *, retry_count: int) -> KnowledgeFulltextAutoRepairDecision:
        if error_type == KnowledgeFulltextChunkCorruptedError.__name__:
            return KnowledgeFulltextAutoRepairDecision.REQUEST
        if error_type == KnowledgeFulltextChunkNotReadyError.__name__:
            if retry_count + 1 >= constants.KNOWLEDGE_FULLTEXT_AUTO_REPAIR_NOT_READY_FAILURES:
                return KnowledgeFulltextAutoRepairDecision.REQUEST
            return KnowledgeFulltextAutoRepairDecision.RETRY_ONLY
        return KnowledgeFulltextAutoRepairDecision.IGNORE

    @staticmethod
    def fingerprint(source: KnowledgeFulltextAutoRepairSource) -> str:
        canonical = json.dumps(
            {
                "file_id": source.file_id,
                "knowledge_id": source.knowledge_id,
                "source": source.md5 or source.object_name or "",
                "split_rule": source.split_rule or "",
                "desired_content_generation": source.desired_content_generation,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def new_payload(*, fingerprint: str, error_type: str, now: datetime) -> dict:
        return {
            "fingerprint": fingerprint,
            "state": "requested",
            "attempt_count": constants.KNOWLEDGE_FULLTEXT_AUTO_REPAIR_MAX_ATTEMPTS,
            "error_type": error_type,
            "requested_at": now.isoformat(),
            "started_at": None,
            "finished_at": None,
        }
