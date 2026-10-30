"""Safe management summaries and edit-only content, using exact F048 actions."""

from __future__ import annotations

from typing import Any

from bisheng.app_runtime.domain.constants import AppState
from bisheng.app_runtime.domain.services.app_authorization_service import AppAuthorizationService
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import (
    AppManageForbiddenError,
    AppNotFoundError,
)
from bisheng.common.services.config_service import settings
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.database.models.app_instance import PHASE_STOPPED, AppInstanceDao
from bisheng.database.models.app_version import AppVersionDao

#: Which door the caller came through. The *content* is identical for all three
#: (AC-55); only the admission rule differs — see the module docstring.
LOG_ENTRY_DETAIL = "detail"
LOG_ENTRY_CLI = "cli"
LOG_ENTRY_MCP = "mcp"

#: Kept as a transport classification for older callers; it grants no owner exception.
OWNER_ONLY_ENTRIES = frozenset({LOG_ENTRY_CLI, LOG_ENTRY_MCP})


class AppQueryService:
    """Read-only projections of one hosted application, or of a caller's set of them."""

    # -- detail ---------------------------------------------------------

    @classmethod
    async def get_detail(cls, app_id: str, *, actor) -> dict[str, Any]:
        app = await cls._load_visible(app_id, actor)
        actions = await AppAuthorizationService.management_actions(actor, [app])
        return cls._detail_payload(app, allowed_actions=actions.get(app.id, frozenset()))

    @classmethod
    async def get_instance(cls, app_id: str, *, actor, entry: str = LOG_ENTRY_DETAIL) -> dict[str, Any]:
        """Live instance view (AC-23).

        "No instance" and "the orchestration backend is down" are deliberately
        two different answers: collapsing them would make every dockerd restart
        render as "this application was deleted" (contract §2).

        ``entry`` picks the admission rule, the same way ``get_logs`` does: the
        platform detail page admits administrators, a credential door does not.
        """
        app = await cls._load_visible(app_id, actor, entry=entry)
        try:
            status = await orchestrator_client.status(app_id=app.id)
            public_fields = {
                "instance_id",
                "phase",
                "health",
                "current_version_id",
                "started_at",
                "restart_count",
                "last_probe_at",
            }
            return {key: value for key, value in status.items() if key in public_fields}
        except AppNotFoundError:
            async with get_async_db_session() as session:
                row = await AppInstanceDao.aget_by_app(session, app.id)
            return {
                "instance_id": None,
                "phase": (row.phase if row is not None else PHASE_STOPPED),
                "health": (row.health if row is not None else None),
                "current_version_id": app.current_version_id,
                "started_at": (row.started_at if row is not None else None),
                "restart_count": (row.restart_count if row is not None else 0),
                "last_probe_at": (row.last_probe_at if row is not None else None),
            }

    # -- logs -----------------------------------------------------------

    @classmethod
    async def get_logs(
        cls,
        app_id: str,
        *,
        actor,
        tail: int | None = None,
        since: str | None = None,
        keyword: str | None = None,
        entry: str = LOG_ENTRY_DETAIL,
    ) -> dict[str, Any]:
        """The app's own recent output. The platform stores none of it (D14-B).

        An empty ``lines`` is a legitimate answer — a freshly started app has
        not printed anything yet — and must not be dressed up as an error.
        """
        app = await cls._load(app_id)
        await cls._require_log_access(app, actor, entry=entry)
        return await orchestrator_client.logs(app_id=app.id, tail=tail, since=since, keyword=keyword)

    # -- versions & list ------------------------------------------------

    @classmethod
    async def list_versions(cls, app_id: str, *, actor) -> list[dict[str, Any]]:
        """Read-only version list, newest first (AC-52).

        The source is ``app_version``. It is emphatically **not** the
        ``version_list`` that ``add_extra_field`` attaches to a flow row — that
        one comes from ``FlowVersionDao``, is always empty for a hosted app, and
        its UI component writes back to a *workflow* when used (pit 13). There
        is no switch and no rollback here on purpose.
        """
        app = await cls._load_visible(app_id, actor)
        async with get_async_db_session() as session:
            rows = await AppVersionDao.alist_by_app(session, app.id)
        from bisheng.app_publish.application.version_review import version_approval_states

        approval_states = await version_approval_states(app.id, app.tenant_id, [row.id for row in rows])
        return [
            {
                "version_id": row.id,
                "version_no": row.version_no,
                "release_notes": row.release_notes,
                "kind": row.kind,
                "terminal_state": row.terminal_state,
                "approval_status": approval_states.get(row.id),
                "submitted_at": row.submitted_at,
                "is_current": row.id == app.current_version_id,
                "is_pending": row.id == app.pending_version_id,
            }
            for row in rows
        ]

    @classmethod
    async def list_versions_page(
        cls,
        app_id: str,
        *,
        actor,
        page: int = 1,
        page_size: int | None = None,
    ) -> dict[str, Any]:
        """:meth:`list_versions` in the ``{"data", "total"}`` envelope the
        platform's ``useTable`` consumes (F055 T044b).

        ``page_size=None`` means *no paging*: ``data`` is the whole list and
        ``total`` its length — what the card dropdown wants, since it looks for
        the running version and a page may not contain it. With ``page_size``,
        ``data`` is that page and ``total`` counts every version.

        The slice is taken here rather than as SQL ``LIMIT``/``OFFSET`` on
        purpose: the list is bounded by one application's deploy count and the
        dropdown reads it whole anyway, while ``AppVersionDao`` is kept to its
        structurally-asserted INSERT-only surface (``test_app_state_service_registry``)
        — a count method there is a surface change this read does not justify.
        """
        rows = await cls.list_versions(app_id, actor=actor)
        if page_size:
            start = (max(int(page), 1) - 1) * int(page_size)
            data = rows[start : start + int(page_size)]
        else:
            data = rows
        return {"data": data, "total": len(rows)}

    @classmethod
    async def list_apps(cls, *, actor, tenant_id: int | None = None) -> list[dict[str, Any]]:
        from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_is_management_api

        permission_actor = await AppAuthorizationService.resolve_actor(actor)
        scope = get_admin_scope_tenant_id() if get_is_management_api() else None
        scope_tenant = scope if scope is not None else permission_actor.tenant_id
        if tenant_id is not None and tenant_id != scope_tenant:
            raise AppNotFoundError()
        async with get_async_db_session() as session:
            rows = await AppDao.alist_by_tenant(session, scope_tenant)
        actions = await AppAuthorizationService.management_actions(actor, rows)
        return [cls._detail_payload(row, allowed_actions=actions[row.id]) for row in rows if row.id in actions]

    @classmethod
    async def get_runtime_status(cls, *, actor) -> dict[str, Any]:
        """AC-23 — capacity, buildable runtimes and deployment pre-flight.

        Super admin only: it describes the *host*, not any one application, and
        the pre-flight details name paths and commands on it.
        """
        if not bool(getattr(actor, "is_global_super", False)):
            raise AppManageForbiddenError(msg="仅平台超级管理员可查看运行环境状态")
        return await orchestrator_client.runtime_status()

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _detail_payload(app: App, *, allowed_actions=frozenset()) -> dict[str, Any]:
        return {
            "app_id": app.id,
            "allowed_actions": sorted(allowed_actions),
            "slug": app.slug,
            "name": app.name,
            "description": app.description,
            "logo": app.logo,
            "state": app.state,
            "owner_user_id": app.owner_user_id,
            "tenant_id": app.tenant_id,
            "current_version_id": app.current_version_id,
            "pending_version_id": app.pending_version_id,
            "entry_url": AppQueryService.entry_url(app.slug),
            "create_time": app.create_time,
            "update_time": app.update_time,
        }

    @staticmethod
    def entry_url(slug: str) -> str:
        """The full address of the entry (AC-25).

        API/CLI consumers receive the configured base. The browser's publish
        page uses its current origin and deployment prefix for the same app
        route; its development server proxies ``/apps/`` to the installed entry.
        """
        base = (settings.app_runtime.entry_base_url or "").rstrip("/")
        return f"{base}/apps/{slug}"

    @staticmethod
    async def _load(app_id: str) -> App:
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None or row.state == AppState.DELETED.value:
            raise AppNotFoundError(app_id=app_id)
        return row

    @classmethod
    async def _load_visible(cls, app_id: str, actor, *, entry: str = LOG_ENTRY_DETAIL) -> App:
        del entry  # A transport entry never changes the resource action requirement.
        app = await cls._load(app_id)
        return await AppAuthorizationService.authorize_loaded_app(actor, app, "management_read")

    @staticmethod
    async def _require_log_access(app: App, actor, *, entry: str) -> None:
        del entry
        await AppAuthorizationService.authorize_loaded_app(actor, app, "log_read")
