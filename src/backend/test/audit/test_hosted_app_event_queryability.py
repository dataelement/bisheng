"""F056 T028 — every GOV-04 event a writer lands must be findable on the page.

F056 writes exactly one event type of its own (``app.visibility_change``); the
rest are written by F054 / F055 / F049 / F051. What this Feature owes is the
other half — *registration and queryability*: an event that reaches the table
and cannot be selected on the audit page is an F056 defect, not the writer's
(spec §5 「写了必须查得到」, AC-27).

So each case here takes a row **shaped the way its writer actually shapes it**
and asserts the three things that make it reachable:

1. the action is on ``_UI_VISIBLE_V2_ACTIONS`` — otherwise the page's own
   predicate filters it out before any user filter runs;
2. the 「对象应用」 filter finds it — both row shapes exist (``target_type='app'``
   for the state machine, ``metadata.app_id`` for the release pipeline);
3. the 「事件类型」 filter finds it on its own.

Plus AC-26 for all of them at once: the projection must not carry the raw
``metadata`` blob, and no key plaintext may appear anywhere in a response.

Covers AC-18, AC-19, AC-20, AC-21, AC-23, AC-24, AC-25, AC-26.

**Two known gaps are marked, not hidden.** Access records (AC-24) live in
``app_access_log``, a table with no query face at all, and per-call model
records (AC-25) are F051's and not on this branch yet. Both are written as
``xfail(strict=True)`` so the day the face lands the sentinel turns red and has
to be deleted — the same device T015 used for the ``app.release.*`` frontend
gap, which is how that gap got closed instead of being narrated.
"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.services.audit_log import AuditLogService
from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS, AuditLogDao
from test.audit.conftest import insert_audit, make_app, make_credential, make_user_payload

APP_ID = "app-query-1"
TENANT = 2

#: (AC, label, action, row kwargs) for every event family that lands in
#: ``auditlog`` today. ``metadata`` values mirror what the writer stamps.
EVENT_TABLE = [
    (
        "AC-18",
        "CLI first import",
        "app.release.submit",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID, "version_no": 1}},
    ),
    (
        "AC-19",
        "version created",
        "app.release.version_created",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID, "version_no": 1}},
    ),
    (
        "AC-19",
        "precheck failed",
        "app.release.precheck_failed",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "scan blocked",
        "app.release.scan_blocked",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "approval created",
        "app.release.approval_created",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID, "version_no": 2}},
    ),
    # The four approval terminal states. 决议-1 keeps them in the release
    # family rather than mirroring approval-centre rows, and the object-app
    # filter has to reach all four or "trace by application" stops at the gate.
    (
        "AC-19",
        "approval approved",
        "app.release.approved",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "approval rejected",
        "app.release.rejected",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "owner withdrew",
        "app.release.withdrawn",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "cancelled by delete",
        "app.release.cancelled",
        {"target_type": "app_version", "target_id": "ver-1", "audit_metadata": {"app_id": APP_ID}},
    ),
    (
        "AC-19",
        "pending online (capacity / start failure)",
        "app.publish_pending",
        {"target_type": "app", "target_id": APP_ID, "reason": "capacity"},
    ),
    ("AC-19", "manual publish", "app.manual_publish", {"target_type": "app", "target_id": APP_ID}),
    ("AC-19", "online", "app.publish", {"target_type": "app", "target_id": APP_ID}),
    ("AC-20", "stop", "app.stop", {"target_type": "app", "target_id": APP_ID}),
    ("AC-20", "resume", "app.resume", {"target_type": "app", "target_id": APP_ID}),
    ("AC-21", "delete", "app.delete", {"target_type": "app", "target_id": APP_ID}),
    ("AC-23", "meta update", "app.meta_update", {"target_type": "app", "target_id": APP_ID}),
    ("AC-25", "capability declared", "app.release.capability_declared", {"audit_metadata": {"app_id": APP_ID}}),
    ("AC-25", "data row edit", "app.data_row_edit", {"target_type": "app", "target_id": APP_ID}),
    ("AC-25", "data export", "app.data_export", {"target_type": "app", "target_id": APP_ID}),
    ("AC-22", "visibility change", "app.visibility_change", {"target_type": "app", "target_id": APP_ID}),
]

#: F049's key lifecycle. Not object-app rows — a key belongs to a service
#: account, not to one application — so they are asserted on the event-type
#: axis only (AC-25).
KEY_EVENT_ACTIONS = ["open_api.api_key.issue", "open_api.api_key.update", "open_api.api_key.revoke"]


@pytest.fixture()
def admin():
    return make_user_payload(user_id=77, is_admin=True, is_global_super=False)


@pytest.fixture(autouse=True)
def _no_log_menu_lookup(monkeypatch):
    """The role gate is T027's subject; here every caller is an admin already."""
    monkeypatch.setattr(AuditLogService, "_user_has_log_web_menu", AsyncMock(return_value=False))


async def _query(user, **kwargs):
    with (
        patch("bisheng.api.services.audit_log.get_admin_scope_tenant_id", return_value=None),
        patch("bisheng.api.services.audit_log.get_current_tenant_id", return_value=TENANT),
    ):
        return await AuditLogService.get_audit_log(
            user,
            group_ids=[],
            operator_ids=[],
            start_time=None,
            end_time=None,
            system_id=None,
            event_type=kwargs.pop("event_type", None),
            page=1,
            limit=50,
            **kwargs,
        )


class TestEventsAreRegistered:
    @pytest.mark.parametrize(
        "ac,label,action",
        [(ac, label, action) for ac, label, action, _ in EVENT_TABLE],
        ids=[f"{ac}-{label}" for ac, label, _, _ in EVENT_TABLE],
    )
    def test_action_is_on_the_page_whitelist(self, ac, label, action):
        assert action in _UI_VISIBLE_V2_ACTIONS

    @pytest.mark.parametrize("action", KEY_EVENT_ACTIONS)
    def test_key_lifecycle_actions_are_on_the_whitelist(self, action):
        """AC-25. The issue event used to be written as
        ``open_api.api_key.create`` while every registry said ``issue`` — the
        row landed and the page could never show it."""
        assert action in _UI_VISIBLE_V2_ACTIONS

    def test_the_issue_writer_uses_the_registered_name(self):
        """Guard the writer itself, not only the registry.

        The registry half of the lockstep is checked by
        ``test_audit_action_registry_lockstep``; nothing checked that the code
        which writes key issuance spells the action the same way.
        """
        import inspect

        from bisheng.open_api.domain.services.credential_service import CredentialService

        source = inspect.getsource(CredentialService.issue)
        assert '"open_api.api_key.issue"' in source
        assert "open_api.api_key.create" not in source


class TestEventsAreQueryable:
    @pytest.mark.parametrize(
        "ac,label,action,row",
        EVENT_TABLE,
        ids=[f"{ac}-{label}" for ac, label, _, _ in EVENT_TABLE],
    )
    async def test_reachable_by_object_app_and_by_event_type(
        self, patch_audit_dao, audit_lookups, audit_session, admin, ac, label, action, row
    ):
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=TENANT)]
        insert_audit(audit_session, action=action, tenant_id=TENANT, object_name="Alpha", **row)
        # A second application's row of the same type must not come along.
        other = dict(row)
        if other.get("target_id") == APP_ID:
            other["target_id"] = "app-other"
        if isinstance(other.get("audit_metadata"), dict):
            other["audit_metadata"] = {**other["audit_metadata"], "app_id": "app-other"}
        insert_audit(audit_session, action=action, tenant_id=TENANT, **other)

        by_app = await _query(admin, target_app_id=APP_ID)
        by_type = await _query(admin, event_type=action)

        assert by_app["data"]["total"] == 1, f"{label}: object-app filter missed the row"
        assert by_app["data"]["data"][0]["action"] == action
        assert by_type["data"]["total"] == 2, f"{label}: event-type filter missed rows"

    @pytest.mark.parametrize("action", KEY_EVENT_ACTIONS)
    async def test_key_events_reachable_by_event_type(
        self, patch_audit_dao, audit_lookups, audit_session, admin, action
    ):
        insert_audit(
            audit_session,
            action=action,
            tenant_id=TENANT,
            target_type="api_credential",
            target_id="31",
            operator_id=0,
            operator_name="ci-bot",
            audit_metadata={"credential_id": 31, "actor_kind": "service_account"},
        )

        resp = await _query(admin, event_type=action)

        assert resp["data"]["total"] == 1

    async def test_deleted_application_keeps_its_whole_history(
        self, patch_audit_dao, audit_lookups, audit_session, admin
    ):
        """AC-21. The application row is gone; every event about it stays, and
        the object column falls back to the name snapshot the row carries."""
        audit_lookups.apps = []  # the app table no longer has it
        for action in ("app.publish", "app.stop", "app.delete"):
            insert_audit(
                audit_session,
                action=action,
                target_type="app",
                target_id=APP_ID,
                object_name="Alpha",
                tenant_id=TENANT,
            )

        resp = await _query(admin, target_app_id=APP_ID)

        assert resp["data"]["total"] == 3
        assert {row["app_name"] for row in resp["data"]["data"]} == {"Alpha"}
        assert {row["app_id"] for row in resp["data"]["data"]} == {APP_ID}

    async def test_release_and_state_rows_of_one_app_come_back_together(
        self, patch_audit_dao, audit_lookups, audit_session, admin
    ):
        """The two row shapes are one timeline for the reader (AC-19).

        Asserted separately from the parametrised cases because the failure it
        guards is *partial*: a predicate that matches only one shape looks
        perfectly healthy until someone notices the pipeline events are missing
        from an application's history.
        """
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=TENANT)]
        insert_audit(audit_session, action="app.publish", target_type="app", target_id=APP_ID, tenant_id=TENANT)
        insert_audit(
            audit_session,
            action="app.release.online",
            target_type="app_version",
            target_id="ver-9",
            audit_metadata={"app_id": APP_ID, "version_no": 9},
            tenant_id=TENANT,
        )

        resp = await _query(admin, target_app_id=APP_ID)

        assert {row["action"] for row in resp["data"]["data"]} == {"app.publish", "app.release.online"}
        assert {row["version_no"] for row in resp["data"]["data"]} == {None, 9}


class TestResponseCarriesNoSecret:
    """AC-26 — no plaintext key in a record, a query response or an export."""

    async def test_projection_drops_the_raw_metadata_blob(self, patch_audit_dao, audit_lookups, audit_session, admin):
        audit_lookups.apps = [make_app(APP_ID, name="Alpha", slug="alpha", tenant_id=TENANT)]
        insert_audit(
            audit_session,
            action="app.release.submit",
            target_type="app_version",
            target_id="ver-1",
            tenant_id=TENANT,
            # A writer that put a secret in metadata would leak it if the blob
            # were forwarded; the projection is what makes that impossible.
            audit_metadata={"app_id": APP_ID, "plaintext": "bs-sak-SUPERSECRETVALUE"},
        )

        resp = await _query(admin, target_app_id=APP_ID)
        item = resp["data"]["data"][0]

        assert "metadata" not in item and "audit_metadata" not in item
        assert "SUPERSECRETVALUE" not in str(item)

    async def test_service_account_row_shows_a_mask_not_a_key(
        self, patch_audit_dao, audit_lookups, audit_session, admin
    ):
        credential = make_credential(31, last4="ab12")
        audit_lookups.credentials = [credential]
        insert_audit(
            audit_session,
            action="open_api.api_key.issue",
            tenant_id=TENANT,
            operator_id=0,
            operator_name="ci-bot",
            audit_metadata={"credential_id": 31, "actor_kind": "service_account"},
        )

        resp = await _query(admin, event_type="open_api.api_key.issue")
        item = resp["data"]["data"][0]

        assert item["operator_kind"] == "service_account"
        assert item["operator_key_mask"] == credential.key_mask
        assert "ab12" in item["operator_key_mask"]
        # A mask is a prefix plus four characters — never the 43-character
        # secret, which is not stored anywhere to begin with.
        assert len(item["operator_key_mask"]) < 24


class TestKnownGaps:
    """The two GOV-04 rows that are *not* reachable on the audit face today.

    Written as strict xfails on purpose. A prose note in a report is invisible
    to whoever lands the missing piece; a sentinel that turns red the moment
    the gap closes forces the todo to be deleted rather than to outlive the
    defect it describes.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "AC-24 gap: F054 writes access records to the `app_access_log` table "
            "(AppAccessLogDao), which no endpoint reads — there is no audit-face "
            "route for them and no `app.access` action on the whitelist. Delete "
            "this sentinel when the access record becomes queryable."
        ),
    )
    def test_access_record_is_reachable_from_the_audit_face(self):
        # Read off the source tree rather than off the route table: this package
        # stubs ``bisheng.api.router`` into ``sys.modules``, so importing the app
        # here would raise and the sentinel would 「pass」 forever on the wrong
        # reason — exactly the way a sentinel stops being one.
        from pathlib import Path

        import bisheng

        on_whitelist = any(action.startswith("app.access") for action in _UI_VISIBLE_V2_ACTIONS)
        package_root = Path(bisheng.__file__).parent
        readers = [
            path
            for path in package_root.rglob("*.py")
            if "/api/" in path.as_posix() and "AppAccessLogDao" in path.read_text(encoding="utf-8")
        ]
        assert on_whitelist or readers

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "AC-25 gap: per-call model records are F051's `model_call_record` "
            "table and are not on this branch yet. Delete this sentinel when "
            "F051 lands a face that traces them by key / by object application."
        ),
    )
    def test_model_call_records_are_traceable(self):
        import importlib.util

        assert importlib.util.find_spec("bisheng.database.models.model_call_record") is not None


class TestDaoStillCountsWhatItReturns:
    """The page and its total must agree for every family, or 「查得到」 becomes
    「第一页查得到」."""

    async def test_total_matches_the_rows_for_a_mixed_history(self, patch_audit_dao, audit_session):
        for action in ("app.publish", "app.stop", "app.meta_update", "app.delete"):
            insert_audit(audit_session, action=action, target_type="app", target_id=APP_ID, tenant_id=TENANT)
        insert_audit(
            audit_session,
            action="app.release.online",
            target_type="app_version",
            target_id="v1",
            audit_metadata={"app_id": APP_ID},
            tenant_id=TENANT,
        )

        page_one, total = await AuditLogDao.get_audit_logs([], target_app_id=APP_ID, page=1, limit=3)
        page_two, _ = await AuditLogDao.get_audit_logs([], target_app_id=APP_ID, page=2, limit=3)

        assert total == 5
        assert len(page_one) + len(page_two) == 5
        assert {row.id for row in page_one}.isdisjoint({row.id for row in page_two})
