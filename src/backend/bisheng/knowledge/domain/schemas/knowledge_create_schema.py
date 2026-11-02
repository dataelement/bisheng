"""Web-only knowledge creation preconditions; never a target-tenant selector."""

from pydantic import Field

from bisheng.knowledge.domain.models.knowledge import KnowledgeCreate


class KnowledgeWebCreate(KnowledgeCreate):
    expected_tenant_id: int | None = Field(default=None, gt=0)
