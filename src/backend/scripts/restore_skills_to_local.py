#!/usr/bin/env python3
"""Write skill bundles back to the legacy on-disk layout (rollback aid).

Only needed when rolling BACK to a release that reads skill bundles from
``SKILLS_ROOT`` instead of object storage. Skills created or edited while the
newer release was running exist only as objects; the older code looks for them on
local disk, finds nothing, and — because that path only logs a warning — the skill
silently stops working.

Run this on every host that will serve the older release, BEFORE rolling back.
Bundles are written to ``SKILLS_ROOT/data/skills/{tenant_id}/{name}/``.

How to run (from src/backend/)
------------------------------
    cd src/backend/
    export config=config.yaml
    PYTHONPATH=./ .venv/bin/python scripts/restore_skills_to_local.py            # dry-run
    PYTHONPATH=./ .venv/bin/python scripts/restore_skills_to_local.py --apply
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
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao  # noqa: E402
from bisheng.linsight.domain.services.skill_store import LEGACY_TENANT_SKILLS_DIR, SkillStore  # noqa: E402


async def restore(apply: bool, legacy_root: Path, store: SkillStore) -> dict:
    report: dict[str, list] = {"restored": [], "unavailable": []}

    with bypass_tenant_filter():
        rows, _ = await LinsightSkillDao.get_page(page=1, page_size=100000)

    for row in rows:
        entry = {"tenant_id": row.tenant_id, "name": row.name}
        try:
            entries = store.list_files(row.tenant_id, row.name, row.content_hash)
            if not entries:
                raise FileNotFoundError(row.object_path)
            files = {e["path"]: store.read_bytes(row.tenant_id, row.name, row.content_hash, e["path"]) for e in entries}
        except Exception as exc:
            logger.warning("cannot read bundle for {}/{}: {}", row.tenant_id, row.name, exc)
            report["unavailable"].append(entry)
            continue

        if apply:
            base = legacy_root / LEGACY_TENANT_SKILLS_DIR / str(row.tenant_id) / row.name
            for rel, content in files.items():
                target = base / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        report["restored"].append(entry)

    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    parser.add_argument("--legacy-root", default=None, help="target SKILLS_ROOT (default: linsight_conf.skills_root)")
    args = parser.parse_args()

    await initialize_app_context(settings, instance_role="script")
    try:
        legacy_root = Path(args.legacy_root or settings.get_linsight_conf().skills_root).resolve()
        report = await restore(args.apply, legacy_root, SkillStore())
        mode = "apply" if args.apply else "dry-run"
        print(json.dumps({"mode": mode, "legacy_root": str(legacy_root), **report}, ensure_ascii=False, indent=2))
        return 0
    finally:
        await close_app_context()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
