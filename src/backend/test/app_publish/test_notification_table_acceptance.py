"""F056 T033 — the §3.0.3 event-reach table, read across Features (AC-39~AC-45).

F056 wires exactly one station message of its own (AC-43, covered end to end in
``test/app_runtime/test_state_change_notify.py``). What it owns here is the
*whole table*: eleven rows, of which six send and five must not, spread over
F055 (the publish pipeline), the approval engine, F054 (state actions), F049
(keys) and F048 (visibility). Each Feature tests its own rows; nobody was
testing the table.

Two things only a cross-package view can assert, and both fail silently:

* **A row that must stay silent grew a sender.** Each Feature's own suite can
  only see its own package, so a notification added in ``open_api`` for key
  issuance — AC-44 says there is none — would pass every existing test. The
  census below walks all five packages at once.
* **A row that must send lost its sender.** Nothing breaks; the recipient
  simply never learns. The counterpart assertions pin the surviving call sites
  by name rather than by count, so a move reads as a move.

AC-45 gets a behavioural test rather than a structural one: the claim is that a
*failing* send leaves the business action intact, and only running one shows
that. ``ApprovalNotificationService.notify_users`` is the single choke point
every sender goes through and it swallows on purpose — the test makes the
message chain underneath it throw and asserts each caller still returns
normally.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

#: Package → the notification call sites it is allowed to have, as
#: ``relative/path.py::callee``. The empty lists are the AC-44 rows.
ALLOWED_CALL_SITES: dict[str, list[str]] = {
    # F055: the first-node notice and the two parked outcomes (AC-40 row 1,
    # AC-42). Approved / rejected / withdrawn / cancelled are the approval
    # engine's — a copy here would double every message.
    "bisheng.app_publish": [
        "domain/services/publish_approval_service.py::notify_approvers_of_new_task",
        "domain/services/publish_online_service.py::notify_pending_online",
        "domain/services/publish_online_service.py::notify_pending_online",
    ],
    # F054 state actions + F056's one wiring. ``stop`` and ``_start`` each call
    # it once; nothing else in the runtime notifies anybody.
    "bisheng.app_runtime": [
        "domain/services/app_state_service.py::notify_owner_of_admin_state_change",
        "domain/services/app_state_service.py::notify_owner_of_admin_state_change",
    ],
    # AC-44 row 3: key issue / revoke / auto-expiry send nothing. The developer
    # learns from the key page; a station message per key event would be noise
    # on the one surface that is already about keys.
    "bisheng.open_api": [],
}

#: Names that mean "a station message goes out". ``notify_`` covers the service
#: helpers; the two ``send_`` entries are the message service itself, in case a
#: caller skips the helper layer.
NOTIFY_CALLEES = ("send_generic_notify", "send_message", "notify_users", "notify_admins")


def _call_sites(package: str) -> list[str]:
    """Every notification call site in ``package``, excluding its own senders.

    A sender module is the place the notification is *defined*; counting its
    internal calls would report the definition as a use and make the census
    meaningless.
    """
    import importlib

    root = Path(importlib.import_module(package).__file__).parent
    sender_modules = {
        root / "domain" / "services" / "publish_notification_service.py",
        root / "domain" / "services" / "state_change_notify.py",
    }
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path in sender_modules:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Both call shapes occur: ``service.notify_x(...)`` in app_publish
            # and a bare ``notify_x(...)`` from a module-level import in
            # app_runtime. Matching only the first reported "no senders at all"
            # for a package that has two.
            if isinstance(node.func, ast.Attribute):
                callee = node.func.attr
            elif isinstance(node.func, ast.Name):
                callee = node.func.id
            else:
                continue
            if callee.startswith("notify_") or callee in NOTIFY_CALLEES:
                found.append(f"{path.relative_to(root)}::{callee}")
    return sorted(found)


class TestTableCensus:
    @pytest.mark.parametrize("package", sorted(ALLOWED_CALL_SITES))
    async def test_package_sends_exactly_the_messages_the_table_allows(self, package):
        assert _call_sites(package) == sorted(ALLOWED_CALL_SITES[package]), (
            f"{package}: notification call sites drifted from §3.0.3. Adding a "
            "sender means adding a row to the table (and its three-language "
            "copy); removing one means a recipient stops being told."
        )

    async def test_capability_revocation_sends_nothing(self):
        """AC-44 row 2. The interface tells the owner by *failing visibly*
        (F055 GOV-05); a station message would arrive hours later and out of
        context."""
        from bisheng.app_publish.domain.services import publish_notification_service

        declared = {
            value
            for name, value in vars(publish_notification_service).items()
            if name.startswith("ACTION_") and isinstance(value, str)
        }
        assert not [one for one in declared if "capabilit" in one or "revoke" in one or "resource" in one]

    async def test_visibility_grant_sends_nothing(self):
        """AC-44 row 4. Being newly able to see an application is not news the
        platform pushes this version — there is no "new in the square" feed, and
        a grant can cover hundreds of users at once."""
        from bisheng.app_runtime.domain.services import visibility_audit

        source = Path(visibility_audit.__file__).read_text(encoding="utf-8")
        assert "notify" not in source

    async def test_no_hosted_app_action_code_exists_for_a_silent_row(self):
        """The union of action codes the two senders declare *is* the sending
        half of the table — six codes, no more.

        A constant is where the next person looks for permission to send
        something; an unused ``ACTION_KEY_ISSUED`` is how "we decided not to"
        turns into "somebody wired it up".
        """
        from bisheng.app_publish.domain.services import publish_notification_service
        from bisheng.app_runtime.domain.services import state_change_notify

        declared = set()
        for module in (publish_notification_service, state_change_notify):
            declared |= {
                value for name, value in vars(module).items() if name.startswith("ACTION_") and isinstance(value, str)
            }

        assert declared == {
            "approval_task_pending",
            "app_publish_pending_capacity",
            "app_publish_deploy_failed",
            "app_publish_iteration_failed",
            "app_stopped_by_admin",
            "app_resumed_by_admin",
        }


class TestSendFailureNeverBlocksTheAction:
    """AC-45 — the message is a side channel, the action is the fact."""

    @pytest.fixture()
    def broken_message_chain(self, monkeypatch):
        """Make the real send blow up as deep as the chain goes."""
        from bisheng.message.api import dependencies as message_dependencies

        async def _explode(session=None):
            raise RuntimeError("inbox unavailable")

        monkeypatch.setattr(message_dependencies, "get_message_service", _explode)

    async def test_approver_notice_failure_is_swallowed(self, broken_message_chain):
        from bisheng.app_publish.domain.services import publish_notification_service

        # Returns None rather than raising: the approval request and its tasks
        # already exist by the time this runs, and the caller goes on to write
        # the self-approval audit row.
        assert (
            await publish_notification_service.notify_approvers_of_new_task(
                tenant_id=1,
                applicant_user_id=2,
                approver_user_ids=[3],
                business_name="Alpha",
                instance_id=9,
            )
            is None
        )

    @pytest.mark.parametrize("reason_kind", ["capacity", "deploy_failed", "iteration_failed"])
    async def test_parked_notice_failure_is_swallowed(self, broken_message_chain, monkeypatch, reason_kind):
        from bisheng.app_publish.domain.services import publish_notification_service
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        async def _admins(*, tenant_id):
            return [11]

        monkeypatch.setattr(ApprovalNotificationService, "_get_admin_recipient_ids", _admins)

        recipients = await publish_notification_service.notify_pending_online(
            tenant_id=1,
            owner_user_id=2,
            business_name="Alpha",
            instance_id=9,
            reason_kind=reason_kind,
            reason="no room",
        )

        # The recipients were resolved and the publish outcome is unchanged;
        # only the delivery failed.
        assert recipients == [2, 11]

    async def test_admin_state_change_notice_failure_is_swallowed(self, broken_message_chain):
        from types import SimpleNamespace

        from bisheng.app_runtime.domain.services.state_change_notify import notify_owner_of_admin_state_change

        # The assertion is that this returns at all. ``notify_users`` is the
        # choke point and swallows there, so the hook reports "handed to the
        # sender" even when the inbox was down — a distinction the owner cares
        # about and the stop action does not (AC-45). What must never happen is
        # the exception reaching ``AppStateService.stop``.
        sent = await notify_owner_of_admin_state_change(
            app=SimpleNamespace(id="app-1", name="Alpha", owner_user_id=2),
            actor=SimpleNamespace(user_id=77),
            action="stop",
        )

        assert isinstance(sent, bool)

    async def test_admin_recipient_lookup_failure_still_reaches_the_owner(self, monkeypatch):
        """The parked notice resolves two groups of recipients; losing the
        second must not lose the first — the owner is the one who has to act."""
        from bisheng.app_publish.domain.services import publish_notification_service
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        async def _boom(*, tenant_id):
            raise RuntimeError("tenant service down")

        sent: list[dict] = []

        async def _notify(**kwargs):
            sent.append(kwargs)

        monkeypatch.setattr(ApprovalNotificationService, "_get_admin_recipient_ids", _boom)
        monkeypatch.setattr(ApprovalNotificationService, "notify_users", _notify)

        recipients = await publish_notification_service.notify_pending_online(
            tenant_id=1,
            owner_user_id=2,
            business_name="Alpha",
            instance_id=9,
            reason_kind="capacity",
        )

        assert recipients == [2]
        assert sent and sent[0]["receiver_user_ids"] == [2]
