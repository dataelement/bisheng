"""Processing state only; callers first verify the real space and original action."""

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState


def require_space_processing_idle(space: Knowledge, *, operation: str) -> None:
    """Reject a conflicting sequential call while this space is rebuilding."""
    if space.state == KnowledgeState.REBUILDING.value or space.model_transition is not None:
        raise KnowledgeProcessingConflictError(reason=f"space_rebuilding:{operation}")


def require_space_deletion_allowed(space: Knowledge, *, operation: str) -> None:
    """Whole-space deletion supersedes rebuilding; transfer inputs stay protected."""
    if operation != "knowledge_space_delete":
        require_space_processing_idle(space, operation="delete")
    if (
        space.state == KnowledgeState.COPYING.value
        or space.copy_target_id is not None
        or (space.copy_source_id is not None and space.state != KnowledgeState.PUBLISHED.value)
    ):
        raise KnowledgeProcessingConflictError(reason="space_copying:delete")
