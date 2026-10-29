from datetime import datetime

from sqlalchemy import Integer, func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Column, DateTime, Field, String, Text, UniqueConstraint, col, or_, select, text

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.context.tenant import (
    DEFAULT_TENANT_ID,
    get_current_tenant_id,
    strict_tenant_filter,
)
from bisheng.core.database import get_async_db_session
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.database.base import async_get_count

# Skill source markers (C3/C7 contract).
SKILL_SOURCE_MANUAL = "manual"
SKILL_SOURCE_SOP_MIGRATED = "sop_migrated"
# Shipped with the kernel and seeded into every tenant at startup
# (services/builtin_skill_seeder.py). Editing one through the API flips it to
# ``manual``, which permanently opts that tenant's copy out of re-seeding.
SKILL_SOURCE_BUILTIN = "builtin"


class LinsightSkillBase(SQLModelSerializable):
    """Tenant-scoped custom skill metadata (F035).

    The skill body lives in object storage, keyed by ``object_path`` (which embeds
    ``content_hash``); this table only owns the metadata and the pointer. Nodes
    materialize the bundle into a local cache on demand, so every API replica and
    every Linsight worker resolves the same bytes regardless of which host wrote
    them. Kernel built-in skills
    are seeded into this same table (``source='builtin'``) so they share one
    runtime path with uploaded ones — the picker, the enable/disable toggle and
    ``materialize_session_skills`` need no special case for them.
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
    default_checked: bool = Field(
        default=False,
        description="Preselected in the end-user picker of every new conversation (user can still remove it)",
        sa_column=Column(
            "default_checked",
            Integer,
            nullable=False,
            server_default=text("0"),
            comment="Preselected in the end-user picker",
        ),
    )
    source: str = Field(
        default=SKILL_SOURCE_MANUAL,
        description="manual | sop_migrated | builtin",
        sa_column=Column(
            String(32), nullable=False, server_default=text(f"'{SKILL_SOURCE_MANUAL}'"), comment="Skill origin"
        ),
    )
    object_path: str = Field(
        ...,
        description="Object-storage key of the bundle archive",
        sa_column=Column(String(512), nullable=False, comment="Bundle object key"),
    )
    content_hash: str = Field(
        default="",
        description="sha256 of the bundle's file mapping; '' means not yet on object storage",
        sa_column=Column(String(64), nullable=False, server_default=text("''"), comment="Bundle content hash"),
    )
    size: int | None = Field(
        default=0,
        description="Total bundle size in bytes",
        sa_column=Column(Integer, nullable=False, server_default=text("0"), comment="File size in bytes"),
    )
    created_by: int | None = Field(
        default=None, description="Creator user id", sa_column=Column(Integer, nullable=True, comment="Creator user id")
    )
    # 0 is a tenant skill (built-in or admin upload). A non-zero value is the
    # user who owns a personal skill. NULL is not used: a unique index treats
    # NULLs as distinct, so it would not stop two tenant skills from sharing a name.
    owner_user_id: int = Field(
        default=0,
        description="0 for a tenant skill; otherwise the owning user id",
        sa_column=Column(
            Integer,
            nullable=False,
            server_default=text("0"),
            comment="0 for a tenant skill; otherwise the owning user id",
        ),
    )
    last_import_id: str | None = Field(
        default=None,
        description="Latest personal-skill import id; empty for tenant skills",
        sa_column=Column(String(64), nullable=True, comment="Latest personal-skill import id"),
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
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_user_id", "name", name="uq_linsight_skill_tenant_owner_name"),
        UniqueConstraint(
            "tenant_id",
            "owner_user_id",
            "last_import_id",
            name="uq_linsight_skill_tenant_owner_import",
        ),
    )

    id: int | None = Field(default=None, primary_key=True, description="Skill unique id")


class LinsightSkillDao:
    """Data access for tenant custom skills.

    Skills are **tenant-private** (F035): a tenant only ever sees and mutates
    its own rows; Root skills are never shared down to children. The global
    tenant filter (core/database/tenant_filter.py) defaults to the F012 IN-list
    ``WHERE tenant_id IN (leaf, ROOT)`` for child tenants, which would otherwise
    leak Root skills into a child's list. So every SELECT here runs inside
    ``strict_tenant_filter()`` to collapse that IN-list to ``tenant_id = current``.

    Bulk ``UPDATE`` statements (``set_enabled``) are *not* rewritten by the
    do_orm_execute listener — it only touches SELECTs — so they carry an
    explicit ``WHERE tenant_id = current AND owner_user_id = owner``. The
    default owner is 0, the tenant skill the management pages still edit.
    """

    @classmethod
    async def create(cls, skill: LinsightSkill) -> LinsightSkill:
        async with get_async_db_session() as session:
            # A never-edited skill still needs a modified time: the management
            # list sorts on it, and NULL sinks a freshly imported skill to the
            # last page (MySQL orders NULL last under DESC).
            if skill.update_time is None:
                skill.update_time = skill.create_time
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
    async def get_by_name(cls, name: str, *, owner_user_id: int = 0) -> LinsightSkill | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(LinsightSkill).where(
                        LinsightSkill.name == name,
                        LinsightSkill.owner_user_id == owner_user_id,
                    )
                )
                return result.first()

    @classmethod
    async def get_by_display_name(cls, display_name: str, *, owner_user_id: int = 0) -> LinsightSkill | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(LinsightSkill).where(
                        LinsightSkill.display_name == display_name,
                        LinsightSkill.owner_user_id == owner_user_id,
                    )
                )
                return result.first()

    @classmethod
    async def get_page(
        cls,
        keyword: str | None = None,
        enabled: bool | None = None,
        page: int = 1,
        page_size: int = 10,
        owner_user_id: int = 0,
    ) -> tuple[list[LinsightSkill], int]:
        statement = select(LinsightSkill).where(LinsightSkill.owner_user_id == owner_user_id)
        if owner_user_id == 0:
            statement = statement.where(LinsightSkill.source != "personal")
        if keyword:
            pattern = f"%{keyword}%"
            statement = statement.where(
                or_(
                    # `name` is searchable so the list can find what the
                    # duplicate check (name + display_name) already rejects;
                    # otherwise a Chinese display name makes its ASCII skill id
                    # unsearchable.
                    col(LinsightSkill.name).ilike(pattern),
                    col(LinsightSkill.display_name).ilike(pattern),
                    col(LinsightSkill.description).ilike(pattern),
                )
            )
        if enabled is not None:
            statement = statement.where(LinsightSkill.enabled == enabled)
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                total = await async_get_count(session, statement)
                # COALESCE keeps legacy rows with a NULL update_time in
                # creation order instead of sinking them; the id tiebreaker makes
                # OFFSET paging deterministic — skills seeded in one batch share
                # an update_time to the second, and without it the same row can
                # repeat on two pages while another is never listed at all.
                statement = (
                    statement.order_by(
                        func.coalesce(col(LinsightSkill.update_time), col(LinsightSkill.create_time)).desc(),
                        col(LinsightSkill.id).desc(),
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                result = await session.exec(statement)
                return list(result.all()), total

    @classmethod
    async def list_enabled(cls, *, owner_user_id: int = 0) -> list[LinsightSkill]:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(LinsightSkill).where(
                    LinsightSkill.enabled == True,  # noqa: E712
                    LinsightSkill.owner_user_id == owner_user_id,
                )
                statement = statement.order_by(col(LinsightSkill.create_time).desc())
                result = await session.exec(statement)
                return list(result.all())

    @classmethod
    async def set_enabled(cls, name: str, enabled: bool, *, owner_user_id: int = 0) -> bool:
        # Bulk UPDATE is not intercepted by the do_orm_execute tenant filter
        # (it only rewrites SELECTs), so scope the write to the current tenant
        # explicitly — otherwise toggling a name shared with Root (or any
        # same-named skill in another tenant) would flip every tenant's row.
        tid = get_current_tenant_id() or DEFAULT_TENANT_ID
        async with get_async_db_session() as session:
            statement = (
                update(LinsightSkill)
                .where(col(LinsightSkill.name) == name)
                .where(col(LinsightSkill.tenant_id) == tid)
                .where(col(LinsightSkill.owner_user_id) == owner_user_id)
                .values(enabled=enabled, update_time=datetime.now())
            )
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def set_default_checked(cls, name: str, default_checked: bool, *, owner_user_id: int = 0) -> bool:
        # Same explicit tenant scoping (and update_time bump) as set_enabled;
        # MySQL's ON UPDATE would bump update_time anyway.
        tid = get_current_tenant_id() or DEFAULT_TENANT_ID
        async with get_async_db_session() as session:
            statement = (
                update(LinsightSkill)
                .where(col(LinsightSkill.name) == name)
                .where(col(LinsightSkill.tenant_id) == tid)
                .where(col(LinsightSkill.owner_user_id) == owner_user_id)
                .values(default_checked=default_checked, update_time=datetime.now())
            )
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def delete_by_name(cls, name: str, *, owner_user_id: int = 0) -> bool:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(LinsightSkill).where(
                        LinsightSkill.name == name,
                        LinsightSkill.owner_user_id == owner_user_id,
                    )
                )
                skill = result.first()
                if not skill:
                    return False
                await session.delete(skill)
                await session.commit()
                return True

    @classmethod
    async def get_by_id(cls, skill_id: int) -> LinsightSkill | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(select(LinsightSkill).where(LinsightSkill.id == skill_id))
                return result.first()

    @classmethod
    async def get_by_last_import_id(cls, import_id: str, *, owner_user_id: int) -> LinsightSkill | None:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(LinsightSkill).where(
                        LinsightSkill.last_import_id == import_id,
                        LinsightSkill.owner_user_id == owner_user_id,
                    )
                )
                return result.first()

    @classmethod
    async def list_visible(cls, owner_user_id: int) -> list[LinsightSkill]:
        """Tenant skills plus this user's personal skills, in one query."""
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                statement = (
                    select(LinsightSkill)
                    .where(or_(LinsightSkill.owner_user_id == 0, LinsightSkill.owner_user_id == owner_user_id))
                    .order_by(col(LinsightSkill.id).asc())
                )
                result = await session.exec(statement)
                return list(result.all())

    @classmethod
    async def personal_usage(cls, owner_user_id: int) -> tuple[int, int]:
        """Count and total bytes of one user's personal skills in the current tenant."""
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                statement = select(
                    func.count(LinsightSkill.id),
                    func.coalesce(func.sum(LinsightSkill.size), 0),
                ).where(LinsightSkill.owner_user_id == owner_user_id)
                count, total = (await session.exec(statement)).one()
                return int(count), int(total)

    @classmethod
    async def create_personal(cls, skill: LinsightSkill, *, count_limit: int, bytes_limit: int) -> LinsightSkill:
        """Insert one personal skill only when the owner's quota still has room.

        The count, the byte total and the insert commit together. A quota miss
        rolls back and leaves every existing row as it was.
        """
        async with get_async_db_session() as session:
            with strict_tenant_filter():
                statement = select(
                    func.count(LinsightSkill.id),
                    func.coalesce(func.sum(LinsightSkill.size), 0),
                ).where(LinsightSkill.owner_user_id == skill.owner_user_id)
                count, total = (await session.exec(statement)).one()
            if int(count) >= count_limit:
                raise PersonalQuotaExceeded("count")
            if int(total) + int(skill.size or 0) > bytes_limit:
                raise PersonalQuotaExceeded("bytes")
            if skill.update_time is None:
                skill.update_time = skill.create_time
            session.add(skill)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                raise
            await session.refresh(skill)
            return skill

    @classmethod
    async def update_bundle(
        cls,
        skill_id: int,
        *,
        owner_user_id: int,
        expected_content_hash: str,
        content_hash: str,
        object_path: str,
        size: int,
        display_name: str,
        description: str,
        last_import_id: str | None,
    ) -> bool:
        """Replace the stored bundle only while the row still has the expected hash.

        The skill id and enabled flag are not in the SET clause, so a successful
        overwrite keeps both. A lost race updates nothing.
        """
        tid = get_current_tenant_id() or DEFAULT_TENANT_ID
        async with get_async_db_session() as session:
            statement = (
                update(LinsightSkill)
                .where(col(LinsightSkill.id) == skill_id)
                .where(col(LinsightSkill.tenant_id) == tid)
                .where(col(LinsightSkill.owner_user_id) == owner_user_id)
                .where(col(LinsightSkill.content_hash) == expected_content_hash)
                .values(
                    content_hash=content_hash,
                    object_path=object_path,
                    size=size,
                    display_name=display_name,
                    description=description,
                    last_import_id=last_import_id,
                    update_time=datetime.now(),
                )
            )
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def set_owner_enabled(cls, skill_id: int, *, owner_user_id: int, enabled: bool) -> bool:
        """Toggle one personal skill. Bulk UPDATE must name the tenant and the owner."""
        tid = get_current_tenant_id() or DEFAULT_TENANT_ID
        async with get_async_db_session() as session:
            statement = (
                update(LinsightSkill)
                .where(col(LinsightSkill.id) == skill_id)
                .where(col(LinsightSkill.tenant_id) == tid)
                .where(col(LinsightSkill.owner_user_id) == owner_user_id)
                .values(enabled=enabled, update_time=datetime.now())
            )
            result = await session.exec(statement)
            await session.commit()
            return result.rowcount > 0

    @classmethod
    async def delete_owned(cls, skill_id: int, *, owner_user_id: int) -> bool:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.exec(
                    select(LinsightSkill).where(
                        LinsightSkill.id == skill_id,
                        LinsightSkill.owner_user_id == owner_user_id,
                    )
                )
                skill = result.first()
                if skill is None:
                    return False
                await session.delete(skill)
                await session.commit()
                return True


class PersonalQuotaExceeded(Exception):
    """Raised inside the insert transaction. ``kind`` is ``count`` or ``bytes``."""

    def __init__(self, kind: str):
        self.kind = kind
        super().__init__(kind)
