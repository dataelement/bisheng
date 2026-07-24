"""Schemas for Link B tag resolution (formal library exact / pending similar)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TagMatchKind = Literal["exact", "substring", "similarity", "new"]
TagResolveTarget = Literal["approved", "pending"]


@dataclass(frozen=True)
class TagNameCatalogEntry:
    canonical_name: str
    normalized_key: str
    resource_type: str | None = None


@dataclass(frozen=True)
class LinkBTagResolverCatalogSnapshot:
    library_by_key: dict[str, str]
    pending_catalog: list[object]
    cache_source: Literal["process", "redis", "db"] = "db"

    @property
    def library_names(self) -> list[str]:
        return list(self.library_by_key.values())


@dataclass(frozen=True)
class CachedPendingReviewTagRow:
    id: int | None
    name: str
    resource_type: str | None
    business_type: str
    business_id: str | None
    tenant_id: int | None
    review_status: int
    is_deleted: bool


@dataclass(frozen=True)
class PendingReviewTagMatch:
    review_tag: object
    original: str
    canonical_name: str
    match_kind: Literal["exact", "substring", "similarity"]
    score: float | None = None


@dataclass(frozen=True)
class ResolvedTagCandidate:
    original: str
    canonical_name: str
    target: TagResolveTarget
    match_kind: TagMatchKind
    score: float | None = None


@dataclass
class TagResolutionBatch:
    entries: list[ResolvedTagCandidate] = field(default_factory=list)

    @property
    def approved_names(self) -> list[str]:
        return [entry.canonical_name for entry in self.entries if entry.target == "approved"]

    @property
    def pending_names(self) -> list[str]:
        return [entry.canonical_name for entry in self.entries if entry.target == "pending"]
