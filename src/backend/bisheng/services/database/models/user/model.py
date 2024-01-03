from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, unique=True)
    username: str = Field(index=True, unique=True)
    password: str = Field()
    profile_image: Optional[str] = Field(default=None, nullable=True)
    is_active: bool = Field(default=False)
    create_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = Field(default=None, nullable=True)
    store_api_key: Optional[str] = Field(default=None, nullable=True)


class UserCreate(SQLModel):
    username: str = Field()
    password: str = Field()


class UserRead(SQLModel):
    id: UUID = Field(default_factory=uuid4)
    username: str = Field()
    profile_image: Optional[str] = Field()
    is_active: bool = Field()
    is_superuser: bool = Field()
    create_at: datetime = Field()
    updated_at: datetime = Field()
    last_login_at: Optional[datetime] = Field(nullable=True)


class UserUpdate(SQLModel):
    username: Optional[str] = None
    profile_image: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    last_login_at: Optional[datetime] = None
