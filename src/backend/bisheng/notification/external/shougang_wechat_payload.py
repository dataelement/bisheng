"""Build Shougang enterprise WeChat push payloads from InboxMessage content."""

from typing import Any

from bisheng.common.services.config_service import settings
from bisheng.core.config.settings import ShougangWeChatMessagePushConf

PUSHABLE_ACTION_CODES: set[str] = {
    "qa_expert_invited",
    "qa_expert_answered",
    "qa_answer_commented",
    "qa_answer_accepted",
}


def _resolve_action_code(message) -> str:
    """Extract action_code from an InboxMessage.

    Prefers the model-level action_code field, then falls back to the
    ``type='system_text'`` content block used by notify-type messages.
    """
    code = getattr(message, "action_code", None)
    if isinstance(code, str) and code:
        return code
    for block in getattr(message, "content", None) or []:
        if block.get("type") == "system_text":
            c = block.get("content")
            if isinstance(c, str) and c:
                return c
    return ""


def _extract_applicant_name(content: list[dict[str, Any]]) -> str:
    """Extract applicant name from the first user content block."""
    for block in content or []:
        if block.get("type") == "user":
            raw = block.get("content") or ""
            if isinstance(raw, str) and raw.startswith("@"):
                return raw[1:]
            return raw
    return ""


def _extract_resource_name(content: list[dict[str, Any]]) -> str:
    """Extract resource name from the first business_url content block."""
    for block in content or []:
        if block.get("type") == "business_url":
            raw = block.get("content") or ""
            if isinstance(raw, str) and raw.startswith("--"):
                return raw[2:]
            return raw
    return ""


def _extract_preview(content: list[dict[str, Any]]) -> str:
    """Extract preview text from the first tooltip_text content block."""
    for block in content or []:
        if block.get("type") == "tooltip_text":
            raw = block.get("content") or ""
            return raw if isinstance(raw, str) else ""
    return ""


def render_body(
    *,
    action_code: str,
    content: list[dict[str, Any]],
    conf: ShougangWeChatMessagePushConf | None = None,
) -> str:
    """Render the message body for the given action_code.

    Template variables:
      - {applicant}: sender display name
      - {resource}: business resource display name
      - {preview}: preview text

    Raises:
        KeyError: if action_code has no configured template.
    """
    if conf is None:
        conf = settings.get_shougang_wechat_message_push_conf()

    template = getattr(conf.templates, action_code)
    if not isinstance(template, str):
        raise KeyError(f"No template configured for action_code={action_code}")

    return template.format(
        applicant=_extract_applicant_name(content),
        resource=_extract_resource_name(content),
        preview=_extract_preview(content),
    )


def resolve_action_code(message) -> str:
    """Public helper to resolve the action_code of a message."""
    return _resolve_action_code(message)
