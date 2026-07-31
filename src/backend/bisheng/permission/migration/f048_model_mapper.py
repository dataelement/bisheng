"""Pure legacy permission-model and action mapper for F048."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256

from bisheng.permission.domain.services.catalog_policy import (
    ACTION_RESOURCE_SCOPES,
    REGISTERED_ACTION_CODES,
    CatalogAction,
    CatalogActionRelease,
    derive_action_release,
)
from bisheng.permission.domain.services.model_policy import (
    CustomModelSelection,
    derive_permission_models,
)

INITIAL_ACTION_LEVELS: dict[str, int] = {
    "manage_permission": 3,
    "rename": 2,
    "edit": 2,
    "create_folder": 2,
    "upload_file": 2,
    "move": 2,
    "download": 1,
    "delete": 4,
    "share": 3,
    "use": 1,
    "publish": 3,
    "unpublish": 3,
}
STANDARD_RELATION_LEVELS = {
    "viewer": 1,
    "editor": 2,
    "manager": 3,
    "owner": 4,
}
LEGACY_MANAGE_TIER_LEVELS = {
    "viewer": frozenset({1, 2}),
    "user": frozenset({1, 2}),
    "editor": frozenset({1, 2}),
    "manager": frozenset({1, 2, 3}),
    "owner": frozenset({1, 2, 3, 4}),
    "relation": frozenset({1, 2, 3, 4}),
}
_MODEL_KEY_PATTERN = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True, slots=True)
class LegacyPermissionModel:
    source_key: str
    name: str
    relation: str | None
    permissions: tuple[str, ...]
    is_system: bool = False
    permissions_explicit: bool = True
    active: bool | None = None
    grantable_relations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelMappingDifference:
    source_key: str
    difference_type: str
    message: str
    severity: str = "BLOCKER"


@dataclass(frozen=True, slots=True)
class MappedLegacyModel:
    model_key: str
    legacy_source_key: str
    name: str
    action_codes: tuple[str, ...]
    derived_level: int | None
    active: bool
    allow_same_level: bool


@dataclass(frozen=True, slots=True)
class LegacyModelMappingResult:
    action_release: CatalogActionRelease
    standard_references: dict[str, str]
    custom_models: tuple[MappedLegacyModel, ...]
    differences: tuple[ModelMappingDifference, ...]
    blockers: tuple[str, ...]


def build_initial_action_release() -> CatalogActionRelease:
    """Build the complete, normalized initial action Catalog."""

    actions = tuple(
        CatalogAction(
            code=code,
            name=code,
            level=INITIAL_ACTION_LEVELS[code],
            active=True,
            resource_types=ACTION_RESOURCE_SCOPES[code],
            sort_order=index,
        )
        for index, code in enumerate(REGISTERED_ACTION_CODES)
    )
    return derive_action_release(actions)


def map_legacy_action(permission_id: str) -> str | None:
    """Map one old permission ID to zero or one concrete F048 action."""

    normalized = permission_id.strip().casefold()
    if not normalized:
        raise ValueError("legacy permission id is empty")
    if normalized in REGISTERED_ACTION_CODES:
        return normalized
    if normalized.startswith("view_") or normalized == "accesstype.dashboard":
        return None
    if normalized.startswith("manage_"):
        return "manage_permission"
    if normalized in {"rename_folder", "rename_file"}:
        return "rename"
    if normalized.startswith("edit_") or normalized in {
        "dashboard_write",
        "accesstype.dashboard_write",
    }:
        return "edit"
    if normalized == "create_folder":
        return "create_folder"
    if normalized == "upload_file":
        return "upload_file"
    if normalized in {"move_folder", "move_file"}:
        return "move"
    if normalized in {"download_folder", "download_file"}:
        return "download"
    if normalized.startswith("delete_"):
        return "delete"
    if normalized.startswith("share_"):
        return "share"
    if normalized in {"use_app", "use_kb", "use_tool"}:
        return "use"
    if normalized == "publish_app":
        return "publish"
    if normalized == "unpublish_app":
        return "unpublish"
    raise ValueError(f"unknown legacy permission id: {permission_id}")


def _stable_model_key(model: LegacyPermissionModel) -> str:
    digest = sha256(model.source_key.encode("utf-8")).hexdigest()[:10]
    if model.is_system:
        relation = (model.relation or "unknown").strip().casefold()
        return f"legacy-system-{relation}-{digest}"
    slug = _MODEL_KEY_PATTERN.sub(
        "-",
        model.source_key.strip().casefold(),
    ).strip("-_")
    slug = slug[:32] or "model"
    return f"legacy-custom-{slug}-{digest}"


def _manage_target_levels(model: LegacyPermissionModel) -> set[int]:
    if model.grantable_relations:
        try:
            return {STANDARD_RELATION_LEVELS[row] for row in model.grantable_relations}
        except KeyError as exc:
            raise ValueError(f"unknown grantable relation: {exc.args[0]}") from exc

    levels: set[int] = set()
    for permission_id in model.permissions:
        normalized = permission_id.strip().casefold()
        if not normalized.startswith("manage_"):
            continue
        suffix = normalized.rsplit("_", 1)[-1]
        levels.update(LEGACY_MANAGE_TIER_LEVELS.get(suffix, ()))
    return levels


def _infer_same_level(
    model: LegacyPermissionModel,
    *,
    derived_level: int,
) -> tuple[bool, bool]:
    source_levels = _manage_target_levels(model)
    target_levels = {level for level in source_levels if level <= derived_level}
    clamped = target_levels != source_levels
    lower = set(range(1, derived_level))
    lower_and_same = set(range(1, derived_level + 1))
    if target_levels == lower:
        return False, clamped
    if target_levels == lower_and_same:
        return True, clamped
    raise ValueError("NON_CONTIGUOUS_MANAGE_BOUNDARY")


def _mapped_actions(
    model: LegacyPermissionModel,
    action_release: CatalogActionRelease,
) -> tuple[str, ...]:
    mapped: set[str] = set()
    for permission_id in model.permissions:
        action = map_legacy_action(permission_id)
        if action is not None:
            mapped.add(action)
    return tuple(action.code for action in action_release.actions if action.code in mapped)


def map_legacy_models(
    models: tuple[LegacyPermissionModel, ...],
) -> LegacyModelMappingResult:
    """Map legacy models without guessing missing actions or manage ranges."""

    action_release = build_initial_action_release()
    standard_actions = {
        model.model_key: model.action_codes
        for model in derive_permission_models(action_release).models
        if model.kind == "STANDARD"
    }
    standard_references: dict[str, str] = {}
    candidates: list[tuple[LegacyPermissionModel, CustomModelSelection, str]] = []
    differences: list[ModelMappingDifference] = []
    seen_sources: dict[str, LegacyPermissionModel] = {}

    for model in models:
        existing = seen_sources.get(model.source_key)
        if existing is not None:
            if existing != model:
                differences.append(
                    ModelMappingDifference(
                        source_key=model.source_key,
                        difference_type="CONFLICTING_MODEL_SOURCE",
                        message="one legacy model key has conflicting snapshots",
                    )
                )
            continue
        seen_sources[model.source_key] = model
        relation = (model.relation or "").strip().casefold()
        if model.is_system and not model.permissions_explicit and relation in STANDARD_RELATION_LEVELS:
            standard_references[model.source_key] = relation
            continue

        try:
            action_codes = _mapped_actions(model, action_release)
        except ValueError as exc:
            differences.append(
                ModelMappingDifference(
                    source_key=model.source_key,
                    difference_type="UNKNOWN_LEGACY_ACTION",
                    message=str(exc),
                )
            )
            continue
        if not action_codes and not any(
            permission_id.strip().casefold().startswith("view_")
            or permission_id.strip().casefold() == "accesstype.dashboard"
            for permission_id in model.permissions
        ):
            differences.append(
                ModelMappingDifference(
                    source_key=model.source_key,
                    difference_type="EMPTY_MODEL_AFTER_VIEW_REMOVAL",
                    message="legacy model has no concrete action after view removal",
                )
            )
            continue
        if not action_codes:
            differences.append(
                ModelMappingDifference(
                    source_key=model.source_key,
                    difference_type="VISIBILITY_ONLY_MODEL_PRESERVED",
                    message="legacy view-only model is preserved without business actions",
                    severity="INFO",
                )
            )
        if model.is_system and relation in STANDARD_RELATION_LEVELS and action_codes == standard_actions[relation]:
            standard_references[model.source_key] = relation
            continue

        derived_level = max(
            (INITIAL_ACTION_LEVELS[code] for code in action_codes),
            default=None,
        )
        allow_same_level = False
        if "manage_permission" in action_codes:
            if derived_level is None:
                raise AssertionError("manage_permission must have a configured level")
            try:
                allow_same_level, clamped = _infer_same_level(
                    model,
                    derived_level=derived_level,
                )
            except ValueError as exc:
                differences.append(
                    ModelMappingDifference(
                        source_key=model.source_key,
                        difference_type="NON_CONTIGUOUS_MANAGE_BOUNDARY",
                        message=str(exc),
                    )
                )
                continue
            if clamped:
                differences.append(
                    ModelMappingDifference(
                        source_key=model.source_key,
                        difference_type="MANAGE_SCOPE_CLAMPED_TO_MODEL_LEVEL",
                        message="legacy higher-tier grant scope was removed at the derived model level",
                        severity="INFO",
                    )
                )
        model_key = _stable_model_key(model)
        candidates.append(
            (
                model,
                CustomModelSelection(
                    model_key=model_key,
                    name=model.name,
                    action_codes=action_codes,
                    active=True if model.active is None else model.active,
                    allow_same_level=allow_same_level,
                ),
                model_key,
            )
        )

    selections = tuple(candidate[1] for candidate in candidates)
    try:
        release = derive_permission_models(
            action_release,
            custom_models=selections,
        )
    except ValueError as exc:
        differences.append(
            ModelMappingDifference(
                source_key="catalog",
                difference_type="INVALID_MODEL_RELEASE",
                message=str(exc),
            )
        )
        candidates = []
        release = derive_permission_models(action_release)

    derived_by_key = {row.model_key: row for row in release.models}
    custom_models = tuple(
        MappedLegacyModel(
            model_key=model_key,
            legacy_source_key=source.source_key,
            name=derived_by_key[model_key].name,
            action_codes=derived_by_key[model_key].action_codes,
            derived_level=derived_by_key[model_key].derived_level,
            active=derived_by_key[model_key].active,
            allow_same_level=derived_by_key[model_key].allow_same_level,
        )
        for source, _, model_key in candidates
    )
    ordered_differences = tuple(
        sorted(
            differences,
            key=lambda row: (row.source_key, row.difference_type),
        )
    )
    blockers = tuple(row.difference_type for row in ordered_differences if row.severity == "BLOCKER")
    return LegacyModelMappingResult(
        action_release=action_release,
        standard_references=standard_references,
        custom_models=custom_models,
        differences=ordered_differences,
        blockers=blockers,
    )
