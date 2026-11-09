"""Only explicitly supplied old upload rules override unified-space defaults."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.api.v1.schemas import FileProcessBase
from bisheng.knowledge.application.file_processing_adapter import capture_legacy_processing_overrides
from bisheng.knowledge.domain.schemas.processing_settings import LegacyProcessingOverrides
from bisheng.open_endpoints.api.endpoints import filelib
from bisheng.open_mcp import application
from bisheng.open_mcp.contracts import KnowledgeFileUploadInput
from test.open_api import test_filelib_param_errors as fixtures

api = fixtures.api


@pytest.mark.parametrize(
    "explicit",
    [
        {},
        {"chunk_size": 512, "chunk_overlap": 0, "retain_images": 0, "force_ocr": 1},
        {"split_mode": "custom", "separator": "|"},
    ],
)
async def test_actual_multipart_space_upload_keeps_only_provided_rule_fields(api, monkeypatch, explicit):
    add = AsyncMock(return_value=[{"id": 81}])
    monkeypatch.setattr(filelib.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(type=3)))
    monkeypatch.setattr(filelib, "_build_space_service", lambda *args: SimpleNamespace(add_file=add))
    response = await api.client.post("/api/v2/filelib/file/7", files=fixtures._form(explicit), headers=fixtures.AUTH)
    assert response.status_code == 200, response.text
    override = add.await_args.kwargs.get("processing_overrides")
    if not explicit:
        assert override is None
    else:
        assert isinstance(override, LegacyProcessingOverrides)
        expected = dict(explicit)
        if "separator" in expected:
            expected["separator"] = [expected["separator"]]
            expected["separator_rule"] = ["after"]
        assert override.document.model_dump(exclude_none=True) == expected
        assert override.table is None
    api.process.assert_not_awaited()


@pytest.mark.parametrize(
    "explicit",
    [
        {},
        {"chunk_size": 512, "chunk_overlap": 0, "retain_images": 0, "force_ocr": 1},
        {"split_mode": "custom", "separator": ["|"], "separator_rule": ["before"]},
    ],
)
async def test_mcp_upload_preserves_explicit_zero_flags_and_omitted_defaults(monkeypatch, explicit):
    add = AsyncMock(return_value=[{"id": 81}])
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=SimpleNamespace(user_id=7)))
    monkeypatch.setattr(application.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(type=3)))
    monkeypatch.setattr(application, "_space_service", lambda *args: SimpleNamespace(add_file=add))
    await application.upload_knowledge_file(
        request=application.current_request(),
        command=KnowledgeFileUploadInput(knowledge_id=7, file_name="doc.txt", content_base64="dGVzdA==", **explicit),
        path="staged.txt",
        file_name="doc.txt",
        version_repo=None,
        doc_repo=None,
    )
    override = add.await_args.kwargs.get("processing_overrides")
    if not explicit:
        assert override is None
    else:
        assert isinstance(override, LegacyProcessingOverrides)
        assert override.document.model_dump(exclude_none=True) == explicit
        assert override.table is None


def test_legacy_separator_derivation_does_not_turn_other_defaults_into_overrides():
    request = FileProcessBase(knowledge_id=7, separator=["|", ";"], excel_rule={"slice_length": 0})
    override = capture_legacy_processing_overrides(request)
    assert override.document.model_dump(exclude_none=True) == {
        "separator": ["|", ";"],
        "separator_rule": ["after", "after"],
    }
    assert override.table.model_dump(exclude_none=True) == {"slice_length": 0}
