"""Frozen cross-module contracts for SPACE shared storage (M0, refactor spec).

These modules define the three stable boundaries agreed at interface freeze:

- :mod:`shared_space_storage` - ``SharedSpaceStorageWriter`` (F1 implements,
  F2 consumes)
- :mod:`retrieval_scope` - ``KnowledgeRetrievalScopeResolver`` (F3
  implements, B1-B6 consume)
- :mod:`projection_readiness` - ``ProjectionReadinessService`` (F2
  implements, B4/B6 consume)

Contract changes require a dedicated reviewed PR onto the integration branch
before module PRs follow (task-breakdown document, section 7).
"""
from bisheng.knowledge.domain.contracts.errors import (
    SharedStorageContractError,
    SharedStorageErrorCode,
)
from bisheng.knowledge.domain.contracts.identifiers import (
    CanonicalDocumentId,
    CanonicalVersionId,
    ContentFileId,
    EntryFileId,
    SpaceId,
    TenantId,
)
from bisheng.knowledge.domain.contracts.metadata_schema import (
    SHARED_SPACE_CONTENT_METADATA_SCHEMA,
    SHARED_SPACE_METADATA_FIELD_KNOWLEDGE_IDS,
)
from bisheng.knowledge.domain.contracts.projection_readiness import (
    ProjectionReadiness,
    ProjectionReadinessService,
)
from bisheng.knowledge.domain.contracts.retrieval_scope import (
    BackendQueryFilter,
    CanonicalChunkHit,
    CanonicalGenerationConstraint,
    EntryRef,
    KnowledgeRetrievalScopeResolver,
    MappedEntryHit,
    RetrievalScope,
)
from bisheng.knowledge.domain.contracts.shared_space_storage import (
    ContentDeleteRequest,
    ContentProjectionIdentity,
    ContentUpsertRequest,
    MembershipUpdateRequest,
    SharedContentChunk,
    SharedSpaceStorageWriter,
    validate_knowledge_ids,
)

__all__ = [
    "BackendQueryFilter",
    "CanonicalChunkHit",
    "CanonicalDocumentId",
    "CanonicalGenerationConstraint",
    "CanonicalVersionId",
    "ContentDeleteRequest",
    "ContentFileId",
    "ContentProjectionIdentity",
    "ContentUpsertRequest",
    "EntryFileId",
    "EntryRef",
    "KnowledgeRetrievalScopeResolver",
    "MappedEntryHit",
    "MembershipUpdateRequest",
    "ProjectionReadiness",
    "ProjectionReadinessService",
    "RetrievalScope",
    "SHARED_SPACE_CONTENT_METADATA_SCHEMA",
    "SHARED_SPACE_METADATA_FIELD_KNOWLEDGE_IDS",
    "SharedContentChunk",
    "SharedStorageContractError",
    "SharedSpaceStorageWriter",
    "SharedStorageErrorCode",
    "SpaceId",
    "TenantId",
    "validate_knowledge_ids",
]
