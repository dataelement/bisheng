"""Validated wire input and authenticated actor for project operations."""

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
ChatId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,255}$")]
LegacyId = Annotated[str, StringConstraints(min_length=1, max_length=255)]


@dataclass(frozen=True, slots=True)
class ProjectActor:
    tenant_id: int
    user_id: int

    def __post_init__(self):
        if self.tenant_id <= 0 or self.user_id <= 0:
            raise ValueError("Project actor must be an authenticated natural person")


class ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateProject(ActionBase):
    """The client generates project_id, so retrying the same create is idempotent."""

    operation: Literal["create"]
    project_id: UUID
    name: ProjectName
    chat_id: ChatId | None = None


class RenameProject(ActionBase):
    operation: Literal["rename"]
    project_id: UUID
    name: ProjectName


class DeleteProject(ActionBase):
    operation: Literal["delete"]
    project_id: UUID


class AssignProject(ActionBase):
    operation: Literal["assign"]
    chat_id: ChatId
    project_id: UUID | None


class LegacyProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    legacy_id: LegacyId
    name: ProjectName
    created_at: str | None = Field(default=None, max_length=64)


class LegacyMembership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_id: ChatId
    legacy_project_id: LegacyId


class ImportProjects(ActionBase):
    """The whole legacy browser record in one request, processed in one transaction."""

    operation: Literal["import"]
    projects: list[LegacyProject] = Field(max_length=100)
    memberships: list[LegacyMembership] = Field(max_length=2000)


ProjectAction = Annotated[
    CreateProject | RenameProject | DeleteProject | AssignProject | ImportProjects,
    Field(discriminator="operation"),
]
PROJECT_ACTION_ADAPTER = TypeAdapter(ProjectAction)
