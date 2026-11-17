"""Index legacy DSH usage streams and Linsight checkpoints during stopped-service maintenance.

From src/backend with the service's config environment:
    python scripts/backfill_redis_processing_indexes.py
    python scripts/backfill_redis_processing_indexes.py --apply --services-stopped

The default is read-only. Stop all API, Celery/Beat and Linsight producers and consumers before apply;
run before resuming old tasks on the indexed reader. Interruption is resumable
by repeating the command. Existing payloads and their expiration are preserved.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(apply, verify):
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.dsh.infrastructure.usage_index_backfill import backfill_usage_indexes
    from bisheng.linsight.domain.services.checkpoint_index_backfill import backfill_checkpoint_indexes

    await initialize_app_context(config=settings)
    try:
        redis = await get_redis_client()
        checkpoints = await backfill_checkpoint_indexes(redis.async_connection, apply=apply)
        usage = await backfill_usage_indexes(redis.async_connection, apply=apply) if settings.dsh.enabled else None
        ready = checkpoints["ready"] and (usage is None or usage["ready"])
        print(json.dumps({"apply": apply, "ready": ready, "checkpoints": checkpoints, "usage": usage}))
        return 0 if ready or not (apply or verify) else 1
    finally:
        await close_app_context()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--verify", action="store_true", help="Read-only verification; fail unless every old item is indexed"
    )
    parser.add_argument(
        "--services-stopped", action="store_true", help="Confirm all API, Celery/Beat and Linsight services are stopped"
    )
    args = parser.parse_args()
    if args.apply and not args.services_stopped:
        parser.error("--apply requires --services-stopped")
    return asyncio.run(run(args.apply, args.verify))


if __name__ == "__main__":
    sys.exit(main())
