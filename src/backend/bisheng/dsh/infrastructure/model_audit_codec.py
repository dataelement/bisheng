"""Bounded, lossless JSON fragments and unambiguous content scopes."""

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class AuditScope:
    tenant_id: int
    user_id: int
    scope_type: Literal["CONVERSATION", "REQUEST"]
    scope_id: str
    encoding_version: int = 1

    def __post_init__(self):
        if (
            type(self.tenant_id) is not int
            or type(self.user_id) is not int
            or type(self.encoding_version) is not int
            or self.encoding_version < 1
            or self.tenant_id < 1
            or self.user_id < 1
            or self.scope_type not in {"CONVERSATION", "REQUEST"}
            or not isinstance(self.scope_id, str)
            or not self.scope_id
        ):
            raise ValueError("Invalid audit scope")

    @property
    def associated_data(self) -> bytes:
        return json.dumps(
            [self.tenant_id, self.user_id, self.scope_type, self.scope_id, self.encoding_version],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf8")

    @property
    def key(self) -> str:
        return sha256(self.associated_data).hexdigest()


def conversation_key(tenant_id: int, user_id: int, conversation_id: str) -> str:
    return sha256(
        json.dumps([tenant_id, user_id, conversation_id], ensure_ascii=False, separators=(",", ":")).encode("utf8")
    ).hexdigest()


def encode_chunks(value, chunk_bytes: int):
    """Yield original JSON values without allocating one full encoded body."""
    if chunk_bytes < 64:
        raise ValueError("Audit chunks must be at least 64 bytes")
    character_window = max(1, chunk_bytes // 12)

    def string_pieces(value):
        yield '"'
        for start in range(0, len(value), character_window):
            yield json.dumps(value[start : start + character_window], ensure_ascii=False)[1:-1]
        yield '"'

    def pieces(value, depth=0):
        if depth > 64:
            raise ValueError("Audit encoding depth exceeded")
        if isinstance(value, str):
            yield from string_pieces(value)
        elif isinstance(value, BaseModel):
            # Shallow fields retain required nulls without copying nested payload trees.
            fields = {
                key: item
                for key, descriptor in type(value).model_fields.items()
                if (item := getattr(value, key)) is not None or descriptor.is_required()
            }
            yield from pieces(fields, depth + 1)
        elif isinstance(value, dict):
            yield "{"
            for index, (key, item) in enumerate(value.items()):
                if not isinstance(key, str):
                    raise ValueError("Audit JSON keys must be strings")
                if index:
                    yield ","
                yield from string_pieces(key)
                yield ":"
                yield from pieces(item, depth + 1)
            yield "}"
        elif isinstance(value, (list, tuple)):
            yield "["
            for index, item in enumerate(value):
                if index:
                    yield ","
                yield from pieces(item, depth + 1)
            yield "]"
        else:
            yield json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    buffer = bytearray()
    for piece in pieces(value):
        data = piece.encode("utf8")
        offset = 0
        while offset < len(data):
            length = min(chunk_bytes - len(buffer), len(data) - offset)
            buffer.extend(data[offset : offset + length])
            offset += length
            if len(buffer) == chunk_bytes:
                boundary = len(buffer)
                try:
                    bytes(buffer).decode("utf8")
                except UnicodeDecodeError as error:
                    if error.reason != "unexpected end of data":
                        raise
                    boundary = error.start
                yield bytes(buffer[:boundary])
                del buffer[:boundary]
    if buffer:
        yield bytes(buffer)
