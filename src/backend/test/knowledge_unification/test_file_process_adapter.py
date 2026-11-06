"""T069: real legacy normalization, sparse explicit input and actual rules."""

from copy import deepcopy

import pytest

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase, KnowledgeFileProcess
from bisheng.knowledge.application.file_processing_adapter import (
    capture_legacy_processing_overrides,
    legacy_rule_from_snapshot,
    resolve_file_processing_snapshot,
)
from test.knowledge_unification import test_settings_repo as fixtures

system_defaults = fixtures.system_defaults
changed_defaults = fixtures.changed_defaults


def resolve(defaults, **kwargs):
    return resolve_file_processing_snapshot(
        file_name=kwargs.pop("file_name", "source.txt"),
        file_source=kwargs.pop("file_source", "space_upload"),
        system_defaults=defaults,
        space_defaults=kwargs.pop("space_defaults", None),
        space_config_version=7,
        **kwargs,
    )


def test_before_defaults_capture_does_not_mutate_input_or_serialize_private_values():
    raw = {"knowledge_id": 40, "chunk_size": None, "force_ocr": None, "separator": ["!"], "separator_rule": ["before"]}
    before = deepcopy(raw)
    request = FileProcessBase.model_validate(raw)
    assert raw == before
    overrides = capture_legacy_processing_overrides(request).model_dump(exclude_none=True)
    assert overrides == {"document": {"separator": ["!"], "separator_rule": ["before"]}}
    assert request.force_ocr == 1 and request.chunk_size == 1000
    assert not any(key.startswith("_") for key in request.model_dump())
    assert capture_legacy_processing_overrides(FileProcessBase(knowledge_id=40)).model_dump(exclude_none=True) == {}


def test_each_file_excel_explicit_fields_survive_nested_normalization():
    request = KnowledgeFileProcess.model_validate(
        {
            "knowledge_id": 40,
            "excel_rule": {"slice_length": 12},
            "file_list": [{"file_path": "ignored.xlsx", "excel_rule": {"header_start_row": 2, "header_end_row": 3}}],
        }
    )
    assert capture_legacy_processing_overrides(request).table.model_dump(exclude_none=True) == {"slice_length": 12}
    file_request = FileProcessBase(knowledge_id=40, excel_rule=request.file_list[0].excel_rule)
    assert capture_legacy_processing_overrides(file_request).table.model_dump(exclude_none=True) == {
        "header_start_row": 2,
        "header_end_row": 3,
    }
    assert (
        capture_legacy_processing_overrides(FileProcessBase(knowledge_id=40, excel_rule=ExcelRule())).model_dump(
            exclude_none=True
        )
        == {}
    )


def test_explicit_key_capture_keeps_existing_legacy_type_normalization():
    request = FileProcessBase(knowledge_id=40, chunk_size="400", excel_rule={"slice_length": "20"})
    assert request.chunk_size == 400 and request.excel_rule.slice_length == 20
    explicit = capture_legacy_processing_overrides(request)
    assert explicit.document.chunk_size == 400 and explicit.table.slice_length == 20


def test_system_space_batch_file_priority_and_table_separation(system_defaults):
    space = changed_defaults(system_defaults, chunk_size=800, slice_length=20)
    doc = resolve(
        system_defaults,
        space_defaults=space,
        batch_overrides={"document": {"chunk_size": 600}, "table": {"slice_length": 30}},
        file_overrides={"document": {"chunk_size": 400}},
    )
    assert doc.effective_rule.chunk_size == 400 and doc.space_config_version == 7
    table = resolve(
        system_defaults,
        file_name="table.xlsx",
        space_defaults=space,
        batch_overrides={"document": {"chunk_size": 2}, "table": {"slice_length": 30}},
        file_overrides={"table": {"slice_length": 40}},
    )
    assert table.file_kind == "table" and table.effective_rule.slice_length == 40
    assert "chunk_size" not in table.effective_rule.model_dump()
    actual = legacy_rule_from_snapshot(table, space_id=40)
    assert actual.excel_rule.slice_length == 40


@pytest.mark.parametrize("name,kind", [("clip.mp3", "audio"), ("clip.mp4", "video"), ("source.pdf", "document")])
def test_actual_loader_capabilities_do_not_invent_hierarchical_support(system_defaults, name, kind):
    result = resolve(system_defaults, file_name=name, batch_overrides={"document": {"split_mode": "hierarchical"}})
    assert result.file_kind == kind and result.effective_rule.split_mode == "auto"


def test_web_rules_win_and_legacy_complete_rule_never_inherits_new_defaults(system_defaults):
    web = resolve(
        system_defaults,
        file_name="page.md",
        file_source="web_link",
        batch_overrides={"document": {"separator": ["!"], "separator_rule": ["before"], "chunk_overlap": 10}},
    )
    assert web.effective_rule.chunk_overlap == 0 and web.effective_rule.separator[-1] == ""
    old = FileProcessBase(knowledge_id=40, chunk_size=333).model_dump(mode="json")
    frozen = resolve(
        system_defaults, space_defaults=changed_defaults(system_defaults, chunk_size=900), legacy_split_rule=old
    )
    assert frozen.effective_rule.chunk_size == 333
    old["chunk_size"] = 444
    assert frozen.effective_rule.chunk_size == 333
    assert legacy_rule_from_snapshot(frozen, space_id=40).knowledge_id == 40


def test_new_historical_operation_applies_explicit_overrides_to_old_actual_rules(system_defaults):
    old = FileProcessBase(
        knowledge_id=40, chunk_size=333, chunk_overlap=17, excel_rule={"slice_length": 12}
    ).model_dump(mode="json")
    current_space = changed_defaults(system_defaults, chunk_size=900, slice_length=99)
    changed = resolve(
        system_defaults,
        space_defaults=current_space,
        legacy_split_rule=old,
        batch_overrides={"document": {"chunk_size": 222}},
        file_overrides={"document": {"chunk_overlap": 3}},
    )
    assert changed.effective_rule.chunk_size == 222 and changed.effective_rule.chunk_overlap == 3
    assert changed.effective_rule.force_ocr == old["force_ocr"]
    table = resolve(
        system_defaults,
        file_name="old.xlsx",
        space_defaults=current_space,
        legacy_split_rule=old,
        batch_overrides={"table": {"slice_length": 30}},
        file_overrides={"table": {"slice_length": 40}},
    )
    assert table.effective_rule.slice_length == 40
    assert old["chunk_size"] == 333 and old["excel_rule"]["slice_length"] == 12
