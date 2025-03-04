from typing import Optional

from bisheng.database.models.knowledge_file import KnowledgeFileBase
from pydantic import Field


class KnowledgeFileResp(KnowledgeFileBase):
    id: Optional[int] = Field(default=None)
    title: Optional[str] = Field(default=None, description="文件摘要")
