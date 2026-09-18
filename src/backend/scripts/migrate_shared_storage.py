#!/usr/bin/env python3
"""F4: Shared-storage migration CLI entry point.

仅保留旧空间存储到共享存储的正向迁移；不会切回旧路由。
从 backend 根目录运行，先预览：

    bash scripts/migrate_shared_storage.sh migrate --tenant-id 1 --dry-run
    bash scripts/migrate_shared_storage.sh migrate --tenant-id 1
    bash scripts/migrate_shared_storage.sh status --tenant-id 1

代码回退应使用旧版本及其迁移工具，本版本不提供 reverse 操作。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("migrate_shared_storage")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shared-storage forward migration CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # migrate
    migrate_parser = sub.add_parser("migrate", help="Forward migration (per-space → shared)")
    migrate_parser.add_argument("--tenant-id", type=int, required=True)
    migrate_parser.add_argument("--dry-run", action="store_true", default=False)
    migrate_parser.add_argument("--collection-name", type=str, default=None)
    migrate_parser.add_argument("--index-name", type=str, default=None)
    migrate_parser.add_argument("--embedding-model-id", type=int, default=None)

    # status
    status_parser = sub.add_parser("status", help="Show tenant routing status")
    status_parser.add_argument("--tenant-id", type=int, required=True)

    return parser


async def _cmd_migrate(args: argparse.Namespace) -> int:
    from bisheng.knowledge.domain.services.file_migration.shared_storage_migration import (
        SharedStorageMigrationCoordinator,
    )

    coordinator = SharedStorageMigrationCoordinator()
    progress = await coordinator.migrate_tenant(
        tenant_id=args.tenant_id,
        collection_name=args.collection_name,
        index_name=args.index_name,
        embedding_model_id=args.embedding_model_id,
        dry_run=args.dry_run,
    )
    logger.info(
        "migrate done tenant=%s phase=%s migrated=%d/%d failed=%d dry_run=%s",
        progress.tenant_id,
        progress.phase,
        progress.migrated_spaces,
        progress.total_spaces,
        progress.failed_spaces,
        args.dry_run,
    )
    if progress.errors:
        for err in progress.errors:
            logger.error("  %s", err)
        return 1
    return 0


async def _cmd_status(args: argparse.Namespace) -> int:
    from bisheng.knowledge.domain.models.knowledge_space_shared_storage import (
        KnowledgeSpaceSharedStorageRoutingDao,
    )

    row = await KnowledgeSpaceSharedStorageRoutingDao.aget_by_tenant(args.tenant_id)
    if row is None:
        logger.info("tenant=%s: no routing row (not configured)", args.tenant_id)
        return 0
    logger.info(
        "tenant=%s: legacy_shared_enabled_ignored=%s write_frozen=%s routing_version=%s "
        "migration_state=%s collection=%s index=%s",
        args.tenant_id,
        row.shared_enabled,
        row.write_frozen,
        row.routing_version,
        row.migration_state,
        row.collection_name,
        row.index_name,
    )
    return 0


async def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "migrate":
        return await _cmd_migrate(args)
    if args.command == "status":
        return await _cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))