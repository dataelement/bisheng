"""统一 PDF Artifact Repository 契约与状态结果。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
)


@dataclass(frozen=True)
class PdfArtifactSourceSnapshot:
    tenant_id: int
    knowledge_file_id: int
    source_object_name: str
    source_md5: str | None


@dataclass(frozen=True)
class PdfArtifactGenerationRequest:
    artifact: KnowledgeFilePdfArtifact
    previous_object_name: str | None
    previous_origin: int | None


class PdfArtifactClaimState(str, Enum):
    CLAIMED = "claimed"
    ALREADY_COMPLETED = "already_completed"
    STALE = "stale"
    FAILED = "failed"


@dataclass(frozen=True)
class PdfArtifactClaimResult:
    state: PdfArtifactClaimState
    artifact: KnowledgeFilePdfArtifact | None


@dataclass(frozen=True)
class PdfArtifactCompleteResult:
    completed: bool
    artifact: KnowledgeFilePdfArtifact | None
    previous_object_name: str | None = None
    previous_origin: int | None = None


class KnowledgeFilePdfArtifactRepository(Protocol):
    async def request_generation(self, snapshot: PdfArtifactSourceSnapshot) -> PdfArtifactGenerationRequest: ...

    async def request_on_demand_generation(
        self,
        snapshot: PdfArtifactSourceSnapshot,
        *,
        invalid_generation: int | None = None,
    ) -> PdfArtifactGenerationRequest: ...

    async def find_available(
        self,
        tenant_id: int,
        knowledge_file_id: int,
    ) -> KnowledgeFilePdfArtifact | None: ...

    async def claim_generation(
        self,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        started_at,
    ) -> PdfArtifactClaimResult: ...

    async def complete_generation(
        self,
        *,
        tenant_id: int,
        knowledge_file_id: int,
        generation: int,
        origin: KnowledgeFilePdfArtifactOrigin,
        object_name: str,
        artifact_sha256: str,
        page_count: int,
        artifact_size: int,
        completed_at,
    ) -> PdfArtifactCompleteResult: ...
