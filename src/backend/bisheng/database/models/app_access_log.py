"""``app_access_log`` — who used which hosted application, and when (F054 AC-38, design D14-B).

One row per **entry**, not per request. The row answers PRD RT-01's "who is
using it" and is what the F056 audit query face reads (its AC-24); it is *not*
an ``audit_log`` action — access is a high-frequency event and the operations
audit table carries a UI whitelist plus an ``operator_name`` join it would only
slow down. Same shape as ``llm_call_log``: an independent business log table.

Facts that are easy to get wrong:

* **Entries are merged, not counted.** The Redis window
  ``app_access:{app_id}:{user_id}`` (``app_runtime.access_log_merge_window_seconds``,
  default 1800 s — the value is F056 design D7's) collapses the proxy's cache
  misses, a refresh and every sub-request of one session into one row. A row
  count is therefore "distinct visits", never "requests".
* **Only an ``allow`` verdict writes.** A visitor stopped by the login /
  forbidden / stopped / not-found page was not using anything (F056 spec
  决议-2); refused attempts are a separate event type that does not exist yet.
* **``tenant_id`` is the application's, set explicitly by the writer.** The
  internal authorize endpoint runs under ``bypass_tenant_filter`` (no session on
  that request), so the ``before_flush`` auto-fill does not run there. The
  module is nevertheless registered in ``_TENANT_AWARE_MODEL_MODULES`` so reads
  on the query face are auto-filtered.
* **The writer is backend's ``entry_authz_service``, never app-proxy.** The
  proxy holds no database driver (design D6-C); a second writer would be a
  second definition of what an entry is.

Module location: ``database/models/`` like the other three F054 tables (see
the header of ``app.py`` — arch-guard RULE-2, not preference).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, func, text
from sqlmodel import Field, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.base import SQLModelSerializable


class AppAccessLog(SQLModelSerializable, table=True):
    """One successful entry into one hosted application by one visitor."""

    __tablename__ = "app_access_log"
    __table_args__ = (
        # The two shapes the query face asks for: "who used this app" and
        # "what did this person use", both bounded by a time range.
        Index("ix_app_access_log_app_time", "app_id", "entry_time"),
        Index("ix_app_access_log_user_time", "user_id", "entry_time"),
    )

    # Autoincrement on purpose (the other F054 tables use uuids): an append-only
    # log is read newest-first, and ``entry_time`` is second-precision, so the
    # id is the tie-breaker that keeps pagination stable (AGENTS.md pitfall).
    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=False, index=True, comment="Tenant of the application (not of the token)"),
    )
    app_id: str = Field(sa_column=Column(String(36), nullable=False, comment="app.id that was entered"))
    user_id: int = Field(sa_column=Column(Integer, nullable=False, comment="Visitor user.user_id"))
    user_name: str | None = Field(
        default=None,
        sa_column=Column(String(128), nullable=True, comment="Visitor display name at entry time (denormalised)"),
    )
    entry_time: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(
            DateTime,
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            comment="When the entry verdict was allow",
        ),
    )
    request_id: str | None = Field(
        default=None,
        sa_column=Column(String(64), nullable=True, comment="app-proxy request id of the entry request"),
    )


class AppAccessLogDao:
    """Append + page; the caller owns the session and the transaction."""

    @classmethod
    async def ainsert(cls, session: AsyncSession, row: AppAccessLog) -> AppAccessLog:
        session.add(row)
        await session.flush()
        return row

    @classmethod
    async def alist_page(
        cls,
        session: AsyncSession,
        *,
        app_id: str | None = None,
        user_id: int | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[AppAccessLog], int]:
        """Newest first, ``id`` as the tie-breaker; ``end_time`` is exclusive.

        Tenant scoping is the automatic filter's job (the table carries
        ``tenant_id`` and the module is registered) — a caller that needs a
        cross-tenant view says so with ``bypass_tenant_filter``.
        """
        conditions = []
        if app_id:
            conditions.append(AppAccessLog.app_id == app_id)
        if user_id:
            conditions.append(AppAccessLog.user_id == int(user_id))
        if start_time is not None:
            conditions.append(AppAccessLog.entry_time >= start_time)
        if end_time is not None:
            conditions.append(AppAccessLog.entry_time < end_time)

        count_stmt = select(func.count()).select_from(AppAccessLog)
        rows_stmt = select(AppAccessLog)
        for condition in conditions:
            count_stmt = count_stmt.where(condition)
            rows_stmt = rows_stmt.where(condition)

        total = int((await session.exec(count_stmt)).one())
        rows_stmt = (
            rows_stmt.order_by(col(AppAccessLog.entry_time).desc(), col(AppAccessLog.id).desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
        rows = (await session.exec(rows_stmt)).all()
        return rows, total
