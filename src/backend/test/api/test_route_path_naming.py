"""Route paths must not contain "config".

Customer WAFs block URLs containing "config" (sensitive-file probe rules), so
the request never reaches the backend. New routes use "settings" instead.

LEGACY_CONFIG_ROUTES freezes the routes that predate the rule. It may only
shrink: when a route is renamed, delete it here.
"""

from fastapi.routing import APIRoute, APIWebSocketRoute

from bisheng.main import app

LEGACY_CONFIG_ROUTES = {
    ("GET", "/api/v1/web/config"),
    ("POST", "/api/v1/web/config"),
    ("GET", "/api/v1/workstation/config"),
    ("GET", "/api/v1/workstation/config/daily"),
    ("POST", "/api/v1/workstation/config/daily"),
    ("GET", "/api/v1/workstation/config/linsight"),
    ("POST", "/api/v1/workstation/config/linsight"),
    ("GET", "/api/v1/workstation/config/subscription"),
    ("POST", "/api/v1/workstation/config/subscription"),
    ("GET", "/api/v1/workstation/config/knowledge_space"),
    ("POST", "/api/v1/workstation/config/knowledge_space"),
    ("POST", "/api/v1/tool/config"),
    ("POST", "/api/v1/org-sync/configs"),
    ("GET", "/api/v1/org-sync/configs"),
    ("GET", "/api/v1/org-sync/configs/{config_id}"),
    ("PUT", "/api/v1/org-sync/configs/{config_id}"),
    ("DELETE", "/api/v1/org-sync/configs/{config_id}"),
    ("GET", "/api/v1/brand/config"),
    ("PUT", "/api/v1/brand/config"),
    ("GET", "/api/v1/brand/runtime-config"),
    ("GET", "/api/v2/workstation/config"),
}


def _config_routes():
    result = set()
    for route in app.routes:
        # Path parameter names never reach the URL, so only literal segments count.
        literal = "/".join(seg for seg in route.path.split("/") if not seg.startswith("{"))
        if "config" not in literal.lower():
            continue
        if isinstance(route, APIWebSocketRoute):
            result.add(("WS", route.path))
        elif isinstance(route, APIRoute):
            result.update((method, route.path) for method in route.methods)
    return result


def test_no_new_route_contains_config():
    assert _config_routes() - LEGACY_CONFIG_ROUTES == set()


def test_legacy_config_routes_only_shrink():
    # A renamed route left in the allowlist would let it silently come back.
    assert LEGACY_CONFIG_ROUTES - _config_routes() == set()
