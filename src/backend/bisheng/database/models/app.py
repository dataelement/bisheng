"""``app`` — the hosted-application aggregate root (F054 design D8).

Facts that are easy to get wrong:

* **This file lives in ``database/models/`` on purpose, not in
  ``app_runtime/domain/models/``.** The build-page list is one query: a
  ``UNION ALL`` of workflow + assistant + hosted app, assembled inside
  ``database/models/flow.py``. That file would have to
  ``from bisheng.app_runtime.domain.models... import App`` — which
  ``scripts/arch-guard.sh`` RULE-2 rejects outright. Keeping the three tables
  next to ``flow.py`` / ``assistant.py`` is the price of the single query
  (design D8 "模型落点" / pit 27). Do **not** "tidy it up" into the module.
  For the same reason this module must never import ``bisheng.*.domain.*`` —
  the ``AppState`` enum lives in ``app_runtime/domain/constants.py`` and the
  DAO deliberately speaks plain ``str``.
* ``id`` is a **str**. ``Flow.id`` and ``Assistant.id`` are str, and the three
  legs of the UNION must agree on column types (design K5 ③).
* ``slug`` is unique **globally, across tenants** (AC-08): it is the public
  entry path ``/apps/{slug}``, resolved by app-proxy before any tenant context
  exists — so ``aget_by_slug`` must be called inside ``bypass_tenant_filter()``.
* ``state`` is an explicit ``VARCHAR(16)`` column, never a JSON field: the list
  API filters on it and ``JSON_EXTRACT`` is banned on DM8 (design K4).
* Application state has exactly one writer, ``AppStateService`` (决议-8).
  The DAO exposes no generic UPDATE — only :meth:`AppDao.aupdate_state_cas`,
  a compare-and-set pinned to one primary key, which is also what makes
  concurrent "stop" vs "publish finalise" safe without row locks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, UniqueConstraint, text, update
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.utils import generate_uuid

# Sentinel telling ``aupdate_state_cas`` "leave this column alone" — distinct
# from ``None``, which means "write NULL" (clearing ``pending_version_id`` after
# a successful start is exactly that case).
_UNSET: Any = object()


class App(SQLModelSerializable, table=True):
    """One hosted application. The row is the app; versions hang off it."""

    __tablename__ = "app"
    __table_args__ = (
        UniqueConstraint("slug", name="uk_app_slug"),
        Index("ix_app_tenant_state", "tenant_id", "state"),
    )

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    slug: str = Field(
        sa_column=Column(String(64), nullable=False, comment="Entry path segment /apps/{slug}; globally unique"),
    )
    name: str = Field(sa_column=Column(String(128), nullable=False, comment="Display name"))
    description: str | None = Field(default=None, sa_column=Column(String(1000), nullable=True))
    logo: str | None = Field(default=None, sa_column=Column(String(512), nullable=True))
    owner_user_id: int = Field(sa_column=Column(Integer, nullable=False, index=True, comment="Owner (natural person)"))
    # ``default=None`` on purpose: the before_flush hook fills it from the
    # current tenant context. A Python default would silently write child-tenant
    # rows to Root (same guard as F049 ``api_credential``).
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    state: str = Field(
        sa_column=Column(
            String(16),
            nullable=False,
            comment="draft | online | pending_capacity | stopped | deleted (see AppState)",
        ),
    )
    current_version_id: str | None = Field(
        default=None,
        sa_column=Column(String(36), nullable=True, comment="Version currently running / last started"),
    )
    pending_version_id: str | None = Field(
        default=None,
        sa_column=Column(
            String(36),
            nullable=True,
            comment="Approved but not yet started version (AC-04); cleared once it starts",
        ),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class AppDao:
    """Single-row ORM access. Sessions and tenant-filter bypass are the caller's job.

    No bulk ``update()`` / ``delete()`` and no ``text()``: the tenant filter
    rewrites SELECT statements only (design K5 ③), so a bulk write would escape
    isolation silently. The one conditional UPDATE
    (:meth:`aupdate_state_cas`) is pinned to a primary key.
    """

    @classmethod
    async def acreate(cls, session: AsyncSession, row: App) -> App:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aget(cls, session: AsyncSession, app_id: str) -> App | None:
        result = await session.exec(select(App).where(App.id == app_id))
        return result.first()

    @classmethod
    async def aget_by_slug(cls, session: AsyncSession, slug: str) -> App | None:
        """Resolve the public entry segment.

        ``slug`` is unique across tenants, and the entry path is hit before any
        tenant context exists — the *caller* wraps this in
        ``bypass_tenant_filter()`` and treats the row's ``tenant_id`` as the
        authoritative tenant for everything that follows.
        """
        result = await session.exec(select(App).where(App.slug == slug))
        return result.first()

    @classmethod
    async def alist_by_owner(cls, session: AsyncSession, owner_user_id: int) -> list[App]:
        """All apps of one owner, newest first. Tenant scoping comes from the auto filter."""
        statement = (
            select(App)
            .where(App.owner_user_id == owner_user_id)
            .order_by(col(App.update_time).desc(), col(App.id).desc())
        )
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def aupdate_state_cas(
        cls,
        session: AsyncSession,
        app_id: str,
        *,
        from_states: tuple[str, ...],
        to_state: str,
        current_version_id: Any = _UNSET,
        pending_version_id: Any = _UNSET,
    ) -> bool:
        """Compare-and-set the application state; ``True`` only for the caller that won.

        ``WHERE id = :id AND state IN (:from_states)`` is the whole concurrency
        story (design D8): a losing caller sees ``rowcount == 0`` and the service
        raises ``AppStateConflictError`` (16102). No row lock, no state-history
        table — every transition is audited, and the audit *is* the history.

        ``current_version_id`` / ``pending_version_id`` accept ``None`` to write
        NULL; omit them entirely to leave the column untouched.
        """
        values: dict[str, Any] = {"state": to_state, "update_time": datetime.now()}
        if current_version_id is not _UNSET:
            values["current_version_id"] = current_version_id
        if pending_version_id is not _UNSET:
            values["pending_version_id"] = pending_version_id
        result = await session.exec(
            update(App).where(App.id == app_id, col(App.state).in_(from_states)).values(**values)
        )
        return bool(result.rowcount)
