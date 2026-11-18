import importlib


def test_formal_routes_declare_capabilities_without_browser_dependencies():
    name = "bisheng.open_endpoints.api.endpoints.kunlian_workflow_api"
    assert importlib.util.find_spec(name) is not None, "formal Workflow routes missing"
    module = importlib.import_module(name)
    routes = module.router.routes
    assert len(routes) >= 19
    assert all(getattr(route.endpoint, "kunlian_capability", None) for route in routes)
    delete_routes = [route for route in routes if "DELETE" in route.methods]
    assert [(route.path, route.endpoint.kunlian_capability) for route in delete_routes] == [
        ("/api/v2/kunlian/workflows/{workflow_id}", "write")
    ]
