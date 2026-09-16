"""Categories ① and ② — knowledge retrieval and the knowledge-base list (`knowledge:read`).

Both go through the **unified retrieval facade**
(``knowledge/domain/services/retrieval_facade_service.py``, F052 Line A), which
is what makes "what this key sees through MCP" and "what the same key sees
through ``POST /api/v2/filelib/retrieve``" the same set by construction rather
than by two implementations agreeing. Nothing here filters, ranks or decides
visibility.

The facade is imported **lazily**, inside the handlers: the tool registry gates
these two entries on the module being importable, so on a tree where the facade
has not landed yet they simply do not appear in ``tools/list`` instead of
breaking the whole MCP face at import time.
"""

from __future__ import annotations

import importlib.util
from typing import Any

from pydantic import BaseModel, Field

FACADE_MODULE = "bisheng.knowledge.domain.services.retrieval_facade_service"
FACADE_SCHEMA_MODULE = "bisheng.knowledge.domain.schemas.retrieval_facade"

#: Mirrors the facade's own ceilings (design §4.2 ③). Declared here too so the
#: tool's ``inputSchema`` tells an agent the limit before it wastes a call.
TOP_K_MAX = 200
MAX_CONTENT_MAX = 60000
LIST_LIMIT_MAX = 200


def facade_available() -> bool:
    """Whether the retrieval facade has landed on this tree."""

    try:
        return (
            importlib.util.find_spec(FACADE_MODULE) is not None
            and importlib.util.find_spec(FACADE_SCHEMA_MODULE) is not None
        )
    except (ImportError, ValueError):  # a parent package that itself fails to import
        return False


class RetrievedChunk(BaseModel):
    knowledge_id: int
    knowledge_type: int | None = None
    knowledge_name: str | None = None
    document_id: int | None = None
    document_name: str | None = None
    chunk_index: int | None = None
    content: str = ""
    document_update_time: str | None = None


class KnowledgeSearchResult(BaseModel):
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    total: int = 0
    effective_scope: list[int] = Field(default_factory=list)
    truncated_params: dict[str, int] = Field(default_factory=dict)


class AccessibleKnowledgeItem(BaseModel):
    knowledge_id: int
    name: str
    #: ``library`` = document knowledge base, ``space`` = knowledge space. QA and
    #: personal bases are not retrievable through this face and never appear.
    type: str
    description: str | None = None


class KnowledgeListResult(BaseModel):
    items: list[AccessibleKnowledgeItem] = Field(default_factory=list)
    total: int = 0


async def bisheng_knowledge_search(
    query: str,
    knowledge_ids: list[int] | None = None,
    top_k: int = 10,
    max_content: int = 15000,
    tags: dict[int, list[str]] | None = None,
) -> KnowledgeSearchResult:
    """Search the knowledge bases this key was granted. Omit `knowledge_ids` to search all of them."""

    from bisheng.knowledge.domain.schemas.retrieval_facade import (
        RetrievalIdentity,
        RetrievalRequest,
    )
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
    from bisheng.open_api.domain.context import get_current_open_api_principal

    identity = RetrievalIdentity.from_open_api_principal(get_current_open_api_principal())
    result = await RetrievalFacadeService.retrieve(
        identity,
        RetrievalRequest(
            query=query,
            knowledge_ids=list(knowledge_ids) if knowledge_ids else None,
            # No whitelist on this face: a developer key's range is what an
            # administrator granted it, not what an application declared.
            whitelist=None,
            top_k=min(int(top_k or 10), TOP_K_MAX),
            max_content=min(int(max_content or 15000), MAX_CONTENT_MAX),
            tag_filters=tags,
        ),
    )
    return KnowledgeSearchResult(
        chunks=[RetrievedChunk(**_chunk_payload(chunk)) for chunk in result.chunks],
        total=int(result.total),
        effective_scope=list(result.effective_scope),
        truncated_params=dict(result.truncated_params or {}),
    )


async def bisheng_knowledge_list(name: str | None = None, limit: int = 200) -> KnowledgeListResult:
    """List the knowledge bases this key can actually search — use these ids with the search tool."""

    from bisheng.knowledge.domain.schemas.retrieval_facade import RetrievalIdentity
    from bisheng.knowledge.domain.services.retrieval_facade_service import RetrievalFacadeService
    from bisheng.open_api.domain.context import get_current_open_api_principal

    identity = RetrievalIdentity.from_open_api_principal(get_current_open_api_principal())
    items = await RetrievalFacadeService.list_accessible_knowledge(
        identity,
        name=name,
        limit=min(int(limit or LIST_LIMIT_MAX), LIST_LIMIT_MAX),
    )
    payload = [AccessibleKnowledgeItem(**_knowledge_payload(item)) for item in items]
    return KnowledgeListResult(items=payload, total=len(payload))


def _chunk_payload(chunk: Any) -> dict[str, Any]:
    update_time = getattr(chunk, "document_update_time", None)
    return {
        "knowledge_id": int(getattr(chunk, "knowledge_id", 0) or 0),
        "knowledge_type": getattr(chunk, "knowledge_type", None),
        "knowledge_name": getattr(chunk, "knowledge_name", None),
        "document_id": getattr(chunk, "document_id", None),
        "document_name": getattr(chunk, "document_name", None),
        "chunk_index": getattr(chunk, "chunk_index", None),
        "content": getattr(chunk, "content", "") or "",
        "document_update_time": str(update_time) if update_time is not None else None,
    }


def _knowledge_payload(item: Any) -> dict[str, Any]:
    raw_type = getattr(item, "type", None)
    return {
        "knowledge_id": int(getattr(item, "knowledge_id", 0) or 0),
        "name": getattr(item, "name", "") or "",
        "type": raw_type if isinstance(raw_type, str) else _type_label(raw_type),
        "description": getattr(item, "description", None),
    }


def _type_label(raw_type: Any) -> str:
    """The facade may hand back the numeric ``Knowledge.type``; agents read words."""

    return "space" if int(raw_type or 0) == 3 else "library"


__all__ = [
    "FACADE_MODULE",
    "LIST_LIMIT_MAX",
    "MAX_CONTENT_MAX",
    "TOP_K_MAX",
    "bisheng_knowledge_list",
    "bisheng_knowledge_search",
    "facade_available",
]
