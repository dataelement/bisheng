#!/usr/bin/env python3
"""Upgrade backfill for pre-3.0 workbench model settings (dry-run by default).

Two steps, both also run automatically on startup (``main.lifespan``):

1. ``chat_default_model_id``: a ``linsight_llm`` row with no default (absent or
   null) gets the last listed model — the one the old client opened daily chat with.
   (``bisheng.llm.domain.services.chat_default_model_backfill``)
2. Model visibility: each active tenant's workbench models without a
   ``dsh_model_visibility`` row become "visible to all members", once per tenant.
   Tenants that already have visibility rows are skipped unless
   ``--include-configured-tenants`` is given.
   Tenants with unmigrated legacy DSH grants are skipped — run
   ``scripts/dsh/migrate_unified_credits.py`` for them first, then rerun this.
   (``bisheng.dsh.domain.services.workbench_visibility_backfill``)

Run from ``src/backend/`` (DB-only):

    export config=config.yaml
    export PYTHONPATH="./"
    python scripts/backfill_workbench_upgrade.py                    # dry-run
    python scripts/backfill_workbench_upgrade.py --apply            # write
    python scripts/backfill_workbench_upgrade.py --apply --tenant-id 2 --actor-id 1
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
from bisheng.dsh.domain.services.workbench_visibility_backfill import (  # noqa: E402
    SYSTEM_ACTOR_ID,
    backfill_workbench_model_visibility,
)
from bisheng.llm.domain.services.chat_default_model_backfill import backfill_chat_default_model  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write changes. Omit for a dry-run preview.")
    parser.add_argument("--tenant-id", type=int, help="Limit the visibility step to one tenant.")
    parser.add_argument(
        "--include-configured-tenants",
        action="store_true",
        help="Also fill tenants that already have visibility rows (startup skips them); configured models are kept.",
    )
    parser.add_argument(
        "--actor-id", type=int, default=SYSTEM_ACTOR_ID, help="User recorded on visibility rows and the audit."
    )
    args = parser.parse_args()

    async def _main() -> int:
        try:
            chat_default = await backfill_chat_default_model(apply=args.apply)
            visibility = await asyncio.to_thread(
                backfill_workbench_model_visibility,
                args.apply,
                actor_id=args.actor_id,
                tenant_id=args.tenant_id,
                include_configured=args.include_configured_tenants,
            )
            print(
                json.dumps(
                    {
                        "mode": "apply" if args.apply else "dry-run",
                        "chat_default": chat_default,
                        "visibility": visibility,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1 if chat_default["errors"] or visibility["errors"] else 0
        finally:
            await close_app_context()

    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
