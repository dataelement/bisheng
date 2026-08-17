"""``app_version`` — immutable version records of a hosted application (F054 design D8).

Facts that are easy to get wrong:

* **There is no tenant_id column** (design K5 ②). Registering this module in
  ``_TENANT_AWARE_MODEL_MODULES`` only guarantees the metadata is imported;
  ``_discover_tenant_aware_tables`` skips tables without the column, so rows
  here are **never** auto-filtered. Isolation is derived: load the ``app`` row
  by ``app_id`` first (that one *is* filtered), then read the version. Every
  DAO method that starts from a ``version_id`` therefore takes ``app_id`` as
  well — a plain ``select(AppVersion).where(id=...)`` leaks another tenant's
  ``code_object_key``, i.e. the object key of their source snapshot (pit 31).
* **Rows are INSERT-only** (RT-05 / AC-02). Code snapshot, capability
  declaration, injection config and resource tier belong to one record and no
  writer may change one of them in isolation — enforced by simply not offering
  a generic UPDATE. :meth:`AppVersionDao.amark_terminal` is the sole exception:
  a single-column latch for the approval outcome, written by F055.
* ``runtime`` / ``tier_id`` are explicit columns, not manifest lookups: they are
  filtered/joined in SQL and ``JSON_EXTRACT`` is banned on DM8 (design K4).
  ``manifest`` / ``capabilities`` / ``injections`` are ``JsonType`` (CLOB on
  DM8) and are only ever inspected in Python.
* The code snapshot itself is **not** in the database — ``code_object_key``
  points at MinIO (``bisheng-apps`` bucket, design D10).

Module location: see the header of ``app.py`` — these tables sit in
``database/models/`` because of arch-guard RULE-2, not by preference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint, text, update
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT, JsonType
from bisheng.utils import generate_uuid

# ``kind`` values — the first version of an app vs. every later one.
VERSION_KIND_INITIAL = "initial"
VERSION_KIND_ITERATION = "iteration"

# ``terminal_state`` values. NULL means "no approval outcome yet"; it cannot
# express "approved but not started" — that state is carried by
# ``app.pending_version_id`` instead (design D8, AC-04).
TERMINAL_STATE_ONLINE = "online"
TERMINAL_STATE_REJECTED = "rejected"
TERMINAL_STATE_WITHDRAWN = "withdrawn"


class AppVersion(SQLModelSerializable, table=True):
    """One submitted version. Written once; only ``terminal_state`` is latched later."""

    __tablename__ = "app_version"
    __table_args__ = (
        UniqueConstraint("app_id", "version_no", name="uk_app_version_no"),
        Index("ix_app_version_app_id", "app_id"),
    )

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    app_id: str = Field(sa_column=Column(String(36), nullable=False, comment="Owning app.id — the isolation handle"))
    version_no: int = Field(sa_column=Column(Integer, nullable=False, comment="1-based, monotonic within one app"))
    kind: str = Field(sa_column=Column(String(16), nullable=False, comment="initial | iteration"))
    terminal_state: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True, comment="online | rejected | withdrawn | NULL (undecided)"),
    )
    code_object_key: str = Field(
        sa_column=Column(String(512), nullable=False, comment="MinIO object key of the code snapshot; never inline"),
    )
    manifest: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False, comment="Frozen bisheng-app.yaml; inspected in Python only"),
    )
    capabilities: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False, comment="Frozen capability declaration (F055)"),
    )
    injections: dict = Field(
        default_factory=dict,
        sa_column=Column(JsonType, nullable=False, comment="Frozen injection config (F055)"),
    )
    tier_id: str = Field(sa_column=Column(String(32), nullable=False, comment="Resource tier id, frozen at submit"))
    runtime: str = Field(
        sa_column=Column(String(32), nullable=False, comment="Dockerfile template key, e.g. python3.11")
    )
    image_ref: str | None = Field(
        default=None,
        sa_column=Column(String(256), nullable=True, comment="Built image tag; never reused across versions"),
    )
    submitted_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class AppVersionDao:
    """INSERT-only access, plus one single-column latch.

    Every lookup takes ``app_id`` — there is no tenant column here, so the
    ``app_id`` predicate is what keeps a version read inside the tenant whose
    ``app`` row the caller already resolved (design K5 ② / pit 31).
    """

    @classmethod
    async def ainsert(cls, session: AsyncSession, row: AppVersion) -> AppVersion:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aget(cls, session: AsyncSession, app_id: str, version_id: str) -> AppVersion | None:
        """One version of one app. ``app_id`` is mandatory — see the class docstring."""
        result = await session.exec(select(AppVersion).where(AppVersion.app_id == app_id, AppVersion.id == version_id))
        return result.first()

    @classmethod
    async def alist_by_app(cls, session: AsyncSession, app_id: str) -> list[AppVersion]:
        """All versions of one app, newest first (feeds the read-only version dropdown, AC-52)."""
        statement = select(AppVersion).where(AppVersion.app_id == app_id).order_by(col(AppVersion.version_no).desc())
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def amax_version_no(cls, session: AsyncSession, app_id: str) -> int:
        """Highest ``version_no`` of one app, 0 when there is none — the next version is this + 1."""
        statement = (
            select(AppVersion.version_no)
            .where(AppVersion.app_id == app_id)
            .order_by(col(AppVersion.version_no).desc())
            .limit(1)
        )
        result = await session.exec(statement)
        row = result.first()
        return int(row) if row is not None else 0

    @classmethod
    async def amark_terminal(
        cls,
        session: AsyncSession,
        app_id: str,
        version_id: str,
        terminal_state: str,
    ) -> bool:
        """Latch the approval outcome; ``True`` only for the caller that won.

        The sole write that is not an INSERT, and the only reason this table is
        not strictly append-only. Pinned to (``app_id``, ``id``) with
        ``terminal_state IS NULL``, so it can neither reach another app's rows
        nor overwrite a decision that was already recorded.
        """
        values: dict[str, Any] = {"terminal_state": terminal_state, "update_time": datetime.now()}
        result = await session.exec(
            update(AppVersion)
            .where(
                AppVersion.app_id == app_id,
                AppVersion.id == version_id,
                col(AppVersion.terminal_state).is_(None),
            )
            .values(**values)
        )
        return bool(result.rowcount)
