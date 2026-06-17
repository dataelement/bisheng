#!/usr/bin/env python3
"""Backfill WEB_MENU ``linsight_task_mode`` for roles that already have ``home`` (F035).

Why this exists
---------------
Before F035, the 灵思任务模式 entry (``/linsight``) shared the same ``home`` menu
permission as 日常对话 (``/c``). F035 splits it into its own sub-toggle
``linsight_task_mode`` (under 首页, a workstation child). After upgrade the
``/linsight`` route guard checks ``linsight_task_mode`` instead of ``home``, so any
existing role that could enter 任务模式 (i.e. already has ``home``) must be granted
the new key — otherwise those users lose access (regression). See PRD §4.7.7
FR-7.11 and design §6.7.

What it does
------------
For every (role_id, tenant_id) that has WEB_MENU ``home`` but not yet
``linsight_task_mode``, insert a ``linsight_task_mode`` WEB_MENU row inheriting the
same tenant_id. Idempotent & re-runnable: rows that already exist are skipped.

The actual logic lives in
``bisheng.permission.domain.linsight_task_mode_menu_backfill`` (shared with the
startup auto-backfill in ``main.lifespan``); this script is a dry-run/apply CLI over it.

How to run (from src/backend/)
------------------------------
    export config=config.yaml        # must match the running service
    export PYTHONPATH="./"
    python scripts/backfill_linsight_task_mode_web_menu.py            # dry-run (default, no writes)
    python scripts/backfill_linsight_task_mode_web_menu.py --apply    # actually write rows
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.permission.domain.linsight_task_mode_menu_backfill import (  # noqa: E402
    LINSIGHT_TASK_MODE,
    backfill_linsight_task_mode_web_menu,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write rows (default: dry-run, no writes)")
    args = parser.parse_args()

    async def _main() -> int:
        try:
            summary = await backfill_linsight_task_mode_web_menu(apply=args.apply)
            if args.apply:
                print(f"[done] backfilled {summary['backfilled']} role(s) with '{LINSIGHT_TASK_MODE}'")
            else:
                print(f"[dry-run] would backfill {summary['backfilled']} role(s) — pass --apply to write")
            print(json.dumps(summary, ensure_ascii=False))
            return 0
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
