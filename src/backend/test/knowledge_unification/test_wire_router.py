"""T196: the real cold application, its matching order, DI and OpenAPI contract."""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

SPACE = "/api/v1/knowledge/space"
CONFIRM = {"idempotency_key", "confirmation_id", "plan_digest"}

# Run production registration in a fresh process: a warmed pytest module cache
# must never hide a worker/API circular import. Only deployment file logging is
# disabled. Neither routers, endpoints, schema factories nor dependencies change.
SNAPSHOT = r"""
import json,re,sys,warnings
from bisheng.common.services.config_service import settings
settings.logger_conf.handlers = []
from bisheng.main import app
from bisheng.api.router import router,router_rpc
from bisheng.knowledge.api.router import knowledge_space_router
from fastapi.routing import APIRoute
from starlette.routing import Match

def feature(route):
    return route.path.startswith(("/api/v1/knowledge", "/api/v1/llm", "/api/v2/knowledge", "/api/v2/filelib", "/api/v1/permissions")) or ("/service-accounts/" in route.path and "/resource-grants" in route.path)
def calls(dependant):
    result=[]
    for child in dependant.dependencies:
        result.append(getattr(child.call,"__qualname__",str(child.call)))
        result.extend(calls(child))
    return result
routes=[]
shadows=[]
for route in app.routes:
    if not isinstance(route,APIRoute) or not feature(route): continue
    routes.append({"path":route.path,"methods":sorted(route.methods),"endpoint":route.endpoint.__module__+"."+route.endpoint.__qualname__,"dependencies":calls(route.dependant)})
    sample=re.sub(r"\{[^}]+\}","101",route.path)
    for method in route.methods:
        scope={"type":"http","method":method,"path":sample,"root_path":"","headers":[],"query_string":b"","scheme":"http","server":("wire.test",80)}
        first=next((candidate for candidate in app.routes if candidate.matches(scope)[0] is Match.FULL),None)
        if first is not route:
            shadows.append({"method":method,"path":route.path,"first":getattr(first,"path",None)})
with warnings.catch_warnings(record=True) as recorded:
    schema=app.openapi()

# Inspect actual cold-process constructors/registries without starting workers,
# opening SQL connections or initializing external permission transports.
import asyncio
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.open_endpoints.api.endpoints.filelib import _build_space_service
from bisheng.open_mcp.application import _space_service
from bisheng.open_mcp.registry import TOOL_DEFINITIONS
from bisheng.open_mcp.tools import TOOL_HANDLERS
from bisheng.permission.api.dependencies import get_permission_resource_normalizer
from bisheng.knowledge.application.legacy_files import make_legacy_space_service
from bisheng.open_endpoints.api import dependencies as open_dependencies
from bisheng.knowledge.api import dependencies as web_dependencies
from bisheng.worker.main import bisheng_celery
from bisheng.worker import config as worker_config
from bisheng.worker.knowledge import processing_jobs, metadata_jobs, move_jobs, space_copy_jobs, space_delete

def qualified(value):
    return value.__class__.__module__+"."+value.__class__.__qualname__
user=UserPayload(user_id=7,tenant_id=101,user_role=[])
factories={}
for name,builder in (("v2",lambda:_build_space_service(None,user,object(),object())),("mcp",lambda:_space_service(None,user,object(),object())),("legacy",lambda:make_legacy_space_service(None,user))):
    service=builder()
    first,second=service.upload_application_factory(),service.upload_application_factory()
    factories[name]={"type":qualified(first),"fresh":first is not second,"identity":first.user is user,"deletion":callable(getattr(service,"deletion_application_factory",None))}
async def bridges():
    repo,files=object(),object()
    metadata=await web_dependencies.get_knowledge_metadata_service(repo,files)
    web_file=await web_dependencies.get_knowledge_file_service(repo,files)
    open_file=await open_dependencies.get_knowledge_file_service(repo,files)
    opened=await open_dependencies.get_knowledge_service(repo,files)
    return {"web_schema":qualified(metadata.space_writer),"v2_schema":qualified(opened.metadata_service.space_writer),"web_values":qualified(web_file.metadata_value_writer),"v2_values":qualified(open_file.metadata_value_writer),"normalizer":qualified(await get_permission_resource_normalizer())}
task_names=(processing_jobs.EXECUTE_TASK,processing_jobs.SCAN_TASK,space_delete.PURGE_TASK,space_delete.SCAN_TASK)
tasks={name:{"registered":name in bisheng_celery.tasks,"queue":bisheng_celery.amqp.router.route({},name).get("queue").name} for name in task_names}
mcp=[{"name":tool.name,"route":tool.source_route,"method":tool.source_method,"handler":TOOL_HANDLERS[tool.name].__module__+"."+TOOL_HANDLERS[tool.name].__qualname__} for tool in TOOL_DEFINITIONS if tool.name.startswith("bisheng_knowledge")]
result={"routes":routes,"shadows":shadows,"schema":schema,"warnings":[str(value.message) for value in recorded],"v1":router.prefix,"v2":router_rpc.prefix,"space":knowledge_space_router.prefix,"factories":factories,"bridges":asyncio.run(bridges()),"tasks":tasks,"beat":{key:worker_config.beat_schedule[key] for key in ("knowledge-space-delete-recovery","knowledge-processing-recovery")},"mcp":mcp,"worker_handlers":{"metadata":callable(metadata_jobs.execute_metadata_job),"move":callable(move_jobs.execute_move_job),"copy":callable(space_copy_jobs.execute_copy_job),"ordinary":sorted(processing_jobs.PROCESSING_HANDLERS)}}
with open(sys.argv[1],"w") as output:json.dump(result,output)
"""


@pytest.fixture(scope="module")
def wire(tmp_path_factory):
    backend = Path(__file__).resolve().parents[2]
    output = tmp_path_factory.mktemp("f118-native-router") / "actual.json"
    result = subprocess.run(
        [sys.executable, "-c", SNAPSHOT, str(output)],
        cwd=backend,
        env={**os.environ, "PYTHONPATH": str(backend)},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-12000:]
    return json.loads(output.read_text())


def operation(wire, path, method):
    return wire["schema"]["paths"][path][method.lower()]


def dereference(wire, value):
    while "$ref" in value:
        value = wire["schema"]["components"]["schemas"][value["$ref"].rsplit("/", 1)[-1]]
    return value


def body(wire, path, method="post"):
    return dereference(wire, operation(wire, path, method)["requestBody"]["content"]["application/json"]["schema"])


def parameters(wire, path, method):
    return {value["name"]: value for value in operation(wire, path, method).get("parameters", [])}


def test_actual_registry_and_openapi_import_in_a_fresh_process(wire):
    assert (wire["v1"], wire["v2"], wire["space"]) == ("/api/v1", "/api/v2", "/knowledge/space")
    assert wire["routes"] and wire["schema"]["paths"]


def test_feature_methods_are_unique_and_no_static_endpoint_is_shadowed(wire):
    counts = Counter((method, route["path"]) for route in wire["routes"] for method in route["methods"])
    assert all(count == 1 for count in counts.values()), [value for value, count in counts.items() if count != 1]
    assert not wire["shadows"], wire["shadows"]
    # OpenAPI must not silently discard another operation at the same path.
    for method, path in counts:
        assert method.lower() in wire["schema"]["paths"][path]
    feature_ids = {operation(wire, path, method)["operationId"] for method, path in counts}
    all_ids = Counter(
        value["operationId"]
        for path in wire["schema"]["paths"].values()
        for value in path.values()
        if isinstance(value, dict) and "operationId" in value
    )
    assert all(all_ids[value] == 1 for value in feature_ids), {
        value: all_ids[value] for value in feature_ids if all_ids[value] != 1
    }
    # Warning messages include absolute source paths. A checkout named
    # "knowledge-space-unification" must not turn an unrelated multi-method
    # route's warning into a knowledge-route collision.
    duplicate_ids = {
        matched.group(1)
        for warning in wire["warnings"]
        if (matched := re.search(r"Duplicate Operation ID (\S+)", warning))
    }
    assert not feature_ids & duplicate_ids, feature_ids & duplicate_ids


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/creation-settings"),
        ("GET", "/list"),
        ("GET", "/admin/list"),
        ("GET", "/{space_id}/info"),
        ("GET", "/{space_id}/children"),
        ("POST", "/{space_id}/folders"),
        ("POST", "/{space_id}/folders/upload"),
        ("POST", "/{space_id}/files"),
        ("POST", "/{space_id}/web-links"),
        ("GET", "/{space_id}/processing-settings"),
        ("PUT", "/{space_id}/processing-settings"),
        ("GET", "/{space_id}/files/upload-settings"),
        ("GET", "/{space_id}/metadata-schema"),
        ("GET", "/{space_id}/files/{file_id}/processing-target"),
        ("POST", "/{space_id}/processing-jobs/precheck"),
        ("POST", "/{space_id}/processing-jobs"),
        ("GET", "/{space_id}/processing-jobs"),
        ("GET", "/{space_id}/processing-jobs/{job_id}"),
        ("GET", "/{space_id}/processing-jobs/{job_id}/items"),
        ("POST", "/{space_id}/processing-jobs/{job_id}/retry"),
        ("POST", "/{space_id}/files/move/precheck"),
        ("POST", "/{space_id}/files/move/confirm"),
        ("POST", "/{space_id}/copy/precheck"),
        ("POST", "/{space_id}/copy/confirm"),
        ("GET", "/{space_id}/references"),
        ("POST", "/{space_id}/files/references"),
        ("POST", "/{space_id}/files/delete/inspect"),
        ("POST", "/{space_id}/files/delete/precheck"),
        ("POST", "/{space_id}/delete/precheck"),
        ("POST", "/{space_id}/clear/precheck"),
        ("POST", "/{space_id}/deletion/confirm"),
        ("GET", "/{space_id}/deletion/{job_id}"),
        ("POST", "/{space_id}/files/batch/{operation}/inspect"),
        ("POST", "/{space_id}/files/batch/{operation}/precheck"),
        ("POST", "/{space_id}/files/batch/{operation}/confirm"),
        ("GET", "/file/{knowledge_file_id}/versions"),
        ("POST", "/version/{version_id}/set-primary"),
        ("DELETE", "/version/{version_id}"),
        ("GET", "/{space_id}/similar-pending"),
        ("GET", "/file/{knowledge_file_id}/similar"),
        ("POST", "/document/link"),
        ("POST", "/version/merge"),
    ],
)
def test_each_actual_knowledge_contract_endpoint_is_mounted_once(wire, method, suffix):
    assert operation(wire, SPACE + suffix, method)
    assert sum(route["path"] == SPACE + suffix and method in route["methods"] for route in wire["routes"]) == 1


def test_all_new_confirmation_bodies_keep_only_the_original_three_fields(wire):
    for suffix in (
        "/files/move/confirm",
        "/copy/confirm",
        "/deletion/confirm",
        "/files/batch/{operation}/confirm",
        "/processing-jobs",
    ):
        schema = body(wire, SPACE + "/{space_id}" + suffix)
        assert set(schema["properties"]) == CONFIRM
        assert set(schema["required"]) == CONFIRM
        assert schema["additionalProperties"] is False


def test_force_is_only_declared_for_whole_space_and_model_removal(wire):
    selected = body(wire, SPACE + "/{space_id}/files/delete/precheck")
    assert set(selected["properties"]) == {"items"} and selected["additionalProperties"] is False
    whole = body(wire, SPACE + "/{space_id}/delete/precheck")
    assert set(whole["properties"]) == {"force"} and whole["properties"]["force"]["default"] is False
    clear = operation(wire, SPACE + "/{space_id}/clear/precheck", "post")
    assert "requestBody" not in clear and "force" not in parameters(wire, SPACE + "/{space_id}/clear/precheck", "post")
    for method in ("put", "delete"):
        assert parameters(wire, "/api/v1/llm", method)["force"]["schema"]["default"] is False
    for suffix in ("/removal-plan", "/server-removal-plan", "/removal-sources"):
        assert operation(wire, "/api/v1/llm" + suffix, "post")


def test_processing_kind_and_retry_schema_are_explicit_closed_wire_contracts(wire):
    allowed = {
        "embedding_rebuild",
        "file_reprocess",
        "file_resplit",
        "metadata_schema_change",
        "move_index",
        "space_copy",
    }
    for suffix, method in (
        ("/processing-jobs", "get"),
        ("/processing-jobs/{job_id}", "get"),
        ("/processing-jobs/{job_id}/items", "get"),
        ("/processing-jobs/{job_id}/retry", "post"),
    ):
        kind = parameters(wire, SPACE + "/{space_id}" + suffix, method)["kind"]["schema"]
        options = [dereference(wire, option) for option in kind.get("anyOf", [kind])]
        assert next(set(option["enum"]) for option in options if "enum" in option) == allowed
    precheck = body(wire, SPACE + "/{space_id}/processing-jobs/precheck")
    assert set(precheck["properties"]["kind"]["enum"]) == allowed - {"move_index", "space_copy"}
    schema = body(wire, SPACE + "/{space_id}/processing-jobs/{job_id}/retry")
    assert set(schema["properties"]) == {"idempotency_key", "expected_job_revision"}
    assert schema["additionalProperties"] is False
    for phase in ("inspect", "precheck", "confirm"):
        schema = parameters(wire, SPACE + "/{space_id}/files/batch/{operation}/" + phase, "post")["operation"]["schema"]
        assert set(schema["enum"]) == {"download", "tag", "retry"}


def test_original_v2_faces_keep_the_registered_authenticator_and_scope_markers(wire):
    v2 = [route for route in wire["routes"] if route["path"].startswith("/api/v2/")]
    assert v2
    for route in v2:
        assert "verify_open_api_access" in route["dependencies"]
        for method in route["methods"]:
            assert operation(wire, route["path"], method)["security"]
    # These are actual F118-adapted old entry points, not invented v2 aliases.
    for method, path in (
        ("POST", "/api/v2/knowledge/upload"),
        ("POST", "/api/v2/filelib/"),
        ("POST", "/api/v2/filelib/retrieve"),
        ("DELETE", "/api/v2/filelib/{knowledge_id}"),
    ):
        assert operation(wire, path, method)


def test_actual_open_and_legacy_factories_install_native_upload_owner(wire):
    for name, factory in wire["factories"].items():
        assert factory["type"] == "bisheng.knowledge.application.space_upload.SpaceUploadApplication"
        assert factory["fresh"] and factory["identity"]
        if name in {"v2", "mcp"}:
            assert factory["deletion"]
    assert wire["bridges"] == {
        "web_schema": "bisheng.knowledge.application.metadata_legacy.LegacyMetadataWriter",
        "v2_schema": "bisheng.knowledge.application.metadata_legacy.LegacyMetadataWriter",
        "web_values": "bisheng.knowledge.application.knowledge_index_edit.KnowledgeIndexEditApplication",
        "v2_values": "bisheng.knowledge.application.knowledge_index_edit.KnowledgeIndexEditApplication",
        "normalizer": "bisheng.knowledge.application.legacy_documents.LegacyDocumentsApplication",
    }


def test_actual_mcp_knowledge_allowlist_has_real_handlers_and_original_http_faces(wire):
    assert wire["mcp"]
    for tool in wire["mcp"]:
        assert tool["handler"].startswith("bisheng.open_mcp.tools.")
        assert operation(wire, tool["route"], tool["method"])
    assert len({tool["name"] for tool in wire["mcp"]}) == len(wire["mcp"])


def test_existing_celery_tasks_beat_and_all_native_handlers_are_registered(wire):
    assert len(wire["tasks"]) == 4
    assert all(task == {"registered": True, "queue": "knowledge_celery"} for task in wire["tasks"].values())
    for key in ("knowledge-space-delete-recovery", "knowledge-processing-recovery"):
        assert wire["beat"][key]["task"] in wire["tasks"]
    assert wire["worker_handlers"] == {
        "metadata": True,
        "move": True,
        "copy": True,
        "ordinary": ["embedding_rebuild", "file_reprocess", "file_resplit"],
    }


def test_public_legacy_permission_alias_is_injected_at_actual_http_boundary(wire):
    for route in wire["routes"]:
        if route["endpoint"].startswith(
            ("bisheng.permission.api.endpoints.decision.", "bisheng.permission.api.endpoints.grant.")
        ):
            assert "get_permission_resource_normalizer" in route["dependencies"], route
