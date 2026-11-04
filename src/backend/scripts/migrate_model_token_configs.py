#!/usr/bin/env python3
"""Upgrade legacy max_tokens into advanced model parameters.

Run from src/backend/ with the service's config environment and interpreter:
    python scripts/migrate_model_token_configs.py --all-tenants
    python scripts/migrate_model_token_configs.py --all-tenants --apply \
        --backup-file /secure-backups/model-tokens-before.json

The default is read-only. Pause API/Worker model-configuration writers and
drain in-flight calls before apply; restart them afterwards to clear caches.
Use --restore-backup with a fresh --backup-file to restore unchanged records.
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all-tenants", action="store_true")
    scope.add_argument("--tenant-id", type=int, action="append", dest="tenant_ids")
    parser.add_argument("--apply", action="store_true", help="Write changes; default is dry-run.")
    parser.add_argument("--backup-file", help="New private backup path, required with --apply.")
    parser.add_argument("--restore-backup", help="Restore configurations from a previous upgrade backup.")
    args = parser.parse_args()
    if args.apply and not args.backup_file:
        parser.error("--apply requires a new --backup-file")
    if args.tenant_ids and any(value < 1 for value in args.tenant_ids):
        parser.error("--tenant-id must be a positive integer")

    from bisheng.core.context.manager import close_app_context
    from bisheng.llm.domain.services.model_token_config_upgrade import migrate_model_token_configs

    async def run() -> int:
        try:
            result = await migrate_model_token_configs(
                apply=args.apply,
                tenant_ids=args.tenant_ids,
                backup_file=args.backup_file,
                restore_backup=args.restore_backup,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 1 if result["errors"] else 0
        except Exception:
            # Database connection exceptions can embed credentials; use a fixed message.
            print(
                "Migration failed. Verify the database and backup before retrying.",
                file=sys.stderr,
            )
            return 2
        finally:
            await close_app_context()

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
