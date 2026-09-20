import hashlib
import re
from dataclasses import dataclass
from time import time

from loguru import logger

from bisheng.knowledge.domain.repositories.interfaces.knowledge_chat_session_repository import (
    MAX_KNOWLEDGE_CHAT_REHOME_FLOWS,
    KnowledgeChatSessionRehomeResult,
    KnowledgeChatSessionRepository,
)

DEFAULT_FLOW_CHUNK_SIZE = MAX_KNOWLEDGE_CHAT_REHOME_FLOWS
DEFAULT_REHOME_COUNTDOWN_SECONDS = 5
_FLOW_PATTERN = re.compile(r"^space_(?P<space_id>[1-9]\d*)_(?P<kind>folder|file)_(?P<resource_id>\d+)$")


@dataclass(frozen=True)
class ValidatedKnowledgeChatRehome:
    source_space_id: int
    source_root_flow_id: str
    source_flow_ids: list[str]


class KnowledgeSpaceChatHistoryRetentionService:
    def __init__(self, repository: KnowledgeChatSessionRepository):
        self.repository = repository

    @staticmethod
    def validate_rehome_request(
        source_space_id: int,
        source_flow_ids: list[str],
    ) -> ValidatedKnowledgeChatRehome:
        if source_space_id <= 0:
            raise ValueError("source_space_id must be positive")
        if len(source_flow_ids) > DEFAULT_FLOW_CHUNK_SIZE:
            raise ValueError(f"source_flow_ids exceeds {DEFAULT_FLOW_CHUNK_SIZE}")

        unique_flows = sorted(set(source_flow_ids))
        for flow_id in unique_flows:
            matched = _FLOW_PATTERN.fullmatch(flow_id)
            if not matched:
                raise ValueError(f"invalid knowledge chat flow: {flow_id}")
            if int(matched.group("space_id")) != source_space_id:
                raise ValueError(f"flow does not belong to source space: {flow_id}")
            if int(matched.group("resource_id")) <= 0:
                raise ValueError(f"resource flow must not be the space root: {flow_id}")

        return ValidatedKnowledgeChatRehome(
            source_space_id=source_space_id,
            source_root_flow_id=f"space_{source_space_id}_folder_0",
            source_flow_ids=unique_flows,
        )

    async def rehome_by_flows(
        self,
        source_space_id: int,
        source_flow_ids: list[str],
    ) -> KnowledgeChatSessionRehomeResult:
        request = self.validate_rehome_request(source_space_id, source_flow_ids)
        if not request.source_flow_ids:
            return KnowledgeChatSessionRehomeResult(matched_count=0, updated_count=0)
        return await self.repository.rehome_by_flows(
            request.source_root_flow_id,
            request.source_flow_ids,
        )


def build_knowledge_chat_flows(
    source_space_id: int,
    resources: list[tuple[str, int]],
) -> list[str]:
    """Convert frozen resource identities into stable knowledge-chat flows."""
    flows: set[str] = set()
    for resource_type, resource_id in resources:
        if resource_id <= 0:
            raise ValueError("resource_id must be positive")
        if resource_type == "folder":
            flows.add(f"space_{source_space_id}_folder_{resource_id}")
        elif resource_type in {"file", "knowledge_file"}:
            flows.add(f"space_{source_space_id}_file_{resource_id}")
        else:
            raise ValueError(f"unsupported knowledge resource type: {resource_type}")
    return sorted(flows)


def dispatch_knowledge_chat_rehome(
    *,
    source_space_id: int,
    source_flow_ids: list[str],
    reason: str,
    countdown: int = DEFAULT_REHOME_COUNTDOWN_SECONDS,
) -> int:
    """Best-effort dispatch of exact flow chunks after a resource commit."""
    from bisheng.worker.knowledge.knowledge_chat_history_retention import (
        rehome_knowledge_chat_sessions,
    )

    unique_flows = sorted(set(source_flow_ids))
    dispatched = 0
    for start in range(0, len(unique_flows), DEFAULT_FLOW_CHUNK_SIZE):
        chunk = unique_flows[start : start + DEFAULT_FLOW_CHUNK_SIZE]
        try:
            validated = KnowledgeSpaceChatHistoryRetentionService.validate_rehome_request(
                source_space_id,
                chunk,
            )
            rehome_knowledge_chat_sessions.apply_async(
                kwargs={
                    "source_space_id": source_space_id,
                    "source_flow_ids": validated.source_flow_ids,
                    "reason": reason,
                    "dispatched_at_ms": int(time() * 1000),
                },
                countdown=countdown,
            )
            dispatched += 1
            chunk_hash = hashlib.sha256("\n".join(chunk).encode()).hexdigest()
            logger.info(
                "knowledge_chat_entry.task_dispatched source_space={} reason={} "
                "flow_count={} flow_hash={} countdown={}",
                source_space_id,
                reason,
                len(chunk),
                chunk_hash,
                countdown,
            )
        except Exception:
            # Entry recovery is explicitly best-effort; the resource commit is final.
            logger.exception(
                "knowledge_chat_entry.task_failed stage=dispatch source_space={} reason={} source_flows={}",
                source_space_id,
                reason,
                chunk,
            )
    return dispatched
