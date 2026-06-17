#!/usr/bin/env python3
"""F035 Track E: migrate ``linsight_llm`` config from ``task_model`` /
``linsight_executor_mode`` to the new single ``linsight_default_model_id``.

The actual transform lives in
``bisheng.llm.domain.services.linsight_default_model_backfill`` (shared with the
startup auto-backfill in ``main.lifespan``); this script is a dry-run/apply CLI over it.

Context
-------
The deepagents migration removes ``WorkbenchModelConfig.task_model`` (a full
``WSModel``) and ``linsight_executor_mode`` (deepagents now owns the execution
mode). The execution model is now a single id chosen from the ``models`` list:
``linsight_default_model_id``.

Run from ``src/backend/`` (DB-only; no app context needed):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/migrate_linsight_task_model_to_default.py            # dry-run
    python scripts/migrate_linsight_task_model_to_default.py --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.llm.domain.services.linsight_default_model_backfill import (  # noqa: E402
    backfill_linsight_default_model,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply writes. Omit for dry-run preview (default).",
    )
    args = parser.parse_args()

    async def _main() -> int:
        try:
            summary = await backfill_linsight_default_model(apply=args.apply)
            print("Mode:", "apply" if args.apply else "dry-run")
            print(
                f"Rows scanned: {summary['scanned']}  migrated: {summary['migrated']}  "
                f"skipped: {summary['skipped']}  errors: {summary['errors']}"
            )
            print(json.dumps({"dry_run": not args.apply, "rows": summary["rows"]}, ensure_ascii=False))
            return 1 if summary["errors"] else 0
        finally:
            await close_app_context()

    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
