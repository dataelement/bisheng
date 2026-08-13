from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return deepcopy(value)


def _freeze_snapshot(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be a mapping")
    return MappingProxyType({key: _freeze_value(value) for key, value in snapshot.items()})


def _require_positive_id(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


class ResourceGrantExecutorNotFoundError(RuntimeError):
    """No resource owner executor is registered for the requested type."""


@dataclass(frozen=True, slots=True)
class ResourceGrantCommand:
    """Stable Permission-owned command passed to a resource authorization owner."""

    tenant_id: int
    request_id: int
    request_fingerprint: str
    resource_type: str
    resource_id: str
    inviter_user_id: int
    target_user_id: int
    relation: str
    model_id: str | None
    include_children: bool
    role_snapshot: Mapping[str, object]
    role_fingerprint: str

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "request_id",
            "inviter_user_id",
            "target_user_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_positive_id(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "request_fingerprint",
            "resource_type",
            "resource_id",
            "relation",
            "role_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(self, "role_snapshot", _freeze_snapshot(self.role_snapshot))


@dataclass(frozen=True, slots=True)
class ResourceGrantVerificationResult:
    """Authoritative read-after-write result for an idempotent grant attempt."""

    applied: bool
    result_snapshot: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.applied, bool):
            raise ValueError("applied must be a boolean")
        object.__setattr__(self, "result_snapshot", _freeze_snapshot(self.result_snapshot))


@runtime_checkable
class ResourceGrantExecutor(Protocol):
    """Resource-owner port used by Permission without importing owner services."""

    resource_type: str

    async def execute(self, command: ResourceGrantCommand) -> None: ...

    async def verify(
        self,
        command: ResourceGrantCommand,
    ) -> ResourceGrantVerificationResult: ...


__all__ = [
    "ResourceGrantCommand",
    "ResourceGrantExecutor",
    "ResourceGrantExecutorNotFoundError",
    "ResourceGrantVerificationResult",
]
