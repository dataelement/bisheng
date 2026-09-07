from fastapi.routing import APIRoute, APIWebSocketRoute

from bisheng.api.router import router_rpc
from bisheng.main import app
from bisheng.open_api.api.dependencies import verify_open_api_access
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
    assert any(item.dependency is verify_open_api_access for item in router_rpc.dependencies)
    v2_routes = [route for route in app.routes if route.path.startswith("/api/v2")]
    assert v2_routes
    assert all(get_open_api_scope_marker(route.endpoint) is not None for route in v2_routes)


def test_route_registry_matches_complete_key_authenticated_surface():
    registered = {
        endpoint
        for scope in OPEN_API_SCOPES
        for endpoint in scope.endpoints
    }
    actual = actual_v2_routes()
    actual_without_whoami = actual - {("GET", "/api/v2/auth/whoami")}
    assert DAILY_ROUTES <= actual_without_whoami
    assert registered - actual_without_whoami == set()
    assert actual_without_whoami - registered == set()
    assert len([item for item in actual if item[0] == "WS"]) == 2


def test_removed_chat_routes_are_not_registered():
    paths = {path for _method, path in actual_v2_routes()}
    assert paths.isdisjoint(REMOVED_CHAT_ROUTES)
