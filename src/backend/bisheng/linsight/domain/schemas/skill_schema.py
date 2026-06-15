"""API schemas for the Linsight skill module (F035 Track D, contract C3 + 2026-06-12 increment)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from bisheng.linsight.domain.models.linsight_skill import LinsightSkill


class SkillBrief(BaseModel):
    """Management list item. UI shows display_name/description/enabled only;
    name (skill ID) is detail-level, source is internal provenance."""

    id: int
    name: str
    display_name: str
    description: str
    enabled: bool
    source: str
    create_time: datetime | None = None
    update_time: datetime | None = None

    @classmethod
    def from_model(cls, skill: LinsightSkill) -> SkillBrief:
        return cls(
            id=skill.id,
            name=skill.name,
            display_name=skill.display_name or skill.name,
            description=skill.description,
            enabled=bool(skill.enabled),
            source=skill.source,
            create_time=skill.create_time,
            # never-edited skills report their creation time as the modified time
            update_time=skill.update_time or skill.create_time,
        )


class SkillSelectable(BaseModel):
    """End-user picker item (enabled tenant custom skills only)."""

    name: str
    display_name: str
    description: str


class SkillFileEntry(BaseModel):
    path: str
    size: int


class SkillDetail(SkillBrief):
    """Detail view: SKILL.md body preview/source + bundle file tree."""

    preview: str = ""
    source_text: str = ""
    files: list[SkillFileEntry] = Field(default_factory=list)


class SkillFileContent(BaseModel):
    """Read-only content of a bundle asset (GET /skill/{name}/file)."""

    path: str
    content: str


class SkillStatusUpdate(BaseModel):
    enabled: bool


class SkillCreateForm(BaseModel):
    """Form-create payload (the multipart upload path uses a file instead)."""

    display_name: str = Field(..., max_length=255, description="Human-readable name (Chinese OK)")
    name: str = Field(..., max_length=64, description="Skill ID: lowercase alnum + single hyphens")
    description: str = Field(..., max_length=1024)
    content: str = Field(..., description="SKILL.md markdown body (frontmatter is generated)")
