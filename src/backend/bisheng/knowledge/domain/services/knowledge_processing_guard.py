"""Processing state only; callers first verify the real space and original action."""

from bisheng.common.errcode.knowledge import KnowledgeProcessingConflictError
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeState


def require_space_processing_idle(space: Knowledge, *, operation: str) -> None:
    """Reject a conflicting sequential call while this space is rebuilding."""
    if space.state == KnowledgeState.REBUILDING.value or space.model_transition is not None:
        raise KnowledgeProcessingConflictError(reason=f"space_rebuilding:{operation}")
