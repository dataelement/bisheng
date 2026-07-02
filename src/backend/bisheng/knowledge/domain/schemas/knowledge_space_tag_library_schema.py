from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeSpaceTagLibraryCreateReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, description="标签库名称")
    description: str | None = Field(default=None, max_length=1000, description="标签库说明")
    tags: list[str] = Field(default_factory=list, description="标签列表，最多 200 个")
    is_builtin: bool = Field(
        default=False,
        description="是否后台配置的内置库；普通用户不能删除",
    )


class KnowledgeSpaceTagLibraryUpdateReq(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=20, description="标签库名称")
    description: str | None = Field(default=None, max_length=1000, description="标签库说明")
    tags: list[str] | None = Field(default=None, description="人工标签列表，最多 200 个")
    ai_tags: list[str] | None = Field(default=None, description="AI 标签列表")


class KnowledgeSpaceTagLibraryTagItem(BaseModel):
    name: str
    resource_type: str = Field(description="manual_tag | ai_auto_tag | system_tag")
    resource_count: int = Field(default=0, description="Number of knowledge files using this tag")
    create_time: datetime | None = Field(default=None, description="Tag creation time in library")
    creator_name: str | None = Field(default=None, description="Creator display name")


class KnowledgeSpaceTagLibraryListItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    tag_count: int = 0
    bound_space_count: int = Field(default=0, description="Number of bound knowledge spaces")
    bound_space_names: list[str] = Field(default_factory=list, description="Names of bound knowledge spaces")
    used_knowledge_count: int = Field(default=0, description="Distinct knowledge files using library tags")
    is_builtin: bool = False


class KnowledgeSpaceTagLibraryDetail(KnowledgeSpaceTagLibraryListItem):
    tags: list[str] = Field(default_factory=list)
    tag_items: list[KnowledgeSpaceTagLibraryTagItem] = Field(default_factory=list)
