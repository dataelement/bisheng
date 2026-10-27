"""``resource_tier`` — the platform's resource tiers for hosted apps (F055 design D11).

Facts that are easy to get wrong:

* **This file lives in ``database/models/`` on purpose, not in
  ``app_publish/domain/models/``.** The entity is owned by F055 (seed, tier
  resolution, disable semantics) but **read** by F054 — ``app_version.tier_id``
  is a frozen reference and the runtime layer resolves the spec from it. Put
  the model inside ``app_publish`` and ``app_runtime`` has to import
  ``app_publish``: the dependency becomes bidirectional, and **no arch-guard
  rule would catch it** (RULE-5 only looks at the API layer). The business
  logic still lives in ``app_publish``'s ``ResourceTierService`` — this module
  is the table and nothing else.
* **There is no ``tenant_id`` column.** Tiers are platform-level and shared
  across tenants (AC-44). Registering the module in
  ``_TENANT_AWARE_MODEL_MODULES`` only guarantees the metadata is imported;
  ``_discover_tenant_aware_tables`` skips tables without the column, so rows
  here are never auto-filtered — which is the intent, not an oversight.
* **CPU is stored as integer millicores and memory as integer MB.** Not float
  vCPU: floats round-trip through DM8 and JSON into values like
  ``0.30000000000000004``, which then show up in a super admin's edit form.
* **The DAO offers no delete.** ``app_version.tier_id`` is a historical
  snapshot reference; deleting a tier would leave an old version unable to
  resolve its spec when it is re-enabled (AC-47). Retirement is
  ``enabled=False``, which blocks *new* selections only — running apps keep
  running and their specs keep resolving. F054 may rely on "``tier_id`` always
  resolves" as an invariant precisely because of this.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, text, update
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT

# Tier codes shipped out of the box (AC-44). The specs themselves are **not**
# here — they come from ``app_runtime/domain/constants.py DEFAULT_TIERS``
# (overridable by ``settings.app_runtime.default_tiers``), so an un-seeded
# deployment and a freshly seeded one resolve identical limits.
TIER_CODE_LIGHT = "light"
TIER_CODE_STANDARD = "standard"
TIER_CODE_PERFORMANCE = "performance"

#: The tier a manifest gets when it declares none (AC-46).
DEFAULT_TIER_CODE = TIER_CODE_LIGHT


class ResourceTier(SQLModelSerializable, table=True):
    """One selectable resource tier. Platform-level; retired by ``enabled``, never deleted."""

    __tablename__ = "resource_tier"
    __table_args__ = (UniqueConstraint("code", name="uk_resource_tier_code"),)

    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(
        sa_column=Column(String(32), nullable=False, comment="light | standard | performance; the manifest value"),
    )
    name: str = Field(sa_column=Column(String(64), nullable=False, comment="Display name"))
    cpu_millicores: int = Field(
        sa_column=Column(Integer, nullable=False, comment="CPU limit in millicores — integer, never float vCPU"),
    )
    memory_mb: int = Field(sa_column=Column(Integer, nullable=False, comment="Memory limit in MB"))
    description: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    enabled: bool = Field(
        default=True,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("1"),
            comment="False blocks NEW selections only; running apps keep resolving their spec",
        ),
    )
    sort_order: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0"), comment="Display order, ascending"),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class ResourceTierDao:
    """Single-row ORM access. **Deliberately no delete** — see the module docstring."""

    @classmethod
    async def alist(cls, session: AsyncSession, *, enabled_only: bool = False) -> list[ResourceTier]:
        """All tiers in display order. ``enabled_only`` is the selection list; the full list is the admin view."""
        statement = select(ResourceTier)
        if enabled_only:
            statement = statement.where(col(ResourceTier.enabled).is_(True))
        statement = statement.order_by(col(ResourceTier.sort_order).asc(), col(ResourceTier.id).asc())
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def aget_by_code(cls, session: AsyncSession, code: str) -> ResourceTier | None:
        """Resolve a manifest ``tier`` value. Returns disabled tiers too — the *caller* decides (AC-47)."""
        result = await session.exec(select(ResourceTier).where(ResourceTier.code == code))
        return result.first()

    @classmethod
    async def acreate(cls, session: AsyncSession, row: ResourceTier) -> ResourceTier:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aupdate_row(cls, session: AsyncSession, tier_code: str, **values: Any) -> bool:
        """Patch the tier identified by ``tier_code``; ``True`` when the row was touched.

        Pinned to the unique ``code``, i.e. exactly one row. Only the columns a
        super admin may retune (``name`` / ``cpu_millicores`` / ``memory_mb`` /
        ``description`` / ``enabled`` / ``sort_order``) are accepted. The row key
        is named ``tier_code`` precisely so that ``code=...`` lands in
        ``**values`` and is **rejected**: renaming a tier would dangle every
        ``app_version.tier_id`` that points at it.
        """
        editable = {"name", "cpu_millicores", "memory_mb", "description", "enabled", "sort_order"}
        unknown = set(values) - editable
        if unknown:
            raise ValueError(f"resource_tier columns not editable: {sorted(unknown)}")
        if not values:
            return False
        payload: dict[str, Any] = dict(values)
        payload["update_time"] = datetime.now()
        result = await session.exec(update(ResourceTier).where(ResourceTier.code == tier_code).values(**payload))
        return bool(result.rowcount)
