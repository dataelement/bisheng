"""Transport-only activity metadata and an authenticated, request-local capability.

This module deliberately knows nothing about business admission or DSH storage.
Only authentication installs the capability; route metadata is server-owned.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from starlette.requests import HTTPConnection

Endpoint = TypeVar("Endpoint", bound=Callable)


@dataclass(frozen=True)
class ActivityPolicy:
    http: bool = False
    websocket_actions: frozenset[str] = frozenset()
    rpc_methods: frozenset[str] = frozenset()


def business_activity(
    *, http: bool = True, websocket_actions: tuple[str, ...] = (), rpc_methods: tuple[str, ...] = ()
) -> Callable[[Endpoint], Endpoint]:
    """Declare business entrances without wrapping or changing their signatures."""
    policy = ActivityPolicy(http, frozenset(websocket_actions), frozenset(rpc_methods))

    def mark(endpoint: Endpoint) -> Endpoint:
        endpoint.__session_activity_policy__ = policy
        return endpoint

    return mark


class AuthenticatedActivity(ABC):
    """A capability bound to one verified device, never a user-supplied callback."""

    @abstractmethod
    async def record(self) -> None:
        """Recheck and renew the authenticated device session."""


async def record_authenticated_activity(connection: HTTPConnection | None, *, message: object = None) -> None:
    """Run after authentication and before business permission/quota decisions."""
    if not isinstance(connection, HTTPConnection):
        return
    endpoint = connection.scope.get("endpoint")
    policy = getattr(endpoint, "__session_activity_policy__", None)
    if not isinstance(policy, ActivityPolicy):
        return
    if message is None:
        eligible = connection.scope["type"] == "http" and policy.http
        if getattr(connection.state, "_session_activity_recorded", False):
            return
    elif isinstance(message, dict):
        action, method = message.get("action"), message.get("method")
        eligible = (
            connection.scope["type"] == "websocket" and isinstance(action, str) and action in policy.websocket_actions
        ) or (connection.scope["type"] == "http" and isinstance(method, str) and method in policy.rpc_methods)
    else:
        return
    recorder = getattr(connection.state, "authenticated_activity", None)
    if eligible and isinstance(recorder, AuthenticatedActivity):
        await recorder.record()
        if message is None:
            connection.state._session_activity_recorded = True
