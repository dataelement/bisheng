"""Application boundary for the original knowledge deletion projection proof."""

from bisheng.permission.domain.repositories.knowledge_delete_projection_repository import (
    DeleteProjectionExpectation,
    KnowledgeDeleteProjectionRepository,
    delete_key,
)

__all__ = ["DeleteProjectionExpectation", "KnowledgeDeleteProjectionRepository", "delete_key"]
