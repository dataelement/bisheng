"""T054 — the read side: detail, instance, logs, runtime status, versions, list.

Two things this file is really guarding:

* **Answers, not HTTP statuses.** Everything a management surface refuses must
  come back as a 161xx business code inside a 200 envelope, because the platform
  request interceptor turns a GET answered with 403/404 into a full-page
  redirect (design pit 25). A test that only asserted "raises" would pass with
  the wrong exception class.
* **One log scope, three doors.** The detail tab, ``bisheng logs`` (F053) and the
  MCP tool must see the *same* lines; only who may open each door differs.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppState
from bisheng.common.errcode.app_factory import (
    AppLogForbiddenError,
    AppManageForbiddenError,
    AppNotFoundError,
    AppOrchestratorUnavailableError,
)

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator")


def _super_admin_payload(user_id: int = 90999):
    from bisheng.common.dependencies.user_deps import UserPayload

    return UserPayload(user_id=user_id, user_name="f054-super", user_role=[], tenant_id=1, is_global_super=True)


class TestDetail:
    async def test_detail_returns_entry_url_from_backend_config(self, app_db, app_factory, app_owner, monkeypatch):
        """AC-25 — the backend returns the **full** address.

        The front end must not build it from ``location.origin``: in dev that is
        :3001 and ``/apps`` is not in the vite proxy, so the link would point at
        a page that does not exist.
        """
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
        from bisheng.common.services.config_service import settings

        monkeypatch.setattr(settings.app_runtime, "entry_base_url", "https://bisheng.example.com/", raising=False)
        app, _ = await app_factory(slug="my-app", state=AppState.ONLINE.value)

        detail = await AppQueryService.get_detail(app.id, actor=app_owner.payload)

        assert detail["entry_url"] == "https://bisheng.example.com/apps/my-app"
        assert detail["slug"] == "my-app" and detail["state"] == AppState.ONLINE.value
        assert detail["owner_user_id"] == app_owner.user_id

    async def test_detail_falls_back_to_a_relative_entry_path(self, app_db, app_factory, app_owner, monkeypatch):
        """An unconfigured deployment still gets a usable link, just a relative one."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
        from bisheng.common.services.config_service import settings

        monkeypatch.setattr(settings.app_runtime, "entry_base_url", "", raising=False)
        app, _ = await app_factory(slug="rel-app")

        assert (await AppQueryService.get_detail(app.id, actor=app_owner.payload))["entry_url"] == "/apps/rel-app"

    async def test_detail_denied_for_unrelated_user(self, app_db, app_factory, normal_user, tenant_admins):
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory()
        with pytest.raises(AppManageForbiddenError):
            await AppQueryService.get_detail(app.id, actor=normal_user.payload)

    async def test_cross_tenant_app_id_is_not_found(self, app_db, app_factory, sub_tenant, app_owner):
        """Explicit tenant check on top of the auto filter: the listener rewrites
        SELECTs only, and a management read must not depend on that alone."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        theirs, _ = await app_factory(tenant_id=sub_tenant.tenant_id, owner_user_id=sub_tenant.admin_user_id)
        with pytest.raises(AppNotFoundError):
            await AppQueryService.get_detail(theirs.id, actor=app_owner.payload)


class TestInstance:
    async def test_instance_status_shape(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-23 — the shape-neutral instance view, straight from the manager."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, version = await app_factory(state=AppState.ONLINE.value)
        fake_orchestrator.responses["status"] = {
            "instance_id": "bisheng-app-x",
            "phase": "running",
            "health": "healthy",
            "current_version_id": version.id,
            "started_at": "2026-08-17T00:00:00Z",
            "restart_count": 2,
            "last_probe_at": None,
        }

        status = await AppQueryService.get_instance(app.id, actor=app_owner.payload)

        assert set(status) >= {
            "instance_id",
            "phase",
            "health",
            "current_version_id",
            "started_at",
            "restart_count",
            "last_probe_at",
        }
        assert status["phase"] == "running" and status["restart_count"] == 2

    async def test_missing_instance_is_not_an_error(self, app_db, app_factory, app_owner, fake_orchestrator):
        """A stopped app has no instance; the detail page still renders."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        fake_orchestrator.responses["status"] = AppNotFoundError()
        app, _ = await app_factory(state=AppState.STOPPED.value)

        status = await AppQueryService.get_instance(app.id, actor=app_owner.payload)
        assert status["phase"] == "stopped" and status["instance_id"] is None

    async def test_dead_orchestrator_is_not_reported_as_deleted(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """Contract §2 — "the backend is down" and "the instance is gone" are two
        answers. Merging them makes a dockerd restart read as "app deleted"."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        fake_orchestrator.responses["status"] = AppOrchestratorUnavailableError()
        app, _ = await app_factory(state=AppState.ONLINE.value)

        with pytest.raises(AppOrchestratorUnavailableError):
            await AppQueryService.get_instance(app.id, actor=app_owner.payload)


class TestLogs:
    async def test_logs_scope_identical_across_three_entries(self, app_db, app_factory, app_owner, fake_orchestrator):
        """AC-23 / AC-55 — detail tab, CLI (F053) and MCP tool (F052) read the
        same lines through the same call; only the door differs."""
        from bisheng.app_runtime.domain.services.app_query_service import (
            LOG_ENTRY_CLI,
            LOG_ENTRY_DETAIL,
            LOG_ENTRY_MCP,
            AppQueryService,
        )

        fake_orchestrator.responses["logs"] = {"lines": ["boot", "ready"]}
        app, _ = await app_factory(state=AppState.ONLINE.value)

        results = [
            await AppQueryService.get_logs(app.id, actor=app_owner.payload, tail=100, keyword="e", entry=entry)
            for entry in (LOG_ENTRY_DETAIL, LOG_ENTRY_CLI, LOG_ENTRY_MCP)
        ]

        assert [result["lines"] for result in results] == [["boot", "ready"]] * 3
        issued = [kwargs for name, kwargs in fake_orchestrator.calls if name == "logs"]
        assert len({tuple(sorted(kwargs.items(), key=str)) for kwargs in issued}) == 1

    async def test_logs_visible_to_owner_and_tenant_admin_only(
        self, app_db, app_factory, app_owner, normal_user, tenant_admins
    ):
        """AC-55 — a business pre-check, not an F048 check: the permission runtime
        short-circuits administrators to ALLOW, so it cannot express this."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory(state=AppState.ONLINE.value)
        admin = _super_admin_payload(90888)
        admin.is_global_super = False
        tenant_admins.grant(admin.user_id, app.tenant_id)

        assert await AppQueryService.get_logs(app.id, actor=app_owner.payload) is not None
        assert await AppQueryService.get_logs(app.id, actor=admin) is not None
        with pytest.raises(AppLogForbiddenError):
            await AppQueryService.get_logs(app.id, actor=normal_user.payload)

    async def test_logs_denied_returns_business_code_not_403(self, app_db, app_factory, normal_user, tenant_admins):
        """Pit 25 — 403 on a GET makes the platform SPA navigate away from the page."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        app, _ = await app_factory()
        with pytest.raises(AppLogForbiddenError) as excinfo:
            await AppQueryService.get_logs(app.id, actor=normal_user.payload)
        assert excinfo.value.code == 16161
        assert excinfo.value.code not in (403, 404)

    async def test_cli_and_mcp_entries_are_owner_only(self, app_db, app_factory, tenant_admins):
        """A credential acts for its resource owner; a tenant admin's key must not
        widen it to every app in the tenant (open-API boundary)."""
        from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_CLI, AppQueryService

        app, _ = await app_factory()
        admin = _super_admin_payload(90888)
        admin.is_global_super = False
        tenant_admins.grant(admin.user_id, app.tenant_id)

        with pytest.raises(AppLogForbiddenError):
            await AppQueryService.get_logs(app.id, actor=admin, entry=LOG_ENTRY_CLI)

    async def test_logs_no_platform_side_logs_and_has_empty_state(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """AC-55 / D14-B — the platform stores no logs of its own (zero collector,
        zero retention cost); "no output yet" is an empty list, not an error."""
        import sqlmodel

        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        fake_orchestrator.responses["logs"] = {"lines": []}
        app, _ = await app_factory(state=AppState.ONLINE.value)

        result = await AppQueryService.get_logs(app.id, actor=app_owner.payload)
        assert result["lines"] == []

        # ``app_access_log`` is not a runtime log: it is the AC-38 access
        # record (who entered, when) that the same D14-B decision *does* put in
        # a table. What must stay absent is any store of application output.
        tables = set(sqlmodel.SQLModel.metadata.tables) - {"app_access_log"}
        assert not {name for name in tables if name.startswith("app_") and "log" in name}

    async def test_owner_only_entries_refuse_a_root_tenant_app_from_a_leaf_key(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """The owner-only doors compare the tenant too — owner equality is not enough.

        ``/api/v2`` seeds ``visible_tenant_ids`` as ``{root, credential tenant}``,
        so the automatic filter hands a **Root-tenant** application to a
        child-tenant key; and under D19 a token survives its holder moving
        tenants, so ``owner_user_id`` still matches on the app they left behind.
        ``get_logs`` reaches the check through ``_load`` rather than
        ``_load_visible``, so without this comparison ``bisheng logs`` reads a
        Root application the platform face already answers 16101 for.
        """
        from bisheng.app_runtime.domain.services.app_query_service import (
            LOG_ENTRY_CLI,
            LOG_ENTRY_MCP,
            AppQueryService,
        )
        from bisheng.common.dependencies.user_deps import UserPayload

        from .conftest import ROOT_TENANT_ID, SUB_TENANT_ID

        app, _ = await app_factory(state=AppState.ONLINE.value)
        assert app.tenant_id == ROOT_TENANT_ID and app.owner_user_id == app_owner.user_id
        moved_owner = UserPayload(
            user_id=app_owner.user_id,
            user_name=app_owner.user_name,
            user_role=[],
            tenant_id=SUB_TENANT_ID,
            is_global_super=False,
        )

        for entry in (LOG_ENTRY_CLI, LOG_ENTRY_MCP):
            with pytest.raises(AppNotFoundError) as excinfo:
                await AppQueryService.get_logs(app.id, actor=moved_owner, entry=entry)
            # Same code a genuinely missing app gets: a caller must not learn
            # the application exists in a tenant they cannot see.
            assert excinfo.value.code == 16101
        assert not [name for name, _kwargs in fake_orchestrator.calls if name == "logs"]

    async def test_owner_only_entries_still_serve_the_owner_inside_one_leaf_tenant(
        self, app_db, app_factory, app_owner, fake_orchestrator
    ):
        """The guard is a tenant *comparison*, not a "root only" rule: an app and a
        key that live in the same child tenant are the ordinary case and pass."""
        from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_CLI, AppQueryService
        from bisheng.common.dependencies.user_deps import UserPayload

        from .conftest import SUB_TENANT_ID

        fake_orchestrator.responses["logs"] = {"lines": ["ready"]}
        app, _ = await app_factory(state=AppState.ONLINE.value, tenant_id=SUB_TENANT_ID)
        owner_in_leaf = UserPayload(
            user_id=app_owner.user_id,
            user_name=app_owner.user_name,
            user_role=[],
            tenant_id=SUB_TENANT_ID,
            is_global_super=False,
        )

        result = await AppQueryService.get_logs(app.id, actor=owner_in_leaf, entry=LOG_ENTRY_CLI)
        assert result["lines"] == ["ready"]

    async def test_owner_only_entries_refuse_leaf_to_leaf_as_well(self, app_db, app_factory, app_owner):
        """Leaf-to-leaf is already shut out by the ``visible_tenant_ids`` IN-list
        one layer down; asserted here so the service answers the same 16101 on
        its own, rather than depending on a filter that a call path without
        tenant context would not have injected."""
        from bisheng.app_runtime.domain.services.app_query_service import LOG_ENTRY_CLI, AppQueryService
        from bisheng.common.dependencies.user_deps import UserPayload

        from .conftest import SUB_TENANT_ID

        app, _ = await app_factory(state=AppState.ONLINE.value, tenant_id=SUB_TENANT_ID)
        other_leaf_owner = UserPayload(
            user_id=app_owner.user_id,
            user_name=app_owner.user_name,
            user_role=[],
            tenant_id=SUB_TENANT_ID + 1,
            is_global_super=False,
        )

        with pytest.raises(AppNotFoundError):
            await AppQueryService.get_logs(app.id, actor=other_leaf_owner, entry=LOG_ENTRY_CLI)


class TestRuntimeStatus:
    async def test_runtime_status_superadmin_only(self, app_db, app_owner, tenant_admins, fake_orchestrator):
        """AC-23 — one endpoint, both deployment shapes, super admin only."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        status = await AppQueryService.get_runtime_status(actor=_super_admin_payload())
        assert status["backend_available"] is True and status["supported_runtimes"] == ["python3.11"]

        with pytest.raises(AppManageForbiddenError):
            await AppQueryService.get_runtime_status(actor=app_owner.payload)


class TestVersionsAndList:
    async def test_version_list_readonly_source_not_flow_version(self, app_db, app_factory, app_owner):
        """AC-52 / pit 13 — the dropdown reads ``app_version``.

        ``add_extra_field``'s ``version_list`` comes from ``FlowVersionDao`` and
        is empty for a hosted app; reusing the workflow component against it
        would offer a "switch version" control that edits a *workflow*.
        """
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService
        from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

        app, _first = await app_factory(state=AppState.ONLINE.value)
        async with app_db() as session:
            second = AppVersion(
                app_id=app.id,
                version_no=2,
                kind=VERSION_KIND_ITERATION,
                code_object_key="apps/x/v2/code.tar.gz",
                manifest={},
                capabilities={},
                injections={},
                tier_id="light",
                runtime="python3.11",
            )
            await AppVersionDao.ainsert(session, second)
            await session.commit()
            second_id = second.id

        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        await AppStateService.stage_version(app.id, second_id)

        versions = await AppQueryService.list_versions(app.id, actor=app_owner.payload)

        assert [row["version_no"] for row in versions] == [2, 1], "newest first"
        assert set(versions[0]) == {
            "version_id",
            "version_no",
            "kind",
            "terminal_state",
            "submitted_at",
            "is_current",
            "is_pending",
        }
        assert versions[0]["is_pending"] is True and versions[1]["is_current"] is True
        assert all(not name.startswith("switch") and not name.startswith("rollback") for name in dir(AppQueryService))

    async def test_owner_list_filter_and_tenant_admin_scope(
        self, app_db, app_factory, app_owner, normal_user, tenant_admins, sub_tenant
    ):
        """AC-57 — an owner sees their own; a tenant administrator sees the tenant's."""
        from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

        mine, _ = await app_factory(owner_user_id=app_owner.user_id)
        theirs, _ = await app_factory(owner_user_id=normal_user.user_id)
        other_tenant, _ = await app_factory(tenant_id=sub_tenant.tenant_id, owner_user_id=sub_tenant.admin_user_id)

        owned = await AppQueryService.list_apps(actor=app_owner.payload)
        assert {row["app_id"] for row in owned} == {mine.id}

        admin = _super_admin_payload(90888)
        admin.is_global_super = False
        tenant_admins.grant(admin.user_id, 1)
        scoped = await AppQueryService.list_apps(actor=admin)
        assert {row["app_id"] for row in scoped} == {mine.id, theirs.id}
        assert other_tenant.id not in {row["app_id"] for row in scoped}
