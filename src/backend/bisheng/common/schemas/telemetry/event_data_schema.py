from pydantic import BaseModel


class BaseEventData(BaseModel):
    """All event-specific data models should inherit from this base class for type constraints."""
    pass


class UserLoginEventData(BaseEventData):
    login_method: str
