"""T042 — the six publish events that reach a person (AC-64 / AC-65).

The event table has six rows and **two** of them are ours. That asymmetry is the
whole design, and it is the thing a test suite has to pin, because both ways of
getting it wrong are silent:

* Sending our own "your release was approved" would give the owner **two**
  station messages for one event — the approval engine already sent one from
  ``_advance_after_node_approved``. Nothing fails; the inbox just doubles.
* Not sending the first-node notice would give the approvers **none** — the gate
  writes task rows and an audit row and deliberately notifies nobody (design
  坑 5). Nothing fails; the approvers simply never learn there is work.

So the four engine-sent events are asserted *through the engine* — approve and
reject via :meth:`ApprovalCenterService.decide_task_api`, withdraw via
``withdraw_instance`` — rather than by reading ``publish_notification_service``
and believing its docstring. The two remaining classes ("资源释放后可手动上线"
and "能力被收回") are asserted by their **absence**, which needs a behavioural
run *and* a structural guard: a test that only watches one manual publish cannot
tell "we chose not to notify" from "this particular branch happened not to".

The delete-cancel event is covered end to end in
``test_release_terminal_states.py::test_app_deleted_cancels_active_instance_and_notifies_approvers``
and is not duplicated here; :func:`test_app_publish_owns_exactly_two_notification_call_sites`
is what keeps this file honest about the other four.

Two fixtures, two different questions:

* ``approval_notifications`` answers **who** was told — it replaces
  ``ApprovalNotificationService`` wholesale, so nothing below it runs.
* ``message_sink`` answers **what the message is** — it lets the real
  ``notify_users`` → ``send_generic_notify`` → ``send_message`` chain run and
  only replaces the repository, which is the only way ``message_type`` and the
  content blocks can be observed rather than asserted from source.

They are mutually exclusive on purpose; a test that requested both would be
watching a notification that never reached the message service.
"""

from __future__ import annotations

import pytest

from .conftest import (
    OWNER_USER_ID,
    ROOT_TENANT_ID,
    SUB_TENANT_ID,
    SUPER_ADMIN_USER_ID,
    TENANT_ADMIN_USER_ID,
)

pytestmark = pytest.mark.asyncio

SCENARIO_CODE = "app_publish_request"

#: The two action codes ``publish_notification_service`` is allowed to send.
#: Everything else on the AC-64 table belongs to the approval engine.
OUR_ACTION_CODES = frozenset({"app_publish_pending_capacity", "app_publish_deploy_failed", "approval_task_pending"})

#: Content block types that carry an operation. AC-65 forbids every one of them
#: on a publish notification — the handling happens on the publish face or in
#: the approval centre, never on the card in the inbox.
ACTION_BEARING_BLOCK_TYPES = frozenset({"agree_reject_button", "button", "approval_button"})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _publish_approval():
    from bisheng.app_publish.domain.services import publish_approval_service

    return publish_approval_service


def _center():
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    return ApprovalCenterService


async def _submitted(
    app_factory,
    deployment_factory,
    *,
    owner_user_id: int | None = None,
    tenant_id: int = ROOT_TENANT_ID,
):
    """An app whose release is sitting in the approval centre, PENDING.

    Returns ``(app, deployment, gate_result)``. Goes through the real
    ``publish_approval_service.submit`` rather than seeding an instance by hand
    because the applicant identity — owner, never the service account that ran
    the CLI (INV-29) — is exactly what the approve/reject recipients are read
    from, and hand-seeding would let this file assert its own assumption.
    """
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_PROBE, STATUS_RUNNING

    app, _ = await app_factory(tenant_id=tenant_id, with_version=False, owner_user_id=owner_user_id)
    deployment = await deployment_factory(
        app_id=app.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        stage=STAGE_PRECHECK_PROBE,
        status=STATUS_RUNNING,
        version_id="ver-notify",
        tier_code="light",
        manifest={"name": app.name, "runtime": "python3.11", "port": 8080, "tier": "light"},
    )
    result = await _publish_approval().submit(deployment)
    return app, deployment, result


async def _decide(result, *, action: str, operator_user_id: int, comment: str | None = None):
    """Drive one approval task through the real engine entry point."""
    return await _center().decide_task_api(
        task_id=result.task_ids[0],
        action=action,
        operator_user_id=operator_user_id,
        operator_user_name=f"user-{operator_user_id}",
        operator_tenant_id=ROOT_TENANT_ID,
        comment=comment,
    )


def _by_action(sent: list[dict], action_code: str) -> list[dict]:
    return [one for one in sent if one.get("action_code") == action_code]


@pytest.fixture()
def message_sink(monkeypatch):
    """Let the real notification chain run; capture the ``InboxMessage`` it builds.

    Only ``InboxMessageRepository.save`` is replaced, so ``message_type``,
    ``status`` and the content blocks are produced by production code. Asserting
    those from ``inspect.getsource`` — as the AC-65 smoke test in
    ``test_publish_approval_service.py`` has to, since it runs without a
    database — proves the literal is present, not that this action code takes
    that branch.

    ``notify_users`` swallows every exception it meets, so each test using this
    fixture asserts the sink is **non-empty** before asserting anything about
    its contents; otherwise a broken chain reads as a passing test.
    """
    from bisheng.message.api import dependencies as message_dependencies
    from bisheng.message.domain.services.message_service import MessageService

    saved: list = []

    class _RecordingRepository:
        async def save(self, message):
            message.id = len(saved) + 1
            saved.append(message)
            return message

    service = MessageService(
        message_repository=_RecordingRepository(),
        message_read_repository=None,
    )

    async def _get_message_service(session=None):
        return service

    monkeypatch.setattr(message_dependencies, "get_message_service", _get_message_service)
    return saved


# ---------------------------------------------------------------------------
# AC-64 — approved / rejected reach the owner, sent by the engine
# ---------------------------------------------------------------------------


async def test_approved_notifies_the_owner_as_applicant(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """The last approver says yes → the **owner** gets ``approval_instance_approved``.

    The receiver is ``instance.applicant_user_id``, which
    ``publish_approval_service`` set to the application's owner rather than the
    service account that ran ``bisheng deploy``. A service account has no
    inbox anybody reads, so getting this wrong loses the message entirely
    without any error (INV-29).
    """
    app, _, result = await _submitted(app_factory, deployment_factory)
    approval_notifications.clear()

    outcome = await _decide(result, action="approve", operator_user_id=SUPER_ADMIN_USER_ID)

    assert outcome["instance_status"] == "approved"
    approved = _by_action(approval_notifications, "approval_instance_approved")
    assert len(approved) == 1
    assert approved[0]["receiver_user_ids"] == [app.owner_user_id]
    assert app.owner_user_id == OWNER_USER_ID
    assert approved[0]["scenario_code"] == SCENARIO_CODE
    assert approved[0]["instance_id"] == result.instance_id


async def test_rejected_notifies_the_owner_and_carries_the_comment(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """Rejection reaches the same person approval would have, with the reason attached.

    The comment is the only thing that tells the owner what to change before
    the next ``bisheng deploy``; dropping it turns a rejection into "no".
    """
    app, _, result = await _submitted(app_factory, deployment_factory)
    approval_notifications.clear()

    outcome = await _decide(result, action="reject", operator_user_id=SUPER_ADMIN_USER_ID, comment="端口未声明")

    assert outcome["instance_status"] == "rejected"
    rejected = _by_action(approval_notifications, "approval_task_rejected")
    assert len(rejected) == 1
    assert rejected[0]["receiver_user_ids"] == [app.owner_user_id]
    assert rejected[0]["reason"] == "端口未声明"


async def test_decision_does_not_add_a_second_publish_side_message(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """Approve and reject send **one** message each — none of it from our side.

    The engine owns four of the six events precisely so the owner's inbox holds
    one line per thing that happened. A well-meaning "your application was
    approved" added in ``publish_notification_service`` would double it, and no
    assertion anywhere else in the suite would notice.
    """
    _, _, approved_result = await _submitted(app_factory, deployment_factory)
    approval_notifications.clear()
    await _decide(approved_result, action="approve", operator_user_id=SUPER_ADMIN_USER_ID)
    after_approve = list(approval_notifications)

    assert [one["action_code"] for one in after_approve] == ["approval_instance_approved"]
    assert not OUR_ACTION_CODES.intersection({one["action_code"] for one in after_approve})

    approval_notifications.clear()
    _, _, rejected_result = await _submitted(app_factory, deployment_factory)
    approval_notifications.clear()
    await _decide(rejected_result, action="reject", operator_user_id=SUPER_ADMIN_USER_ID, comment="no")

    assert [one["action_code"] for one in approval_notifications] == ["approval_task_rejected"]


# ---------------------------------------------------------------------------
# AC-64 — withdrawn reaches the approvers who held a task, and nobody else
# ---------------------------------------------------------------------------


async def test_withdraw_notifies_only_the_approvers_who_held_a_task(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """Withdrawal is addressed to the people holding the task, not to the applicant.

    The applicant is the person who just pressed 撤回 — telling them is noise.
    The approver has an item in their inbox pointing at a request that no longer
    needs a decision, which is the actual problem this message solves.
    """
    _, _, result = await _submitted(app_factory, deployment_factory)
    approval_notifications.clear()

    await _center().withdraw_instance(
        instance_id=result.instance_id,
        operator_user_id=OWNER_USER_ID,
        operator_user_name="f055-owner",
        reason="本地还要再改",
    )

    withdrawn = _by_action(approval_notifications, "approval_instance_withdrawn")
    assert len(withdrawn) == 1
    assert withdrawn[0]["receiver_user_ids"] == [SUPER_ADMIN_USER_ID]
    assert OWNER_USER_ID not in withdrawn[0]["receiver_user_ids"]
    assert withdrawn[0]["reason"] == "本地还要再改"


async def test_withdraw_never_notifies_the_withdrawer_even_when_they_are_the_approver(
    publish_db, app_factory, deployment_factory, approval_env, audit_sink, approval_notifications, super_admin_user
):
    """Self-approval is the case where "exclude the operator" is load-bearing.

    Normally the applicant and the approvers are different people, so the
    exclusion in ``withdraw_instance`` never has to do anything and a suite can
    pass without it. Here the single administrator owns the app *and* holds the
    only task (AC-17's permitted self-approval), so the filter is the only thing
    between the operator and a station message about their own click.
    """
    _, _, result = await _submitted(app_factory, deployment_factory, owner_user_id=SUPER_ADMIN_USER_ID)
    approval_notifications.clear()

    await _center().withdraw_instance(
        instance_id=result.instance_id,
        operator_user_id=SUPER_ADMIN_USER_ID,
        operator_user_name="f055-super-admin",
    )

    assert _by_action(approval_notifications, "approval_instance_withdrawn") == []


# ---------------------------------------------------------------------------
# AC-64 — the parked recipients are an unconditional union
# ---------------------------------------------------------------------------


async def test_pending_online_union_reaches_owner_super_admin_and_tenant_admin(
    publish_db, approval_notifications, super_admin_user, tenant_admin_user
):
    """Owner plus every platform super admin plus this tenant's administrators — no fallback.

    This is *notification* recipient resolution and it must not be confused with
    *approver* resolution, which is a conditional chain (department admin →
    tenant admin → super admin only for Root). One extra person reading "an app
    is waiting for capacity" costs nothing; one extra resolved approver is one
    more person who can decide (design D8 ⚠️ / 坑 2).

    Asserted in the **child** tenant because Root has no tenant administrators
    by construction — running it there would prove only that the super admin
    branch works.
    """
    from bisheng.app_publish.domain.services import publish_notification_service

    recipients = await publish_notification_service.notify_pending_online(
        tenant_id=SUB_TENANT_ID,
        owner_user_id=OWNER_USER_ID,
        business_name="f055 app",
        instance_id=4242,
        reason_kind="capacity",
        reason="no room",
    )

    assert recipients == sorted({OWNER_USER_ID, SUPER_ADMIN_USER_ID, TENANT_ADMIN_USER_ID})
    parked = _by_action(approval_notifications, "app_publish_pending_capacity")
    assert len(parked) == 1
    assert parked[0]["receiver_user_ids"] == recipients


# ---------------------------------------------------------------------------
# AC-64 — the two classes that deliberately stay silent
# ---------------------------------------------------------------------------


async def test_manual_publish_after_resources_freed_notifies_nobody(
    publish_db, app_factory, deployment_factory, audit_sink, approval_notifications, monkeypatch
):
    """ "资源释放后可手动上线" is a state the publish face reports, not a message.

    Nothing watches for capacity coming back, so there is no event to send;
    the owner finds out by opening the publish face, where ``can.manual_publish``
    is computed. A retry that succeeds must therefore produce an audit row and
    **zero** station messages — if it grew one, every parked application in a
    busy cluster would page its owner twice.
    """
    from bisheng.app_publish.domain.services.publish_online_service import PublishOnlineService
    from bisheng.app_runtime.domain.services.app_state_service import ActionResult, AppStateService
    from bisheng.database.models.app import AppDao

    app, version = await app_factory(state="pending_capacity", with_version=True)
    await deployment_factory(
        app_id=app.id,
        stage="pending_online",
        status="pending_capacity",
        version_id=version.id,
        tier_code="light",
    )
    async with publish_db() as session:
        row = await AppDao.aget(session, app.id)
        row.pending_version_id = version.id
        session.add(row)
        await session.commit()

    async def _manual_publish(app_id, *, actor=None):
        return ActionResult(app_id=app_id, state="online", ok=True, reason="", version_id=version.id, detail={})

    monkeypatch.setattr(AppStateService, "manual_publish", staticmethod(_manual_publish))

    outcome = await PublishOnlineService.manual_publish(app.id, actor=None)

    assert outcome["status"] == "online"
    assert [call["action"] for call in audit_sink if call["action"] == "app.release.online"]
    assert approval_notifications == []


async def test_app_publish_owns_exactly_two_notification_call_sites():
    """The structural half of "these two classes send nothing".

    A behavioural test can only show that *one* run stayed quiet. This walks the
    whole ``app_publish`` package and pins the complete set of notification call
    sites at two — the first-node notice and the parked notice. A third would
    mean either a duplicate of an engine-sent event or a message for one of the
    two classes AC-64 says must stay silent, and both are invisible at runtime.
    """
    import ast
    from pathlib import Path

    import bisheng.app_publish as app_publish

    package_root = Path(app_publish.__file__).parent
    service_module = package_root / "domain" / "services" / "publish_notification_service.py"

    call_sites: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        if path == service_module:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr.startswith("notify_"):
                call_sites.append(f"{path.relative_to(package_root)}::{node.func.attr}")

    assert sorted(call_sites) == [
        "domain/services/publish_approval_service.py::notify_approvers_of_new_task",
        "domain/services/publish_online_service.py::notify_pending_online",
    ], f"unexpected notification call site(s) in app_publish: {sorted(call_sites)}"


async def test_publish_notification_service_declares_no_silent_class_action_code():
    """No action code exists for the two silent classes — not even an unused one.

    A constant is where the next person looks for permission to send something.
    Leaving ``ACTION_RESOURCE_RELEASED`` lying around unused is how "we decided
    not to notify" becomes "somebody wired it up".
    """
    from bisheng.app_publish.domain.services import publish_notification_service

    declared = {
        value
        for name, value in vars(publish_notification_service).items()
        if name.startswith("ACTION_") and isinstance(value, str)
    }

    assert declared == {"app_publish_pending_capacity", "app_publish_deploy_failed", "approval_task_pending"}
    assert not [one for one in declared if "resource" in one or "capabilit" in one or "revoke" in one]


# ---------------------------------------------------------------------------
# AC-65 — a notification, never an operation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_code",
    ["approval_task_pending", "app_publish_pending_capacity", "app_publish_deploy_failed"],
)
async def test_publish_notifications_are_neutral_notify_messages(publish_db, message_sink, action_code):
    """``message_type`` must never be ``approve`` — the client grows a button from the type alone.

    ``isApprovalMessageType`` in ``NotificationsDialog.tsx`` is true for the
    approval message types *regardless* of action code, so a publish notice sent
    with the wrong type renders an 同意/驳回 pair that errors when pressed. The
    guarantee has to live on the sending side, and this asserts it on the real
    ``send_generic_notify`` path rather than on its source text.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService
    from bisheng.message.domain.models.inbox_message import MessageStatusEnum, MessageTypeEnum

    await ApprovalNotificationService.notify_users(
        sender=OWNER_USER_ID,
        receiver_user_ids=[SUPER_ADMIN_USER_ID],
        action_code=action_code,
        business_name="f055 app",
        instance_id=7001,
        scenario_code=SCENARIO_CODE,
    )

    assert len(message_sink) == 1, "the notification never reached the message service"
    message = message_sink[0]
    assert message.message_type == MessageTypeEnum.NOTIFY
    assert message.message_type != MessageTypeEnum.APPROVE
    assert message.status == MessageStatusEnum.APPROVED
    assert message.action_code == action_code


async def test_publish_notification_content_carries_no_action_payload(publish_db, message_sink):
    """AC-65 on the content blocks: text and a link, never a button.

    ``build_generic_approval_content`` — the shape used for real approval
    requests — appends an ``agree_reject_button`` block carrying a
    ``button_action_code`` and an ``approval_id``. A publish notice must contain
    none of that: the handling lives on the publish face and in the approval
    centre, so the inbox card is a statement with a link at most.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    await ApprovalNotificationService.notify_users(
        sender=OWNER_USER_ID,
        receiver_user_ids=[SUPER_ADMIN_USER_ID],
        action_code="app_publish_deploy_failed",
        business_name="f055 app",
        instance_id=7002,
        scenario_code=SCENARIO_CODE,
        reason="probe failed",
    )

    assert len(message_sink) == 1, "the notification never reached the message service"
    content = message_sink[0].content
    assert content

    types = {str(block.get("type")) for block in content}
    assert not types.intersection(ACTION_BEARING_BLOCK_TYPES), f"action-bearing block(s) in a notification: {types}"

    for block in content:
        metadata = block.get("metadata") or {}
        assert "button_action_code" not in metadata
        assert "action_code" not in metadata, "an action code inside metadata is what renders a button"
        assert "approval_id" not in (metadata.get("data") or {})


async def test_task_pending_metadata_is_a_deep_link_not_a_command(publish_db, message_sink):
    """The one identifier a publish notice may carry is where to go, not what to do.

    ``approval_task_id`` rides in ``metadata.data`` so the card can link into the
    approval centre. That is navigation — the decision is still taken there,
    with its own permission check — and it is the boundary AC-65 draws.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    await ApprovalNotificationService.notify_users(
        sender=OWNER_USER_ID,
        receiver_user_ids=[SUPER_ADMIN_USER_ID],
        action_code="approval_task_pending",
        business_name="f055 app",
        instance_id=7003,
        scenario_code=SCENARIO_CODE,
        task_id=31337,
    )

    assert len(message_sink) == 1, "the notification never reached the message service"
    linked = [
        block
        for block in message_sink[0].content
        if (block.get("metadata") or {}).get("data", {}).get("approval_task_id") == "31337"
    ]
    assert linked, "the approval task id must survive to the card so it can link into the approval centre"
    assert all(str(block.get("type")) not in ACTION_BEARING_BLOCK_TYPES for block in linked)
