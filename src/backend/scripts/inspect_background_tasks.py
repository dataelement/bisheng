"""按租户和 ID 检查失败任务; 只有 --restore --apply 同时出现才恢复终态。"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import current_tenant_id, strict_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.knowledge.domain.repositories.implementations.background_task_maintenance_repository_impl import (
        BackgroundTaskMaintenanceRepositoryImpl,
    )

    await initialize_app_context(config=settings)
    token = current_tenant_id.set(args.tenant_id)
    try:
        with strict_tenant_filter():
            async with get_async_db_session() as session:
                result = await session.run_sync(lambda sync: BackgroundTaskMaintenanceRepositoryImpl(sync).inspect_or_restore(
                    args.kind, args.ids, restore=args.restore and args.apply))
                if args.restore and args.apply:
                    await session.commit()
                print(json.dumps({"applied": args.restore and args.apply, "records": result}, ensure_ascii=False, indent=2))
    finally:
        current_tenant_id.reset(token)
        await close_app_context()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=int)
    parser.add_argument("--kind", required=True, choices=["background", "repair", "points", "course", "openfga"])
    parser.add_argument("--ids", required=True, nargs="+")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.restore:
        parser.error("--apply 必须和 --restore 同时使用")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
