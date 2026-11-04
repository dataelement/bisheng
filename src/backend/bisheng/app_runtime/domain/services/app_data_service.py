"""Edit-authorized application data, preserving identifier, export and audit limits.

Backend never opens the runtime database. Docker and Kubernetes retain their
existing data transports and writer/session fences; all user doors share this
resource-action check before any data is read or changed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bisheng.app_runtime.domain.constants import AppAuditAction
from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import (
    AppDataInvalidError,
    AppDataNotReadyError,
)
from bisheng.database.models.app import App
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
        app = await cls._load_authorized(app_id, actor)
        if not app.current_version_id and not app.pending_version_id:
            raise AppDataNotReadyError(app_id=app.id)
        return await cls._call(app, actor, "tables", {}, lambda: orchestrator_client.db_tables(app_id=app.id))

    @classmethod
    async def get_table_schema(cls, app_id: str, table: str, *, actor) -> dict[str, Any]:
        app = await cls._load_authorized(app_id, actor)
        table = cls._identifier(table, what="table")
        return await cls._call(
            app, actor, "schema", {"table": table}, lambda: orchestrator_client.db_schema(app_id=app.id, table=table)
        )

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
        app = await cls._load_authorized(app_id, actor)
        parameters = {
            "table": cls._identifier(table, what="table"),
            "page": cls._page(page),
            "size": cls._size(size),
            "order": cls._order(order),
        }
        return await cls._call(
            app, actor, "rows", parameters, lambda: orchestrator_client.db_rows(app_id=app.id, **parameters)
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
        app = await cls._load_authorized(app_id, actor)
        table = cls._identifier(table, what="table")
        cls._row_key(key)
        cls._values(values)
        parameters = {"table": table, "key": str(key), "values": values}
        result = await cls._call(
            app, actor, "update", parameters, lambda: orchestrator_client.db_update_row(app_id=app.id, **parameters)
        )
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
    async def export_table(cls, app_id: str, table: str, *, actor) -> tuple[str, bytes | Path]:
        """Return bytes for Docker or a private CSV cache for K8s, with the same audit."""
        app = await cls._load_authorized(app_id, actor)
        table = cls._identifier(table, what="table")
        content = await cls._call(
            app, actor, "export", {"table": table}, lambda: orchestrator_client.db_export(app_id=app.id, table=table)
        )
        try:
            await cls._audit(
                AppAuditAction.DATA_EXPORT,
                app,
                actor,
                reason=f"table {table} exported",
                detail={
                    "table": table,
                    "bytes": content.stat().st_size if isinstance(content, Path) else len(content or b""),
                },
            )
        except BaseException:
            if isinstance(content, Path):
                cls.cleanup_export(content)
            raise
        return f"{app.slug or app.id}-{table}.csv", content

    @staticmethod
    def cleanup_export(path: Path):
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except FileNotFoundError:
            pass

    @classmethod
    async def recover_result(cls, app_id, operation_id, *, actor):
        app = await cls._load_authorized(app_id, actor)
        from bisheng.app_runtime.domain.services.runtime_data_session_service import RuntimeDataSessionService

        return await RuntimeDataSessionService().recover(app, actor, operation_id)

    @staticmethod
    async def _call(app, actor, action, parameters, legacy):
        from bisheng.app_runtime.domain.services.runtime_data_session_service import RuntimeDataSessionService

        sessions = RuntimeDataSessionService()
        if await sessions.supports(app):
            return await sessions.execute(app, actor, action, parameters)
        return await legacy()

    # -- helpers --------------------------------------------------------

    @classmethod
    async def _load_authorized(cls, app_id: str, actor) -> App:
        return await AppAuthorizationService.authorize_app(actor, app_id, "data_read")

    @staticmethod
    async def _require_editor(app: App, actor) -> None:
        await AppAuthorizationService.authorize_loaded_app(actor, app, "data_edit")

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
