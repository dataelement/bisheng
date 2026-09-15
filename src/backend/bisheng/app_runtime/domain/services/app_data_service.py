"""The application's own data — the platform's *only* way to read or write it (AC-56, D10-C).

Five operations, mirroring the manager's data-plane RPC one to one: table list,
table shape, one page of rows, one-row update, CSV export. What this layer adds
and the manager cannot:

* **Owner narrowing.** The data tab and the F052 MCP data tools are for the
  person who owns the app — not the tenant administrator, not the platform
  super admin. Like the delete action this is a *business* pre-check, because
  the permission runtime short-circuits administrators to ALLOW and "only the
  owner" is inexpressible there (constitution C4 note). Refusals are 16162
  inside a 200 envelope, never HTTP 403: the platform SPA turns a 403 on a GET
  into a full-page redirect (design pit 25).
* **Audit.** A row edit is ``app.data_row_edit`` with table / key / before /
  after; an export is ``app.data_export``. The manager knows neither the
  operator nor the tenant, so the row can only be written here.
* **Backend-side identifier hygiene.** The manager checks every name against
  the live schema; this layer refuses anything that is not a plain identifier
  *before* it leaves the process, so a ``DROP TABLE`` smuggled into a table
  name is refused twice and the second check never has to be the only one.

What it does **not** do is open the file. The database lives on the manager's
host (``{data_root}/apps/{app_id}/db/app.db``); backend does not know that
layout (K1) and in the multi-node shape is not even on that machine. Every
call here is one ``orchestrator_client.db_*`` RPC. The F052 MCP data tools call
*these* methods — never the client directly — so that the owner rule and the
audit row hold for every door (``test_mcp_face_reuses_same_service_method``).
"""

from __future__ import annotations

import re
from typing import Any

from bisheng.app_runtime.domain.constants import AppAuditAction, AppState
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import AppDataForbiddenError, AppDataInvalidError, AppNotFoundError
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.database.models.audit_log import AuditLogDao

#: A table, column or order column. The manager re-checks against
#: ``sqlite_master``; this is the cheap first gate that keeps statements out.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: Row keys travel as a URL path segment on both hops.
_ROW_KEY = re.compile(r"^[^/\\\x00-\x1f]{1,200}$")

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

_SCALAR_TYPES = (str, int, float, bool, type(None))


class AppDataService:
    """Owner-only, audited access to one hosted application's database."""

    # -- reads ----------------------------------------------------------

    @classmethod
    async def list_tables(cls, app_id: str, *, actor) -> dict[str, Any]:
        """``{tables: [{name, column_count}]}`` — ``[]`` is a legitimate answer."""
        app = await cls._load_owned(app_id, actor)
        return await orchestrator_client.db_tables(app_id=app.id)

    @classmethod
    async def get_table_schema(cls, app_id: str, table: str, *, actor) -> dict[str, Any]:
        app = await cls._load_owned(app_id, actor)
        return await orchestrator_client.db_schema(app_id=app.id, table=cls._identifier(table, what="table"))

    @classmethod
    async def get_rows(
        cls,
        app_id: str,
        table: str,
        *,
        actor,
        page: int | None = None,
        size: int | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        """One page in a stable order — the manager appends the row key as tiebreaker."""
        app = await cls._load_owned(app_id, actor)
        return await orchestrator_client.db_rows(
            app_id=app.id,
            table=cls._identifier(table, what="table"),
            page=cls._page(page),
            size=cls._size(size),
            order=cls._order(order),
        )

    # -- writes ---------------------------------------------------------

    @classmethod
    async def update_row(cls, app_id: str, table: str, key: str, values: dict[str, Any], *, actor) -> dict[str, Any]:
        """Change exactly one row and audit it with the before / after values.

        The manager returns ``before`` / ``after`` from inside the same short
        transaction, so the audit row records what was actually replaced and
        not what a second read — possibly already overtaken by the app's own
        next write — would have shown.
        """
        app = await cls._load_owned(app_id, actor)
        table = cls._identifier(table, what="table")
        cls._row_key(key)
        cls._values(values)
        result = await orchestrator_client.db_update_row(app_id=app.id, table=table, key=str(key), values=values)
        await cls._audit(
            AppAuditAction.DATA_ROW_EDIT,
            app,
            actor,
            reason=f"row edited in table {table}",
            detail={
                "table": table,
                "key": result.get("key", key),
                "columns": sorted(values),
                "before": result.get("before") or {},
                "after": result.get("after") or {},
            },
        )
        return result

    @classmethod
    async def export_table(cls, app_id: str, table: str, *, actor) -> tuple[str, bytes]:
        """``(filename, csv_bytes)`` — the whole table, audited as ``app.data_export``."""
        app = await cls._load_owned(app_id, actor)
        table = cls._identifier(table, what="table")
        content = await orchestrator_client.db_export(app_id=app.id, table=table)
        await cls._audit(
            AppAuditAction.DATA_EXPORT,
            app,
            actor,
            reason=f"table {table} exported",
            detail={"table": table, "bytes": len(content or b"")},
        )
        return f"{app.slug or app.id}-{table}.csv", content

    # -- helpers --------------------------------------------------------

    @classmethod
    async def _load_owned(cls, app_id: str, actor) -> App:
        """The app, or 16101 — then the owner rule, or 16162.

        Order matters: a non-owner of a deleted app gets "does not exist", the
        same answer a stranger gets, so the refusal leaks nothing about which
        apps exist.
        """
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None or row.state == AppState.DELETED.value:
            raise AppNotFoundError(app_id=app_id)
        set_current_tenant_id(int(row.tenant_id or 0))
        cls._require_owner(row, actor)
        return row

    @staticmethod
    def _require_owner(app: App, actor) -> None:
        """Owner only — administrators included in the refusal (AC-56).

        Deliberately does not consult ``is_global_super`` or the tenant-admin
        check: this is the one surface where an administrator's reach ends,
        and the check must not have a branch that could widen it.
        """
        if int(getattr(actor, "user_id", 0) or 0) != int(app.owner_user_id or 0):
            raise AppDataForbiddenError(app_id=app.id)

    @staticmethod
    def _identifier(name: Any, *, what: str) -> str:
        if not isinstance(name, str) or not _IDENTIFIER.match(name) or name.lower().startswith("sqlite_"):
            raise AppDataInvalidError(msg=f"{what} is not a plain identifier", **{what: str(name)[:80]})
        return name

    @classmethod
    def _order(cls, order: str | None) -> str | None:
        if not order:
            return None
        column = order[1:] if order.startswith("-") else order
        cls._identifier(column, what="order")
        return order

    @staticmethod
    def _page(page: int | None) -> int | None:
        if page is None:
            return None
        if int(page) < 1:
            raise AppDataInvalidError(msg="page must be ≥ 1", page=page)
        return int(page)

    @staticmethod
    def _size(size: int | None) -> int | None:
        if size is None:
            return None
        if not 1 <= int(size) <= MAX_PAGE_SIZE:
            raise AppDataInvalidError(msg=f"size must be between 1 and {MAX_PAGE_SIZE}", size=size)
        return int(size)

    @staticmethod
    def _row_key(key: Any) -> str:
        text = str(key)
        if not _ROW_KEY.match(text):
            raise AppDataInvalidError(msg="row key is not usable as a path segment")
        return text

    @classmethod
    def _values(cls, values: Any) -> dict[str, Any]:
        if not isinstance(values, dict) or not values:
            raise AppDataInvalidError(msg="values must be a non-empty object of column → value")
        for column, value in values.items():
            cls._identifier(column, what="column")
            if not isinstance(value, _SCALAR_TYPES):
                raise AppDataInvalidError(msg="only scalar values are accepted", column=column)
        return values

    @staticmethod
    async def _audit(
        action: AppAuditAction,
        app: App,
        actor,
        *,
        reason: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        await AuditLogDao.ainsert_v2(
            tenant_id=int(app.tenant_id or 0),
            operator_id=int(getattr(actor, "user_id", 0) or 0),
            operator_tenant_id=int(getattr(actor, "tenant_id", 0) or app.tenant_id or 0),
            operator_name=getattr(actor, "user_name", None),
            action=action.value,
            target_type="app",
            target_id=app.id,
            object_name=app.name,
            reason=reason or None,
            metadata={"state": app.state, "reason": reason, **(detail or {})},
        )
