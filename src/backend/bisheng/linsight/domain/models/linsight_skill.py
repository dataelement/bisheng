from datetime import datetime

from sqlalchemy import Integer
from sqlmodel import Column, DateTime, Field, String, Text, UniqueConstraint, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT

# Skill source markers (C3/C7 contract).
SKILL_SOURCE_MANUAL = "manual"
SKILL_SOURCE_SOP_MIGRATED = "sop_migrated"


class LinsightSkillBase(SQLModelSerializable):
    """Tenant-scoped custom skill metadata (F035).

    The skill body lives on disk under ``SKILLS_ROOT/data/skills/{tenant_id}/<name>/SKILL.md``
    (see design §7.1); this table only owns the metadata. Built-in skills are
    never persisted here and never exposed through the ``/skill`` API.
    """

    tenant_id: int = Field(
        default=1,
        sa_column=Column(Integer, nullable=False, server_default=text("1"), index=True, comment="Tenant ID"),
    )
    name: str = Field(
        ...,
        description="Skill name (frontmatter name, [a-z0-9-], <=64)",
        sa_column=Column(String(64), nullable=False, comment="Skill name"),
    )
    description: str = Field(
        ...,
        description="Skill description (<=1024)",
        sa_column=Column(Text, nullable=False, comment="Skill description"),
    )
    enabled: bool = Field(
        default=True,
        description="Whether the skill is enabled",
        sa_column=Column("enabled", Integer, nullable=False, server_default=text("1"), comment="Enabled flag"),
    )
    source: str = Field(
        default=SKILL_SOURCE_MANUAL,
        description="manual | sop_migrated",
        sa_column=Column(
            String(32), nullable=False, server_default=text(f"'{SKILL_SOURCE_MANUAL}'"), comment="Skill origin"
        ),
    )
    object_path: str = Field(
        ...,
        description="Relative disk path under SKILLS_ROOT",
        sa_column=Column(String(512), nullable=False, comment="SKILL.md relative path"),
    )
    size: int | None = Field(
        default=0,
        description="SKILL.md file size in bytes",
        sa_column=Column(Integer, nullable=False, server_default=text("0"), comment="File size in bytes"),
    )
    created_by: int | None = Field(
        default=None, description="Creator user id", sa_column=Column(Integer, nullable=True, comment="Creator user id")
    )
    create_time: datetime = Field(
        default_factory=datetime.now,
        description="Creation time",
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None, sa_column=Column(DateTime, nullable=True, server_default=UPDATE_TIME_SERVER_DEFAULT)
    )


class LinsightSkill(LinsightSkillBase, table=True):
    """Inspiration (Linsight) tenant custom skill."""

    __tablename__ = "linsight_skill"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_linsight_skill_tenant_name"),)

    id: int | None = Field(default=None, primary_key=True, description="Skill unique id")
