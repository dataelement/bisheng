"""Legacy API normalization at the file-processing application boundary."""

import json
from copy import deepcopy

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.knowledge.domain.schemas.processing_settings import (
    DocumentProcessingRule,
    EffectiveProcessingSnapshot,
    LegacyProcessingOverrides,
    LegacyTableProcessingRule,
    ProcessingDefaults,
    ProcessingOverrides,
    TableProcessingRule,
)
from bisheng.knowledge.domain.services.processing_settings_service import ProcessingSettingsService

_WEB_SEPARATORS = ["\n\n", "\n", "。", "\\.", "，", ",", "；", ";", "、", "\\s+", ""]  # noqa: RUF001
_TABLE_EXTENSIONS = {"xlsx", "xls", "csv", "et"}
_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "flac", "ogg"}
_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
_HIERARCHICAL_EXTENSIONS = {"md", "doc", "docx"}


def capture_legacy_processing_overrides(request: FileProcessBase) -> LegacyProcessingOverrides:
    raw = deepcopy(request._processing_explicit_input)
    document = {key: deepcopy(getattr(request, key)) for key in raw if key in DocumentProcessingRule.model_fields}
    excel = raw.get("excel_rule")
    if isinstance(excel, ExcelRule):
        excel = excel._processing_explicit_input
    table = {
        key: deepcopy(getattr(request.excel_rule, key))
        for key, value in (excel or {}).items()
        if key in TableProcessingRule.model_fields and value is not None
    }
    if "append_header" in table:
        table["append_header"] = int(bool(table["append_header"]))
    return LegacyProcessingOverrides.model_validate(
        {**({"document": document} if document else {}), **({"table": table} if table else {})}
    )


def system_processing_defaults(space_id: int) -> ProcessingDefaults:
    actual = FileProcessBase(knowledge_id=space_id)
    return ProcessingDefaults.model_validate(
        {
            "document": actual.model_dump(include=set(DocumentProcessingRule.model_fields)),
            "table": actual.excel_rule.model_dump(mode="json"),
        }
    )


def _legacy_table(table):
    result = deepcopy(table)
    start = max((result["header_start_row"] or 1) - 1, 0) + 1
    end = max(max((result["header_end_row"] or 1) - 1, 0) + 1, start)
    result.update(header_start_row=start, header_end_row=end, append_header=int(bool(result["append_header"])))
    if result["slice_length"] is None or result["slice_length"] <= 0:
        result["slice_length"] = 0
    return result


def _table_snapshot(
    *, system_defaults, space_defaults, space_config_version, legacy_table, batch_overrides, file_overrides
):
    table = _legacy_table(legacy_table) if legacy_table is not None else system_defaults.table.model_dump(mode="json")
    provenance = {"system": sorted(table)}
    if legacy_table is None and space_defaults is not None:
        table.update(space_defaults.table.model_dump(mode="json"))
        provenance["space"] = sorted(table)
    for name, value in (("batch", batch_overrides), ("file", file_overrides)):
        if value is None:
            continue
        legacy = isinstance(value, LegacyProcessingOverrides)
        parsed = (
            value
            if legacy
            else ProcessingOverrides.model_validate(
                value.model_dump(mode="json") if isinstance(value, ProcessingOverrides) else value
            )
        )
        layer = parsed.table.model_dump(mode="json", exclude_none=True) if parsed.table is not None else {}
        table.update(layer)
        provenance[name] = sorted(layer)
        if legacy:
            table = _legacy_table(table)
    rule = (
        LegacyTableProcessingRule.model_validate({**table, "legacy_unbounded": True})
        if table["slice_length"] == 0
        else TableProcessingRule.model_validate(table)
    )
    return EffectiveProcessingSnapshot(
        file_kind="table",
        effective_rule=rule,
        space_config_version=space_config_version,
        supplied_fields_by_layer=provenance,
    )


def resolve_file_processing_snapshot(
    *,
    file_name,
    file_source,
    system_defaults,
    space_defaults,
    space_config_version,
    batch_overrides=None,
    file_overrides=None,
    legacy_split_rule=None,
) -> EffectiveProcessingSnapshot:
    extension = "md" if file_source == "web_link" else (file_name or "").rsplit(".", 1)[-1].lower()
    kind = (
        "web"
        if file_source == "web_link"
        else "table"
        if extension in _TABLE_EXTENSIONS
        else "audio"
        if extension in _AUDIO_EXTENSIONS
        else "video"
        if extension in _VIDEO_EXTENSIONS
        else "document"
    )
    actual = None
    if legacy_split_rule is not None:
        payload = json.loads(legacy_split_rule) if isinstance(legacy_split_rule, str) else deepcopy(legacy_split_rule)
        actual = FileProcessBase.model_validate(payload)
    if kind == "table":
        return _table_snapshot(
            system_defaults=system_defaults,
            space_defaults=space_defaults,
            space_config_version=space_config_version,
            legacy_table=actual.excel_rule.model_dump(mode="json") if actual is not None else None,
            batch_overrides=batch_overrides,
            file_overrides=file_overrides,
        )
    # Document paths consume only document rules. An old table-only unlimited
    # setting must not invalidate an unrelated document's actual rule.
    if isinstance(batch_overrides, LegacyProcessingOverrides):
        batch_overrides = ProcessingOverrides(document=batch_overrides.document)
    if isinstance(file_overrides, LegacyProcessingOverrides):
        file_overrides = ProcessingOverrides(document=file_overrides.document)
    if legacy_split_rule is not None:
        resolved = ProcessingDefaults.model_validate(
            {
                "document": actual.model_dump(include=set(DocumentProcessingRule.model_fields)),
                "table": system_defaults.table.model_dump(mode="json"),
            }
        )
        snapshot = ProcessingSettingsService.resolve_effective_snapshot(
            file_kind=kind,
            system_defaults=resolved,
            space_config_version=space_config_version,
            batch_overrides=batch_overrides,
            file_overrides=file_overrides,
            specialized_overrides={} if kind in {"web", "audio", "video"} else None,
        )
    else:
        snapshot = ProcessingSettingsService.resolve_effective_snapshot(
            file_kind=kind,
            system_defaults=system_defaults,
            space_defaults=space_defaults,
            space_config_version=space_config_version,
            batch_overrides=batch_overrides,
            file_overrides=file_overrides,
            specialized_overrides={} if kind in {"web", "audio", "video"} else None,
        )
    values = snapshot.model_dump(mode="json")
    if kind != "table":
        rule = values["effective_rule"]
        if rule["split_mode"] == "hierarchical" and extension not in _HIERARCHICAL_EXTENSIONS:
            rule["split_mode"] = "auto"
        if kind == "web":
            rule.update(
                separator=list(_WEB_SEPARATORS), separator_rule=["after"] * len(_WEB_SEPARATORS), chunk_overlap=0
            )
    return EffectiveProcessingSnapshot.model_validate(values)


def legacy_rule_from_snapshot(snapshot, *, space_id) -> FileProcessBase:
    actual = EffectiveProcessingSnapshot.model_validate(
        snapshot.model_dump(mode="json") if isinstance(snapshot, EffectiveProcessingSnapshot) else snapshot
    )
    rule = actual.effective_rule.model_dump(mode="json", exclude={"legacy_unbounded"})
    return FileProcessBase(knowledge_id=space_id, **({"excel_rule": rule} if actual.file_kind == "table" else rule))
