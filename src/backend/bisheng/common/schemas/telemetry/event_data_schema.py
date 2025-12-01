from pydantic import BaseModel


class BaseEventData(BaseModel):
    """All event-specific data models should inherit from this base class for type constraints."""
    pass

class KnowledgeEventData(BaseEventData):
    knowledge_id: int
    knowledge_name: str
    action: str  # e.g., "create", "update", "delete"