"""Verified pure protocol behavior for the production E+ integration."""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from bisheng.eplus.domain.schemas.protocol import EPlusContentKind
from bisheng.eplus.infrastructure.protocol import (
    MAX_STREAM_BYTES,
    EPlusProtocolError,
    build_ping_frame,
    build_stream_frame,
    build_subscribe_frame,
    decrypt_media,
    parse_message_callback,
    sanitize_for_log,
    stable_stream_id,
    truncate_utf8,
)


def _encrypt_media(plaintext: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(256).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def test_builds_documented_subscribe_ping_and_stream_frames() -> None:
    assert build_subscribe_frame("bot-1", "secret-1", "subscribe-1") == {
        "cmd": "aibot_subscribe",
        "headers": {"req_id": "subscribe-1"},
        "body": {"bot_id": "bot-1", "secret": "secret-1"},
    }
    assert build_ping_frame("ping-1") == {
        "cmd": "ping",
        "headers": {"req_id": "ping-1"},
    }
    assert build_stream_frame("callback-1", "stream-1", "累计内容", finish=True) == {
        "cmd": "aibot_respond_msg",
        "headers": {"req_id": "callback-1"},
        "body": {
            "msgtype": "stream",
            "stream": {"id": "stream-1", "finish": True, "content": "累计内容"},
        },
    }


def test_parses_text_image_and_mixed_content_in_original_order() -> None:
    text = parse_message_callback(
        {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": "req-text"},
            "body": {
                "msgid": "msg-text",
                "aibotid": "bot-1",
                "chattype": "single",
                "from": {"userid": "user-1"},
                "msgtype": "text",
                "text": {"content": "你好"},
            },
        }
    )
    image = parse_message_callback(
        {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": "req-image"},
            "body": {
                "msgid": "msg-image",
                "aibotid": "bot-1",
                "chattype": "single",
                "from": {"userid": "user-1"},
                "msgtype": "image",
                "image": {"url": "https://media.example.test/image?id=1", "aeskey": "key-1"},
            },
        }
    )
    mixed = parse_message_callback(
        {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": "req-mixed"},
            "body": {
                "msgid": "msg-mixed",
                "aibotid": "bot-1",
                "chatid": "group-1",
                "chattype": "group",
                "from": {"userid": "user-2"},
                "msgtype": "mixed",
                "mixed": {
                    "msg_item": [
                        {"text": {"content": "@机器人 看这张图"}},
                        {"image": {"url": "https://media.example.test/image?id=2", "aeskey": "key-2"}},
                        {"msgtype": "text", "text": {"content": "右下角是什么"}},
                    ]
                },
            },
        }
    )

    assert [(block.kind, block.text) for block in text.blocks] == [(EPlusContentKind.TEXT, "你好")]
    assert [(block.kind, block.url, block.aes_key) for block in image.blocks] == [
        (EPlusContentKind.IMAGE, "https://media.example.test/image?id=1", "key-1")
    ]
    assert [(block.kind, block.text) for block in mixed.blocks] == [
        (EPlusContentKind.TEXT, "看这张图"),
        (EPlusContentKind.IMAGE, None),
        (EPlusContentKind.TEXT, "右下角是什么"),
    ]
    assert mixed.chat_id == "group-1"
    assert mixed.sender_external_id == "user-2"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda frame: frame["headers"].pop("req_id"), "req_id"),
        (lambda frame: frame["body"].pop("msgid"), "msgid"),
        (lambda frame: frame["body"].pop("aibotid"), "aibotid"),
        (lambda frame: frame["body"]["from"].pop("userid"), "userid"),
        (lambda frame: frame["body"].update({"chattype": "group"}), "chatid"),
    ],
)
def test_rejects_callbacks_missing_protocol_identity(mutator, message: str) -> None:
    frame = {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": "req-1"},
        "body": {
            "msgid": "msg-1",
            "aibotid": "bot-1",
            "chattype": "single",
            "from": {"userid": "user-1"},
            "msgtype": "text",
            "text": {"content": "hello"},
        },
    }
    mutator(frame)

    with pytest.raises(EPlusProtocolError, match=message):
        parse_message_callback(frame)


def test_stream_id_is_stable_bot_scoped_and_utf8_limit_is_safe() -> None:
    first = stable_stream_id("bot-a", "msg-1")
    assert first == stable_stream_id("bot-a", "msg-1")
    assert first != stable_stream_id("bot-b", "msg-1")
    assert len(first) == 32

    text = "a" * (MAX_STREAM_BYTES - 2) + "中文"
    truncated, did_truncate = truncate_utf8(text)
    assert did_truncate is True
    assert truncated == "a" * (MAX_STREAM_BYTES - 2)
    with pytest.raises(EPlusProtocolError, match="20,480"):
        build_stream_frame("req-1", "stream-1", text, finish=False)


def test_decrypt_media_accepts_unpadded_key_non_aligned_ciphertext_and_large_padding() -> None:
    key = bytes(range(32))
    aes_key = base64.b64encode(key).decode("ascii").rstrip("=")

    plaintext_with_large_padding = b"fifteen-bytes!!"
    assert len(plaintext_with_large_padding) == 15
    ciphertext = _encrypt_media(plaintext_with_large_padding, key)
    assert decrypt_media(ciphertext, aes_key) == plaintext_with_large_padding

    # The customer SDK zero-aligns ciphertext before decrypting. Find a real
    # encrypted vector ending in zero, remove that byte, and require recovery.
    for suffix in range(4096):
        plaintext = f"media-{suffix}".encode()
        aligned_ciphertext = _encrypt_media(plaintext, key)
        if aligned_ciphertext.endswith(b"\x00"):
            assert decrypt_media(aligned_ciphertext[:-1], aes_key) == plaintext
            break
    else:  # pragma: no cover - probability is negligible and signals a crypto regression
        pytest.fail("could not produce a zero-terminated AES test vector")


def test_decrypt_media_rejects_invalid_key_and_padding() -> None:
    with pytest.raises(EPlusProtocolError, match="base64"):
        decrypt_media(b"ciphertext", "not-base64!")

    key = bytes(range(32))
    aes_key = base64.b64encode(key).decode("ascii")
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    invalid = encryptor.update(b"x" * 32) + encryptor.finalize()
    with pytest.raises(EPlusProtocolError, match="padding"):
        decrypt_media(invalid, aes_key)


def test_log_sanitizer_removes_credentials_message_text_and_url_query() -> None:
    payload = {
        "cmd": "aibot_subscribe",
        "body": {
            "bot_id": "bot-1",
            "secret": "top-secret",
            "image": {
                "url": "https://media.example.test/image?id=1&token=url-secret",
                "aeskey": "media-secret",
            },
            "text": {"content": "private question"},
        },
    }

    sanitized = sanitize_for_log(payload, secrets=("top-secret", "media-secret"))

    assert sanitized == {
        "cmd": "aibot_subscribe",
        "body": {
            "bot_id": "bot-1",
            "secret": "***REDACTED***",
            "image": {
                "url": "https://media.example.test/image?<redacted>",
                "aeskey": "***REDACTED***",
            },
            "text": {"content": "***REDACTED***"},
        },
    }
    rendered = repr(sanitized)
    assert "top-secret" not in rendered
    assert "media-secret" not in rendered
    assert "url-secret" not in rendered
    assert "private question" not in rendered
