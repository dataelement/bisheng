"""Reject invalid v2 parsing options before file caching, downloading or ingestion."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from bisheng.common.errcode.open_api import OpenApiCredentialMissingError
from bisheng.open_api.api import dependencies
from bisheng.open_api.api.exception_handlers import register_open_api_exception_handlers
from bisheng.open_endpoints.api.endpoints import filelib
from test.open_api.test_dependencies import service_account_principal

FLAGS = ("retain_images", "force_ocr", "enable_formula", "filter_page_header_footer")


@pytest.fixture
async def upload_api(monkeypatch):
    app = FastAPI()
    register_open_api_exception_handlers(app)
    app.include_router(filelib.router, prefix="/api/v2", dependencies=[Depends(dependencies.verify_open_api_access)])
    app.dependency_overrides[filelib.get_knowledge_document_version_repository] = lambda: None
    app.dependency_overrides[filelib.get_knowledge_document_repository] = lambda: None

    validate = AsyncMock(return_value=service_account_principal(scopes=frozenset({"knowledge:write"})))
    monkeypatch.setattr(dependencies, "validate_bearer", validate)
    operator = AsyncMock(return_value=SimpleNamespace(user_id=12, tenant_id=9))
    monkeypatch.setattr(filelib, "get_open_api_operator_async", operator)
    lookup = AsyncMock(return_value=SimpleNamespace(type=0))
    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", lookup)
    save = Mock(return_value="/tmp/upload-validation.txt")
    download = AsyncMock(return_value=("/tmp/upload-validation.txt", "upload-validation.txt"))
    monkeypatch.setattr(filelib, "save_download_file", save)
    monkeypatch.setattr(filelib, "async_file_download", download)
    process = AsyncMock(return_value=[{"id": 1421}])
    add_file = AsyncMock(return_value=[{"id": 1421}])
    monkeypatch.setattr(filelib.KnowledgeService, "aprocess_knowledge_file", process)
    monkeypatch.setattr(filelib, "_build_space_service", Mock(return_value=SimpleNamespace(add_file=add_file)))
    monkeypatch.setattr(filelib.QuotaService, "get_knowledge_space_upload_limit_bytes", AsyncMock(return_value=1024))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            validate=validate,
            operator=operator,
            lookup=lookup,
            save=save,
            download=download,
            process=process,
            add_file=add_file,
        )


async def upload(api, params: dict, source: str = "local"):
    fields = []
    for name, value in params.items():
        for item in value if isinstance(value, list) else [value]:
            fields.append((name, (None, str(item))))
    if source == "local":
        fields.append(("file", ("upload-validation.txt", b"test content", "text/plain")))
    else:
        fields.append(("file_url", (None, "https://example.test/upload-validation.txt")))
    return await api.client.post("/api/v2/filelib/file/7", files=fields, headers={"Authorization": "Bearer fixture"})


def assert_no_file_side_effects(api):
    api.save.assert_not_called()
    api.download.assert_not_awaited()
    api.operator.assert_not_awaited()
    api.lookup.assert_not_awaited()
    api.process.assert_not_awaited()
    api.add_file.assert_not_awaited()


@pytest.mark.parametrize("source", ["local", "url"])
@pytest.mark.parametrize(
    ("field", "value"),
    [("separator_rule", "middle"), ("separator_rule", ["before", "middle"])]
    + [(flag, value) for flag in FLAGS for value in ("2", "-1", "1.5", "true")],
)
async def test_invalid_parsing_option_rejected_before_file_side_effects(upload_api, source, field, value):
    response = await upload(upload_api, {field: value}, source)
    assert response.status_code == 400
    body = response.json()
    assert body["status_code"] == 400
    assert any(error["loc"][:2] == ["body", field] for error in body["status_message"])
    assert_no_file_side_effects(upload_api)


async def test_all_reported_invalid_options_are_returned_together(upload_api):
    response = await upload(upload_api, {"separator_rule": "middle", **dict.fromkeys(FLAGS, "2")})
    assert response.status_code == 400
    assert {error["loc"][1] for error in response.json()["status_message"]} == {"separator_rule", *FLAGS}
    assert_no_file_side_effects(upload_api)


@pytest.mark.parametrize("knowledge_type", [0, 1, 3])
@pytest.mark.parametrize("value", [0, 1])
async def test_valid_multipart_options_preserve_upload_and_ingestion_values(upload_api, knowledge_type, value):
    upload_api.lookup.return_value = SimpleNamespace(type=knowledge_type)
    response = await upload(
        upload_api,
        {
            "split_mode": "custom",
            "separator": ["\\n", "。"],
            "separator_rule": ["before", "after"],
            **dict.fromkeys(FLAGS, str(value)),
        },
    )
    assert (response.status_code, response.json()["status_code"]) == (200, 200)
    assert response.json()["data"] == {"id": 1421}
    upload_api.save.assert_called_once()
    upload_api.download.assert_not_awaited()
    if knowledge_type == 3:
        upload_api.add_file.assert_awaited_once()
        upload_api.process.assert_not_awaited()
    else:
        request = upload_api.process.await_args.kwargs["req_data"]
        assert request.separator_rule == ["before", "after"]
        assert request.separator == ["\\n", "。"]
        for flag in FLAGS:
            assert getattr(request, flag) == value
            assert type(getattr(request, flag)) is int
        upload_api.add_file.assert_not_awaited()


@pytest.mark.parametrize("source", ["local", "url"])
async def test_omitted_options_keep_defaults(upload_api, source):
    response = await upload(upload_api, {}, source)
    assert response.status_code == 200
    request = upload_api.process.await_args.kwargs["req_data"]
    assert request.split_mode == "auto"
    assert request.separator_rule == ["after"] * len(request.separator)
    assert [getattr(request, field) for field in FLAGS] == [1, 0, 1, 0]


async def test_both_file_sources_still_prefer_the_local_file(upload_api):
    response = await upload(upload_api, {"file_url": "https://example.test/unused.txt"})
    assert response.status_code == 200
    upload_api.save.assert_called_once()
    upload_api.download.assert_not_awaited()
    upload_api.process.assert_awaited_once()


async def test_invalid_options_do_not_bypass_credential_validation(upload_api):
    upload_api.validate.side_effect = OpenApiCredentialMissingError()
    response = await upload(upload_api, {"retain_images": "2"})
    assert (response.status_code, response.json()["status_code"]) == (401, 26001)
    assert_no_file_side_effects(upload_api)


async def test_invalid_options_do_not_bypass_scope_validation(upload_api):
    upload_api.validate.return_value = service_account_principal(scopes=frozenset({"knowledge:read"}))
    response = await upload(upload_api, {"retain_images": "2"})
    assert (response.status_code, response.json()["status_code"]) == (403, 26003)
    assert_no_file_side_effects(upload_api)
