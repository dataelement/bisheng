"""Build E+ textcard payloads from InboxMessage action_codes."""
from bisheng.core.config import settings


FORWARDABLE_ACTION_CODES: set[str] = {
    "request_channel",
    "approved_channel",
    "rejected_channel",
    "request_knowledge_space",
    "approved_knowledge_space",
    "rejected_knowledge_space",
}


_TEMPLATES: dict[str, dict[str, str]] = {
    "request_channel": {
        "title": "[知源] 新的频道订阅申请",
        "normal": "{applicant} 申请订阅频道「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_channel": {
        "title": "[知源] 频道订阅申请已通过",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_channel": {
        "title": "[知源] 频道订阅申请被拒绝",
        "normal": "你订阅频道「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
    "request_knowledge_space": {
        "title": "[知源] 新的知识空间加入申请",
        "normal": "{applicant} 申请加入知识空间「{resource_name}」",
        "highlight": "需要你审批",
    },
    "approved_knowledge_space": {
        "title": "[知源] 知识空间加入申请已通过",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "已通过",
    },
    "rejected_knowledge_space": {
        "title": "[知源] 知识空间加入申请被拒绝",
        "normal": "你加入知识空间「{resource_name}」的申请",
        "highlight": "被拒绝",
    },
}


def build_textcard_url(message_id: int) -> str:
    """Return the BiSheng callback URL for a textcard button."""
    base = settings.in_app_message_forwarding.cofco.bisheng_inbox_url.rstrip("/")
    return f"{base}/?open-notifications=1&message-id={message_id}"


def _truncate_bytes(text: str, max_bytes: int) -> str:
    """Truncate text to at most max_bytes UTF-8 bytes without splitting a multi-byte char."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Binary search for the largest prefix that fits within max_bytes
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(text[:mid].encode("utf-8")) <= max_bytes:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def build_textcard(
    *,
    message_id: int,
    action_code: str,
    applicant_name: str,
    resource_name: str,
    triggered_at: str,
) -> dict:
    """Build the ``textcard`` dict for the E+ /v2/message/send body.

    Returns a dict with keys: title, description, url, btntxt.
    Raises KeyError when action_code is not in _TEMPLATES.
    """
    tpl = _TEMPLATES[action_code]  # KeyError for unknown codes — intentional
    title = _truncate_bytes(tpl["title"], 128)
    normal = tpl["normal"].format(applicant=applicant_name, resource_name=resource_name)
    description = (
        f'<div class="gray">{triggered_at}</div>'
        f'<div class="normal">{normal}</div>'
        f'<div class="highlight">{tpl["highlight"]}</div>'
    )
    description = _truncate_bytes(description, 512)
    return {
        "title": title,
        "description": description,
        "url": build_textcard_url(message_id),
        "btntxt": "去查看",
    }
