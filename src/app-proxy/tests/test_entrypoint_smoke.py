"""Import the production entrypoint the way systemd does.

Every other test reaches the app through the ``proxy_client`` fixture, which
imports ``app_proxy.main`` lazily *inside* the fixture body. That kept the
test-first phase collectable, but it also meant a module-level crash in
``create_app()`` stayed invisible: the suite went green while
``uvicorn app_proxy.main:app`` — the command in the systemd unit — failed to
import at all, because ``FastAPI.add_websocket_route`` had been removed in the
FastAPI version a fresh resolve picks up.

This module imports at collection time on purpose. It is the smoke layer for
"can the service actually start", so keep the import at module scope.
"""

from app_proxy.main import app


def test_entry_routes_registered() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert any(p.endswith("/{slug}") for p in paths)
    assert any(p.endswith("/{tail:path}") for p in paths)


def test_websocket_routes_registered() -> None:
    ws_routes = [r for r in app.routes if type(r).__name__ == "WebSocketRoute"]
    assert len(ws_routes) == 2, f"expected both WS entry routes, got {ws_routes}"


def test_healthz_registered() -> None:
    assert any(getattr(route, "path", "") == "/healthz" for route in app.routes)
