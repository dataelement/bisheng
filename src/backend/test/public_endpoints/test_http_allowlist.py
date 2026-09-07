from fastapi.routing import APIRoute, APIWebSocketRoute

from bisheng.main import app

EXPECTED_HTTP = {
    ("POST", "/api/v3/workflow/invoke"),
    ("POST", "/api/v3/workflow/stop"),
    ("POST", "/api/v3/assistant/chat/completions"),
    ("GET", "/api/v3/assistant/info/{assistant_id}"),
    ("GET", "/api/v3/flows/{flow_id}"),
    ("GET", "/api/v3/chat/history"),
    ("POST", "/api/v3/chat/gen_title"),
}
EXPECTED_WEBSOCKETS = {
    "/api/v3/workflow/chat/{workflow_id}",
    "/api/v3/assistant/chat/{assistant_id}",
}


def test_public_v3_route_allowlist_is_exact() -> None:
    http_routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v3")
        for method in route.methods
    }
    websocket_routes = {
        route.path
        for route in app.routes
        if isinstance(route, APIWebSocketRoute) and route.path.startswith("/api/v3")
    }

    assert http_routes == EXPECTED_HTTP
    assert websocket_routes == EXPECTED_WEBSOCKETS
    assert ("GET", "/api/v3/assistant/list") not in http_routes
