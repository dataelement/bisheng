"""CLI entry point for F006 RBAC to ReBAC migration."""

from __future__ import annotations

import argparse
import asyncio
import sys

from loguru import logger

from bisheng.permission.migration.f006_migrator import RBACToReBACMigrator
from bisheng.permission.migration.f006_schemas import VerifyReport


def main() -> None:
    parser = argparse.ArgumentParser(
        description='F006: RBAC -> ReBAC Permission Migration',
        epilog='Migrates legacy permission data to OpenFGA for BiSheng v2.5.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview migration statistics without writing to OpenFGA',
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Compare old RBAC and new ReBAC permission checks',
    )
    parser.add_argument(
        '--step',
        type=int,
        default=1,
        metavar='N',
        help='Start from step N (default: 1)',
    )
    parser.add_argument(
        '--only-step',
        type=int,
        metavar='N',
        help='Run only step N without reading or writing the checkpoint',
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        metavar='N',
        help='Database read batch size (default: 1000)',
    )
    parser.add_argument(
        '--dedup-backend',
        choices=('memory', 'sqlite'),
        default='memory',
        help='Cross-step tuple dedup backend (default: memory)',
    )
    parser.add_argument(
        '--dedup-db',
        help='SQLite dedup database path when --dedup-backend=sqlite',
    )
    progress_group = parser.add_mutually_exclusive_group()
    progress_group.add_argument(
        '--progress',
        action='store_true',
        default=None,
        help='Force progress bars on',
    )
    progress_group.add_argument(
        '--no-progress',
        action='store_false',
        dest='progress',
        help='Force progress bars off',
    )
    args = parser.parse_args()

    async def _run() -> None:
        from bisheng.common.services.config_service import settings
        from bisheng.core.context import close_app_context, initialize_app_context

        await initialize_app_context(config=settings)
        try:
            migrator = RBACToReBACMigrator(
                dry_run=args.dry_run,
                verify_only=args.verify,
                start_step=args.step,
                only_step=args.only_step,
                batch_size=args.batch_size,
                dedup_backend=args.dedup_backend,
                dedup_db_path=args.dedup_db,
                progress=args.progress,
            )
            result = await migrator.run()

            if args.verify and isinstance(result, VerifyReport) and result.regression > 0:
                logger.error(f'VERIFY FAILED: {result.regression} regressions detected')
                sys.exit(1)
        finally:
            await close_app_context()

    asyncio.run(_run())
