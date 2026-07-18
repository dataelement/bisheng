from typing import List, Optional

from pydantic import BaseModel, Field


class KnowledgeSpaceTagLibraryCreateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description='标签库名称')
    description: Optional[str] = Field(default=None, max_length=1000, description='标签库说明')
    tags: List[str] = Field(default_factory=list, description='标签列表，最多 200 个')
    is_builtin: bool = Field(
        default=False,
        description='是否后台配置的内置库；普通用户不能删除',
    )


class KnowledgeSpaceTagLibraryUpdateReq(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200, description='标签库名称')
    description: Optional[str] = Field(default=None, max_length=1000, description='标签库说明')
    tags: Optional[List[str]] = Field(default=None, description='标签列表，最多 200 个')


class KnowledgeSpaceTagLibraryListItem(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    tag_count: int = 0
    is_builtin: bool = False


class KnowledgeSpaceTagLibraryDetail(KnowledgeSpaceTagLibraryListItem):
    tags: List[str] = Field(default_factory=list)
