"""Legacy API normalization at the file-processing application boundary."""

import json
from copy import deepcopy

from bisheng.api.v1.schemas import ExcelRule, FileProcessBase
from bisheng.knowledge.domain.schemas.processing_settings import (
    DocumentProcessingRule,
    EffectiveProcessingSnapshot,
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


def capture_legacy_processing_overrides(request: FileProcessBase) -> ProcessingOverrides:
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
    return ProcessingOverrides.model_validate(
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
    extension = (file_name or "").rsplit(".", 1)[-1].lower()
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
    if legacy_split_rule is not None:
        payload = json.loads(legacy_split_rule) if isinstance(legacy_split_rule, str) else deepcopy(legacy_split_rule)
        actual = FileProcessBase.model_validate(payload)
        resolved = ProcessingDefaults.model_validate(
            {
                "document": actual.model_dump(include=set(DocumentProcessingRule.model_fields)),
                "table": actual.excel_rule.model_dump(mode="json"),
            }
        )
        snapshot = ProcessingSettingsService.resolve_effective_snapshot(
            file_kind=kind,
            system_defaults=resolved,
            space_config_version=space_config_version,
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
    rule = actual.effective_rule.model_dump(mode="json")
    return FileProcessBase(knowledge_id=space_id, **({"excel_rule": rule} if actual.file_kind == "table" else rule))
