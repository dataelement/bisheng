"""Publish-event station messages (design §4.2 ⑦ / AC-64 / AC-65).

Six events reach a person, and only three of them need code here — the other
three are already sent by the approval engine when it creates, approves or
rejects a request. Adding our own copy of those would double every message an
owner receives.

| event | who sends it | action_code |
|---|---|---|
| request created | us, after the gate (the gate itself does **not** notify) | ``approval_task_pending`` |
| approved / rejected / withdrawn | the approval engine | existing codes |
| cancelled because the app was deleted | ``cancel_instance_by_business`` | ``approval_instance_cancelled`` |
| parked: capacity | us | ``app_publish_pending_capacity`` |
| parked: start failed | us | ``app_publish_deploy_failed`` |

Two rules with teeth:

* **The message carries no action** (AC-65). Every one of these is a statement;
  the buttons live on the publish face and in the approval centre. This is not
  only a copy decision: the client shows an approval button whenever
  ``message_type`` is ``request`` or ``approve``, *regardless* of action code, so
  a wrong type grows a button that errors when pressed.
  ``ApprovalNotificationService`` routes through ``send_generic_notify``, which
  sends ``MessageTypeEnum.NOTIFY`` — neutral, and asserted in the tests.
* **The parked-state recipients are an unconditional union**, and that is
  correct *here* precisely because it is wrong for approver resolution. This is
  a notification: one extra administrator reading "an app is waiting for
  capacity" costs nothing, whereas one extra resolved approver is one more
  person who can decide. ``_get_admin_recipient_ids`` is the right function for
  this job and the wrong one for that job (design D8 ⚠️ / 坑 2).
"""

from __future__ import annotations

from loguru import logger

#: Parked after approval because the capacity gate refused the start.
ACTION_PENDING_CAPACITY = "app_publish_pending_capacity"
#: Parked after approval because the start or the readiness probe failed.
ACTION_DEPLOY_FAILED = "app_publish_deploy_failed"
#: The new version did not start, but the application is still serving the
#: version it was already running. Separate from the two above because the
#: remedy is the same while the urgency is not: nothing is down.
ACTION_ITERATION_FAILED = "app_publish_iteration_failed"
#: An approver has a new task waiting. Existing code — the gate creates the
#: task rows but sends nothing, so every scenario notifies from its own side.
ACTION_TASK_PENDING = "approval_task_pending"

#: ``reason_kind`` → action code. A mapping rather than a chain of conditionals
#: so adding an outcome cannot silently fall through to "it failed to start".
_ACTION_BY_REASON: dict[str, str] = {
    "capacity": ACTION_PENDING_CAPACITY,
    "deploy_failed": ACTION_DEPLOY_FAILED,
    "iteration_failed": ACTION_ITERATION_FAILED,
}

SCENARIO_CODE = "app_publish_request"


async def notify_approvers_of_new_task(
    *,
    tenant_id: int,
    applicant_user_id: int,
    approver_user_ids: list[int],
    business_name: str,
    instance_id: int,
    task_id: int | None = None,
) -> None:
    """Tell the resolved approvers a request is waiting (AC-64).

    The gate creates the tasks and the audit row and stops there — every
    shipped scenario sends this itself. Skipping it means approvers only ever
    discover work by opening the approval centre and looking (design 坑 5).
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    recipients = [int(one) for one in approver_user_ids if one]
    if not recipients:
        return
    await ApprovalNotificationService.notify_users(
        sender=int(applicant_user_id),
        receiver_user_ids=recipients,
        action_code=ACTION_TASK_PENDING,
        business_name=business_name,
        instance_id=int(instance_id),
        scenario_code=SCENARIO_CODE,
        task_id=task_id,
    )


async def notify_pending_online(
    *,
    tenant_id: int,
    owner_user_id: int,
    business_name: str,
    instance_id: int,
    reason_kind: str,
    reason: str = "",
) -> list[int]:
    """Approved, but it did not start — tell the owner and the administrators (AC-31 / AC-64).

    ``reason_kind`` is ``"capacity"``, ``"deploy_failed"`` or
    ``"iteration_failed"``; they map to different action codes because the
    remedy differs ("wait for room, or publish manually" vs "your application
    failed to start" vs "the new version did not go up, the live one is
    untouched"). Returns the recipients so a caller can log or assert on them.
    """
    from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

    action_code = _ACTION_BY_REASON.get(reason_kind, ACTION_DEPLOY_FAILED)
    recipients = {int(owner_user_id)} if owner_user_id else set()
    try:
        admins = await ApprovalNotificationService._get_admin_recipient_ids(tenant_id=int(tenant_id))
        recipients.update(int(one) for one in admins)
    except Exception:
        # Best effort by design: the owner still has to be told, and the publish
        # face reports the parked state whether or not this message arrived.
        logger.exception(f"app_publish.pending_online_recipients_failed tenant_id={tenant_id}")

    ordered = sorted(recipients)
    if not ordered:
        return []
    await ApprovalNotificationService.notify_users(
        sender=int(owner_user_id or 0),
        receiver_user_ids=ordered,
        action_code=action_code,
        business_name=business_name,
        instance_id=int(instance_id or 0),
        scenario_code=SCENARIO_CODE,
        reason=reason or None,
    )
    return ordered
