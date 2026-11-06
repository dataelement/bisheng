"""T690: honest legacy unlimited rows; new public commands stay positive."""

import pytest
from pydantic import ValidationError

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.knowledge.application.file_processing_adapter import (
    capture_legacy_processing_overrides,
    legacy_rule_from_snapshot,
    resolve_file_processing_snapshot,
)
from bisheng.knowledge.domain.schemas.processing_settings import (
    EffectiveProcessingSnapshot,
    LegacyProcessingOverrides,
    LegacyTableProcessingRule,
    ProcessingDefaults,
    ProcessingOverrides,
    TableProcessingRule,
)
from bisheng.knowledge.rag.pipeline.loader.utils.md_from_excel import _plan_chunks
from test.knowledge_unification import test_settings_repo as fixtures

system_defaults = fixtures.system_defaults


def snapshot(defaults, **kwargs):
    return resolve_file_processing_snapshot(
        file_name="source.xlsx",
        file_source="space_upload",
        system_defaults=defaults,
        space_defaults=fixtures.changed_defaults(defaults, slice_length=33),
        space_config_version=5,
        **kwargs,
    )


@pytest.mark.parametrize("length", [None, 0, -3])
def test_saved_complete_rules_keep_actual_legacy_unbounded_renderer_semantics(system_defaults, length):
    rule = FileProcessBase(knowledge_id=40, excel_rule=ExcelRule(slice_length=length))
    actual = snapshot(system_defaults, legacy_split_rule=rule.model_dump(mode="json"))
    assert isinstance(actual.effective_rule, LegacyTableProcessingRule)
    assert actual.effective_rule.slice_length == 0 and actual.effective_rule.legacy_unbounded is True
    replay = EffectiveProcessingSnapshot.model_validate(actual.model_dump(mode="json"))
    legacy = legacy_rule_from_snapshot(replay, space_id=40)
    rows = [(i, [str(i)]) for i in range(20)]
    assert _plan_chunks(rows, legacy.excel_rule.slice_length, 0, None) == _plan_chunks(rows, length, 0, None)
    assert "legacy_unbounded" not in legacy.excel_rule.model_dump()


@pytest.mark.parametrize("length", [0, -7])
def test_old_requests_explicit_nonpositive_rows_are_internal_legacy_overrides(system_defaults, length):
    explicit = capture_legacy_processing_overrides(
        FileProcessBase(knowledge_id=40, excel_rule={"slice_length": length})
    )
    assert isinstance(explicit, LegacyProcessingOverrides) and explicit.table.slice_length == length
    actual = snapshot(system_defaults, batch_overrides=explicit)
    assert actual.effective_rule.slice_length == 0 and actual.effective_rule.legacy_unbounded


def test_new_legacy_null_is_unspecified_but_saved_null_is_frozen_unbounded(system_defaults):
    request = FileProcessBase(knowledge_id=40, excel_rule={"slice_length": None})
    explicit = capture_legacy_processing_overrides(request)
    assert snapshot(system_defaults, batch_overrides=explicit).effective_rule.slice_length == 33
    assert snapshot(system_defaults, legacy_split_rule=request.model_dump(mode="json")).effective_rule.slice_length == 0


def test_new_explicit_positive_limit_overrides_legacy_unbounded_without_mutating_snapshot(system_defaults):
    saved = FileProcessBase(knowledge_id=40, excel_rule={"slice_length": 0}).model_dump(mode="json")
    original = snapshot(system_defaults, legacy_split_rule=saved)
    changed = snapshot(
        system_defaults,
        legacy_split_rule=saved,
        batch_overrides={"table": {"slice_length": 9}},
        file_overrides={"table": {"slice_length": 11}},
    )
    assert isinstance(changed.effective_rule, TableProcessingRule) and changed.effective_rule.slice_length == 11
    assert "legacy_unbounded" not in changed.effective_rule.model_dump()
    assert original.effective_rule.slice_length == 0 and saved["excel_rule"]["slice_length"] == 0


@pytest.mark.parametrize(
    "table", [{"slice_length": 0}, {"slice_length": -1}, {"slice_length": 10, "legacy_unbounded": True}]
)
def test_public_overrides_and_defaults_do_not_accept_internal_capability(system_defaults, table):
    with pytest.raises(ValidationError):
        ProcessingOverrides.model_validate({"table": table})
    payload = system_defaults.model_dump(mode="json")
    payload["table"].update(table)
    with pytest.raises(ValidationError):
        ProcessingDefaults.model_validate(payload)


def test_internal_unbounded_snapshot_requires_explicit_honest_marker(system_defaults):
    values = snapshot(system_defaults).model_dump(mode="json")
    values["effective_rule"]["slice_length"] = 0
    with pytest.raises(ValidationError):
        EffectiveProcessingSnapshot.model_validate(values)
    values["effective_rule"]["legacy_unbounded"] = True
    assert EffectiveProcessingSnapshot.model_validate(values).effective_rule.slice_length == 0
