"""Pure action Catalog policy for the F048 permission model.

This module deliberately operates on immutable values only. Catalog persistence,
OpenFGA publication, and business-resource lookups belong to their respective
orchestration layers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256

REGISTERED_ACTION_CODES: tuple[str, ...] = (
    "manage_permission",
    "rename",
    "edit",
    "create_folder",
    "upload_file",
    "move",
    "download",
    "delete",
    "share",
    "use",
    "publish",
    "unpublish",
)

MIGRATED_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "knowledge_space",
        "knowledge_library",
        "folder",
        "knowledge_file",
        "workflow",
        "assistant",
        "tool",
        "channel",
        "dashboard",
    }
)

ACTION_RESOURCE_SCOPES: Mapping[str, frozenset[str]] = {
    "manage_permission": MIGRATED_RESOURCE_TYPES,
    "rename": frozenset({"folder", "knowledge_file"}),
    "edit": frozenset(
        {
            "knowledge_space",
            "knowledge_library",
            "workflow",
            "assistant",
            "tool",
            "channel",
            "dashboard",
        }
    ),
    "create_folder": frozenset({"knowledge_space", "folder"}),
    "upload_file": frozenset({"knowledge_space", "folder"}),
    "move": frozenset({"folder", "knowledge_file"}),
    "download": frozenset({"folder", "knowledge_file"}),
    "delete": MIGRATED_RESOURCE_TYPES,
    "share": frozenset({"knowledge_space", "knowledge_file", "workflow", "assistant"}),
    "use": frozenset({"knowledge_library", "workflow", "assistant", "tool"}),
    "publish": frozenset({"workflow", "assistant"}),
    "unpublish": frozenset({"workflow", "assistant"}),
}

STANDARD_MODEL_KEYS: tuple[str, ...] = ("viewer", "editor", "manager", "owner")
ACTION_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CatalogAction:
    """One complete action-Catalog row."""

    code: str
    name: str
    level: int | None
    active: bool = True
    resource_types: frozenset[str] = frozenset()
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class CatalogActionRelease:
    """Canonical, complete action release."""

    actions: tuple[CatalogAction, ...]
    checksum: str


@dataclass(frozen=True, slots=True)
class CatalogActionImpact:
    """Deterministic impact between two complete action releases."""

    changed_action_codes: tuple[str, ...]
    affected_model_keys: tuple[str, ...]
    expanded_pairs: tuple[tuple[str, str], ...]
    revoked_pairs: tuple[tuple[str, str], ...]
    checksum: str


def _checksum(payload: object) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def _action_payload(action: CatalogAction) -> dict[str, object]:
    return {
        "active": action.active,
        "code": action.code,
        "level": action.level,
        "name": action.name,
        "resource_types": sorted(action.resource_types),
        "sort_order": action.sort_order,
    }


def _normalize_action(action: CatalogAction) -> CatalogAction:
    code = action.code.strip()
    name = action.name.strip()
    if code != action.code or not ACTION_CODE_PATTERN.fullmatch(code):
        raise ValueError(f"invalid action code: {action.code!r}")
    if not name:
        raise ValueError(f"action {code!r} name must not be empty")
    if action.level is not None and (isinstance(action.level, bool) or action.level not in {1, 2, 3, 4}):
        raise ValueError(f"action {code!r} level must be 1..4 or unassigned")
    if not isinstance(action.active, bool):
        raise ValueError(f"action {code!r} active must be boolean")
    if isinstance(action.sort_order, bool) or action.sort_order < 0:
        raise ValueError(f"action {code!r} sort_order must be non-negative")

    resource_types = frozenset(resource_type.strip() for resource_type in action.resource_types)
    if not resource_types or "" in resource_types:
        raise ValueError(f"action {code!r} resource scope must not be empty")
    unknown_types = resource_types - MIGRATED_RESOURCE_TYPES
    if unknown_types:
        raise ValueError(f"action {code!r} has unknown resource scope: {sorted(unknown_types)}")
    allowed_scopes = ACTION_RESOURCE_SCOPES.get(code)
    if allowed_scopes is not None and not resource_types <= allowed_scopes:
        raise ValueError(f"action {code!r} has unsupported resource scope: {sorted(resource_types - allowed_scopes)}")
    return CatalogAction(
        code=code,
        name=name,
        level=action.level,
        active=action.active,
        resource_types=resource_types,
        sort_order=action.sort_order,
    )


def derive_action_release(
    actions: Iterable[CatalogAction],
    *,
    registered_action_codes: Iterable[str] = REGISTERED_ACTION_CODES,
) -> CatalogActionRelease:
    """Validate and canonicalize a complete action Catalog release."""

    registered = tuple(registered_action_codes)
    if len(set(registered)) != len(registered):
        raise ValueError("registered action codes must be unique")

    by_code: dict[str, CatalogAction] = {}
    for raw_action in actions:
        action = _normalize_action(raw_action)
        if action.code in by_code:
            raise ValueError(f"duplicate action row: {action.code}")
        by_code[action.code] = action

    unknown = set(by_code) - set(registered)
    if unknown:
        raise ValueError(f"action codes are not registered: {sorted(unknown)}")
    missing = set(registered) - set(by_code)
    if missing:
        raise ValueError(f"Catalog must contain one complete row for every action: {sorted(missing)}")

    canonical_actions = tuple(by_code[code] for code in registered)
    return CatalogActionRelease(
        actions=canonical_actions,
        checksum=_checksum([_action_payload(action) for action in canonical_actions]),
    )


def action_zones(
    actions: Iterable[CatalogAction],
) -> dict[int | None, tuple[CatalogAction, ...]]:
    """Return the five deterministic UI zones: unassigned and levels 1..4."""

    zones: dict[int | None, list[CatalogAction]] = {
        None: [],
        1: [],
        2: [],
        3: [],
        4: [],
    }
    for action in actions:
        if action.level not in zones:
            raise ValueError(f"action {action.code!r} has invalid level")
        zones[action.level].append(action)
    return {level: tuple(sorted(rows, key=lambda row: (row.sort_order, row.code))) for level, rows in zones.items()}


def effective_action_codes(
    actions: Iterable[CatalogAction],
    resource_type: str,
) -> tuple[str, ...]:
    """Return active, assigned actions effective for one resource type."""

    return tuple(
        action.code
        for action in sorted(actions, key=lambda row: (row.sort_order, row.code))
        if action.active and action.level is not None and resource_type in action.resource_types
    )


def _effective_pairs(
    release: CatalogActionRelease,
) -> frozenset[tuple[str, str]]:
    return frozenset(
        (resource_type, action.code)
        for action in release.actions
        if action.active and action.level is not None
        for resource_type in action.resource_types
    )


def calculate_action_impact(
    before: CatalogActionRelease,
    after: CatalogActionRelease,
    *,
    custom_model_actions: Mapping[str, frozenset[str]],
) -> CatalogActionImpact:
    """Calculate model and effective-action impact for a Catalog change."""

    before_by_code = {action.code: action for action in before.actions}
    after_by_code = {action.code: action for action in after.actions}
    all_codes = set(before_by_code) | set(after_by_code)
    changed_codes = tuple(
        sorted(
            code for code in all_codes if _action_payload(before_by_code[code]) != _action_payload(after_by_code[code])
        )
    )

    affected_models: set[str] = set()
    if changed_codes:
        affected_models.update(STANDARD_MODEL_KEYS)
        changed_set = set(changed_codes)
        affected_models.update(
            model_key for model_key, selected_actions in custom_model_actions.items() if changed_set & selected_actions
        )

    before_pairs = _effective_pairs(before)
    after_pairs = _effective_pairs(after)
    expanded_pairs = tuple(sorted(after_pairs - before_pairs))
    revoked_pairs = tuple(sorted(before_pairs - after_pairs))
    affected_model_keys = tuple(sorted(affected_models))
    payload = {
        "after_checksum": after.checksum,
        "affected_model_keys": affected_model_keys,
        "before_checksum": before.checksum,
        "changed_action_codes": changed_codes,
        "expanded_pairs": expanded_pairs,
        "revoked_pairs": revoked_pairs,
    }
    return CatalogActionImpact(
        changed_action_codes=changed_codes,
        affected_model_keys=affected_model_keys,
        expanded_pairs=expanded_pairs,
        revoked_pairs=revoked_pairs,
        checksum=_checksum(payload),
    )
