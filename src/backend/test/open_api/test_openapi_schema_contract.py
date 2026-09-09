import json
from pathlib import Path

from bisheng.main import app
from bisheng.open_api.api.openapi_schema import BEARER_SCHEME_NAME


def test_all_v2_http_operations_publish_bearer_security():
    schema = app.openapi()
    assert schema["components"]["securitySchemes"][BEARER_SCHEME_NAME]["scheme"] == "bearer"
    operations = [
        operation
        for path, path_item in schema["paths"].items()
        if path.startswith("/api/v2")
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert operations
    assert all(operation["security"] == [{BEARER_SCHEME_NAME: []}] for operation in operations)


def test_daily_chat_openapi_contract_is_narrow():
    schema = app.openapi()
    operation = schema["paths"]["/api/v2/workstation/chat/completions"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    component_name = request_schema["$ref"].rsplit("/", 1)[-1]
    properties = schema["components"]["schemas"][component_name]["properties"]

    assert "files" in properties
    assert "task_mode" not in properties
    assert "use_knowledge_base" not in properties


def test_generated_customer_contract_matches_registered_v2_http_routes():
    contract_path = (
        Path(__file__).resolve().parents[4]
        / "features/v3.0.0-beta1/053-openapi-auth-and-identity/openapi-v2-key-auth-api.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    actual = app.openapi()
    expected_operations = {
        (path, method)
        for path, path_item in actual["paths"].items()
        if path.startswith("/api/v2/")
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    documented_operations = {
        (path, method)
        for path, path_item in contract["paths"].items()
        for method in path_item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert documented_operations == expected_operations
    assert all(
        operation["security"] == [{BEARER_SCHEME_NAME: []}]
        for path_item in contract["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    )

    schemas = contract["components"]["schemas"]
    referenced = {
        ref.rsplit("/", 1)[-1]
        for ref in _collect_refs({"paths": contract["paths"], "schemas": schemas})
        if ref.startswith("#/components/schemas/")
    }
    assert referenced <= schemas.keys()

    workflow_ref = contract["paths"]["/api/v2/workflow/invoke"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    workflow_properties = schemas[workflow_ref.rsplit("/", 1)[-1]]["properties"]
    assert "input" in workflow_properties


def _collect_refs(value):
    if isinstance(value, dict):
        refs = [value["$ref"]] if isinstance(value.get("$ref"), str) else []
        return refs + [ref for item in value.values() for ref in _collect_refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _collect_refs(item)]
    return []
