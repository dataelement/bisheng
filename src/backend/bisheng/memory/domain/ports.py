"""Ports of the memory module and the per-turn memory context.

The memory service depends only on the three protocols below. Real
implementations (Milvus/ES index, MinIO detail store, platform LLM) are wired in
``memory/domain/services/factory.py``; tests use in-memory doubles. This breaks
the "service needs index, index needs service" cycle (design decision 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Scene names, used for source marks, metrics and enablement.
SCENE_DAILY = "daily"
SCENE_LINSIGHT = "linsight"
SCENE_ASSISTANT = "assistant"
SCENE_WORKFLOW = "workflow"
SCENE_MANUAL = "manual"
SCENES = (SCENE_DAILY, SCENE_LINSIGHT, SCENE_ASSISTANT, SCENE_WORKFLOW)


@dataclass
class MemoryContext:
    """Who the memory belongs to and where the current turn runs.

    Built only by ``MemoryGate.resolve`` (from the session registration row) or
    by the management API from the logged-in user. Every repository method that
    reads or writes memory data takes one (design decision 9).
    """

    tenant_id: int
    user_id: int
    timezone: str = "Asia/Shanghai"
    chat_id: str | None = None
    turn_id: str | None = None
    scene: str = SCENE_DAILY
    app_id: str | None = None
    app_name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def build_scope_filter(ctx: MemoryContext) -> dict[str, int]:
    """The only source of the index filter. Both retrieval paths must use it."""
    if ctx.tenant_id is None or ctx.user_id is None:
        raise ValueError("memory scope requires tenant_id and user_id")
    return {"tenant_id": int(ctx.tenant_id), "user_id": int(ctx.user_id)}


@dataclass
class IndexHit:
    item_id: str
    score: float


@runtime_checkable
class MemoryIndex(Protocol):
    """Derived, rebuildable search index of memory items (ES keyword + vector)."""

    async def upsert(self, ctx: MemoryContext, item_id: str, content: str) -> str | None:
        """Index one item. Returns the embedding model id used (None if keyword only)."""

    async def delete(self, ctx: MemoryContext, item_ids: list[str]) -> None: ...

    async def delete_user(self, ctx: MemoryContext) -> None: ...

    async def keyword_search(self, scope: dict[str, int], query: str, limit: int) -> list[IndexHit]: ...

    async def vector_search(self, ctx: MemoryContext, scope: dict[str, int], query: str, limit: int) -> list[IndexHit]:
        """Raises ``VectorUnconfigured`` when the tenant has no embedding model configured."""

    async def current_model_id(self, ctx: MemoryContext) -> str | None: ...


class VectorUnconfigured(Exception):
    """The tenant has no embedding model: keyword-only search is the normal state."""


@runtime_checkable
class DetailStore(Protocol):
    """Immutable detail objects, key ``memory/{tenant_id}/{user_id}/{item_id}.md``."""

    async def put(self, ctx: MemoryContext, item_id: str, text: str) -> str: ...

    async def get(self, key: str) -> str: ...

    async def delete(self, key: str) -> None: ...

    async def delete_user(self, ctx: MemoryContext) -> None: ...

    async def list_keys(self, ctx: MemoryContext) -> list[str]: ...


@runtime_checkable
class MemoryLLM(Protocol):
    """Model calls made on behalf of the memory owner (application type ``memory``)."""

    async def consolidate(self, ctx: MemoryContext, prompt: str) -> str: ...

    async def embed(self, ctx: MemoryContext, texts: list[str]) -> list[list[float]]: ...


def detail_object_key(tenant_id: int, user_id: int, item_id: str) -> str:
    return f"memory/{tenant_id}/{user_id}/{item_id}.md"
