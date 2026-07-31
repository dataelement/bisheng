"""Pure standard/custom permission-model policy for F048."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from hashlib import sha256

from bisheng.permission.domain.services.catalog_policy import (
    CatalogActionRelease,
)

STANDARD_MODEL_DEFINITIONS: tuple[tuple[str, str, int, bool], ...] = (
    ("viewer", "查看者", 1, False),
    ("editor", "编辑者", 2, False),
    ("manager", "管理者", 3, False),
    ("owner", "所有者", 4, True),
)
STANDARD_MODEL_KEYS = frozenset(row[0] for row in STANDARD_MODEL_DEFINITIONS)


@dataclass(frozen=True, slots=True)
class CustomModelSelection:
    """Administrator-owned explicit action selection."""

    model_key: str
    name: str
    action_codes: tuple[str, ...]
    active: bool = True
    allow_same_level: bool = False
    config_scope: str = "PLATFORM"


@dataclass(frozen=True, slots=True)
class ModelPreset:
    """Read-only API preset used only to initialize a custom selection."""

    key: str
    name: str
    action_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedPermissionModel:
    """Canonical model row derived for one complete Catalog release."""

    model_key: str
    name: str
    kind: str
    config_scope: str
    derived_level: int | None
    active: bool
    allow_same_level: bool
    selected_action_codes: tuple[str, ...]
    action_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PermissionModelRelease:
    """Complete standard and custom model release."""

    models: tuple[DerivedPermissionModel, ...]
    blockers: tuple[str, ...]
    checksum: str


@dataclass(frozen=True, slots=True)
class PermissionModelImpact:
    """Models and shared Grant references affected by a release change."""

    changed_model_keys: tuple[str, ...]
    affected_grant_refs: tuple[str, ...]
    checksum: str


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_name(name: str) -> tuple[str, str]:
    display_name = name.strip()
    if not display_name:
        raise ValueError("model name must not be empty")
    return display_name, display_name.casefold()


def _validate_model_key(model_key: str) -> str:
    normalized = model_key.strip()
    if not normalized or normalized != model_key:
        raise ValueError("model key must be a non-empty normalized value")
    return normalized


def _model_payload(model: DerivedPermissionModel) -> dict[str, object]:
    return {
        "action_codes": model.action_codes,
        "active": model.active,
        "allow_same_level": model.allow_same_level,
        "config_scope": model.config_scope,
        "derived_level": model.derived_level,
        "kind": model.kind,
        "model_key": model.model_key,
        "name": model.name,
        "selected_action_codes": model.selected_action_codes,
    }


def _standard_models(
    action_release: CatalogActionRelease,
    standard_allow_same_level: Mapping[str, bool],
) -> tuple[DerivedPermissionModel, ...]:
    models: list[DerivedPermissionModel] = []
    for key, name, level, default_allow_same in STANDARD_MODEL_DEFINITIONS:
        action_codes = tuple(
            action.code
            for action in action_release.actions
            if action.active and action.level is not None and action.level <= level
        )
        allow_same_level = standard_allow_same_level.get(key, default_allow_same)
        if not isinstance(allow_same_level, bool):
            raise ValueError(f"standard model {key} same-level policy must be boolean")
        model = DerivedPermissionModel(
            model_key=key,
            name=name,
            kind="STANDARD",
            config_scope="PLATFORM",
            derived_level=level,
            active=True,
            allow_same_level=allow_same_level,
            selected_action_codes=action_codes,
            action_codes=action_codes,
        )
        if key in standard_allow_same_level and allow_same_level:
            model = with_allow_same_level(model, True)
        models.append(model)

    unknown_overrides = set(standard_allow_same_level) - STANDARD_MODEL_KEYS
    if unknown_overrides:
        raise ValueError(f"unknown standard model same-level overrides: {sorted(unknown_overrides)}")
    return tuple(models)


def _custom_model(
    selection: CustomModelSelection,
    action_release: CatalogActionRelease,
) -> tuple[DerivedPermissionModel, tuple[str, ...]]:
    model_key = _validate_model_key(selection.model_key)
    if model_key in STANDARD_MODEL_KEYS:
        raise ValueError(f"custom model key conflicts with standard model: {model_key}")
    name, _ = _normalize_name(selection.name)
    if selection.config_scope != "PLATFORM":
        raise ValueError("custom model config_scope must be PLATFORM")
    if not isinstance(selection.active, bool):
        raise ValueError(f"custom model {model_key} active must be boolean")
    if not isinstance(selection.allow_same_level, bool):
        raise ValueError(f"custom model {model_key} same-level policy must be boolean")

    selected = tuple(selection.action_codes)
    if not selected:
        raise ValueError(f"custom model {model_key} action selection is empty")
    if len(set(selected)) != len(selected):
        raise ValueError(f"custom model {model_key} has duplicate actions")

    action_by_code = {action.code: action for action in action_release.actions}
    unknown = set(selected) - set(action_by_code)
    if unknown:
        raise ValueError(f"custom model {model_key} selects unknown actions: {sorted(unknown)}")

    selected_set = set(selected)
    effective_actions = tuple(
        action
        for action in action_release.actions
        if action.code in selected_set and action.active and action.level is not None
    )
    effective_codes = tuple(action.code for action in effective_actions)
    unavailable = tuple(sorted(selected_set - set(effective_codes)))
    derived_level = max(
        (action.level for action in effective_actions if action.level is not None),
        default=None,
    )
    model = DerivedPermissionModel(
        model_key=model_key,
        name=name,
        kind="CUSTOM",
        config_scope="PLATFORM",
        derived_level=derived_level,
        active=selection.active,
        allow_same_level=selection.allow_same_level,
        selected_action_codes=selected,
        action_codes=effective_codes,
    )
    if model.allow_same_level and "manage_permission" not in model.action_codes:
        raise ValueError(f"custom model {model_key} cannot allow same level without manage_permission")

    blockers: list[str] = []
    if model.active:
        if not model.action_codes:
            blockers.append(f"active custom model {model_key} has no effective actions")
        if unavailable:
            blockers.append(f"custom model {model_key} selects unavailable actions: {','.join(unavailable)}")
    return model, tuple(blockers)


def derive_permission_models(
    action_release: CatalogActionRelease,
    *,
    custom_models: Iterable[CustomModelSelection] = (),
    standard_allow_same_level: Mapping[str, bool] | None = None,
) -> PermissionModelRelease:
    """Rebuild all standards and derive every custom model in one release."""

    models = list(_standard_models(action_release, standard_allow_same_level or {}))
    blockers: list[str] = []
    model_keys = set(STANDARD_MODEL_KEYS)
    normalized_names = {model.name.casefold() for model in models}

    derived_customs: list[DerivedPermissionModel] = []
    for selection in custom_models:
        model, model_blockers = _custom_model(selection, action_release)
        if model.model_key in model_keys:
            raise ValueError(f"duplicate model key: {model.model_key}")
        normalized_name = model.name.casefold()
        if normalized_name in normalized_names:
            raise ValueError(f"duplicate model name: {model.name}")
        model_keys.add(model.model_key)
        normalized_names.add(normalized_name)
        derived_customs.append(model)
        blockers.extend(model_blockers)

    models.extend(sorted(derived_customs, key=lambda model: model.model_key))
    ordered_blockers = tuple(sorted(blockers))
    payload = {
        "action_release_checksum": action_release.checksum,
        "blockers": ordered_blockers,
        "models": [_model_payload(model) for model in models],
    }
    return PermissionModelRelease(
        models=tuple(models),
        blockers=ordered_blockers,
        checksum=_checksum(payload),
    )


def effective_model_action_codes(
    model: DerivedPermissionModel,
    action_release: CatalogActionRelease,
    resource_type: str,
) -> tuple[str, ...]:
    """Intersect a model with active actions applicable to one resource."""

    if not model.active:
        return ()
    model_actions = set(model.action_codes)
    return tuple(
        action.code
        for action in action_release.actions
        if action.code in model_actions
        and action.active
        and action.level is not None
        and resource_type in action.resource_types
    )


def with_allow_same_level(
    model: DerivedPermissionModel,
    allow_same_level: bool,
) -> DerivedPermissionModel:
    """Apply the only mutable standard field after capability validation."""

    if not isinstance(allow_same_level, bool):
        raise ValueError("same-level policy must be boolean")
    if allow_same_level and "manage_permission" not in model.action_codes:
        raise ValueError(f"model {model.model_key} requires manage_permission to allow same level")
    return replace(model, allow_same_level=allow_same_level)


def validate_standard_model_update(
    current: DerivedPermissionModel,
    candidate: DerivedPermissionModel,
) -> None:
    """Reject mutation of every standard field except same-level policy."""

    if current.kind != "STANDARD" or candidate.kind != "STANDARD":
        raise ValueError("standard model update requires standard models")
    immutable_fields = (
        "model_key",
        "name",
        "kind",
        "config_scope",
        "derived_level",
        "active",
        "selected_action_codes",
        "action_codes",
    )
    if any(getattr(current, field) != getattr(candidate, field) for field in immutable_fields):
        raise ValueError("standard model fields are immutable")
    with_allow_same_level(current, candidate.allow_same_level)


def ensure_model_deletable(
    model: DerivedPermissionModel,
    *,
    reference_count: int,
) -> None:
    """Permit final deletion only for an inactive, unreferenced custom model."""

    if model.kind == "STANDARD":
        raise ValueError("standard models cannot be deleted")
    if model.active:
        raise ValueError("custom model must be inactive before deletion")
    if reference_count:
        raise ValueError("custom model is still referenced by Grants")


def initialize_from_preset(
    preset: ModelPreset,
    *,
    model_key: str,
    name: str,
) -> CustomModelSelection:
    """Copy a preset selection without creating a runtime preset relation."""

    if not preset.key.strip() or not preset.name.strip() or not preset.action_codes:
        raise ValueError("preset must define key, name, and actions")
    return CustomModelSelection(
        model_key=_validate_model_key(model_key),
        name=_normalize_name(name)[0],
        action_codes=tuple(preset.action_codes),
    )


def calculate_model_impact(
    before: PermissionModelRelease,
    after: PermissionModelRelease,
    *,
    grant_references: Mapping[str, Iterable[str]],
) -> PermissionModelImpact:
    """Resolve all shared Grant references of changed model definitions."""

    before_by_key = {model.model_key: model for model in before.models}
    after_by_key = {model.model_key: model for model in after.models}
    changed_model_keys = tuple(
        sorted(
            model_key
            for model_key in set(before_by_key) | set(after_by_key)
            if (
                model_key not in before_by_key
                or model_key not in after_by_key
                or _model_payload(before_by_key[model_key]) != _model_payload(after_by_key[model_key])
            )
        )
    )
    affected_grant_refs = tuple(
        sorted(
            {str(grant_ref) for model_key in changed_model_keys for grant_ref in grant_references.get(model_key, ())}
        )
    )
    payload = {
        "after_checksum": after.checksum,
        "affected_grant_refs": affected_grant_refs,
        "before_checksum": before.checksum,
        "changed_model_keys": changed_model_keys,
    }
    return PermissionModelImpact(
        changed_model_keys=changed_model_keys,
        affected_grant_refs=affected_grant_refs,
        checksum=_checksum(payload),
    )
