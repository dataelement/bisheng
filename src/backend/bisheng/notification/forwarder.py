"""Synchronous hook: decide / resolve recipients / schedule HTTP task. Never blocks."""
import asyncio
import logging
from typing import Optional, Tuple

from bisheng.common.services.config_service import settings
from bisheng.user.domain.models.user import UserDao
from bisheng.notification.external._payload import FORWARDABLE_ACTION_CODES, build_textcard
from bisheng.notification.external.cofco_eplus_client import CofcoEPlusClient

logger = logging.getLogger(__name__)

# Keep strong references to in-flight fire-and-forget tasks so the event loop
# does not garbage-collect them mid-execution (asyncio caveat).
_pending_tasks: set = set()


def _fire_and_forget(coro) -> None:
    """Schedule a coroutine without awaiting; retain a reference until done."""
    task = asyncio.create_task(coro)
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def resolve_eplus_recipient(target_user_id: int) -> Tuple[Optional[str], str]:
    """Return (e_plus_userid, skip_reason). skip_reason is empty string when resolved."""
    user = UserDao.get_user(target_user_id)
    if not user:
        return None, "user_not_found"
    if user.source != "cofco_eplus":
        return None, f"source={user.source}_not_eplus"
    if not user.external_id:
        return None, "external_id_empty"
    return user.external_id, ""


def _extract_payload_fields(message) -> Tuple[str, str]:
    """Extract (applicant_name, resource_name) from an InboxMessage content list.

    InboxMessage.content is a list of typed blocks. We look for:
      - type='user': the applicant (first occurrence)
      - type='business_url': the resource name

    Returns ('', '') if anything is missing or parsing fails.
    """
    applicant_name = ""
    resource_name = ""
    try:
        for block in (message.content or []):
            btype = block.get("type")
            if btype == "user" and not applicant_name:
                # Resolve the applicant display name from user_id in metadata
                applicant_id = (block.get("metadata") or {}).get("user_id")
                if applicant_id:
                    user = UserDao.get_user(int(applicant_id))
                    if user:
                        applicant_name = user.user_name or user.email or str(applicant_id)
            elif btype == "business_url" and not resource_name:
                meta = block.get("metadata") or {}
                business_type = meta.get("business_type") or ""
                data = (meta.get("data") or {}).get(business_type) or {}
                if isinstance(data, dict):
                    resource_name = data.get("resource_name") or data.get("name") or ""
                elif isinstance(data, str):
                    resource_name = data
    except Exception as exc:
        logger.debug("_extract_payload_fields parse error: %s", exc, exc_info=True)
    return applicant_name, resource_name


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
    conf = settings.in_app_message_forwarding.cofco
    if not conf.enabled:
        # High-frequency path: use DEBUG to avoid log spam when feature is off
        logger.debug(
            "forward.skipped message_id=%s reason=feature_disabled",
            getattr(message, "id", "?"),
        )
        return

    if message.action_code not in FORWARDABLE_ACTION_CODES:
        logger.info(
            "forward.skipped message_id=%s action_code=%s reason=not_in_whitelist",
            message.id, message.action_code,
        )
        return

    # InboxMessage.receiver is List[int] — resolve each to an E+ employee ID
    resolved_eids: list[str] = []
    for uid in (message.receiver or []):
        eid, skip_reason = resolve_eplus_recipient(uid)
        if eid is None:
            logger.info(
                "forward.skipped message_id=%s action_code=%s reason=%s target_user_id=%s",
                message.id, message.action_code, skip_reason, uid,
            )
        else:
            resolved_eids.append(eid)

    if not resolved_eids:
        return

    applicant_name, resource_name = _extract_payload_fields(message)
    triggered_at = message.create_time.strftime("%Y-%m-%d %H:%M")

    textcard = build_textcard(
        message_id=message.id,
        action_code=message.action_code,
        applicant_name=applicant_name,
        resource_name=resource_name,
        triggered_at=triggered_at,
    )

    client = CofcoEPlusClient()
    _fire_and_forget(
        client.send_textcard(
            message_id=message.id,
            action_code=message.action_code,
            touser=resolved_eids,
            textcard=textcard,
        )
    )
