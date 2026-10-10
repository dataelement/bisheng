"""v2 filelib: caller parameter errors return HTTP 400 (or 404), never HTTP 500.

Before the fix these requests reached code that raised an unhandled
``ValidationError`` / ``ValueError`` / ``TypeError`` or ``ServerError`` (500).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from bisheng.open_api.api import dependencies
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_endpoints.api.endpoints import filelib
from test.open_api.test_dependencies import service_account_principal

AUTH = {"Authorization": "Bearer fixture"}


@pytest.fixture
async def api(monkeypatch):
    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.include_router(filelib.router, prefix="/api/v2", dependencies=[Depends(dependencies.verify_open_api_access)])
    for dep in (
        filelib.get_knowledge_document_version_repository,
        filelib.get_knowledge_document_repository,
        filelib.get_knowledge_file_repository,
    ):
        app.dependency_overrides[dep] = lambda: None

    validate = AsyncMock(
        return_value=service_account_principal(scopes=frozenset({"knowledge:read", "knowledge:write"}))
    )
    monkeypatch.setattr(dependencies, "validate_bearer", validate)
    operator = AsyncMock(return_value=SimpleNamespace(user_id=12, tenant_id=9))
    monkeypatch.setattr(filelib, "get_open_api_operator_async", operator)
    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(type=0)))
    save = Mock(return_value="/tmp/param-errors.txt")
    monkeypatch.setattr(filelib, "save_download_file", save)
    download = AsyncMock(return_value=("/tmp/param-errors.txt", "param-errors.txt"))
    monkeypatch.setattr(filelib, "async_file_download", download)
    process = AsyncMock(return_value=[{"id": 1}])
    monkeypatch.setattr(filelib.KnowledgeService, "aprocess_knowledge_file", process)
    sync_process = Mock(return_value=[{"id": 2}])
    monkeypatch.setattr(filelib.KnowledgeService, "sync_process_knowledge_file", sync_process)
    monkeypatch.setattr(filelib.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1024))
    save_kf = AsyncMock(return_value=(SimpleNamespace(id=7), [], [SimpleNamespace(id=3)], None))
    monkeypatch.setattr(filelib.KnowledgeService, "asave_knowledge_file", save_kf)
    monkeypatch.setattr(filelib.KnowledgeService, "aingest_text_chunks", AsyncMock(return_value={"id": 3}))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            save=save,
            download=download,
            process=process,
            sync_process=sync_process,
            save_kf=save_kf,
        )


def _form(params: dict, with_file: bool = True):
    fields = [(name, (None, str(value))) for name, value in params.items()]
    if with_file:
        fields.append(("file", ("a.txt", b"hello", "text/plain")))
    return fields


def _assert_400(response, field: str | None = None):
    assert response.status_code == 400, response.text
    body = response.json()
    assert body["status_code"] == 400
    if field is not None:
        assert any(err["loc"][-1] == field for err in body["status_message"]), body


SPLIT_CASES = [
    ("hierarchy_level", 0),
    ("hierarchy_level", 7),
    ("hierarchy_level", -1),
    ("max_chunk_size", 0),
    ("max_chunk_size", -5),
]


# --------------------------------------------------------------------------- #
# POST /filelib/file/{knowledge_id}
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("field", "value"), SPLIT_CASES)
async def test_upload_split_parameter_out_of_range_is_400(api, field, value):
    response = await api.client.post("/api/v2/filelib/file/7", files=_form({field: value}), headers=AUTH)
    _assert_400(response, field)
    api.save.assert_not_called()
    api.process.assert_not_awaited()


@pytest.mark.parametrize(("field", "value"), [("hierarchy_level", 1), ("hierarchy_level", 6), ("max_chunk_size", 1)])
async def test_upload_split_parameter_bounds_accepted(api, field, value):
    response = await api.client.post("/api/v2/filelib/file/7", files=_form({field: value}), headers=AUTH)
    assert response.status_code == 200
    assert getattr(api.process.await_args.kwargs["req_data"], field) == value


async def test_upload_without_file_or_file_url_is_400(api):
    response = await api.client.post(
        "/api/v2/filelib/file/7", files=_form({"split_mode": "auto"}, with_file=False), headers=AUTH
    )
    _assert_400(response)
    assert "file_url" in response.json()["status_message"]
    api.download.assert_not_awaited()
    api.process.assert_not_awaited()


async def test_upload_with_empty_file_url_is_400(api):
    response = await api.client.post(
        "/api/v2/filelib/file/7", files=_form({"file_url": ""}, with_file=False), headers=AUTH
    )
    _assert_400(response)
    api.download.assert_not_awaited()


async def test_upload_with_undownloadable_file_url_is_400(api):
    api.download.side_effect = ValueError("Check the url of your file; returned status code 404")
    response = await api.client.post(
        "/api/v2/filelib/file/7",
        files=_form({"file_url": "https://example.test/missing.pdf"}, with_file=False),
        headers=AUTH,
    )
    _assert_400(response)
    assert "returned status code 404" in response.json()["status_message"]
    api.process.assert_not_awaited()


async def test_upload_storage_failure_is_not_reported_as_caller_error(api):
    """A non-ValueError (e.g. object storage down) is a server fault, not a 400."""
    api.download.side_effect = RuntimeError("minio unavailable")
    with pytest.raises(RuntimeError):
        await api.client.post(
            "/api/v2/filelib/file/7",
            files=_form({"file_url": "https://example.test/a.pdf"}, with_file=False),
            headers=AUTH,
        )


# --------------------------------------------------------------------------- #
# POST /filelib/chunks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("field", "value"), SPLIT_CASES)
async def test_chunks_split_parameter_out_of_range_is_400(api, field, value):
    response = await api.client.post(
        "/api/v2/filelib/chunks", files=_form({"knowledge_id": 7, "metadata": "{}", field: value}), headers=AUTH
    )
    _assert_400(response, field)
    api.save.assert_not_called()
    api.sync_process.assert_not_called()


async def test_chunks_valid_split_parameters_pass(api):
    response = await api.client.post(
        "/api/v2/filelib/chunks",
        files=_form({"knowledge_id": 7, "metadata": "{}", "hierarchy_level": 6, "max_chunk_size": 1}),
        headers=AUTH,
    )
    assert response.status_code == 200
    req_data = api.sync_process.call_args.args[2]
    assert (req_data.hierarchy_level, req_data.max_chunk_size) == (6, 1)


# --------------------------------------------------------------------------- #
# POST /filelib/chunks_string
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "documents",
    [
        [{"page_content": "x", "metadata": {}}],
        [{"page_content": "x"}],
        [{"page_content": "x", "metadata": {"source": ""}}],
        [{"page_content": "x", "metadata": {"source": 12}}],
        [
            {"page_content": "x", "metadata": {"category": "faq"}},
            {"page_content": "y", "metadata": {"source": "b.txt"}},
        ],
        [],
    ],
)
async def test_chunks_string_without_source_is_400(api, documents):
    response = await api.client.post(
        "/api/v2/filelib/chunks_string", json={"knowledge_id": 7, "documents": documents}, headers=AUTH
    )
    _assert_400(response, "documents")
    api.save.assert_not_called()
    api.save_kf.assert_not_awaited()


async def test_chunks_string_with_source_passes(api):
    response = await api.client.post(
        "/api/v2/filelib/chunks_string",
        json={"knowledge_id": 7, "documents": [{"page_content": "x", "metadata": {"source": "faq.txt"}}]},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert api.save.call_args.args[2] == "faq.txt"


# --------------------------------------------------------------------------- #
# GET /filelib/download_statistic
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "file_path",
    [
        "/app/data/stat.txt",
        "/app/data/stat.log.bak",
        "/etc/passwd.log",
        "/app/data/../../etc/x.log",
        "/app/data.v2/stat.log",
        "/app/database/stat.log",
        "app/data/stat.log",
        "",
    ],
)
async def test_download_statistic_bad_path_is_400(api, file_path):
    response = await api.client.get("/api/v2/filelib/download_statistic", params={"file_path": file_path}, headers=AUTH)
    _assert_400(response, "file_path")


async def test_download_statistic_missing_file_is_404(api, monkeypatch):
    monkeypatch.setattr(filelib.os.path, "isfile", lambda _p: False)
    response = await api.client.get(
        "/api/v2/filelib/download_statistic", params={"file_path": "/app/data/statistic/none.log"}, headers=AUTH
    )
    assert (response.status_code, response.json()["status_code"]) == (404, 404)


async def test_download_statistic_existing_file_is_returned(api, monkeypatch, tmp_path):
    real = tmp_path / "stat.log"
    real.write_text("line\n")
    monkeypatch.setattr(filelib.os.path, "isfile", lambda _p: True)
    monkeypatch.setattr(filelib, "FileResponse", lambda path, filename: Response(content=real.read_bytes()))
    response = await api.client.get(
        "/api/v2/filelib/download_statistic", params={"file_path": "/app/data/statistic/stat.log"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.content == b"line\n"
