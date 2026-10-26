"""``app_instance`` — the platform's view of a running hosted application (F054 design D8).

Facts that are easy to get wrong:

* **This table is not the routing truth.** ``exec_ref`` (the container name in
  the compose shape) is an audit / troubleshooting handle only, and it is the
  single field allowed to carry a shape-specific value — and only inwards.
  app-proxy resolves upstreams through ``GET /v1/apps/{id}/route`` on
  runtime-manager, whose desired-state store is the only routing truth
  (design D5.1). Copying ``exec_ref`` into a proxy would desync on every
  version switch.
* ``phase`` values are shape-neutral (``pending | building | starting |
  running | unhealthy | stopped | failed``, INV-33). No "container" or
  "compose" wording ever reaches this column — F059 swaps the orchestration
  backend without touching it.
* One app has at most one long-running instance (AC-24 / K6: SQLite WAL binds
  a single writer to a local volume), hence ``aupsert`` keyed by ``app_id``.

Module location: see the header of ``app.py`` — these tables sit in
``database/models/`` because of arch-guard RULE-2, not by preference.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text, update
from sqlmodel import Field, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.utils import generate_uuid

# ``phase`` values — shape-neutral by contract (design §4.2 ①).
PHASE_PENDING = "pending"
PHASE_BUILDING = "building"
PHASE_STARTING = "starting"
PHASE_RUNNING = "running"
PHASE_UNHEALTHY = "unhealthy"
PHASE_STOPPED = "stopped"
PHASE_FAILED = "failed"


class AppInstance(SQLModelSerializable, table=True):
    """At most one row per app — the platform-side mirror of the running execution."""

    __tablename__ = "app_instance"
    __table_args__ = (UniqueConstraint("app_id", name="uk_app_instance_app"),)

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    app_id: str = Field(sa_column=Column(String(36), nullable=False, comment="Owning app.id"))
    # ``default=None`` on purpose — filled by the before_flush tenant hook.
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    version_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, comment="Version this instance was started from"),
    )
    phase: str = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            comment="pending | building | starting | running | unhealthy | stopped | failed",
        ),
    )
    health: str | None = Field(
        default=None,
        sa_column=Column(String(16), nullable=True, comment="Last known health probe verdict"),
    )
    exec_ref: str | None = Field(
        default=None,
        sa_column=Column(
            String(128),
            nullable=True,
            comment="Execution handle (compose: container name). Audit/debug only — never a routing source",
        ),
    )
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    restart_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0"), comment="Self-heal restarts observed"),
    )
    last_probe_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class AppInstanceDao:
    """Single-row ORM access; the caller owns the session and the transaction."""

    @classmethod
    async def aget_by_app(cls, session: AsyncSession, app_id: str) -> AppInstance | None:
        result = await session.exec(select(AppInstance).where(AppInstance.app_id == app_id))
        return result.first()

    @classmethod
    async def aupsert(cls, session: AsyncSession, app_id: str, **fields: Any) -> AppInstance:
        """Create or refresh the single instance row of one app (AC-24: at most one).

        Not a bulk statement: the existing row is loaded first and mutated in
        place, so the SELECT still goes through the tenant filter and the INSERT
        still goes through the ``before_flush`` tenant fill.
        """
        row = await cls.aget_by_app(session, app_id)
        if row is None:
            row = AppInstance(app_id=app_id, phase=fields.pop("phase", PHASE_PENDING))
        for key, value in fields.items():
            setattr(row, key, value)
        row.update_time = datetime.now()
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aset_phase(
        cls,
        session: AsyncSession,
        app_id: str,
        phase: str,
        *,
        health: str | None = None,
        last_probe_at: datetime | None = None,
    ) -> bool:
        """Move one app's instance to ``phase``; ``True`` when a row was touched.

        Pinned to ``app_id`` (unique), so no row of another app — and therefore
        of another tenant — can be reached by this conditional UPDATE even
        though the tenant listener does not rewrite non-SELECT statements.
        """
        values: dict[str, Any] = {"phase": phase, "update_time": datetime.now()}
        if health is not None:
            values["health"] = health
        if last_probe_at is not None:
            values["last_probe_at"] = last_probe_at
        result = await session.exec(update(AppInstance).where(AppInstance.app_id == app_id).values(**values))
        return bool(result.rowcount)
