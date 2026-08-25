"""Strongly typed identifiers for the shared-space storage contracts.

These NewTypes exist to prevent entry IDs and content IDs from being mixed up
(risk R2 in the refactor spec): an ``EntryFileId`` is a ``KnowledgeFile`` row
acting as a space entry, while a ``ContentFileId`` is the physical
``KnowledgeFile`` row carrying MinIO/parse payload. At runtime both are ints,
but static analysis and review can catch accidental cross-assignment.
"""
from __future__ import annotations

from typing import NewType

TenantId = NewType("TenantId", int)
SpaceId = NewType("SpaceId", int)

# KnowledgeFile row used as a space directory entry (manager/publish/share).
EntryFileId = NewType("EntryFileId", int)

# KnowledgeDocument / KnowledgeDocumentVersion primary keys.
CanonicalDocumentId = NewType("CanonicalDocumentId", int)
CanonicalVersionId = NewType("CanonicalVersionId", int)

# Physical KnowledgeFile row referenced by a KnowledgeDocumentVersion.
ContentFileId = NewType("ContentFileId", int)
