from fastapi.routing import APIRoute

from bisheng.api.router import router


def test_file_change_routes_are_registered_on_v1_api():
    registered_routes = {
        (route.path, method)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    expected_routes = {
        ("/api/v1/knowledge/space/admin/file-change-policy", "GET"),
        ("/api/v1/knowledge/space/admin/file-change-policy", "PUT"),
        ("/api/v1/knowledge/space/admin/file-change-settings", "GET"),
        ("/api/v1/knowledge/space/admin/file-change-settings/{space_id}", "PUT"),
        ("/api/v1/knowledge/space/admin/file-change-configuration", "PUT"),
        ("/api/v1/knowledge/space/{space_id}/file-changes/uploads", "GET"),
        ("/api/v1/knowledge/space/{space_id}/file-changes/batch-approve", "POST"),
        ("/api/v1/knowledge/space/{space_id}/file-changes/{request_id}", "GET"),
        ("/api/v1/knowledge/space/{space_id}/file-changes/{request_id}", "DELETE"),
        (
            "/api/v1/knowledge/space/{space_id}/file-changes/{request_id}/preview",
            "GET",
        ),
        (
            "/api/v1/knowledge/space/{space_id}/file-changes/{request_id}/decision",
            "POST",
        ),
        (
            "/api/v1/knowledge/space/{space_id}/file-changes/{request_id}/retry-ingest",
            "POST",
        ),
    }

    assert expected_routes <= registered_routes
