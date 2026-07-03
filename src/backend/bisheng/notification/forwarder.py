"""Synchronous hook: decide / resolve recipients / schedule HTTP task. Never blocks."""

import asyncio
import logging

from bisheng.common.services.config_service import settings
from bisheng.common.services.metric_log import emit_metric
from bisheng.notification.external._payload import FORWARDABLE_ACTION_CODES, build_textcard
from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)

# Keep strong references to in-flight fire-and-forget tasks so the event loop
# does not garbage-collect them mid-execution (asyncio caveat).
_pending_tasks: set = set()


def _fire_and_forget(coro) -> None:
    """Schedule a coroutine without awaiting; retain a reference until done."""
    task = asyncio.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def resolve_eplus_recipient(target_user_id: int) -> tuple[str | None, str]:
    """Return (e_plus_userid, skip_reason). skip_reason is empty string when resolved."""
    user = UserDao.get_user(target_user_id)
    if not user:
        return None, "user_not_found"
    conf = settings.get_cofco_forwarding_conf()
    if user.source not in conf.user_sources:
        return None, f"source={user.source}_not_in_allowed_sources"
    if not user.external_id:
        return None, "external_id_empty"
    return user.external_id, ""


def _resolve_action_code(message) -> str:
    """Pick the action_code for a message.

    Approval-type messages (sent via send_generic_approval) set the top-level
    ``message.action_code`` field. Notify-type messages (sent via
    send_generic_notify) do NOT set that field — the code lives inside a
    ``type='system_text'`` content block. Fall back to that block, then to
    legacy approval ``agree_reject_button.metadata`` for back-compat.
    """
    code = getattr(message, "action_code", None)
    if isinstance(code, str) and code:
        return code
    for block in getattr(message, "content", None) or []:
        if block.get("type") == "system_text":
            c = block.get("content")
            if isinstance(c, str) and c:
                return c
    for block in getattr(message, "content", None) or []:
        if block.get("type") == "agree_reject_button":
            meta = block.get("metadata") or {}
            c = meta.get("action_code") or meta.get("business_type")
            if isinstance(c, str) and c:
                return c
    return ""


def _extract_payload_fields(message) -> tuple[str, str, str, str]:
    """Extract (applicant_name, resource_name, reason, scenario_code) from content.

    Content block shapes (see message_schema.py):
      - UserContentItem     → {"type": "user",         "content": "@<user_name>", ...}
      - BusinessContentItem → {"type": "business_url", "content": "--<business_name>", ...}

    The display name is encoded in the ``content`` string with a sentinel prefix
    (``@`` for users, ``--`` for business resources). We strip the prefix.
    """
    applicant_name = ""
    resource_name = ""
    reason = ""
    scenario_code = ""
    try:
        for block in message.content or []:
            btype = block.get("type")
            raw = block.get("content") or ""
            meta = block.get("metadata") or {}
            data = meta.get("data") or {}
            if not scenario_code:
                scenario_code = meta.get("scenario_code") or data.get("scenario_code") or ""
            if btype == "user" and not applicant_name and isinstance(raw, str):
                applicant_name = raw[1:] if raw.startswith("@") else raw
            elif btype == "business_url" and not resource_name and isinstance(raw, str):
                resource_name = raw[2:] if raw.startswith("--") else raw
            elif btype == "target" and not resource_name and isinstance(raw, str):
                resource_name = raw
            elif btype == "tooltip_text" and not reason and isinstance(raw, str):
                reason_prefix = f"原因{chr(0xFF1A)}"
                reason = raw[len(reason_prefix) :].strip() if raw.startswith(reason_prefix) else raw.strip()
    except Exception as exc:
        logger.debug("_extract_payload_fields parse error: %s", exc, exc_info=True)
    return applicant_name, resource_name, reason, scenario_code


def maybe_forward_external(message) -> None:
    """Synchronous hook called from MessageService.send_message().

    Resolves all receivers in message.receiver (List[int]), collects valid
    E+ employee IDs, and schedules a fire-and-forget asyncio task to send
    the textcard. Decoupled from FastAPI BackgroundTasks so any caller in
    an asyncio event loop can invoke it.

    Logging contract:
      INFO  forward.skipped  — every short-circuit path (with reason)
      INFO/WARN forward.attempt + forward.result — delegated to CofcoEPlusClient
    """
    conf = settings.get_cofco_forwarding_conf()
    if not conf.enabled:
        # High-frequency path: use DEBUG to avoid log spam when feature is off
        logger.debug(
            "forward.skipped message_id=%s reason=feature_disabled",
            getattr(message, "id", "?"),
        )
        return

    action_code = _resolve_action_code(message)
    if action_code not in FORWARDABLE_ACTION_CODES:
        logger.info(
            "forward.skipped message_id=%s action_code=%s reason=not_in_whitelist",
            message.id,
            action_code,
        )
        return

    # InboxMessage.receiver is List[int] — resolve each to an E+ employee ID
    resolved_eids: list[str] = []
    for uid in message.receiver or []:
        eid, skip_reason = resolve_eplus_recipient(uid)
        if eid is None:
            logger.info(
                "forward.skipped message_id=%s action_code=%s reason=%s target_user_id=%s",
                message.id,
                action_code,
                skip_reason,
                uid,
            )
            # Only post-whitelist recipient skips are metered (feature_disabled /
            # not_in_whitelist fire on nearly every message — see tasks 偏差记录).
            emit_metric("eplus_notify", result="skipped", action=action_code, reason=skip_reason)
        else:
            resolved_eids.append(eid)

    if not resolved_eids:
        return

    applicant_name, resource_name, reason, scenario_code = _extract_payload_fields(message)
    triggered_at = message.create_time.strftime("%Y-%m-%d %H:%M")

    textcard = build_textcard(
        message_id=message.id,
        action_code=action_code,
        applicant_name=applicant_name,
        resource_name=resource_name,
        triggered_at=triggered_at,
        reason=reason,
        scenario_code=scenario_code,
    )

    client = CofcoEPlusClient()
    _fire_and_forget(
        client.send_textcard(
            message_id=message.id,
            action_code=action_code,
            touser=resolved_eids,
            textcard=textcard,
        )
    )
