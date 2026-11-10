"""Owner notification for an administrator's stop / resume (F056 AC-43 / AC-45).

The only station message F056 wires itself: when a tenant administrator (or a
platform super admin acting through the tenant view) takes an application
offline or brings it back, the owner is told. Every other hosted-application
message — approval outcomes, parked starts, cancellation on delete — is sent by
F055 or the approval engine, and sending a second copy from here would double
them (spec 决议-11).

Two rules with teeth:

* **The owner acting on their own app gets nothing.** The message exists to
  tell someone about a change *they did not make*; it is decided by comparing
  the actor with ``app.owner_user_id``, not by asking the permission runtime
  what the actor is — ``_require_operator`` has already established that a
  non-owner reaching this point is an administrator of one kind or the other.
* **A failed send never touches the state action** (AC-45). The stop or resume
  is a fact by the time this runs; a message that did not arrive changes
  whether the owner *knows*, not whether it *happened*. The whole body is
  guarded, the failure is logged, and the caller's ``ActionResult`` is
  untouched.

The message is a statement (``MessageTypeEnum.NOTIFY`` through
``ApprovalNotificationService``), never a request: the client grows an approval
button for ``request`` / ``approve`` types regardless of action code, and there
is nothing to approve here.
"""

from __future__ import annotations

from loguru import logger

#: An administrator took the application offline.
ACTION_STOPPED_BY_ADMIN = "app_stopped_by_admin"
#: An administrator brought the application back online.
ACTION_RESUMED_BY_ADMIN = "app_resumed_by_admin"

#: ``action`` argument → action code. A mapping so that a typo in a caller
#: fails loudly instead of sending a message with an unmapped code.
_ACTION_CODES: dict[str, str] = {
    "stop": ACTION_STOPPED_BY_ADMIN,
    "resume": ACTION_RESUMED_BY_ADMIN,
}


async def notify_owner_of_admin_state_change(*, app, actor, action: str) -> bool:
    """Tell the owner an administrator stopped / resumed their app (AC-43).

    ``action`` is ``"stop"`` or ``"resume"``. Returns ``True`` when a message
    was handed to the sender, ``False`` when nothing was sent — because the
    actor is the owner, the app has no owner, or the send failed. The return
    value is for logs and tests; callers must not branch their business flow
    on it (AC-45).
    """
    action_code = _ACTION_CODES.get(action)
    if action_code is None:
        logger.error("app_runtime.state_change_notify unknown action={} app_id={}", action, getattr(app, "id", None))
        return False

    actor_user_id = int(getattr(actor, "user_id", 0) or 0)
    owner_user_id = int(getattr(app, "owner_user_id", 0) or 0)
    if not owner_user_id or actor_user_id == owner_user_id:
        return False

    try:
        from bisheng.approval.domain.services.approval_notification_service import ApprovalNotificationService

        await ApprovalNotificationService.notify_users(
            sender=actor_user_id,
            receiver_user_ids=[owner_user_id],
            action_code=action_code,
            business_name=str(getattr(app, "name", "") or ""),
            # Not an approval: there is no instance to deep-link to. The
            # sender's content builder requires an id; zero is "none".
            instance_id=0,
        )
    except Exception:
        # Best effort by design (AC-45): the state action already happened and
        # is audited; a message that did not go out is an operator log line,
        # never a reason to report the stop / resume as failed.
        logger.exception(
            "app_runtime.state_change_notify failed app_id={} action={} owner={} actor={}",
            getattr(app, "id", None),
            action,
            owner_user_id,
            actor_user_id,
        )
        return False
    return True
