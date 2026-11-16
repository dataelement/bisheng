"""Backfill legacy Linsight pending-write indexes without changing checkpoint payloads.

From src/backend with the service's config environment:
    python scripts/backfill_linsight_checkpoint_indexes.py
    python scripts/backfill_linsight_checkpoint_indexes.py --apply --writers-stopped

The default is read-only. Stop all Linsight checkpoint writers before apply;
run before resuming old tasks on the indexed reader. Interruption is resumable
by repeating the command. Existing payloads and their expiration are preserved.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(apply):
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.linsight.domain.services.checkpoint_index_backfill import backfill_checkpoint_indexes

    await initialize_app_context(config=settings)
    try:
        redis = await get_redis_client()
        result = await backfill_checkpoint_indexes(redis.async_connection, apply=apply)
        print(json.dumps({"apply": apply, **result}))
        return 0
    finally:
        await close_app_context()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true", help="Confirm all checkpoint writers are stopped")
    args = parser.parse_args()
    if args.apply and not args.writers_stopped:
        parser.error("--apply requires --writers-stopped")
    return asyncio.run(run(args.apply))


if __name__ == "__main__":
    sys.exit(main())
