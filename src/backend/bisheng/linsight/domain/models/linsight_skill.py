from datetime import datetime

from sqlalchemy import Integer, update
from sqlmodel import Column, DateTime, Field, String, Text, UniqueConstraint, col, or_, select, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.database.base import async_get_count

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
    display_name: str = Field(
        default="",
        description="Human-readable display name (Chinese OK); the only name surfaced in UI",
        sa_column=Column(String(255), nullable=False, server_default=text("''"), comment="Display name"),
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


class LinsightSkillDao:
    """Data access for tenant custom skills.

    tenant_id is injected automatically by the SQLAlchemy tenant filter
    (core/database/tenant_filter.py) — never hand-write tenant WHERE clauses here.
    """

    @classmethod
    async def create(cls, skill: LinsightSkill) -> LinsightSkill:
        async with get_async_db_session() as session:
            session.add(skill)
            await session.commit()
            await session.refresh(skill)
            return skill

    @classmethod
    async def update(cls, skill: LinsightSkill) -> LinsightSkill:
        async with get_async_db_session() as session:
            skill.update_time = datetime.now()
            session.add(skill)
            await session.commit()
            await session.refresh(skill)
            return skill

    @classmethod
    async def get_by_name(cls, name: str) -> LinsightSkill | None:
        async with get_async_db_session() as session:
            result = await session.exec(select(LinsightSkill).where(LinsightSkill.name == name))
            return result.first()

    @classmethod
    async def get_by_display_name(cls, display_name: str) -> LinsightSkill | None:
        async with get_async_db_session() as session:
            result = await session.exec(select(LinsightSkill).where(LinsightSkill.display_name == display_name))
            return result.first()

    @classmethod
    async def get_page(
        cls,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[list[LinsightSkill], int]:
        statement = select(LinsightSkill)
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                or_(
                    col(LinsightSkill.display_name).ilike(pattern),
                    col(LinsightSkill.description).ilike(pattern),
                )
            )
        if enabled is not None:
            statement = statement.where(LinsightSkill.enabled == enabled)
        async with get_async_db_session() as session:
            total = await async_get_count(session, statement)
            statement = (
                statement.order_by(col(LinsightSkill.update_time).desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            result = await session.exec(statement)
            return list(result.all()), total

    @classmethod
    async def list_enabled(cls) -> list[LinsightSkill]:
        async with get_async_db_session() as session:
            statement = select(LinsightSkill).where(LinsightSkill.enabled == True)  # noqa: E712
            statement = statement.order_by(col(LinsightSkill.create_time).desc())
            result = await session.exec(statement)
            return list(result.all())

    @classmethod
    async def set_enabled(cls, name: str, enabled: bool) -> bool:
        async with get_async_db_session() as session:
            statement = (
                update(LinsightSkill)
                .where(col(LinsightSkill.name) == name)
                .values(enabled=enabled, update_time=datetime.now())
            )
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def delete_by_name(cls, name: str) -> bool:
        async with get_async_db_session() as session:
            result = await session.exec(select(LinsightSkill).where(LinsightSkill.name == name))
            skill = result.first()
            if not skill:
                return False
            await session.delete(skill)
            await session.commit()
            return True
