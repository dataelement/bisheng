"""``app_preview_session`` — one approver's temporary trial of a pending version (F055 AC-26 … AC-29).

The row is the platform's half of a preview; the container is runtime-manager's.
Keeping a row at all (rather than asking the manager to enumerate previews) buys
the three things the manager cannot answer:

* **who** the preview belongs to — the entry path injects *that approver's*
  identity and nobody else's (AC-27), so the session must remember the person it
  was raised for;
* **when it dies** — ``expires_at`` is stamped from
  ``settings.app_runtime.preview_ttl_days`` at start time, so shortening the
  deployment setting later cannot retroactively kill a running trial, and the
  sweep is a plain indexed range query rather than a walk over containers;
* **why it is gone** — 「已回收」 needs a reason (approval ended / the approver
  pressed the button / it timed out), and that is a product fact, not a
  container fact.

Facts that are easy to get wrong:

* **``id`` is the URL segment.** It appears in ``/apps/preview/{session}``, so
  it is a generated uuid and never anything derived from the app or the
  approver — a guessable id would be a way into somebody else's trial before
  the identity check even runs.
* **``status`` is an explicit VARCHAR column**, not a JSON key: the sweep
  filters ``(status, expires_at)`` and the panel filters ``(version_id,
  approver_user_id, status)``. ``JSON_EXTRACT`` is banned on DM8 (C2).
* **The DAO issues single-row writes only.** The tenant filter rewrites SELECT
  and nothing else, so a bulk UPDATE would escape isolation silently — every
  write here is pinned to the primary key, and the sweep reads rows first and
  then closes them one at a time.
* **Reclaimed rows are kept.** They are what 「已回收」 renders from, and they
  are the only record that a given approver did try the code before approving
  it. Raising a new preview writes a new row rather than reviving one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, text, update
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable
from bisheng.core.database.dialect_helpers import UPDATE_TIME_SERVER_DEFAULT
from bisheng.utils import generate_uuid

#: The instance is up and the approver may open it.
PREVIEW_STATUS_RUNNING = "running"
#: It has been torn down. ``reclaim_reason`` says which of the three triggers.
PREVIEW_STATUS_RECLAIMED = "reclaimed"

PREVIEW_STATUSES: frozenset[str] = frozenset({PREVIEW_STATUS_RUNNING, PREVIEW_STATUS_RECLAIMED})

#: ``reclaim_reason`` values. Three triggers, three different sentences in the
#: panel — an approver who pressed 「回收」 must not be told the approval ended.
RECLAIM_REASON_MANUAL = "manual"
RECLAIM_REASON_APPROVAL_TERMINAL = "approval_terminal"
RECLAIM_REASON_EXPIRED = "expired"


class AppPreviewSession(SQLModelSerializable, table=True):
    """One approval-time preview instance, from 「拉起」 to 「已回收」."""

    __tablename__ = "app_preview_session"
    __table_args__ = (
        Index("ix_app_preview_session_version_approver", "version_id", "approver_user_id", "status"),
        Index("ix_app_preview_session_status_expires", "status", "expires_at"),
    )

    #: Also the ``/apps/preview/{session}`` segment — generated, never derived.
    id: str = Field(default_factory=generate_uuid, primary_key=True)
    # ``default=None``: the before_flush hook fills it from the current tenant
    # context. A Python default would write child-tenant rows to Root.
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant ID"),
    )
    app_id: str = Field(
        sa_column=Column(String(36), nullable=False, index=True, comment="Application being previewed"),
    )
    version_id: str = Field(
        sa_column=Column(String(36), nullable=False, comment="The version waiting to go live that is being tried"),
    )
    approver_user_id: int = Field(
        sa_column=Column(
            Integer,
            nullable=False,
            comment="The approver this preview was raised for; the only identity injected into it (AC-27)",
        ),
    )
    status: str = Field(
        sa_column=Column(String(16), nullable=False, comment="running | reclaimed"),
    )
    reclaim_reason: str | None = Field(
        default=None,
        sa_column=Column(String(32), nullable=True, comment="manual | approval_terminal | expired"),
    )
    expires_at: datetime = Field(
        sa_column=Column(
            DateTime,
            nullable=False,
            comment="Stamped at start from settings.app_runtime.preview_ttl_days; the sweep reads it",
        ),
    )
    reclaimed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=True),
    )
    create_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")),
    )
    update_time: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime, nullable=False, server_default=UPDATE_TIME_SERVER_DEFAULT),
    )


class AppPreviewSessionDao:
    """Single-row ORM access. Sessions and transactions belong to the caller."""

    @classmethod
    async def acreate(cls, session: AsyncSession, row: AppPreviewSession) -> AppPreviewSession:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def aget(cls, session: AsyncSession, session_id: str) -> AppPreviewSession | None:
        result = await session.exec(select(AppPreviewSession).where(AppPreviewSession.id == session_id))
        return result.first()

    @classmethod
    async def aget_running_for(
        cls,
        session: AsyncSession,
        *,
        version_id: str,
        approver_user_id: int,
    ) -> AppPreviewSession | None:
        """This approver's live trial of this version, if there is one.

        Scoped by approver on purpose: two approvers on the same request each
        get their own instance, because each one's is injected with their own
        identity (AC-27) and sharing one would show approver B the data
        approver A typed.
        """
        statement = (
            select(AppPreviewSession)
            .where(
                AppPreviewSession.version_id == version_id,
                AppPreviewSession.approver_user_id == approver_user_id,
                AppPreviewSession.status == PREVIEW_STATUS_RUNNING,
            )
            .order_by(col(AppPreviewSession.create_time).desc(), col(AppPreviewSession.id).desc())
            .limit(1)
        )
        result = await session.exec(statement)
        return result.first()

    @classmethod
    async def alist_running_by_version(cls, session: AsyncSession, version_id: str) -> list[AppPreviewSession]:
        """Every live trial of one version — what a terminal approval reclaims (AC-28)."""
        statement = select(AppPreviewSession).where(
            AppPreviewSession.version_id == version_id,
            AppPreviewSession.status == PREVIEW_STATUS_RUNNING,
        )
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def alist_expired(cls, session: AsyncSession, *, now: datetime, limit: int = 200) -> list[AppPreviewSession]:
        """Live trials whose deadline has passed, oldest first.

        Read under ``bypass_tenant_filter`` by the sweep: it runs on a Celery
        beat tick with no tenant context, and a tenant-scoped read there would
        either raise or silently sweep one tenant's previews only.
        """
        statement = (
            select(AppPreviewSession)
            .where(
                AppPreviewSession.status == PREVIEW_STATUS_RUNNING,
                AppPreviewSession.expires_at <= now,
            )
            .order_by(col(AppPreviewSession.expires_at).asc(), col(AppPreviewSession.id).asc())
            .limit(limit)
        )
        result = await session.exec(statement)
        return list(result.all())

    @classmethod
    async def amark_reclaimed(cls, session: AsyncSession, session_id: str, *, reason: str) -> bool:
        """Close one trial; ``True`` when this call is the one that closed it.

        The ``status = running`` predicate is what makes the three reclaim
        triggers safe to race: the second one to arrive changes no row and gets
        ``False``, instead of overwriting the first one's reason with its own.
        """
        values: dict[str, Any] = {
            "status": PREVIEW_STATUS_RECLAIMED,
            "reclaim_reason": reason,
            "reclaimed_at": datetime.now(),
            "update_time": datetime.now(),
        }
        result = await session.exec(
            update(AppPreviewSession)
            .where(AppPreviewSession.id == session_id, AppPreviewSession.status == PREVIEW_STATUS_RUNNING)
            .values(**values)
        )
        return bool(result.rowcount)
