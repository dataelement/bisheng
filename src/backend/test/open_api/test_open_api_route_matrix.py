from fastapi.routing import APIRoute, APIWebSocketRoute

from bisheng.api.router import router_rpc
from bisheng.common.services.config_service import settings
from bisheng.main import app
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.exception_handlers import MODEL_GATEWAY_PATH_PREFIX
from bisheng.open_api.domain.scopes import OPEN_API_SCOPES, get_open_api_scope_marker

REMOVED_CHAT_ROUTES = {
    "/api/v2/chat/history",
    "/api/v2/chat/gen_title",
    "/api/v2/chat/liked",
    "/api/v2/chat/solved",
    "/api/v2/chat/comment",
    "/api/v2/chat/sync/messages",
}
DAILY_ROUTES = {
    ("POST", "/api/v2/workstation/chat/completions"),
    ("GET", "/api/v2/workstation/config"),
    ("GET", "/api/v2/chat/list"),
    ("POST", "/api/v2/knowledge/upload"),
    ("GET", "/api/v2/chat/info"),
}


def actual_v2_routes():
    result = set()
    for route in app.routes:
        if not route.path.startswith("/api/v2"):
            continue
        if isinstance(route, APIWebSocketRoute):
            result.add(("WS", route.path))
        elif isinstance(route, APIRoute):
            result.update((method, route.path) for method in route.methods)
    return result


def test_every_real_v2_route_is_globally_key_protected_and_marked():
    """Every FastAPI route under /api/v2 carries the marker the dependency reads.

    The isinstance filter is not a loophole: it is the line between routes that
    ``verify_open_api_access`` governs and the one that cannot be governed by it.
    F052's MCP face is a plain Starlette ``Route`` — no ``APIRoute``, so no
    router-level dependency and no ``@open_api_scope`` marker on its endpoint —
    and it authenticates itself in ``McpAccessGate`` instead, reusing
    ``admit_open_api_principal`` and ``open_api_execution_scope``.
    ``test_mcp_route_is_gated_or_absent`` below is what holds it to that.
    """

    assert any(item.dependency is verify_open_api_access for item in router_rpc.dependencies)
    v2_routes = [
        route
        for route in app.routes
        if route.path.startswith("/api/v2") and isinstance(route, (APIRoute, APIWebSocketRoute))
    ]
    assert v2_routes
    assert all(get_open_api_scope_marker(route.endpoint) is not None for route in v2_routes)


def test_mcp_route_is_gated_or_absent():
    """The one non-APIRoute under /api/v2 — present iff the layer is on, and gated.

    Without this, the isinstance filter above would silently excuse any future
    unauthenticated Starlette route someone appends to the app.
    """

    from bisheng.common.services.config_service import settings
    from bisheng.open_api.mcp.gate import McpAccessGate
    from bisheng.open_api.mcp.server import MCP_ROUTE_PATH

    non_api_routes = [
        route
        for route in app.routes
        if route.path.startswith("/api/v2") and not isinstance(route, (APIRoute, APIWebSocketRoute))
    ]
    if not settings.open_platform.enabled:
        assert non_api_routes == []
        return

    assert [route.path for route in non_api_routes] == [MCP_ROUTE_PATH]
    assert isinstance(non_api_routes[0].endpoint, McpAccessGate)


def test_the_mcp_route_is_registered_exactly_when_the_open_capability_layer_is_on(monkeypatch):
    """Both halves of the switch, whatever this checkout's config happens to say.

    ``test_mcp_route_is_gated_or_absent`` above reads the app built at import
    time, so on a tree whose ``config.yaml`` leaves the layer off it only ever
    exercises "absent" — and the registration in ``create_app`` would be
    untested (AC-01 / AC-37). This builds the app both ways instead.
    """

    from bisheng.common.services.config_service import settings
    from bisheng.main import create_app
    from bisheng.open_api.mcp.gate import McpAccessGate
    from bisheng.open_api.mcp.server import MCP_ROUTE_PATH

    monkeypatch.setattr(settings.open_platform, "enabled", True)
    enabled = create_app()
    mounted = [route for route in enabled.routes if getattr(route, "path", None) == MCP_ROUTE_PATH]
    assert len(mounted) == 1
    route = mounted[0]
    # Not an APIRoute: it carries no ``@open_api_scope`` marker, so it must not
    # be governed by ``router_rpc``'s dependency, and it must stay out of the
    # published OpenAPI document the v2 contract test compares against.
    assert not isinstance(route, (APIRoute, APIWebSocketRoute))
    assert isinstance(route.endpoint, McpAccessGate)
    assert {"GET", "POST", "DELETE"} <= set(route.methods)
    assert MCP_ROUTE_PATH not in enabled.openapi().get("paths", {})

    monkeypatch.setattr(settings.open_platform, "enabled", False)
    disabled = create_app()
    assert [route for route in disabled.routes if getattr(route, "path", None) == MCP_ROUTE_PATH] == []


def test_route_registry_matches_complete_key_authenticated_surface():
    registered = {endpoint for scope in OPEN_API_SCOPES for endpoint in scope.endpoints}
    if not settings.open_platform.enabled:
        # The model protocol face is the one conditionally mounted sub-router
        # (F051 AC-28), and ``bisheng.main.app`` decided that at import time —
        # monkeypatching the switch here would remount nothing. Drop its
        # registrations from the expectation instead; the mounted state is
        # asserted in test_model_gateway_switch.py against a freshly built app.
        registered = {item for item in registered if not item[1].startswith(MODEL_GATEWAY_PATH_PREFIX)}
    actual = actual_v2_routes()
    actual_without_whoami = actual - {("GET", "/api/v2/auth/whoami")}
    assert DAILY_ROUTES <= actual_without_whoami
    assert registered - actual_without_whoami == set()
    assert actual_without_whoami - registered == set()
    assert len([item for item in actual if item[0] == "WS"]) == 2


def test_removed_chat_routes_are_not_registered():
    paths = {path for _method, path in actual_v2_routes()}
    assert paths.isdisjoint(REMOVED_CHAT_ROUTES)


def test_only_the_capability_faces_admit_a_hosted_application():
    """F055 AC-52 as a lockstep, because the scope alone is far too coarse.

    A hosted application's scopes come from its capability declaration, and one
    declared knowledge base derives ``knowledge:read`` — which covers seven
    routes. Six of them execute as the application's **owner**
    (``get_open_api_operator``) or, in ``download_statistic``'s case, serve any
    ``/app/data`` log file to whoever holds the scope. Only the retrieval route
    goes through ``CapabilityBusService``, which narrows to the declared
    whitelist ∩ the visiting user's own visibility.

    So the admission is per route and default-deny, and this test is the list.
    Adding a route here is a decision: it means "this route is safe for a
    subject that is an application, not a person".
    """

    expected = {
        ("POST", "/api/v2/filelib/retrieve"),
        ("POST", "/api/v2/model/v1/chat/completions"),
        ("GET", "/api/v2/model/v1/models"),
    }
    catch_all = {(method, "/api/v2/model/v1/{rest:path}") for method in ("GET", "POST", "PUT", "DELETE", "PATCH")}
    if settings.open_platform.enabled:
        expected |= catch_all
    else:
        # The model face is not mounted at all — see the note in
        # ``test_route_registry_matches_complete_key_authenticated_surface``.
        expected = {("POST", "/api/v2/filelib/retrieve")}

    admitted = set()
    for route in app.routes:
        if not getattr(route, "path", "").startswith("/api/v2") or not isinstance(route, APIRoute):
            continue
        marker = get_open_api_scope_marker(route.endpoint)
        if marker is not None and marker.hosted_app:
            admitted.update((method, route.path) for method in route.methods)

    assert admitted == expected


def test_a_route_admits_no_hosted_application_unless_it_says_so():
    """The default the list above depends on."""
    from bisheng.open_api.domain.scopes import open_api_scope

    @open_api_scope("knowledge:read")
    def _endpoint():  # pragma: no cover - never called
        return None

    assert get_open_api_scope_marker(_endpoint).hosted_app is False
