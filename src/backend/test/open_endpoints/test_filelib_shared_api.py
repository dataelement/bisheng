import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from bisheng.common.errcode.knowledge import KnowledgeSharedStorageUnavailableError
from bisheng.common.errcode.knowledge_space import KnowledgeDocumentStateConflictError, SpacePermissionDeniedError
from bisheng.open_endpoints.api import dependencies
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_endpoints.domain.services.filelib_space_query_service import FilelibSpaceQueryService


def client_for(*, query=None, command=None):
    app = FastAPI()
    app.include_router(filelib.router, prefix="/api/v2")
    app.dependency_overrides[dependencies.get_filelib_request_user] = lambda: SimpleNamespace(user_id=5, tenant_id=1)
    if query is not None:
        app.dependency_overrides[dependencies.get_filelib_space_query_service] = lambda: query
    if command is not None:
        app.dependency_overrides[dependencies.get_filelib_space_command_service] = lambda: command
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "body", "operation"),
    [
        ("post", "/", {"name": "资料"}, "create"),
        ("put", "/", {"knowledge_id": 7, "name": "资料"}, "update"),
        ("delete", "/7", None, "delete_space"),
        ("delete", "/clear/7", None, "clear"),
        ("delete", "/file/12", None, "delete_files"),
        ("post", "/delete_file", [12], "delete_files"),
        (
            "post",
            "/chunks_string",
            {"knowledge_id": 7, "documents": [{"page_content": "正文", "metadata": {}}]},
            "ingest_strings",
        ),
    ],
)
def test_file_commands_delegate_without_touching_qa(method, path, body, operation):
    command = SimpleNamespace(
        **{
            name: AsyncMock(return_value={"id": 7})
            for name in ["create", "update", "delete_space", "clear", "delete_files", "ingest_strings"]
        }
    )
    with client_for(command=command) as client:
        response = client.request(method, "/api/v2/filelib" + path, **({"json": body} if body is not None else {}))
    assert response.status_code in {200, 201}
    assert response.json()["status_code"] == 200
    assert getattr(command, operation).await_count == 1
    if operation == "create":
        assert command.create.await_args.args[0].type == 3


@pytest.mark.parametrize("path", ["/file/7", "/chunks"])
def test_upload_rejects_before_saving_or_downloading(path, monkeypatch):
    command = SimpleNamespace(
        prepare_upload=AsyncMock(side_effect=HTTPException(422, "SPACE required")), upload=AsyncMock()
    )
    save = MagicMock(side_effect=AssertionError("must reject before persisting upload"))
    monkeypatch.setattr(filelib, "save_download_file", save)
    with client_for(command=command) as client:
        response = client.post(
            "/api/v2/filelib" + path,
            data={"knowledge_id": "7", "metadata": "{}"},
            files={"file": ("a.txt", b"data", "text/plain")},
        )
    assert response.status_code == 422
    save.assert_not_called()
    command.upload.assert_not_awaited()


@pytest.mark.parametrize("path", ["/file/7", "/chunks"])
def test_upload_preserves_process_parameters_and_success_shape(path, monkeypatch):
    command = SimpleNamespace(prepare_upload=AsyncMock(), upload=AsyncMock(return_value=[{"id": 99, "status": 2}]))
    monkeypatch.setattr(filelib, "save_download_file", lambda *args: "/tmp/f112-upload.txt")
    with client_for(command=command) as client:
        response = client.post(
            "/api/v2/filelib" + path,
            data={"knowledge_id": "7", "metadata": "{}", "chunk_size": "500"},
            files={"file": ("a.txt", b"data", "text/plain")},
        )
    assert response.status_code == 200 and response.json()["data"] == {"id": 99, "status": 2}
    data = command.upload.await_args.args[0]
    assert data.knowledge_id == 7 and data.chunk_size == 500
    assert command.upload.await_args.kwargs.get("synchronous", False) == (path == "/chunks")


@pytest.mark.parametrize("kind", [0, 1, 2])
def test_explicit_old_create_type_is_rejected(kind):
    command = SimpleNamespace(create=AsyncMock())
    with client_for(command=command) as client:
        response = client.post("/api/v2/filelib/", json={"name": "资料", "type": kind})
    assert response.status_code == 422
    command.create.assert_not_awaited()


@pytest.mark.parametrize(("kind", "tenant", "expected"), [(0, 1, HTTPException), (3, 2, SpacePermissionDeniedError)])
async def test_real_guard_rejects_old_types_and_cross_tenant(kind, tenant, expected):
    repository = SimpleNamespace(
        get_space=AsyncMock(return_value=SimpleNamespace(id=7, type=kind, tenant_id=tenant, state=1))
    )
    owner = SimpleNamespace(_require_read_permission=AsyncMock())
    query = FilelibSpaceQueryService(
        request=None, user=SimpleNamespace(tenant_id=1), repository=repository, space_service=owner
    )
    with pytest.raises(expected):
        await query.require_space(7)
    owner._require_read_permission.assert_not_awaited()


async def test_freeze_blocks_commands_but_keeps_legal_reads(monkeypatch):
    route = SimpleNamespace(write_frozen=True)
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_query_service.aresolve_space_shared_routing",
        AsyncMock(return_value=route),
    )
    query = FilelibSpaceQueryService(
        request=None, user=SimpleNamespace(tenant_id=1), repository=None, space_service=None
    )
    assert await query.route() is route
    with pytest.raises(KnowledgeDocumentStateConflictError):
        await query.route(write=True)


@pytest.mark.parametrize("failure", [None, ConnectionError("route DB unavailable")])
async def test_uninitialized_or_unavailable_route_has_explicit_safe_error(monkeypatch, failure):
    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_space_query_service.aresolve_space_shared_routing",
        AsyncMock(return_value=None, side_effect=failure),
    )
    query = FilelibSpaceQueryService(
        request=None, user=SimpleNamespace(tenant_id=1), repository=None, space_service=None
    )
    with pytest.raises(KnowledgeSharedStorageUnavailableError) as error:
        await query.route()
    assert error.value.code == 10973 and error.value.http_status == 503
    assert "route DB" not in str(error.value)


def test_qa_and_statistic_function_asts_are_unchanged():
    expected = {
        "download_statistic_file": "352e7def5aed8cc6d3e392bf84b9229ca7b91cffb0d0b865d5837706db5394d8",
        "add_qa": "35f3df7c5833608e8185d174fb535cc43a4cdfffca2efba1cd94dcc945bcb564",
        "append_qa": "d4a3cf66501c7020a7491d9a3a1ff2fc2feca13ace4ca85be0b50c96af5a3531",
        "delete_qa_data": "72270ff9558f475c299a7140516e5cf184f24d87533e8f462fc1ddf3a701bc89",
        "update_qa": "14f123029e5fca190bee5e158e591e05cb74c1ac8809d970a861a41883e7e605",
        "detail_qa": "ea4c950110ed6503cdbe8c21c7eae1f79c00e2f51f48e1dd5314613e8da72369",
        "query_qa": "fb6fb72f67ece8ad0530c6c89f4da7769d89a642ec73acdeecc92c7e11b09d3f",
    }
    tree = ast.parse(Path(filelib.__file__).read_text())
    actual = {
        n.name: hashlib.sha256(ast.dump(n, include_attributes=False).encode()).hexdigest()
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in expected
    }
    assert actual == expected
