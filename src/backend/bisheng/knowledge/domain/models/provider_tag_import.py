"""Immutable per-target template snapshot and recoverable publication receipt."""

from uuid import uuid4

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import JsonType
from bisheng.knowledge.domain.models.provider_control import OpaqueId, _generation_fk


class ProviderTagImport(SQLModelSerializable, table=True):
    __tablename__ = "knowledge_provider_tag_import"
    __table_args__ = (
        _generation_fk("generation", "fk_kpti_gen"),
        UniqueConstraint("tenant_id", "space_id", "generation", "request_key", name="uk_kpti_request"),
    )
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True, max_length=36)
    tenant_id: int
    space_id: int
    generation: int
    request_key: str = Field(sa_column=Column(OpaqueId(), nullable=False))
    actor_id: int
    library_id: int
    words: list[str] = Field(sa_column=Column(JsonType, nullable=False))
    published_revision: int | None = None
