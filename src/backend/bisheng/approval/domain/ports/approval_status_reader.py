from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ApprovalStatusSnapshot:
    """Minimal immutable approval fact exposed to business read models."""

    instance_id: int
    status: str

    def __post_init__(self) -> None:
        if isinstance(self.instance_id, bool) or not isinstance(self.instance_id, int) or self.instance_id <= 0:
            raise ValueError("approval instance id must be a positive integer")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("approval instance status must not be empty")
        object.__setattr__(self, "status", self.status.strip())


@runtime_checkable
class ApprovalStatusReadPort(Protocol):
    """Batch-read approval statuses without exposing persistence or payloads."""

    async def get_statuses(
        self,
        *,
        tenant_id: int,
        approval_instance_ids: Sequence[int],
    ) -> Mapping[int, ApprovalStatusSnapshot]: ...


__all__ = [
    "ApprovalStatusReadPort",
    "ApprovalStatusSnapshot",
]
