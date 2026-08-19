from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ResourceUserInviteDispatcher(Protocol):
    """Dispatch one stable Permission business request for execution."""

    async def dispatch(self, *, tenant_id: int, request_id: int) -> None: ...


__all__ = ["ResourceUserInviteDispatcher"]
