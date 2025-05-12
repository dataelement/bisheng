from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import validator, field_validator
from sqlmodel import Field, SQLModel


class ApiKeyBase(SQLModel):
    name: Optional[str] = Field(index=True, nullable=True, default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = Field(default=None, nullable=True)
    total_uses: int = Field(default=0)
    is_active: bool = Field(default=True)


class ApiKey(ApiKeyBase, table=True):
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
    )

    api_key: str = Field(index=True, unique=True)
    # User relationship
    # Delete API keys when user is deleted
    user_id: int = Field(index=True)


class ApiKeyCreate(ApiKeyBase):
    api_key: Optional[str] = None
    user_id: Optional[int] = None


class UnmaskedApiKeyRead(ApiKeyBase):
    id: UUID
    api_key: str = Field()
    user_id: int = Field()


class ApiKeyRead(ApiKeyBase):
    id: UUID
    api_key: str = Field()
    user_id: UUID = Field()

    @field_validator('api_key', mode='before')
    @classmethod
    def mask_api_key(cls, v):
        # This validator will always run, and will mask the API key
        return f"{v[:8]}{'*' * (len(v) - 8)}"
