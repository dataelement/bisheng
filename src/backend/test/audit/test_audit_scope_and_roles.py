"""F056 T027 — who may use the audit query face, and how many faces there are.

Covers spec AC-33 (query **and** export are tenant-admin-and-above only; an
owner or a plain user calling either is refused) and AC-34 (the three
high-frequency event families are reached through the *same* face by the event
type filter — administrators have exactly one query entry).

The role gate is asserted through :class:`AuditLogService` rather than through
the DAO: the DAO has no notion of a caller, and the whole point of AC-33 is
that the refusal happens before any row is read. ``export_audit_log`` is
asserted separately from ``get_audit_log`` on purpose — 决议-8 makes them share
``_prepare_audit_query``, and the test that proves the sharing is the one that
runs both through the same refusal.

What the three callers stand for:

* **owner / plain user** — not ``is_admin()``, no ``log`` web menu, admin of no
  user group. Every gate says no, which is the AC-33 case.
* **user-group admin** — not a tenant admin, but administers a group. The
  legacy audit page has always let them read their own group's rows; that is
  not a hosted-application entry point and stays as it was.
* **tenant admin / log-menu role** — allowed.
"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS
from test.audit.conftest import insert_audit, make_app, make_user_payload

APP_ID = "app-scope-1"


@pytest.fixture()
def no_log_menu(monkeypatch):
    """Nobody in this file gets in through the ``log`` web menu unless asked."""
    monkeypatch.setattr(AuditLogService, "_user_has_log_web_menu", AsyncMock(return_value=False))


@pytest.fixture()
def no_group_admin(monkeypatch):
    monkeypatch.setattr("bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group", AsyncMock(return_value=[]))


def _owner():
    """An application owner — a normal user as far as the audit face is concerned."""
    return make_user_payload(user_id=501, is_admin=False, is_global_super=False)


def _tenant_admin():
    return make_user_payload(user_id=77, is_admin=True, is_global_super=False)


async def _list(user, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=2),
    ):
        return await AuditLogService.get_audit_log(
            user,
            group_ids=[],
            operator_ids=[],
            start_time=None,
            end_time=None,
            system_id=None,
            event_type=None,
            page=1,
            limit=20,
            **kwargs,
        )


async def _export(user, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=2),
    ):
        return await AuditLogService.export_audit_log(
            user,
            group_ids=[],
            operator_ids=[],
            start_time=None,
            end_time=None,
            system_id=None,
            event_type=None,
            **kwargs,
        )


class TestRoleBoundary:
    """AC-33 — tenant admin and above; owners and plain users are refused."""

    async def test_owner_is_refused_on_the_list(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, no_group_admin
    ):
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_ID, tenant_id=2)

        resp = await _list(_owner())

        assert resp.status_code == UnAuthorizedError.Code

    async def test_owner_is_refused_on_the_export(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, no_group_admin
    ):
        # The export raises rather than returning an envelope — the endpoint
        # lets the error middleware answer. What matters for AC-33 is that no
        # rows come back, not the shape of the refusal.
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_ID, tenant_id=2)

        with pytest.raises(UnAuthorizedError):
            await _export(_owner())

    async def test_owner_is_refused_on_the_object_app_selector(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, no_group_admin
    ):
        """The selector feeding the "object application" filter shares the gate.

        It is a read of the application table, so leaving it ungated would hand
        a plain user the tenant's whole hosted-application inventory — the
        filter's options are themselves audit data.
        """
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=2)]

        with pytest.raises(UnAuthorizedError):
            await AuditLogService.search_audit_apps(_owner(), "", 20)

    async def test_tenant_admin_reads_both_faces(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, no_group_admin
    ):
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=2)]
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_ID, tenant_id=2)

        listed = await _list(_tenant_admin())
        exported, total = await _export(_tenant_admin())

        assert listed["data"]["total"] == 1
        assert total == 1
        assert [row["action"] for row in exported] == ["app.publish"]

    async def test_log_menu_role_reads_without_being_an_admin(
        self, patch_audit_dao, audit_lookups, audit_session, monkeypatch, no_group_admin
    ):
        """A role carrying the ``log`` menu is the non-admin case that *is* allowed."""
        monkeypatch.setattr(AuditLogService, "_user_has_log_web_menu", AsyncMock(return_value=True))
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_ID, tenant_id=2)

        resp = await _list(make_user_payload(user_id=502, is_admin=False, is_global_super=False))

        assert resp["data"]["total"] == 1

    async def test_group_admin_keeps_its_legacy_reach_only(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, monkeypatch
    ):
        """A user-group admin is pinned to their groups, exactly as before.

        This is not a hosted-application entry: a v2 row is returned only when
        its operator is a member of the administered group (design pit 15), so
        a group admin never gains a view of the whole tenant.
        """
        from types import SimpleNamespace

        monkeypatch.setattr(
            "bisheng.api.services.audit_log.UserGroupDao.aget_user_admin_group",
            AsyncMock(return_value=[SimpleNamespace(group_id=5)]),
        )
        audit_lookups.group_users = [SimpleNamespace(group_id=5, user_id=42)]
        insert_audit(audit_session, action="app.publish", operator_id=42, group_ids=None, tenant_id=2)
        insert_audit(audit_session, action="app.stop", operator_id=99, group_ids=None, tenant_id=2)

        resp = await _list(make_user_payload(user_id=503, is_admin=False, is_global_super=False))

        assert resp["data"]["total"] == 1
        assert resp["data"]["data"][0]["operator_id"] == 42


class TestSingleQueryEntry:
    """AC-34 — one face, reached by event type; no per-family query page."""

    async def test_low_and_high_frequency_families_share_the_event_type_filter(
        self, patch_audit_dao, audit_lookups, audit_session, no_log_menu, no_group_admin
    ):
        """One low-frequency governance event and one runtime-capability event,
        same endpoint, told apart only by ``event_type``."""
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=2)]
        insert_audit(audit_session, action="app.visibility_change", target_type="app", target_id=APP_ID, tenant_id=2)
        insert_audit(
            audit_session,
            action="app.release.capability_declared",
            target_type="app_version",
            target_id="ver-1",
            audit_metadata={"app_id": APP_ID},
            tenant_id=2,
        )

        governance = await _list_with_event(_tenant_admin(), "app.visibility_change")
        capability = await _list_with_event(_tenant_admin(), "app.release.capability_declared")
        both = await _list(_tenant_admin(), target_app_id=APP_ID)

        assert governance["data"]["total"] == 1
        assert capability["data"]["total"] == 1
        assert both["data"]["total"] == 2

    def test_every_hosted_app_action_is_selectable_on_that_one_face(self):
        """An action that writes but is not on the whitelist is invisible on the
        page — 「写了查不到」, which AC-27 forbids and AC-34 depends on."""
        from bisheng.app_publish.domain.constants import AppReleaseAuditAction
        from bisheng.app_runtime.domain.constants import AppAuditAction

        missing = [
            action.value
            for action in (*AppAuditAction, *AppReleaseAuditAction)
            if action.value not in _UI_VISIBLE_V2_ACTIONS
        ]
        assert missing == []

    def test_no_second_audit_query_route_exists(self):
        """The admin's query entry is one route family.

        A per-family page (an access-record list, a model-call list) would
        satisfy "the data is somewhere" while breaking AC-34's actual promise —
        that an administrator does not have to know which page holds which
        event. Written as a route census so a new page fails here rather than
        being noticed in review.
        """
        from fastapi.routing import APIRoute

        from bisheng.main import app

        audit_reads = {
            route.path
            for route in app.routes
            if isinstance(route, APIRoute) and "GET" in route.methods and _is_audit_read(route.path)
        }
        assert audit_reads == {
            "/api/v1/audit",
            "/api/v1/audit/apps",
            "/api/v1/audit/export/data",
            "/api/v1/audit/operators",
            # Chat-session forensics: a different object (conversations), not an
            # event-type view of the audit log. Predates this feature.
            "/api/v1/audit/session",
            "/api/v1/audit/session/export/data",
        }


def _is_audit_read(path: str) -> bool:
    return path == "/api/v1/audit" or path.startswith("/api/v1/audit/")


async def _list_with_event(user, event_type: str):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=2),
    ):
        return await AuditLogService.get_audit_log(
            user,
            group_ids=[],
            operator_ids=[],
            start_time=None,
            end_time=None,
            system_id=None,
            event_type=event_type,
            page=1,
            limit=20,
        )
