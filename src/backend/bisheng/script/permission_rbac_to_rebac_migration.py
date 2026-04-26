from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime

from loguru import logger


async def run_migration(
    dry_run: bool = False,
    verify: bool = False,
    step: int = 1,
    force: bool = False,
) -> int:
    from bisheng.common.services.config_service import settings
    from bisheng.core.cache.redis_manager import get_redis_client
    from bisheng.core.context import close_app_context, initialize_app_context
    from bisheng.core.openfga.manager import aget_fga_client, get_fga_client
    from bisheng.permission.migration.migrate_rbac_to_rebac import RBACToReBACMigrator, VerifyReport

    await initialize_app_context(config=settings)

    try:
        fga = await aget_fga_client()
        if fga is None:
            fga = get_fga_client()
        if fga is None:
            logger.error('OpenFGA client not available. Cannot execute permission migration.')
            return 1

        redis_client = await get_redis_client()
        completed_key = 'migration:f006:completed'
        lock_key = 'migration:f006:lock'

        if not dry_run and not verify and not force and await redis_client.aget(completed_key):
            logger.info('F006 migration already completed. Use --force to execute again.')
            return 0

        lock_acquired = True
        if not dry_run and not verify:
            lock_acquired = await redis_client.asetNx(lock_key, '1', expiration=3600)
            if not lock_acquired:
                logger.error('F006 migration lock already exists. Another process may be running.')
                return 1

        try:
            started_at = time.time()
            migrator = RBACToReBACMigrator(
                dry_run=dry_run,
                verify_only=verify,
                start_step=step,
            )
            result = await migrator.run()
            elapsed = time.time() - started_at

            if verify:
                assert isinstance(result, VerifyReport)
                logger.info(
                    'F006 verify done in %.1fs: total=%d match=%d regression=%d expansion=%d',
                    elapsed, result.total, result.match, result.regression, result.expansion,
                )
                return 1 if result.regression > 0 else 0

            if dry_run:
                logger.info('F006 dry-run done in %.1fs: total=%d', elapsed, result.total)
                return 0

            await redis_client.aset(completed_key, json.dumps({
                'timestamp': datetime.now().isoformat(),
                'stats': result.to_dict(),
            }))
            logger.info('F006 migration done in %.1fs: total=%d', elapsed, result.total)
            return 0
        finally:
            if not dry_run and not verify and lock_acquired:
                await redis_client.adelete(lock_key)
    finally:
        await close_app_context()


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Manual runner for F006 RBAC -> ReBAC permission migration',
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview migration statistics only')
    parser.add_argument('--verify', action='store_true', help='Verify old/new permission results')
    parser.add_argument('--step', type=int, default=1, metavar='N', help='Start from step N')
    parser.add_argument(
        '--force',
        action='store_true',
        help='Ignore the completed marker and execute migration again',
    )
    args = parser.parse_args()

    if args.dry_run and args.verify:
        parser.error('--dry-run and --verify cannot be used together')

    exit_code = asyncio.run(
        run_migration(
            dry_run=args.dry_run,
            verify=args.verify,
            step=args.step,
            force=args.force,
        )
    )
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
