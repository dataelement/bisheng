"""Repartition existing channel articles using the live service configuration.

From src/backend, export the same `config` as the running service:
    python scripts/repartition_channel_articles.py --run-id maintenance-20261027 --batch-size 1
    python scripts/repartition_channel_articles.py --apply --writers-paused --run-id maintenance-20261027 --batch-size 1
    python scripts/repartition_channel_articles.py --status --run-id maintenance-20261027

Default mode only inspects the cluster. Apply requires operators to stop and
fully drain every article writer first. Backups and failed targets are retained.
See scripts/README.md for failure recovery before restoring application writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from scripts.article_reshard_plan import DEFAULT_BATCH_SIZE, MigrationError  # noqa: E402
from scripts.article_reshard_runtime import run_migration  # noqa: E402


def positive_int(value):
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("batch size must be a positive integer") from exc
    if result < 1:
        raise argparse.ArgumentTypeError("batch size must be a positive integer")
    return result


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    mode = value.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Execute the inspected maintenance plan")
    mode.add_argument("--dry-run", action="store_true", help="Read-only plan (default)")
    mode.add_argument("--status", action="store_true", help="Inspect retained artifacts without replay")
    value.add_argument(
        "--writers-paused", action="store_true", help="All article writers have been stopped and drained"
    )
    value.add_argument("--run-id", help="Explicit maintenance identity, lowercase letters/digits/hyphens")
    value.add_argument(
        "--batch-size",
        type=positive_int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Documents per verification page and reindex scroll batch (default: {DEFAULT_BATCH_SIZE})",
    )
    return value


def output(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


async def run(args):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.search.elasticsearch.manager import get_es_connection

    try:
        await initialize_app_context(config=settings, instance_role="maintenance")
        es = await get_es_connection()
        return await run_migration(
            es,
            settings.channel_article_index.number_of_shards,
            apply=args.apply,
            writers_paused=args.writers_paused,
            run_id=args.run_id,
            status=args.status,
            report=output,
            batch_size=args.batch_size,
        )
    finally:
        await close_app_context()


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output(asyncio.run(run(args)))
        return 0
    except MigrationError as exc:
        output(
            {
                "mode": "error",
                "code": exc.code,
                "message": str(exc),
                "recovery": "Keep writers stopped after any apply failure; inspect retained artifacts before recovery.",
            }
        )
        return exc.code
    except Exception as exc:
        # External exceptions can contain credentials or source content; report only their type.
        output(
            {
                "mode": "error",
                "code": 6,
                "error_type": type(exc).__name__,
                "recovery": "Inspect run status and active tasks; no automatic replay or cleanup was attempted.",
            }
        )
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
