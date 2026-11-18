"""Route scope declarations; no authentication or business-domain dependencies."""

from contextvars import ContextVar
from enum import StrEnum

from fastapi import APIRouter


class RequestScope(StrEnum):
    TENANT = "tenant"
    PERSONAL = "personal"
    IDENTITY = "identity"
    PLATFORM = "platform"
    CREDENTIAL = "credential"
    PUBLIC = "public"


_MARKER = "__bisheng_request_scope__"
admitted_request_scope = ContextVar("admitted_request_scope", default=None)


def get_admitted_request_scope():
    return admitted_request_scope.get()


def request_scope(kind: RequestScope):
    def declare(endpoint):
        previous = getattr(endpoint, _MARKER, None)
        if previous is not None and previous != kind:
            raise ValueError(f"Conflicting request scope: {endpoint.__qualname__}")
        setattr(endpoint, _MARKER, RequestScope(kind))
        return endpoint

    return declare


def endpoint_scope(endpoint):
    return getattr(endpoint, _MARKER, None)


def scope_overrides(router, kind: RequestScope, *names: str):
    """Name explicit mixed-router exceptions at composition, never by URL prefix."""
    remaining = set(names)
    for route in router.routes:
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__name__", None) in remaining:
            request_scope(kind)(endpoint)
            remaining.discard(endpoint.__name__)
    if remaining:
        raise ValueError(f"Unknown scope exceptions: {sorted(remaining)}")


def inherit_scope(router, kind):
    for route in router.routes:
        if endpoint_scope(getattr(route, "endpoint", None)) is None:
            if kind is None:
                raise ValueError(f"Router requires an explicit request scope: {route.path}")
            setattr(route.endpoint, _MARKER, RequestScope(kind))


def scope_query_variant(router, names, *, query, value, kind):
    remaining = set(names)
    for route in router.routes:
        if route.endpoint.__name__ in remaining:
            route.endpoint.__bisheng_scope_variant__ = query, value, RequestScope(kind)
            remaining.discard(route.endpoint.__name__)
    if remaining:
        raise ValueError(f"Unknown scope variants: {sorted(remaining)}")


class ScopedAPIRouter(APIRouter):
    def include_router(self, router, *, request_scope: RequestScope | None = None, **kwargs):
        inherit_scope(router, request_scope)
        return super().include_router(router, **kwargs)


def route_inventory(routes):
    """Same registration source drives startup validation and offline reports."""
    rows = []
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        kind = endpoint_scope(endpoint)
        if kind is None:
            raise ValueError(f"Request scope unregistered: {route.path}")
        rows.extend(
            {
                "method": method,
                "path": route.path,
                "scope": str(kind),
                "variant": getattr(endpoint, "__bisheng_scope_variant__", None),
                "endpoint": f"{endpoint.__module__}.{endpoint.__qualname__}",
            }
            for method in sorted(getattr(route, "methods", None) or ["WS"])
        )
    return rows
