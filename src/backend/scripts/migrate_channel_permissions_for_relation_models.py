#!/usr/bin/env python3
"""Backfill channel-module default permissions into legacy custom relation models.

Why this exists
---------------
Relation models (资源权限模板) are persisted as a single JSON list in
``config.key = 'permission_relation_models_v1'``. User-defined (custom) models
carry an explicit ``permissions`` list and are created with
``is_system = False`` / ``permissions_explicit = True``.

Custom models created *before* the channel module was introduced have no channel
permission ids in their ``permissions`` list, so the relation-model template UI
shows the channel module as empty for them. System models are unaffected — they
compute channel defaults from the template dynamically (``permissions_explicit =
False``).

What it does
------------
For every custom (non-system) relation model that currently has *no* channel
permission ids, it appends the channel-module defaults for that model's inherited
level (``owner`` / ``manager`` / ``editor`` / ``viewer``), taken from
``channel_permission_template.default_permission_ids_for_relation``:

    owner   -> view_channel, edit_channel, delete_channel,
               manage_channel_owner, manage_channel_manager, manage_channel_user
    manager -> view_channel, edit_channel, manage_channel_user
    editor  -> view_channel, edit_channel
    viewer  -> view_channel

Models that already contain at least one channel permission id are left
untouched, so an admin's explicit channel customization is never overwritten.
Non-channel permissions are always preserved.

How to run
----------
Dry-run is the default; pass ``--apply`` to persist changes::

    cd src/backend/
    PYTHONPATH=./ .venv/bin/python scripts/migrate_channel_permissions_for_relation_models.py
    PYTHONPATH=./ .venv/bin/python scripts/migrate_channel_permissions_for_relation_models.py --apply

    bash scripts/migrate_channel_permissions_for_relation_models.sh
    bash scripts/migrate_channel_permissions_for_relation_models.sh apply
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.models.config import ConfigDao  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.permission.domain.channel_permission_template import (  # noqa: E402
    channel_template_permissions,
    default_permission_ids_for_relation,
)

# Must match `_RELATION_MODELS_KEY` in
# bisheng/permission/api/endpoints/resource_permission.py — the single global
# config row holding all relation-model templates.
RELATION_MODELS_KEY = 'permission_relation_models_v1'

# Canonical channel permission ids; a custom model holding none of these is
# considered to predate the channel module.
CHANNEL_PERMISSION_IDS = {item['id'] for item in channel_template_permissions()}


async def migrate(dry_run: bool) -> int:
    row = await ConfigDao.aget_config_by_key(RELATION_MODELS_KEY)
    if not row or not (row.value or '').strip():
        print(f"[skip] config key={RELATION_MODELS_KEY} is empty or missing; nothing to migrate")
        return 0

    try:
        models = json.loads(row.value)
    except json.JSONDecodeError as exc:
        print(f"[error] config key={RELATION_MODELS_KEY} is not valid JSON: {exc}")
        return 1
    if not isinstance(models, list):
        print(f"[error] config key={RELATION_MODELS_KEY} is not a JSON list")
        return 1

    migrated = 0
    skipped_system = 0
    skipped_has_channel = 0
    skipped_unknown_relation = 0

    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get('name') or model.get('id')
        if model.get('is_system'):
            skipped_system += 1
            continue

        permissions = list(model.get('permissions') or [])
        if CHANNEL_PERMISSION_IDS & set(permissions):
            skipped_has_channel += 1
            print(f"[skip] custom model id={model.get('id')} name={name!r} already has channel permissions")
            continue

        relation = model.get('relation') or ''
        defaults = default_permission_ids_for_relation(relation)
        if not defaults:
            skipped_unknown_relation += 1
            print(f"[skip] custom model id={model.get('id')} name={name!r} has unknown relation={relation!r}")
            continue

        added = sorted(defaults - set(permissions))
        # Preserve existing (non-channel) permissions; append channel defaults.
        model['permissions'] = permissions + added
        migrated += 1
        action = 'would add' if dry_run else 'added'
        print(
            f"[{'dry-run' if dry_run else 'migrated'}] custom model id={model.get('id')} "
            f"name={name!r} relation={relation} {action} channel permissions: {added}"
        )

    if migrated and not dry_run:
        await ConfigDao.insert_or_update_config(
            RELATION_MODELS_KEY,
            json.dumps(models, ensure_ascii=False),
        )

    print(json.dumps({
        'dry_run': dry_run,
        'total_models': len(models),
        'migrated': migrated,
        'skipped_system': skipped_system,
        'skipped_has_channel': skipped_has_channel,
        'skipped_unknown_relation': skipped_unknown_relation,
    }, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='Persist changes; default is dry-run')
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    async def _main() -> int:
        try:
            return await migrate(dry_run=not args.apply)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_main())


if __name__ == '__main__':
    sys.exit(main())
