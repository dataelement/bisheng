"""Pure codec for the customer-verified E+ long-connection protocol."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bisheng.eplus.domain.schemas.protocol import EPlusCallback, EPlusContentBlock, EPlusContentKind

MAX_STREAM_BYTES = 20_480
REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = {
    "access_token",
    "aes_key",
    "aeskey",
    "authorization",
    "secret",
    "token",
}
_MESSAGE_KEYS = {"answer_text", "content", "extracted_text", "user_text"}
_LEADING_MENTION = re.compile(r"^\s*@[\w\-\u4e00-\u9fff]+(?:[\s,:\uff0c\uff1a]+|$)")


class EPlusProtocolError(ValueError):
    """Raised when an E+ frame or encrypted media payload is malformed."""


def build_subscribe_frame(bot_id: str, secret: str, req_id: str) -> dict[str, Any]:
    return {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": _nonempty(req_id, "req_id")},
        "body": {
            "bot_id": _nonempty(bot_id, "bot_id"),
            "secret": _nonempty(secret, "secret"),
        },
    }


def build_ping_frame(req_id: str) -> dict[str, Any]:
    return {"cmd": "ping", "headers": {"req_id": _nonempty(req_id, "req_id")}}


def build_stream_frame(
    req_id: str,
    stream_id: str,
    content: str,
    *,
    finish: bool,
) -> dict[str, Any]:
    if len(content.encode("utf-8")) > MAX_STREAM_BYTES:
        raise EPlusProtocolError("stream content exceeds 20,480 UTF-8 bytes")
    return {
        "cmd": "aibot_respond_msg",
        "headers": {"req_id": _nonempty(req_id, "req_id")},
        "body": {
            "msgtype": "stream",
            "stream": {
                "id": _nonempty(stream_id, "stream_id"),
                "finish": bool(finish),
                "content": content,
            },
        },
    }


def stable_stream_id(bot_id: str, msg_id: str) -> str:
    raw = f"{_nonempty(bot_id, 'bot_id')}\0{_nonempty(msg_id, 'msgid')}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def truncate_utf8(text: str, max_bytes: int = MAX_STREAM_BYTES) -> tuple[str, bool]:
    if max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def parse_message_callback(frame: dict[str, Any]) -> EPlusCallback:
    if frame.get("cmd") != "aibot_msg_callback":
        raise EPlusProtocolError("frame cmd is not aibot_msg_callback")
    headers = _required_mapping(frame, "headers")
    body = _required_mapping(frame, "body")
    req_id = _required_string(headers, "req_id")
    msg_id = _required_string(body, "msgid")
    bot_id = _required_string(body, "aibotid")
    sender_external_id = _required_string(_required_mapping(body, "from"), "userid")
    chat_type = _required_string(body, "chattype").lower()
    if chat_type not in {"single", "group"}:
        raise EPlusProtocolError(f"unsupported chattype: {chat_type!r}")
    chat_id = body.get("chatid")
    if chat_id is not None and not isinstance(chat_id, str):
        raise EPlusProtocolError("body.chatid must be a string when present")
    if chat_type == "group" and not chat_id:
        raise EPlusProtocolError("body.chatid is required for group callbacks")

    msg_type = _required_string(body, "msgtype").lower()
    blocks = _parse_content_blocks(body, msg_type=msg_type, strip_mention=chat_type == "group")
    return EPlusCallback(
        req_id=req_id,
        msg_id=msg_id,
        bot_id=bot_id,
        sender_external_id=sender_external_id,
        chat_type=chat_type,
        chat_id=chat_id,
        msg_type=msg_type,
        blocks=blocks,
    )


def decrypt_media(ciphertext: bytes, aes_key: str) -> bytes:
    padded_key = aes_key + "=" * (-len(aes_key) % 4)
    try:
        key = base64.b64decode(padded_key, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise EPlusProtocolError("aeskey is not valid base64") from exc
    if len(key) != 32:
        raise EPlusProtocolError(f"aeskey must decode to 32 bytes, got {len(key)}")
    if not ciphertext:
        raise EPlusProtocolError("encrypted media is empty")

    aligned_ciphertext = ciphertext + b"\x00" * (-len(ciphertext) % 16)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    padded_plaintext = decryptor.update(aligned_ciphertext) + decryptor.finalize()
    pad_length = padded_plaintext[-1]
    if not 1 <= pad_length <= 32:
        raise EPlusProtocolError("decrypted media has invalid PKCS#7 padding length")
    if padded_plaintext[-pad_length:] != bytes([pad_length]) * pad_length:
        raise EPlusProtocolError("decrypted media has invalid PKCS#7 padding bytes")
    return padded_plaintext[:-pad_length]


def sanitize_for_log(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in _SENSITIVE_KEYS or normalized_key in _MESSAGE_KEYS:
                sanitized[key] = REDACTED
            elif normalized_key == "url" or normalized_key.endswith("_url"):
                sanitized[key] = _sanitize_url(item, secrets)
            else:
                sanitized[key] = sanitize_for_log(item, secrets=secrets)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [sanitize_for_log(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        sanitized_text = value
        for secret in secrets:
            if secret:
                sanitized_text = sanitized_text.replace(secret, REDACTED)
        try:
            parsed = urlsplit(sanitized_text)
        except ValueError:
            return sanitized_text
        if parsed.scheme in {"http", "https", "ws", "wss"} and parsed.netloc:
            suffix = "?<redacted>" if parsed.query or parsed.fragment else ""
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")) + suffix
        return sanitized_text
    return value


def _parse_content_blocks(
    body: dict[str, Any],
    *,
    msg_type: str,
    strip_mention: bool,
) -> tuple[EPlusContentBlock, ...]:
    if msg_type == "text":
        return (_parse_text_block(_required_mapping(body, "text"), strip_mention=strip_mention),)
    if msg_type == "image":
        return (_parse_image_block(_required_mapping(body, "image")),)
    if msg_type != "mixed":
        raise EPlusProtocolError(f"unsupported message type: {msg_type!r}")

    raw_items = _required_mapping(body, "mixed").get("msg_item")
    if not isinstance(raw_items, list) or not raw_items:
        raise EPlusProtocolError("mixed.msg_item must be a non-empty list")
    blocks: list[EPlusContentBlock] = []
    text_index = 0
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise EPlusProtocolError(f"mixed.msg_item[{index}] must be an object")
        item_type = raw_item.get("msgtype")
        if item_type is None:
            if "text" in raw_item:
                item_type = "text"
            elif "image" in raw_item:
                item_type = "image"
        if item_type == "text":
            blocks.append(
                _parse_text_block(
                    _required_mapping(raw_item, "text"),
                    strip_mention=strip_mention and text_index == 0,
                )
            )
            text_index += 1
        elif item_type == "image":
            blocks.append(_parse_image_block(_required_mapping(raw_item, "image")))
        else:
            raise EPlusProtocolError(f"unsupported mixed item type at index {index}: {item_type!r}")
    return tuple(blocks)


def _parse_text_block(raw: dict[str, Any], *, strip_mention: bool) -> EPlusContentBlock:
    text = _required_string(raw, "content", allow_empty=True)
    if strip_mention:
        text = _LEADING_MENTION.sub("", text, count=1).lstrip()
    return EPlusContentBlock(kind=EPlusContentKind.TEXT, text=text)


def _parse_image_block(raw: dict[str, Any]) -> EPlusContentBlock:
    return EPlusContentBlock(
        kind=EPlusContentKind.IMAGE,
        url=_required_string(raw, "url"),
        aes_key=_required_string(raw, "aeskey"),
    )


def _required_mapping(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise EPlusProtocolError(f"{key} must be an object")
    return value


def _required_string(parent: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise EPlusProtocolError(f"{key} must be a non-empty string")
    return value


def _nonempty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise EPlusProtocolError(f"{field_name} must be a non-empty string")
    return value


def _sanitize_url(value: Any, secrets: tuple[str, ...]) -> Any:
    if not isinstance(value, str):
        return sanitize_for_log(value, secrets=secrets)
    try:
        parts = urlsplit(value)
    except ValueError:
        return REDACTED
    if not parts.scheme or not parts.netloc:
        return sanitize_for_log(value, secrets=secrets)
    suffix = "?<redacted>" if parts.query or parts.fragment else ""
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) + suffix
    return sanitize_for_log(safe_url, secrets=secrets)
