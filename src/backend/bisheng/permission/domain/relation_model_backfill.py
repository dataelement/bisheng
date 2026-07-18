"""Idempotent backfill for newly-added knowledge-space permissions.

The four system relation tiers (owner/manager/editor/viewer) live in the global
config row ``permission_relation_models_v1``. A tier that was edited & saved in
the admin UI gets ``permissions_explicit=True`` — its checkbox set is frozen to
that moment's snapshot and no longer tracks the code template. Permissions added
later (F034's ``move_file`` / ``move_folder``) therefore never appear in those
frozen tiers, even though runtime enforcement (via space membership) already
grants them.

This module re-aligns those frozen tiers with the template, scoped to exactly
the newly-added permission ids so it never disturbs genuine admin customizations.
It runs automatically on startup (``init_default_data``) and is also exposed as a
standalone CLI script. Idempotent: once aligned, subsequent runs are no-ops.
"""

from __future__ import annotations

import json

from loguru import logger

from bisheng.common.models.config import ConfigDao
from bisheng.permission.domain.knowledge_space_permission_template import (
    default_permission_ids_for_relation,
)

RELATION_MODELS_KEY = "permission_relation_models_v1"
# Permissions added by F034. Backfill is scoped to exactly these ids so the
# alignment can never re-add something an admin intentionally unchecked.
NEW_PERMISSION_IDS = {"move_file", "move_folder"}


def target_new_permissions(relation: str) -> set[str]:
    """The subset of the new permissions this tier should have by default.

    Reuses the same source of truth as the dynamic path, so the
    owner/manager/editor-checked, viewer-unchecked rule is honoured automatically.
    """
    return NEW_PERMISSION_IDS & default_permission_ids_for_relation(relation or "")


def apply_move_permission_backfill(models: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pure transform. Returns (updated_models, change_log); input is not mutated.

    Only frozen system tiers (``is_system`` and ``permissions_explicit``) are
    touched, and only the missing new permission ids are unioned in — every other
    stored permission is preserved.
    """
    updated: list[dict] = []
    changes: list[dict] = []
    for model in models:
        m = dict(model)
        if m.get("is_system") and m.get("permissions_explicit") is True:
            relation = m.get("relation") or ""
            current = set(m.get("permissions") or [])
            missing = target_new_permissions(relation) - current
            if missing:
                m["permissions"] = sorted(current | missing)
                changes.append(
                    {
                        "id": m.get("id"),
                        "name": m.get("name"),
                        "relation": relation,
                        "added": sorted(missing),
                    }
                )
        updated.append(m)
    return updated, changes


async def backfill_relation_model_move_permissions() -> list[dict]:
    """Read config, align frozen system tiers, persist if anything changed.

    Returns the change log (empty when nothing needed fixing). Safe to call on
    every startup. Never raises on benign states (missing/empty/invalid config) —
    those just mean "nothing to backfill".
    """
    row = await ConfigDao.aget_config_by_key(RELATION_MODELS_KEY)
    if not row or not (row.value or "").strip():
        # Fresh / uninitialized env: tiers are still dynamic, nothing frozen.
        return []
    try:
        models = json.loads(row.value)
    except (ValueError, TypeError) as exc:
        logger.warning("relation-model backfill: config {} is not valid JSON: {}", RELATION_MODELS_KEY, exc)
        return []
    if not isinstance(models, list) or not models:
        return []

    updated, changes = apply_move_permission_backfill(models)
    if not changes:
        return []

    await ConfigDao.insert_or_update_config(RELATION_MODELS_KEY, json.dumps(updated, ensure_ascii=False))
    logger.info("relation-model move-permission backfill applied to {} tier(s): {}", len(changes), changes)
    return changes
