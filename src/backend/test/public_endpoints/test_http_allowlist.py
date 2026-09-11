from fastapi.routing import APIRoute, APIWebSocketRoute

from bisheng.main import app

EXPECTED_HTTP = {
    ("GET", "/api/v3/assistant/info/{assistant_id}"),
    ("GET", "/api/v3/flows/{flow_id}"),
    ("GET", "/api/v3/chat/history"),
    ("POST", "/api/v3/chat/gen_title"),
    ("GET", "/api/v3/llm/workbench"),
    ("POST", "/api/v3/llm/workbench/asr"),
    ("POST", "/api/v3/llm/workbench/tts"),
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
        route.path for route in app.routes if isinstance(route, APIWebSocketRoute) and route.path.startswith("/api/v3")
    }

    assert http_routes == EXPECTED_HTTP
    assert websocket_routes == EXPECTED_WEBSOCKETS
    assert ("GET", "/api/v3/assistant/list") not in http_routes


def test_rpc_execution_remains_exclusive_to_authenticated_v2() -> None:
    http_routes = {
        (method, route.path) for route in app.routes if isinstance(route, APIRoute) for method in route.methods
    }
    for path in ("assistant/chat/completions", "workflow/invoke", "workflow/stop"):
        assert ("POST", f"/api/v2/{path}") in http_routes
        assert ("POST", f"/api/v3/{path}") not in http_routes
