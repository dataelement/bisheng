"""Deterministic F048 OpenFGA authorization model builder.

The builder only produces JSON and checksums. Publishing is an explicit
maintenance/Catalog operation; importing this module has no OpenFGA side
effects.
"""

from __future__ import annotations

import copy
import json
from hashlib import sha256

MODEL_VERSION = "f048-v1"

DEFAULT_ACTION_CODES: tuple[str, ...] = (
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

MIGRATED_RESOURCE_TYPES: tuple[str, ...] = (
    "knowledge_space",
    "knowledge_library",
    "folder",
    "knowledge_file",
    "workflow",
    "assistant",
    "tool",
    "channel",
    "dashboard",
)

OWNER_PROJECTION_RESOURCE_TYPES: tuple[str, ...] = ("linsight_skill",)

LEGACY_RESOURCE_TYPES: tuple[str, ...] = ("llm_server", "llm_model")

RESOURCE_ACTION_SCOPES: dict[str, frozenset[str]] = {
    "manage_permission": frozenset(MIGRATED_RESOURCE_TYPES),
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
    "delete": frozenset(MIGRATED_RESOURCE_TYPES),
    "share": frozenset({"knowledge_space", "knowledge_file", "workflow", "assistant"}),
    "use": frozenset({"knowledge_library", "workflow", "assistant", "tool"}),
    "publish": frozenset({"workflow", "assistant"}),
    "unpublish": frozenset({"workflow", "assistant"}),
}

PARENT_TYPES: dict[str, tuple[str, ...]] = {
    "folder": (
        "knowledge_space",
        "knowledge_library",
        "folder",
    ),
    "knowledge_file": (
        "folder",
        "knowledge_space",
        "knowledge_library",
    ),
}

SYSTEM_SHARED_ACTION_TYPES: dict[str, frozenset[str]] = {
    "download": frozenset({"knowledge_space", "folder", "knowledge_file"}),
    "use": frozenset({"knowledge_library", "workflow", "assistant", "tool"}),
}


def _this() -> dict:
    return {"this": {}}


def _computed(relation: str) -> dict:
    return {"computedUserset": {"relation": relation}}


def _from(tupleset: str, relation: str) -> dict:
    return {
        "tupleToUserset": {
            "tupleset": {"relation": tupleset},
            "computedUserset": {"relation": relation},
        }
    }


def _union(*children: dict) -> dict:
    if len(children) == 1:
        return children[0]
    return {"union": {"child": list(children)}}


def _intersection(*children: dict) -> dict:
    return {"intersection": {"child": list(children)}}


def _wildcard_user_type() -> dict:
    return {"type": "user", "wildcard": {}}


def _subject_types() -> list[dict]:
    return [
        {"type": "user"},
        {"type": "department", "relation": "member"},
        {"type": "department", "relation": "subtree_member"},
        {"type": "user_group", "relation": "member"},
        {"type": "user_group", "relation": "admin"},
    ]


def _base_type_definitions() -> list[dict]:
    return [
        {"type": "user", "relations": {}, "metadata": None},
        {
            "type": "system",
            "relations": {"super_admin": _this()},
            "metadata": {"relations": {"super_admin": {"directly_related_user_types": [{"type": "user"}]}}},
        },
        {
            "type": "tenant",
            "relations": {
                "admin": _this(),
                "member": _this(),
                "shared_to": _this(),
            },
            "metadata": {
                "relations": {
                    "admin": {"directly_related_user_types": [{"type": "user"}]},
                    "member": {"directly_related_user_types": [{"type": "user"}]},
                    "shared_to": {"directly_related_user_types": [{"type": "tenant"}]},
                }
            },
        },
        {
            "type": "department",
            "relations": {
                "parent": _this(),
                "child": _this(),
                "admin": _union(_this(), _from("parent", "admin")),
                "member": _this(),
                "subtree_member": _union(
                    _computed("member"),
                    _from("child", "subtree_member"),
                ),
            },
            "metadata": {
                "relations": {
                    "parent": {"directly_related_user_types": [{"type": "department"}]},
                    "child": {"directly_related_user_types": [{"type": "department"}]},
                    "admin": {"directly_related_user_types": [{"type": "user"}]},
                    "member": {"directly_related_user_types": [{"type": "user"}]},
                }
            },
        },
        {
            "type": "user_group",
            "relations": {
                "admin": _this(),
                "member": _union(_this(), _computed("admin")),
            },
            "metadata": {
                "relations": {
                    "admin": {"directly_related_user_types": [{"type": "user"}]},
                    "member": {"directly_related_user_types": [{"type": "user"}]},
                }
            },
        },
    ]


def _catalog_release_type() -> dict:
    return {
        "type": "permission_catalog_release",
        "relations": {"active": _this()},
        "metadata": {"relations": {"active": {"directly_related_user_types": [_wildcard_user_type()]}}},
    }


def _model_release_type(action_codes: tuple[str, ...]) -> dict:
    relations: dict[str, dict] = {
        "catalog": _this(),
        "enabled_marker": _this(),
        "active": _intersection(
            _computed("enabled_marker"),
            _from("catalog", "active"),
        ),
    }
    metadata: dict[str, dict] = {
        "catalog": {"directly_related_user_types": [{"type": "permission_catalog_release"}]},
        "enabled_marker": {"directly_related_user_types": [_wildcard_user_type()]},
    }
    for action in action_codes:
        marker = f"{action}_marker"
        relations[marker] = _this()
        relations[f"can_{action}"] = _intersection(
            _computed("active"),
            _computed(marker),
        )
        metadata[marker] = {"directly_related_user_types": [_wildcard_user_type()]}
    for level in range(1, 5):
        marker = f"grant_level_{level}_marker"
        relations[marker] = _this()
        relations[f"can_grant_level_{level}"] = _intersection(
            _computed("active"),
            _computed(marker),
        )
        metadata[marker] = {"directly_related_user_types": [_wildcard_user_type()]}
    return {
        "type": "permission_model_release",
        "relations": relations,
        "metadata": {"relations": metadata},
    }


def _permission_model_type(action_codes: tuple[str, ...]) -> dict:
    relations = {
        "release": _this(),
        "active": _from("release", "active"),
    }
    metadata = {"release": {"directly_related_user_types": [{"type": "permission_model_release"}]}}
    for action in action_codes:
        relations[f"can_{action}"] = _from("release", f"can_{action}")
    for level in range(1, 5):
        relations[f"can_grant_level_{level}"] = _from(
            "release",
            f"can_grant_level_{level}",
        )
    return {
        "type": "permission_model",
        "relations": relations,
        "metadata": {"relations": metadata},
    }


def _permission_grant_type(action_codes: tuple[str, ...]) -> dict:
    relations = {
        "model": _this(),
        "ordinary_assignee": _this(),
        "protected_assignee": _this(),
        "ordinary_visible": _intersection(
            _computed("ordinary_assignee"),
            _from("model", "active"),
        ),
        "protected_visible": _intersection(
            _computed("protected_assignee"),
            _from("model", "active"),
        ),
    }
    metadata = {
        "model": {"directly_related_user_types": [{"type": "permission_model"}]},
        "ordinary_assignee": {"directly_related_user_types": _subject_types()},
        "protected_assignee": {"directly_related_user_types": [{"type": "user"}]},
    }
    for action in action_codes:
        relations[f"ordinary_can_{action}"] = _intersection(
            _computed("ordinary_assignee"),
            _from("model", f"can_{action}"),
        )
        relations[f"protected_can_{action}"] = _intersection(
            _computed("protected_assignee"),
            _from("model", f"can_{action}"),
        )
    for level in range(1, 5):
        relations[f"ordinary_can_grant_level_{level}"] = _intersection(
            _computed("ordinary_assignee"),
            _from("model", f"can_grant_level_{level}"),
        )
        relations[f"protected_can_grant_level_{level}"] = _intersection(
            _computed("protected_assignee"),
            _from("model", f"can_grant_level_{level}"),
        )
    return {
        "type": "permission_grant",
        "relations": relations,
        "metadata": {"relations": metadata},
    }


def _system_relation(
    *,
    type_name: str,
    parent_types: tuple[str, ...],
    action: str | None,
) -> dict:
    children: list[dict] = []
    if action is None:
        children.extend(
            (
                _computed("system_visible_marker"),
                _computed("public_reader"),
                _from("shared_with", "member"),
            )
        )
        if parent_types:
            children.append(_from("parent", "system_visible"))
    else:
        children.append(_computed(f"system_{action}_marker"))
        if type_name in SYSTEM_SHARED_ACTION_TYPES[action]:
            children.extend(
                (
                    _computed("public_reader"),
                    _from("shared_with", "member"),
                )
            )
        if parent_types:
            children.append(_from("parent", f"system_can_{action}"))
    return _union(*children)


def _resource_type(type_name: str, action_codes: tuple[str, ...]) -> dict:
    parent_types = PARENT_TYPES.get(type_name, ())
    relations: dict[str, dict] = {
        "grant": _this(),
        "permission_enabled": _this(),
        "custom_mode": _this(),
        "shared_with": _this(),
        "public_reader": _this(),
        "system_visible_marker": _this(),
        "system_download_marker": _this(),
        "system_use_marker": _this(),
        "ordinary_visible_from_grant": _from("grant", "ordinary_visible"),
        "protected_visible_from_grant": _from("grant", "protected_visible"),
        "ordinary_custom_visible": _intersection(
            _computed("ordinary_visible_from_grant"),
            _computed("custom_mode"),
        ),
        "system_visible": _system_relation(
            type_name=type_name,
            parent_types=parent_types,
            action=None,
        ),
    }
    metadata: dict[str, dict] = {
        "grant": {"directly_related_user_types": [{"type": "permission_grant"}]},
        "permission_enabled": {"directly_related_user_types": [_wildcard_user_type()]},
        "custom_mode": {"directly_related_user_types": [_wildcard_user_type()]},
        "shared_with": {"directly_related_user_types": [{"type": "tenant"}]},
        "public_reader": {"directly_related_user_types": [_wildcard_user_type()]},
        "system_visible_marker": {"directly_related_user_types": [_wildcard_user_type()]},
        "system_download_marker": {"directly_related_user_types": [_wildcard_user_type()]},
        "system_use_marker": {"directly_related_user_types": [_wildcard_user_type()]},
    }

    visible_children = [
        _computed("protected_visible_from_grant"),
        _computed("ordinary_custom_visible"),
        _computed("system_visible"),
    ]
    if parent_types:
        relations["parent"] = _this()
        relations["inherit_mode"] = _this()
        relations["inherited_visible"] = _intersection(
            _from("parent", "visible"),
            _computed("inherit_mode"),
        )
        visible_children.append(_computed("inherited_visible"))
        metadata["parent"] = {"directly_related_user_types": [{"type": parent_type} for parent_type in parent_types]}
        metadata["inherit_mode"] = {"directly_related_user_types": [_wildcard_user_type()]}

    relations["visible"] = _intersection(
        _computed("permission_enabled"),
        _union(*visible_children),
    )

    for action in action_codes:
        relations[f"ordinary_can_{action}_from_grant"] = _from(
            "grant",
            f"ordinary_can_{action}",
        )
        relations[f"protected_can_{action}_from_grant"] = _from(
            "grant",
            f"protected_can_{action}",
        )
        relations[f"ordinary_custom_can_{action}"] = _intersection(
            _computed(f"ordinary_can_{action}_from_grant"),
            _computed("custom_mode"),
        )
        action_children = [
            _computed(f"protected_can_{action}_from_grant"),
            _computed(f"ordinary_custom_can_{action}"),
        ]
        if parent_types:
            inherited = f"inherited_can_{action}"
            relations[inherited] = _intersection(
                _from("parent", f"can_{action}"),
                _computed("inherit_mode"),
            )
            action_children.append(_computed(inherited))
        if action in SYSTEM_SHARED_ACTION_TYPES:
            system_relation = f"system_can_{action}"
            relations[system_relation] = _system_relation(
                type_name=type_name,
                parent_types=parent_types,
                action=action,
            )
            action_children.append(_computed(system_relation))
        relations[f"can_{action}"] = _intersection(
            _computed("permission_enabled"),
            _union(*action_children),
        )

    for level in range(1, 5):
        ordinary = f"ordinary_can_grant_level_{level}_from_grant"
        protected = f"protected_can_grant_level_{level}_from_grant"
        ordinary_custom = f"ordinary_custom_can_grant_level_{level}"
        relations[ordinary] = _from(
            "grant",
            f"ordinary_can_grant_level_{level}",
        )
        relations[protected] = _from(
            "grant",
            f"protected_can_grant_level_{level}",
        )
        relations[ordinary_custom] = _intersection(
            _computed(ordinary),
            _computed("custom_mode"),
        )
        grant_children = [
            _computed(protected),
            _computed(ordinary_custom),
        ]
        if parent_types:
            inherited = f"inherited_can_grant_level_{level}"
            relations[inherited] = _intersection(
                _from("parent", f"can_grant_level_{level}"),
                _computed("inherit_mode"),
            )
            grant_children.append(_computed(inherited))
        relations[f"can_grant_level_{level}"] = _intersection(
            _computed("permission_enabled"),
            _union(*grant_children),
        )

    return {
        "type": type_name,
        "relations": relations,
        "metadata": {"relations": metadata},
    }


def _legacy_resource_type(type_name: str) -> dict:
    relations = {
        "owner": _this(),
        "manager": _union(_this(), _computed("owner")),
        "editor": _union(_this(), _computed("manager")),
        "viewer": _union(
            _this(),
            _computed("editor"),
            _from("shared_with", "member"),
        ),
        "shared_with": _this(),
        "can_manage": _computed("manager"),
        "can_edit": _computed("editor"),
        "can_read": _computed("viewer"),
        "can_delete": _computed("owner"),
    }
    metadata = {
        "owner": {"directly_related_user_types": [{"type": "user"}]},
        "manager": {"directly_related_user_types": _subject_types()},
        "editor": {"directly_related_user_types": _subject_types()},
        "viewer": {"directly_related_user_types": _subject_types()},
        "shared_with": {"directly_related_user_types": [{"type": "tenant"}]},
    }
    return {
        "type": type_name,
        "relations": relations,
        "metadata": {"relations": metadata},
    }


def build_authorization_model_f048(
    action_codes: tuple[str, ...] = DEFAULT_ACTION_CODES,
) -> dict:
    """Build a fresh, deterministic model without publishing it."""

    normalized_actions = tuple(sorted(set(action_codes)))
    if not normalized_actions:
        raise ValueError("F048 authorization model requires at least one action")
    if any(
        not action or action != action.strip().casefold() or not action.replace("_", "").isalnum()
        for action in normalized_actions
    ):
        raise ValueError("F048 action codes must be normalized lowercase identifiers")

    type_definitions = _base_type_definitions()
    type_definitions.extend(
        (
            _catalog_release_type(),
            _model_release_type(normalized_actions),
            _permission_model_type(normalized_actions),
            _permission_grant_type(normalized_actions),
        )
    )
    type_definitions.extend(
        _resource_type(resource_type, normalized_actions)
        for resource_type in (
            *MIGRATED_RESOURCE_TYPES,
            *OWNER_PROJECTION_RESOURCE_TYPES,
        )
    )
    type_definitions.extend(_legacy_resource_type(resource_type) for resource_type in LEGACY_RESOURCE_TYPES)
    return {
        "schema_version": "1.1",
        "type_definitions": type_definitions,
    }


def authorization_model_checksum(model: dict) -> str:
    """Return the lowercase SHA-256 of canonical model JSON."""

    canonical = json.dumps(
        model,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode()).hexdigest()


def required_relations_checksum(model: dict) -> str:
    """Checksum the type/relation surface used by runtime readiness."""

    surface = {definition["type"]: sorted(definition.get("relations", {})) for definition in model["type_definitions"]}
    canonical = json.dumps(surface, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def get_authorization_model_f048() -> dict:
    """Return an isolated model copy for release tooling."""

    return copy.deepcopy(build_authorization_model_f048())
