#!/usr/bin/env python3
import argparse
import asyncio
import gc
import json

from sqlmodel import select  # noqa: E402

from bisheng.common.models.config import Config, ConfigKeyEnum  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.workstation.domain.models import TenantWorkstationConfigDao  # noqa: E402

KEYS = (
    ConfigKeyEnum.WORKSTATION.value,
    ConfigKeyEnum.WORKSTATION_LINSIGHT.value,
    ConfigKeyEnum.WORKSTATION_SUBSCRIPTION.value,
    ConfigKeyEnum.WORKSTATION_KNOWLEDGE_SPACE.value,
)
ROOT_TENANT_ID = 1


async def migrate(dry_run: bool) -> int:
    migrated = 0
    skipped = 0
    missing = 0
    async with get_async_db_session() as session:
        for key in KEYS:
            with bypass_tenant_filter():
                existing = await TenantWorkstationConfigDao.aget(ROOT_TENANT_ID, key)
            if existing and existing.value:
                skipped += 1
                print(f"[skip] tenant_workstation_config already has root row for key={key}")
                continue

            row = (await session.exec(
                select(Config).where(Config.key == key)
            )).first()
            if row is None or not row.value:
                missing += 1
                print(f"[missing] global config key={key} not found or empty")
                continue
            if dry_run:
                migrated += 1
                print(f"[dry-run] would migrate key={key} to tenant_id={ROOT_TENANT_ID}")
                continue
            with bypass_tenant_filter():
                await TenantWorkstationConfigDao.aupsert(ROOT_TENANT_ID, key, row.value)
            migrated += 1
            print(f"[migrated] key={key} -> tenant_id={ROOT_TENANT_ID}")

    print(json.dumps({
        "dry_run": dry_run,
        "migrated": migrated,
        "skipped": skipped,
        "missing": missing,
    }, ensure_ascii=False))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate workstation config rows to root tenant")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing data")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()


    async def _main() -> int:
        try:
            return await migrate(args.dry_run)
        finally:
            await close_app_context()
            gc.collect()
            await asyncio.sleep(0)


    raise SystemExit(asyncio.run(_main()))
