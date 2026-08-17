#!/usr/bin/env python3
"""Publish skill bundles left on a node's local disk into object storage.

Before this change ``SKILLS_ROOT`` was the authoritative store, so an existing
deployment's bundles live on whichever host wrote them. Rows created since the
upgrade already carry a ``content_hash``; rows with an empty one still point at
nothing and their skill will not load. This script walks those rows, finds the
bundle under the legacy on-disk layout and publishes it.

Run it **on each host that ever served the API**. A host whose disk is empty
reports the rows it could not resolve — those bundles are on a different host, so
run it there too. (The API's startup self-heal covers the same ground but only
for what its own disk holds; see ``bisheng/main.py``.)

Idempotent: a row that already resolves is skipped, and publishing the same
bundle twice writes the same content-addressed object.

How to run (from src/backend/)
------------------------------
    cd src/backend/
    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/migrate_skills_to_object_storage.py               # dry-run
    PYTHONPATH=./ .venv/bin/python scripts/migrate_skills_to_object_storage.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/migrate_skills_to_object_storage.py --tenant-id 3 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import (  # noqa: E402
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao  # noqa: E402

# Same reader the startup self-heal uses — two copies of "what a legacy bundle
# looks like on disk" would drift.
from bisheng.linsight.domain.services.skill_bundle_backfill import read_legacy_bundle  # noqa: E402
from bisheng.linsight.domain.services.skill_store import SkillStore  # noqa: E402


async def migrate(tenant_id: int | None, apply: bool, legacy_root: Path, store: SkillStore) -> dict:
    report: dict[str, list] = {"published": [], "already_ok": [], "unresolved": []}

    with bypass_tenant_filter():
        rows, _ = await LinsightSkillDao.get_page(page=1, page_size=100000)

    for row in rows:
        if tenant_id is not None and row.tenant_id != tenant_id:
            continue
        entry = {"tenant_id": row.tenant_id, "name": row.name, "display_name": row.display_name}

        if row.content_hash and store.exists(row.tenant_id, row.name, row.content_hash):
            report["already_ok"].append(entry)
            continue

        files = read_legacy_bundle(legacy_root, row.tenant_id, row.name)
        if files is None:
            # Not an error here: the bundle almost certainly sits on another host.
            report["unresolved"].append(entry)
            continue

        if apply:
            # The DAO writes under the tenant ContextVar, so enter each row's
            # tenant and restore the caller's on the way out.
            token = set_current_tenant_id(row.tenant_id)
            try:
                ref = store.write_bundle(row.tenant_id, row.name, files)
                row.object_path, row.content_hash, row.size = ref.object_key, ref.content_hash, ref.size
                await LinsightSkillDao.update(row)
            finally:
                current_tenant_id.reset(token)
        report["published"].append(entry)

    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="persist changes (default: dry-run)")
    parser.add_argument("--tenant-id", type=int, default=None, help="limit to one tenant")
    parser.add_argument(
        "--legacy-root",
        default=None,
        help="legacy SKILLS_ROOT to read from (default: linsight_conf.skills_root)",
    )
    args = parser.parse_args()

    await initialize_app_context(settings, instance_role="script")
    try:
        legacy_root = Path(args.legacy_root or settings.get_linsight_conf().skills_root).resolve()
        store = SkillStore()
        report = await migrate(args.tenant_id, args.apply, legacy_root, store)

        mode = "apply" if args.apply else "dry-run"
        print(json.dumps({"mode": mode, "legacy_root": str(legacy_root), **report}, ensure_ascii=False, indent=2))
        if report["unresolved"]:
            # The one outcome an operator must act on: these skills are broken
            # until this script runs on the host that holds their bundle.
            logger.warning(
                "{} skill(s) have no bundle on this host — run this script on the other API hosts: {}",
                len(report["unresolved"]),
                [f"{e['tenant_id']}/{e['name']}" for e in report["unresolved"]],
            )
        return 0
    finally:
        await close_app_context()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
