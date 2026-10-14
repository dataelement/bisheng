"""Validated protocol-neutral E+ callback values."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EPlusContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"


@dataclass(frozen=True, slots=True)
class EPlusContentBlock:
    kind: EPlusContentKind
    text: str | None = None
    url: str | None = None
    aes_key: str | None = None


@dataclass(frozen=True, slots=True)
class EPlusCallback:
    req_id: str
    msg_id: str
    bot_id: str
    sender_external_id: str
    chat_type: str
    chat_id: str | None
    msg_type: str
    blocks: tuple[EPlusContentBlock, ...]
