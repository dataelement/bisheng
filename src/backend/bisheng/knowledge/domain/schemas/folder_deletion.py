from typing import Annotated

from pydantic import BaseModel, Field, model_validator

from bisheng.common.schemas.api import PageInfiniteCursorData

ResourceId = Annotated[int, Field(gt=0, le=2**63 - 1)]


class FolderDeletionOperation(BaseModel):
    folder_id: ResourceId
    operation_id: str = Field(min_length=1, max_length=64)


class FolderDeletionQuery(BaseModel):
    folder_ids: list[ResourceId] = Field(max_length=100)
    known_operations: list[FolderDeletionOperation] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_known_folders(self):
        known = {item.folder_id for item in self.known_operations}
        if not known.issubset(self.folder_ids) or len(known) != len(self.known_operations):
            raise ValueError("Each known operation must identify one requested folder")
        return self


class FolderReconcileRequest(BaseModel):
    folder_id: ResourceId


class FolderDeletionPage(PageInfiniteCursorData):
    scope_deletion_status: dict | None = None
