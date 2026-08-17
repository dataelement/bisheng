"""T056 — ``/api/v1/apps/**`` over HTTP: paths, shapes, and refusal codes.

The domain rules are covered by the service tests. This file pins the two things
only the HTTP layer can get wrong:

* **the paths and payload shapes**, because three front-end surfaces (the card's
  version dropdown, the version tab, the CLI) consume them and must not each
  invent their own;
* **the refusal envelope**: every "you may not" answer is a 161xx code inside an
  HTTP 200 body. A real 403/404 on a GET makes the platform SPA redirect the
  whole page to ``/403`` (design pit 25), so the log tab would take the detail
  page down with it.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppState

pytestmark = pytest.mark.usefixtures("app_db", "fake_orchestrator", "fake_permission_projection", "tenant_admins")


def _data(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {"status_code", "status_message", "data"}, "every endpoint answers in the platform envelope"
    return body


class TestVersions:
    async def test_versions_endpoint_path_and_shape(self, api_app, app_db, app_factory, app_owner):
        """AC-52 — the path and the row shape are defined *here*.

        The card dropdown, the version tab and the CLI all read this one
        endpoint; letting each derive its own shape is how ``version_list`` from
        ``FlowVersionDao`` ended up wired to a hosted app in the first place
        (pit 13).
        """
        from bisheng.database.models.app_version import VERSION_KIND_ITERATION, AppVersion, AppVersionDao

        app, _first = await app_factory(state=AppState.ONLINE.value)

        async def _add_second():
            async with app_db() as session:
                row = AppVersion(
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
                await AppVersionDao.ainsert(session, row)
                await session.commit()

        await _add_second()

        body = _data(await api_app(app_owner.payload).get(f"/api/v1/apps/{app.id}/versions"))

        rows = body["data"]
        assert [row["version_no"] for row in rows] == [2, 1]
        assert set(rows[0]) == {
            "version_id",
            "version_no",
            "kind",
            "terminal_state",
            "submitted_at",
            "is_current",
            "is_pending",
        }

    async def test_versions_endpoint_non_owner_gets_business_code_not_403(self, api_app, app_factory, normal_user):
        """Pit 25 — an HTTP 403 here would navigate the SPA away from the page."""
        app, _ = await app_factory()
        body = _data(await api_app(normal_user.payload).get(f"/api/v1/apps/{app.id}/versions"))
        assert body["status_code"] == 16106


class TestStateActions:
    async def test_stop_resume_happy_path_and_audit(self, api_app, app_factory, app_owner, audit_sink):
        """AC-41 — both directions, and both leave an audit row naming the operator."""
        from bisheng.app_runtime.domain.constants import AppAuditAction

        app, _ = await app_factory(state=AppState.ONLINE.value)
        client = api_app(app_owner.payload)

        stopped = _data(await client.post(f"/api/v1/apps/{app.id}/actions/stop"))["data"]
        assert stopped["state"] == AppState.STOPPED.value and stopped["ok"] is True

        resumed = _data(await client.post(f"/api/v1/apps/{app.id}/actions/resume"))["data"]
        assert resumed["state"] == AppState.ONLINE.value

        actions = [row["action"] for row in audit_sink]
        assert actions == [AppAuditAction.STOP.value, AppAuditAction.RESUME.value]
        assert all(row["operator_id"] == app_owner.user_id for row in audit_sink)

    async def test_publish_capacity_shortage_returns_pending_with_reason(
        self, api_app, app_factory, app_owner, fake_orchestrator
    ):
        """AC-65 — a refused start is a 200 carrying the state and the cause; the
        page has to render "待上线(资源不足)" and say why."""
        fake_orchestrator.responses["admission"] = {
            "admitted": False,
            "reason": "mem_available",
            "snapshot": {"mem_available_mb": 500},
        }
        app, _ = await app_factory(state=AppState.DRAFT.value)

        body = _data(await api_app(app_owner.payload).post(f"/api/v1/apps/{app.id}/actions/publish"))

        assert body["status_code"] == 200, "a parked publish is a handled outcome, not an error"
        assert body["data"]["state"] == AppState.PENDING_CAPACITY.value
        assert body["data"]["ok"] is False and body["data"]["reason"] == "mem_available"
        assert body["data"]["detail"]["snapshot"]["mem_available_mb"] == 500

    async def test_delete_online_returns_16104(self, api_app, app_factory, app_owner):
        app, _ = await app_factory(state=AppState.ONLINE.value)
        body = _data(await api_app(app_owner.payload).delete(f"/api/v1/apps/{app.id}"))
        assert body["status_code"] == 16104

    async def test_delete_non_owner_returns_16105(self, api_app, app_factory, tenant_admins):
        """AC-44 — owner only, and a tenant administrator is *not* the owner."""
        from bisheng.common.dependencies.user_deps import UserPayload

        app, _ = await app_factory(state=AppState.STOPPED.value)
        admin = UserPayload(user_id=90888, user_name="admin", user_role=[], tenant_id=1, is_global_super=False)
        tenant_admins.grant(admin.user_id, app.tenant_id)

        body = _data(await api_app(admin).delete(f"/api/v1/apps/{app.id}"))
        assert body["status_code"] == 16105

    async def test_delete_owner_success_and_hook_called(self, api_app, app_factory, app_owner):
        """AC-43 — deletion fans out to F055's "cancel the in-flight approval" hook."""
        from bisheng.app_runtime.domain.services import lifecycle_hooks

        seen = []

        async def _hook(**kwargs):
            seen.append(kwargs)

        lifecycle_hooks.clear_app_deleted_hooks()
        lifecycle_hooks.register_app_deleted_hook(_hook)
        try:
            app, _ = await app_factory(state=AppState.STOPPED.value)
            body = _data(await api_app(app_owner.payload).delete(f"/api/v1/apps/{app.id}"))
        finally:
            lifecycle_hooks.clear_app_deleted_hooks()

        assert body["data"]["state"] == AppState.DELETED.value
        assert [call["app_id"] for call in seen] == [app.id]


class TestReads:
    async def test_meta_patch_no_version_no_state_change(self, api_app, app_db, app_factory, app_owner):
        """AC-06 — the PATCH and F055's pipeline share one implementation."""
        from bisheng.database.models.app_version import AppVersionDao

        app, _ = await app_factory(state=AppState.ONLINE.value)

        async def _count():
            async with app_db() as session:
                return len(await AppVersionDao.alist_by_app(session, app.id))

        before = await _count()
        body = _data(
            await api_app(app_owner.payload).patch(
                f"/api/v1/apps/{app.id}", json={"name": "Renamed", "logo": "apps/a/icon.png"}
            )
        )

        assert body["data"]["name"] == "Renamed" and body["data"]["state"] == AppState.ONLINE.value
        assert body["data"]["logo"] == "apps/a/icon.png", "an object name, not a presigned URL"
        assert await _count() == before

    async def test_logs_non_owner_gets_16161_not_403(self, api_app, app_factory, normal_user):
        app, _ = await app_factory(state=AppState.ONLINE.value)
        body = _data(await api_app(normal_user.payload).get(f"/api/v1/apps/{app.id}/logs"))
        assert body["status_code"] == 16161

    async def test_detail_returns_entry_url(self, api_app, app_factory, app_owner):
        app, _ = await app_factory(slug="entry-app", state=AppState.ONLINE.value)
        body = _data(await api_app(app_owner.payload).get(f"/api/v1/apps/{app.id}"))
        assert body["data"]["entry_url"].endswith("/apps/entry-app")

    async def test_cross_tenant_app_id_returns_16101(self, api_app, app_factory, sub_tenant, app_owner):
        """Explicit tenant check on top of the auto filter — and the same answer as
        "does not exist", so an app id is not an existence oracle."""
        theirs, _ = await app_factory(tenant_id=sub_tenant.tenant_id, owner_user_id=sub_tenant.admin_user_id)
        body = _data(await api_app(app_owner.payload).get(f"/api/v1/apps/{theirs.id}"))
        assert body["status_code"] == 16101

    async def test_runtime_status_requires_super_admin(self, api_app, app_owner):
        body = _data(await api_app(app_owner.payload).get("/api/v1/apps/runtime-status"))
        assert body["status_code"] == 16106

    async def test_runtime_status_path_wins_over_the_app_id_pattern(self, api_app):
        """Starlette matches in declaration order: the static path must be declared
        first, or this page becomes a lookup for an app named "runtime-status"."""
        from bisheng.common.dependencies.user_deps import UserPayload

        superuser = UserPayload(user_id=90999, user_name="root", user_role=[], tenant_id=1, is_global_super=True)
        body = _data(await api_app(superuser).get("/api/v1/apps/runtime-status"))
        assert body["data"]["supported_runtimes"] == ["python3.11"]


class TestEnvelope:
    async def test_all_endpoints_return_unified_response_model(self, api_app, app_factory, app_owner):
        """Every route answers ``{status_code, status_message, data}``.

        The one deliberate exception is ``/apps/_unavailable``, which is raw HTML
        because nginx serves it straight to a browser when app-proxy is down.
        """
        app, _ = await app_factory(state=AppState.ONLINE.value)
        client = api_app(app_owner.payload)

        for method, path in (
            ("get", f"/api/v1/apps/{app.id}"),
            ("get", f"/api/v1/apps/{app.id}/instance"),
            ("get", f"/api/v1/apps/{app.id}/logs"),
            ("get", f"/api/v1/apps/{app.id}/versions"),
            ("get", "/api/v1/apps"),
            ("post", f"/api/v1/apps/{app.id}/actions/stop"),
            ("post", f"/api/v1/apps/{app.id}/actions/resume"),
            ("post", f"/api/v1/apps/{app.id}/actions/manual-publish"),
        ):
            _data(await getattr(client, method)(path))
