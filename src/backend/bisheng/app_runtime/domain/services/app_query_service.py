"""The read side of a hosted application: detail, instance, logs, versions, list.

Writes nothing. What it does own is the **permission dispatch by entry**, which
is easy to get wrong in a way that only shows up as a security bug:

* the platform detail page is *owner or this tenant's administrator or super
  admin* — the people who operate the app;
* the CLI (F053) and the MCP tools (F052) are *owner only*, because they run on
  a credential that acts for its resource owner. Letting an administrator's key
  read every app's logs would quietly widen the open-API surface past what the
  credential's holder was granted.

Both rules are **business pre-checks**, not F048 checks: the permission runtime
short-circuits administrators to ALLOW, so it cannot express either of them
(constitution C4 note).

Refusals raise 161xx business codes, never HTTP 403/404. The platform request
interceptor turns a GET answered with those statuses into a full-page redirect
to ``/403``, so a user without log access would lose the whole detail page
instead of one tab (design pit 25).
"""

from __future__ import annotations

from typing import Any

from bisheng.app_runtime.domain.constants import AppState
from bisheng.app_runtime.domain.services.orchestrator_client import orchestrator_client
from bisheng.common.errcode.app_factory import (
    AppLogForbiddenError,
    AppManageForbiddenError,
    AppNotFoundError,
)
from bisheng.common.permission_identity import check_tenant_admin
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.app import App, AppDao
from bisheng.database.models.app_instance import PHASE_STOPPED, AppInstanceDao
from bisheng.database.models.app_version import AppVersionDao

#: Which door the caller came through. The *content* is identical for all three
#: (AC-55); only the admission rule differs — see the module docstring.
LOG_ENTRY_DETAIL = "detail"
LOG_ENTRY_CLI = "cli"
LOG_ENTRY_MCP = "mcp"

#: Entries that act on a credential rather than a session, and are therefore
#: bounded by the credential's resource owner.
_OWNER_ONLY_ENTRIES = frozenset({LOG_ENTRY_CLI, LOG_ENTRY_MCP})


class AppQueryService:
    """Read-only projections of one hosted application, or of a caller's set of them."""

    # -- detail ---------------------------------------------------------

    @classmethod
    async def get_detail(cls, app_id: str, *, actor) -> dict[str, Any]:
        app = await cls._load_visible(app_id, actor)
        return cls._detail_payload(app)

    @classmethod
    async def get_instance(cls, app_id: str, *, actor) -> dict[str, Any]:
        """Live instance view (AC-23).

        "No instance" and "the orchestration backend is down" are deliberately
        two different answers: collapsing them would make every dockerd restart
        render as "this application was deleted" (contract §2).
        """
        app = await cls._load_visible(app_id, actor)
        try:
            return await orchestrator_client.status(app_id=app.id)
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
        return [
            {
                "version_id": row.id,
                "version_no": row.version_no,
                "kind": row.kind,
                "terminal_state": row.terminal_state,
                "submitted_at": row.submitted_at,
                "is_current": row.id == app.current_version_id,
                "is_pending": row.id == app.pending_version_id,
            }
            for row in rows
        ]

    @classmethod
    async def list_apps(cls, *, actor, tenant_id: int | None = None) -> list[dict[str, Any]]:
        """AC-57 — an owner's own apps, or a tenant administrator's whole tenant.

        The tenant predicate is written out rather than left to the auto filter:
        that listener rewrites SELECTs only, and a management list that silently
        depended on it would return the wrong set the day it runs on a code path
        without tenant context.
        """
        scope_tenant = int(tenant_id if tenant_id is not None else getattr(actor, "tenant_id", 0) or 0)
        user_id = int(getattr(actor, "user_id", 0) or 0)
        is_admin = bool(getattr(actor, "is_global_super", False)) or await check_tenant_admin(user_id, scope_tenant)
        async with get_async_db_session() as session:
            rows = (
                await AppDao.alist_by_tenant(session, scope_tenant)
                if is_admin
                else await AppDao.alist_by_owner(session, user_id)
            )
        return [
            cls._detail_payload(row)
            for row in rows
            if row.state != AppState.DELETED.value and int(row.tenant_id or 0) == scope_tenant
        ]

    # -- runtime status --------------------------------------------------

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
    def _detail_payload(app: App) -> dict[str, Any]:
        return {
            "app_id": app.id,
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

        Built here, never in the browser: the platform SPA runs on :3001 in dev
        and ``/apps`` is not in its vite proxy, so a front end that composed
        ``location.origin + '/apps/' + slug`` would hand out a dead link.
        """
        base = (settings.app_runtime.entry_base_url or "").rstrip("/")
        return f"{base}/apps/{slug}"

    @staticmethod
    async def _load(app_id: str) -> App:
        async with get_async_db_session() as session:
            row = await AppDao.aget(session, app_id)
        if row is None or row.state == AppState.DELETED.value:
            raise AppNotFoundError(app_id=app_id)
        set_current_tenant_id(int(row.tenant_id or 0))
        return row

    @classmethod
    async def _load_visible(cls, app_id: str, actor) -> App:
        app = await cls._load(app_id)
        user_id = int(getattr(actor, "user_id", 0) or 0)
        actor_tenant = int(getattr(actor, "tenant_id", 0) or 0)
        is_super = bool(getattr(actor, "is_global_super", False))
        if int(app.tenant_id or 0) != actor_tenant and not is_super:
            # Same answer as "does not exist": telling a caller that an app they
            # cannot see exists in another tenant is the leak AC-29 forbids on
            # the entry path, and it applies to the API surface too.
            raise AppNotFoundError(app_id=app_id)
        if user_id == int(app.owner_user_id or 0) or is_super:
            return app
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return app
        raise AppManageForbiddenError(app_id=app_id)

    @staticmethod
    async def _require_log_access(app: App, actor, *, entry: str) -> None:
        user_id = int(getattr(actor, "user_id", 0) or 0)
        if user_id == int(app.owner_user_id or 0):
            return
        if entry in _OWNER_ONLY_ENTRIES:
            raise AppLogForbiddenError(app_id=app.id, entry=entry)
        if bool(getattr(actor, "is_global_super", False)):
            return
        if await check_tenant_admin(user_id, int(app.tenant_id or 0)):
            return
        raise AppLogForbiddenError(app_id=app.id, entry=entry)
