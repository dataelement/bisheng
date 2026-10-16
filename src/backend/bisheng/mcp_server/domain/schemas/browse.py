from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ResourceId = Annotated[int, Field(strict=True, gt=0)]
PageSize = Annotated[int, Field(strict=True, ge=1, le=100)]
Cursor = Annotated[str, StringConstraints(max_length=8192)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Status = Annotated[int, Field(strict=True, ge=1, le=7)]
Statuses = Annotated[list[Status], Field(max_length=7)]
SpaceIds = Annotated[list[ResourceId], Field(min_length=1, max_length=20)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PageRequest(StrictRequest):
    cursor: Cursor | None = None
    page_size: PageSize = 20


class KnowledgeListRequest(PageRequest):
    name: Keyword | None = None
    writable_only: bool = Field(default=False, strict=True)


class FolderListRequest(PageRequest):
    knowledge_id: ResourceId
    folder_id: ResourceId | None = None


class FileListRequest(FolderListRequest):
    statuses: Statuses | None = None
    sort_by: Literal["file_name", "update_time"] = "update_time"
    order: Literal["asc", "desc"] = "desc"


class FolderScope(StrictRequest):
    knowledge_id: ResourceId
    folder_id: ResourceId


class FileSearchRequest(PageRequest):
    keyword: Keyword
    knowledge_ids: SpaceIds | None = None
    folder_scope: FolderScope | None = None
    search_mode: Literal["name", "content", "all"] = "all"

    @model_validator(mode="after")
    def validate_scope(self) -> "FileSearchRequest":
        if self.folder_scope and self.knowledge_ids and self.folder_scope.knowledge_id not in self.knowledge_ids:
            raise ValueError("folder must belong to requested knowledge scope")
        return self


class McpPage(StrictRequest):
    data: list[dict[str, Any]]
    page_size: int
    has_more: bool
    next_cursor: str | None = None
