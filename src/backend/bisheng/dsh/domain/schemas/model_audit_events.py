"""Fixed-channel expectations are advanced before delivery, never from stored rows."""

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Literal


class ChannelExpectation:
    def __init__(self):
        self.count = 0
        self.byte_length = 0
        self.digest = sha256()

    def observe(self, block: bytes) -> int:
        return self.observe_digest(len(block), sha256(block).hexdigest())

    def observe_digest(self, byte_length: int, digest: str) -> int:
        sequence = self.count
        self.count += 1
        self.byte_length += byte_length
        self.digest.update(byte_length.to_bytes(8, "big"))
        self.digest.update(bytes.fromhex(digest))
        return sequence

    def snapshot(self) -> dict:
        return {
            "count": self.count,
            "last_sequence": self.count - 1,
            "byte_length": self.byte_length,
            "checksum": self.digest.hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class AuditEvent:
    request_id: str
    tenant_id: int
    kind: Literal["entered", "body", "terminal", "response", "usage", "evidence", "annotation"]
    observed_at: datetime
    metadata: dict = field(default_factory=dict)
    channel: Literal["input", "output"] | None = None
    sequence: int | None = None
    unit_index: int | None = None
    body: bytes | None = field(default=None, repr=False)
