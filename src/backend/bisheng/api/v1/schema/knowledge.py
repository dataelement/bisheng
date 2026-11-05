from pydantic import Field

from bisheng.database.models.tag import Tag
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileRead


class KnowledgeFileResp(KnowledgeFileRead):
    id: int | None = Field(default=None)
    title: str | None = Field(default=None, description="Document Summary")
    tags: list[Tag] = Field(default_factory=list, description="File tags")
