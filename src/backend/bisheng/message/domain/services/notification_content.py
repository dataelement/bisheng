from __future__ import annotations

from typing import Any


def infer_action_code(content: list[dict[str, Any]] | None) -> str:
    """Return the first system_text action code in a notification payload."""
    for item in content or []:
        if item.get("type") != "system_text":
            continue
        code = item.get("content")
        if isinstance(code, str) and code.strip():
            return code.strip()
    return ""


def build_notify_content(
    *,
    action_code: str,
    target_name: str,
    business_type: str | None = None,
    business_id: str | int | None = None,
    actor_user_id: int | None = None,
    actor_user_name: str | None = None,
    reason: str | None = None,
    navigable: bool = True,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []

    if actor_user_id is not None:
        display_name = actor_user_name or f"User {actor_user_id}"
        content.append(
            {
                "type": "user",
                "content": f"@{display_name}",
                "metadata": {"user_id": actor_user_id},
            }
        )

    content.append({"type": "system_text", "content": action_code})

    target_metadata = dict(metadata or {})
    if business_type and business_id is not None:
        target_metadata.setdefault("business_type", business_type)
        data = dict(target_metadata.get("data") or {})
        data.setdefault(business_type, str(business_id))
        data.setdefault("business_id", str(business_id))
        data.setdefault("business_name", target_name)
        target_metadata["data"] = data

    if navigable and business_type and business_id is not None:
        content.append(
            {
                "type": "business_url",
                "content": f"--{target_name}",
                "metadata": target_metadata,
            }
        )
    elif target_name:
        content.append(
            {
                "type": "target",
                "content": target_name,
                "metadata": target_metadata,
            }
        )

    if reason:
        content.append(
            {
                "type": "tooltip_text",
                "content": f"原因：{reason}",  # noqa: RUF001 - user-facing Chinese punctuation
                "metadata": {"reason": reason},
            }
        )

    return content
