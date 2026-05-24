#!/usr/bin/env python3
"""Revoke v2.5.1 F017 Root→Child shared_with tuples for retired business types.

v2.5.1 F017 fanned Root-created knowledge_space / workflow / assistant / channel
/ tool out to every active Child via OpenFGA ``shared_with → tenant:{cid}``
tuples, mirrored by a ``{table}.is_shared = 1`` column. v2.6.0-beta2 retires
this default-sharing path (owners grant access through ReBAC instead). This
script cleans up the stale tuples + mirror column left over from F017 so the
upgrade matches the new behavior.

Two-pass scan:
  1. DB pass: ``SELECT id FROM {table} WHERE is_shared = 1`` for each retired
     type — these were the Root-shared resources written by F017.
  2. FGA fallback: walk active Children with
     ``list_objects(user=tenant:{cid}, relation=shared_with, type=t)`` and
     merge the result. Catches drift where the mirror column was reset
     manually but the OpenFGA tuple still lingers.

For every collected id we call ``ResourceShareService.disable_sharing`` (purges
all ``shared_with → tenant:*`` for that resource in one round-trip) followed by
``set_is_shared(False)`` to reconcile the DB cache. Idempotent — re-run is
safe; ``--dry-run`` previews without mutating anything.

llm_server is intentionally excluded: it stays in SUPPORTED_SHAREABLE_TYPES
(F020 platform-LLM inheritance still needs the fan-out). Filter via ``--types``
to narrow the run to a single retired type.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import sys
from typing import Iterable

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.openfga.manager import aget_fga_client  # noqa: E402
from bisheng.database.models.tenant import ROOT_TENANT_ID, TenantDao  # noqa: E402
from bisheng.tenant.domain.services.resource_share_service import (  # noqa: E402
    LEGACY_SHAREABLE_TYPES,
    SUPPORTED_SHAREABLE_TYPES,
    ResourceShareService,
)

# Types that *used* to receive default fan-out but no longer do: LEGACY \ SUPPORTED.
RETIRED_SHAREABLE_TYPES: tuple[str, ...] = tuple(sorted(
    LEGACY_SHAREABLE_TYPES - SUPPORTED_SHAREABLE_TYPES,
))

# Map type → (table_name, id_column). Mirrors the retired toggle endpoint's
# _resolve_resource_tenant_id so we hit the exact tables F017 wrote into.
_TYPE_TO_TABLE: dict[str, tuple[str, str]] = {
    'knowledge_space': ('knowledge', 'id'),
    'workflow': ('flow', 'id'),
    'assistant': ('assistant', 'id'),
    'channel': ('channel', 'id'),
    'tool': ('t_gpts_tools_type', 'id'),
}


async def _scan_db_ids(object_type: str) -> set[str]:
    """Return ids of rows whose is_shared=1 — written by F017 share_on_create.

    bypass_tenant_filter so cleanup reaches Root rows even when invoked from a
    Child-scoped admin shell. ``is_shared = 1`` is portable across MySQL and
    DM8 (both store BOOLEAN as 0/1).
    """
    table, id_col = _TYPE_TO_TABLE[object_type]

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            result = await session.exec(sa_text(
                f'SELECT {id_col} FROM {table} WHERE is_shared = 1'
            ))
            return {str(r[0]) for r in result.all() if r and r[0] is not None}


async def _scan_fga_ids(object_type: str) -> set[str]:
    """Collect ids for which an active Child still has ``shared_with`` to this
    resource type in OpenFGA — catches drift past the is_shared mirror.
    """
    fga = await aget_fga_client()
    if fga is None:
        return set()

    child_ids = await TenantDao.aget_children_ids_active(ROOT_TENANT_ID)
    found: set[str] = set()
    for cid in child_ids:
        objects = await fga.list_objects(
            user=f'tenant:{cid}',
            relation='shared_with',
            type=object_type,
        )
        for obj in objects:
            if ':' in obj:
                _, rid = obj.split(':', 1)
                if rid:
                    found.add(rid)
    return found


async def _revoke_one(object_type: str, object_id: str, dry_run: bool) -> int:
    """Return the count of child tuples deleted (or that would be deleted)."""
    if dry_run:
        children = await ResourceShareService.list_sharing_children(
            object_type, object_id,
        )
        return len(children)
    revoked = await ResourceShareService.disable_sharing(object_type, object_id)
    try:
        await ResourceShareService.set_is_shared(object_type, object_id, False)
    except Exception as exc:  # pragma: no cover - DB hiccup
        print(
            f'[warn] set_is_shared failed for {object_type}:{object_id}: {exc}',
            file=sys.stderr,
        )
    return len(revoked)


async def revoke(types_filter: Iterable[str], dry_run: bool) -> int:
    """Core entrypoint — also called from the Alembic wrapper.

    Returns 0 on success, non-zero when no valid types were selected.
    """
    requested = {t for t in types_filter if t}
    selected = [t for t in RETIRED_SHAREABLE_TYPES if t in requested]
    if not selected:
        print(json.dumps({
            'error': 'no retired types selected',
            'requested': sorted(requested),
            'available': list(RETIRED_SHAREABLE_TYPES),
        }, ensure_ascii=False))
        return 1

    summary: dict[str, dict] = {}
    for object_type in selected:
        db_ids = await _scan_db_ids(object_type)
        fga_ids = await _scan_fga_ids(object_type)
        merged = db_ids | fga_ids

        tuples_revoked = 0
        for oid in sorted(merged):
            n = await _revoke_one(object_type, oid, dry_run)
            tuples_revoked += n
            verb = 'would revoke' if dry_run else 'revoked'
            print(f'  [{verb}] {object_type}:{oid} ({n} child tuples)')

        summary[object_type] = {
            'resources_processed': len(merged),
            'tuples_revoked': tuples_revoked,
            'db_only': sorted(db_ids - fga_ids),
            'fga_only': sorted(fga_ids - db_ids),
        }

    print(json.dumps({
        'dry_run': dry_run,
        'by_type': summary,
    }, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Revoke v2.5.1 F017 default Root→Child shared_with '
                    'tuples for retired business resource types.',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview without writing')
    parser.add_argument(
        '--types',
        default=','.join(RETIRED_SHAREABLE_TYPES),
        help=f'Comma-separated subset of {RETIRED_SHAREABLE_TYPES}',
    )
    return parser.parse_args()


async def _amain(args: argparse.Namespace) -> int:
    try:
        types_filter = {t.strip() for t in args.types.split(',') if t.strip()}
        return await revoke(types_filter, args.dry_run)
    finally:
        await close_app_context()
        gc.collect()
        await asyncio.sleep(0)


if __name__ == '__main__':
    cli_args = parse_args()
    raise SystemExit(asyncio.run(_amain(cli_args)))
