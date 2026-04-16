from typing import Optional, List

from pydantic import Field

from bisheng.database.models.tag import Tag
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileBase


class KnowledgeFileResp(KnowledgeFileBase):
    id: Optional[int] = Field(default=None)
    title: Optional[str] = Field(default=None, description="Document Summary")
    tags: List[Tag] = Field(default_factory=list, description="File tags")
