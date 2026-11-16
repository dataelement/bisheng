import importlib


def test_formal_routes_declare_capabilities_without_browser_dependencies():
    name = "bisheng.open_endpoints.api.endpoints.kunlian_workflow_api"
    assert importlib.util.find_spec(name) is not None, "formal Workflow routes missing"
    module = importlib.import_module(name)
    routes = module.router.routes
    assert len(routes) >= 18
    assert all(getattr(route.endpoint, "kunlian_capability", None) for route in routes)
    assert not any("DELETE" in route.methods for route in routes)
