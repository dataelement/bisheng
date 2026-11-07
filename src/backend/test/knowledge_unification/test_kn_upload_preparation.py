"""T883: actual legacy preparation/resolver, with only download/cache IO isolated."""

import copy
import json
from dataclasses import FrozenInstanceError, is_dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Engine, event

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase, KnowledgeFileOne
from bisheng.knowledge.domain.models.knowledge import Knowledge
from test.knowledge_unification import test_legacy_file_processing_callers as fixtures

store = fixtures.store
tenant = fixtures.tenant
business = fixtures.business
admission = fixtures.admission
processing = fixtures.processing
application = fixtures.application
files = fixtures.files
legacy = fixtures.legacy


@pytest.fixture
async def staging(legacy, monkeypatch, tmp_path):
    async with legacy.files.context.sessions() as session:
        root = await session.get(Knowledge, 40)
    cls = legacy.cls
    globals_ = cls.process_one_file.__func__.__globals__
    assert cls.process_one_file.__module__ == "_legacy_rules_service"
    source = tmp_path / "abcdef123_original.bin"
    source.write_bytes("真实文件\nalpha\n".encode())
    download = Mock(return_value=(str(source), "opaque.txt"))
    cache = Mock()
    cache.get.return_value = "restored-original.txt"
    monkeypatch.setitem(globals_, "file_download", download)
    monkeypatch.setitem(globals_, "get_redis_client_sync", lambda: cache)
    forbidden = []
    for name in ("get_minio_storage_sync", "get_f048_runtime", "get_f048_resource_adapter"):
        mock = Mock(side_effect=AssertionError(f"prepare must not call {name}"))
        monkeypatch.setitem(globals_, name, mock)
        forbidden.append(mock)
    for name in ("get_file_by_condition", "add_file", "update", "delete_batch"):
        mock = Mock(side_effect=AssertionError(f"prepare must not call DAO.{name}"))
        monkeypatch.setattr(globals_["KnowledgeFileDao"], name, mock)
        forbidden.append(mock)
    cleanup = Mock(side_effect=AssertionError("prepare must not clean up objects"))
    projection = AsyncMock(side_effect=AssertionError("prepare must not project permissions"))
    monkeypatch.setattr(cls, "remove_unused_file", cleanup)
    monkeypatch.setattr(cls, "_project_library_file_created", projection)
    sql = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        sql.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        yield SimpleNamespace(
            cls=cls,
            user=legacy.files.context.user,
            root=root,
            source=source,
            download=download,
            cache=cache,
            forbidden=forbidden,
            cleanup=cleanup,
            projection=projection,
            sql=sql,
            legacy=legacy,
        )
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


def assert_preparation_only(staging):
    assert staging.sql == []
    for mock in staging.forbidden:
        mock.assert_not_called()
    staging.cleanup.assert_not_called()
    staging.projection.assert_not_called()
    staging.legacy.publish.assert_not_called()
    staging.legacy.auth.ensure_knowledge_write_sync.assert_not_called()
    staging.legacy.auth.ensure_knowledge_write_async.assert_not_called()
    staging.legacy.cls.audit_telemetry_service.telemetry_new_knowledge_file.assert_not_called()
    assert staging.legacy.storage.mock_calls == []


def prepare(staging, *, info=None, rules=None, request=None, kwargs=None):
    return staging.cls.prepare_one_file(
        staging.user,
        staging.root,
        info or KnowledgeFileOne(file_path="opaque-input"),
        {} if rules is None else rules,
        file_kwargs=kwargs,
        processing_rule_request=request,
    )


async def test_actual_file_metadata_original_name_and_frozen_private_dto(staging):
    info = KnowledgeFileOne(file_path="opaque-input")
    raw_rules = {"caller": "not-overwritten"}
    defaults = copy.deepcopy(staging.root.processing_defaults)
    result = prepare(staging, info=info, rules=raw_rules, request=FileProcessBase(knowledge_id=40))
    assert result.local_path == str(staging.source)
    assert result.download_name == "opaque.txt" and result.original_file_name == "restored-original.txt"
    assert result.md5 == "abcdef123" and result.file_size == len(staging.source.read_bytes())
    staging.download.assert_called_once_with("opaque-input")
    staging.cache.get.assert_called_once_with("file_name:opaque")
    assert raw_rules == {"caller": "not-overwritten"} and info.excel_rule is None
    assert result.file_info is not info and result.file_info.file_path == info.file_path
    parsed = json.loads(result.split_rule)
    assert parsed["chunk_size"] == 800 and parsed["force_ocr"] == 0
    assert parsed["_effective_processing"]["schema_version"] == 1
    assert parsed["_effective_processing"]["space_config_version"] == 3
    assert staging.root.processing_defaults == defaults
    assert is_dataclass(result) and not hasattr(result, "__dict__")
    assert str(staging.source) not in repr(result) and "effective_processing" not in repr(result)
    assert "opaque-input" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.file_size = 0
    assert_preparation_only(staging)


@pytest.mark.parametrize("excel", [None, {"slice_length": 17, "header_start_row": 2}])
async def test_without_snapshot_request_preserves_original_excel_and_raw_dict_mutation(staging, excel):
    info = KnowledgeFileOne(file_path="opaque-input", excel_rule=ExcelRule(**excel) if excel else None)
    rules = {"chunk_size": 123, "legacy-extra": "preserved"}
    result = prepare(staging, info=info, rules=rules)
    assert result.file_info is info
    assert info.excel_rule == ExcelRule(**excel) if excel else info.excel_rule == ExcelRule()
    assert rules["excel_rule"] == info.excel_rule.model_dump()
    assert result.split_rule == json.dumps(rules)
    assert json.loads(result.split_rule)["chunk_size"] == 123
    assert "_effective_processing" not in json.loads(result.split_rule)
    assert_preparation_only(staging)


async def test_sparse_batch_and_per_file_excel_resolve_once_without_mutating_explicit_input(staging):
    staging.download.return_value = (str(staging.source), "actual.csv")
    info = KnowledgeFileOne(file_path="opaque-input", excel_rule=ExcelRule(header_start_row=2, header_end_row=3))
    request = FileProcessBase(knowledge_id=40, excel_rule={"slice_length": 20, "append_header": 0})
    before = info.model_dump(mode="json"), request.model_dump(mode="json")
    result = prepare(staging, info=info, request=request)
    parsed = json.loads(result.split_rule)
    assert parsed["excel_rule"] == {"slice_length": 20, "header_start_row": 2, "header_end_row": 3, "append_header": 0}
    snapshot = parsed["_effective_processing"]
    assert snapshot["file_kind"] == "table"
    assert snapshot["supplied_fields_by_layer"]["file"] == ["header_end_row", "header_start_row"]
    assert (info.model_dump(mode="json"), request.model_dump(mode="json")) == before
    assert result.file_info is not info and info.excel_rule.slice_length == 10
    assert_preparation_only(staging)


@pytest.mark.parametrize("length", [None, 0, -3])
async def test_legacy_unbounded_table_snapshot_keeps_original_zero_semantics(staging, length):
    staging.download.return_value = (str(staging.source), "actual.csv")
    result = prepare(staging, request=FileProcessBase(knowledge_id=40, excel_rule={"slice_length": length}))
    parsed = json.loads(result.split_rule)
    assert parsed["excel_rule"]["slice_length"] == (44 if length is None else 0)
    assert_preparation_only(staging)


@pytest.mark.parametrize(
    "name,source,kind,mode",
    [
        ("actual.pdf", None, "document", "auto"),
        ("actual.md", None, "document", "hierarchical"),
        ("actual.mp3", None, "audio", "auto"),
        ("actual.mp4", None, "video", "auto"),
        ("actual.csv", "web_link", "web", "hierarchical"),
    ],
)
async def test_actual_download_kind_and_dedicated_rules_do_not_follow_opaque_or_restored_name(
    staging, name, source, kind, mode
):
    staging.download.return_value = (str(staging.source), name)
    request = FileProcessBase(knowledge_id=40, split_mode="hierarchical", chunk_overlap=0, append_title=False)
    result = prepare(staging, request=request, kwargs={"file_source": source})
    parsed = json.loads(result.split_rule)
    snapshot = parsed["_effective_processing"]
    assert snapshot["file_kind"] == kind and parsed["split_mode"] == mode
    assert parsed["chunk_overlap"] == 0 and parsed["append_title"] is False
    assert parsed["chunk_size"] == 800 and parsed["force_ocr"] == 0
    if kind in {"audio", "video", "web"}:
        assert "specialized" in snapshot["supplied_fields_by_layer"]
    assert_preparation_only(staging)


@pytest.mark.parametrize("failure", ["download", "size", "rule"])
async def test_prepare_io_and_real_rule_validation_fail_without_registration_or_cleanup(staging, failure):
    if failure == "download":
        staging.download.side_effect = OSError("download unavailable")
    elif failure == "size":
        staging.source.unlink()
    else:
        staging.root.processing_defaults["document"]["chunk_size"] = -1
    with pytest.raises((OSError, ValueError)):
        prepare(staging, request=FileProcessBase(knowledge_id=40))
    assert_preparation_only(staging)


async def test_original_process_one_file_consumes_prepared_dto_without_repeating_download(legacy, monkeypatch):
    async with legacy.files.context.sessions() as session:
        root = await session.get(Knowledge, 40)
    actual = legacy.cls.prepare_one_file
    seen = []

    def observe(*args, **kwargs):
        result = actual(*args, **kwargs)
        seen.append(result)
        return result

    spy = Mock(side_effect=observe)
    monkeypatch.setattr(legacy.cls, "prepare_one_file", spy)
    db_file = legacy.cls.process_one_file(
        legacy.files.context.user,
        root,
        KnowledgeFileOne(file_path="opaque-document"),
        {},
        processing_rule_request=FileProcessBase(knowledge_id=40),
    )
    assert spy.call_count == 1 and len(seen) == 1
    assert db_file.split_rule == seen[0].split_rule and db_file.file_name == seen[0].original_file_name
    assert db_file.md5 == seen[0].md5 and db_file.file_size == seen[0].file_size
    legacy.storage.put_object_sync.assert_called_once()
