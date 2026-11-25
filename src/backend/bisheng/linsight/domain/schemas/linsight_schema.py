from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from bisheng_langchain.linsight.event import NeedUserInput

# ``{space_id: tag_ref_id}`` — fixed per-space tag references. Positive int keys,
# strict positive int values: a bool/float/tag-name ref is a client bug, and
# silently coercing it would turn a pinned scope into a different scope.
SpaceTagRefs = dict[Annotated[int, Field(gt=0)], Annotated[int, Field(strict=True, gt=0)]]


class ToolChildrenSchema(BaseModel):
    id: int = Field(..., description="Toolsid")
    name: str | None = Field(None, description="Tool name")
    tool_key: str | None = Field(None, description="Toolskey")
    desc: str | None = Field(None, description="Tools Description")


# Opt-IntoolSchema
class LinsightToolSchema(BaseModel):
    id: int = Field(..., description="Tool LevelID")
    name: str | None = Field(None, description="Tool name")
    is_preset: int = Field(1, description="Whether or not it is a preset tool")
    desc: str | None = Field(None, description="Tools Description")
    # childTools List
    children: list[ToolChildrenSchema] | None = Field(..., description="Subtools List")


class SubmitFileSchema(BaseModel):
    file_id: str = Field(..., description="File UniqueID")
    file_name: str = Field(..., description="File Name")
    parsing_status: str = Field(..., description="File parsing status")
    # F035 unified-resource: when set, the file came from the DAILY upload bucket
    # (workstation), not the linsight pipeline. Carries the raw MinIO path;
    # linsight parses it on-the-fly via TempFilePipeline at ingestion instead of
    # resolving a linsight Redis temp_info / pre-parsed markdown.
    file_url: str | None = Field(None, description="Daily-bucket raw file path (workstation upload)")
    # Folder upload: this file's path relative to the folder the user dropped,
    # e.g. ``年报/2024/Q1.xlsx``. None/empty means a plain single-file upload and
    # keeps the historical flat ``uploads/<name>`` layout. The workspace rebuilds
    # the directory tree from this value, so it is sanitized segment-wise
    # (``_safe_relpath``) before it ever reaches an object key.
    relative_path: str | None = Field(None, description="Path relative to the uploaded folder root")
    # Client-reported size, used ONLY for the batch-level folder-upload gate
    # (all-or-nothing UX, mirroring knowledge-space ``FolderUploadItem.size``).
    # The authoritative per-file size check runs at the upload endpoint.
    size: int = Field(0, ge=0, description="File size in bytes (client-reported, batch gate only)")


# Submit a problemSchema
class LinsightQuestionSubmitSchema(BaseModel):
    question: str = Field(..., description="User Submitted Questions")
    org_knowledge_enabled: bool = Field(False, description="Whether to enable organization knowledge base")
    personal_knowledge_enabled: bool = Field(False, description="Whether or not to enable Personal Knowledge Base")
    # Exact KB selection carried from the daily picker. These are the SPECIFIC ids
    # the user chose, so the task agent searches exactly those — not every KB of a
    # coarse type. organization = NORMAL-type KB ids; knowledge_space = SPACE-type
    # ids. The coarse booleans above are kept for storage/back-compat but no longer
    # drive knowledge injection.
    organization_knowledge_ids: list[int] | None = Field(None, description="Selected organization knowledge base ids")
    knowledge_space_ids: list[int] | None = Field(None, description="Selected knowledge space ids")
    # F026 T042: the per-space FIXED tag reference the user pinned in the picker
    # (``space_id -> tag_ref_id``), carried with the space selection into the task
    # version. Three states, and they must never collapse into each other:
    #
    # * ``None``     — no record: a task version / client that predates this field.
    #   The task keeps its historical no-tag behaviour, but nothing may *reuse*
    #   this as an agreed range (a regenerate has to ask for a new one).
    # * ``{}``       — the user explicitly pinned no tag: the selected spaces are
    #   searched without a tag condition.
    # * non-empty    — the fixed references; retrieval must honour them exactly
    #   and may only narrow further (file permissions, current versions).
    #
    # Note this is deliberately NOT the daily request's plain ``dict`` default:
    # "the request never said" and "the user chose none" are different facts.
    knowledge_space_tag_filters: SpaceTagRefs | None = Field(
        None,
        description="Fixed per-space tag reference ids (space id -> tag ref id); None means 'never recorded'",
    )
    files: list[SubmitFileSchema] | None = Field(None, description="Uploaded files list:")
    tools: list[LinsightToolSchema] | None = Field(None, description="List of available tools")
    # F035: per-task selected execution model id; None falls back to the tenant
    # ``linsight_default_model_id`` at resolve time (agent_factory._resolve_model).
    model: str | None = Field(None, description="Per-task selected execution model id")
    # F035 Track D: skill names the user picked for this run. The worker copies the
    # matched (governance-enabled ∩ selected) bundles into the session workspace at
    # startup (skill_provisioning.materialize_session_skills) — the copy IS the
    # whitelist gate, so unselected skills never reach the agent. Both [] and a
    # missing/None field mean "no skills this run"; skills are opt-in via an
    # explicit non-empty list.
    skills: list[str] | None = Field(None, description="Selected skill names for this run")
    # Ids of the skills the user checked. Provisioning replaces each id with the
    # directory that was actually copied (a same-named personal skill wins) and
    # stores those directory names in the session ``skills`` column. Absent on
    # older clients, which keep sending names only.
    skill_ids: list[int] | None = Field(None, description="Selected skill ids for this run")
    # F035: continue an existing session (a follow-up round in the same 会话).
    # None creates a brand-new session.
    session_id: str | None = Field(None, description="Existing session id to continue; None creates a new session")

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, v: list[LinsightToolSchema]) -> list[dict]:
        if not v:
            return []
        # Convert tool to dictionary format
        return [tool.model_dump() for tool in v]

    @field_validator("knowledge_space_tag_filters", mode="before")
    @classmethod
    def validate_space_tag_refs(cls, value: Any):
        if value is None:
            # No record. Kept as None so ``scope_state`` can tell it apart from {}.
            return None
        if not isinstance(value, dict):
            raise ValueError("Knowledge space tag references must be a mapping of space id to tag reference id")
        if any(
            isinstance(key, bool) or not (isinstance(key, int) or (isinstance(key, str) and key.isdecimal()))
            for key in value
        ):
            raise ValueError("Knowledge space ids must be positive integers")
        return value

    @model_validator(mode="after")
    def validate_selected_space_tag_filters(self):
        if self.knowledge_space_tag_filters is not None and not set(self.knowledge_space_tag_filters).issubset(
            self.knowledge_space_ids or []
        ):
            raise ValueError("Tag filters must belong to selected knowledge spaces")
        return self

    @property
    def tag_scope_recorded(self) -> bool:
        """Whether this task version carries a recorded tag scope at all."""
        return self.knowledge_space_tag_filters is not None

    @property
    def scope_state(self) -> str:
        """``unrecorded`` | ``unspecified`` (no fixed tag) | ``fixed``."""
        if self.knowledge_space_tag_filters is None:
            return "unrecorded"
        return "fixed" if self.knowledge_space_tag_filters else "unspecified"

    @property
    def fixed_tag_refs(self) -> dict[int, int]:
        """Normalised references for retrieval; empty means "no tag condition"."""
        return dict(self.knowledge_space_tag_filters or {})

    def tag_ref_for(self, space_id: int) -> int | None:
        """The fixed tag reference pinned for one space, or None."""
        return (self.knowledge_space_tag_filters or {}).get(int(space_id))


class DownloadFilesSchema(BaseModel):
    file_name: str = Field(..., description="File Name")
    file_url: str = Field(..., description="File download link")


class UserInputEventSchema(NeedUserInput):
    files: list[dict[str, str]] | None = Field(None, description="Uploaded files list:")
    user_input: str | None = Field(None, description="User input")
    is_completed: bool = Field(False, description="Is it completed")
