"""Preserve current role grants as personal quotas before department-tree rollout.

Run from src/backend with the service configuration:
python scripts/dsh_migrate_role_policies.py --tenant 2 --actor 1 --model 7
The default prints a read-only plan. Add --apply to save the migration.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from starlette.requests import Request  # noqa: E402

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id  # noqa: E402
from bisheng.dsh.access_runtime import get_runtime, get_settings  # noqa: E402
from bisheng.dsh.admin_runtime import get_admin_runtime  # noqa: E402
from bisheng.dsh.domain.services.role_migration import migrate_role_policies  # noqa: E402


async def main(args):
    token = set_current_tenant_id(args.tenant)
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace())})
    runtime = None
    try:
        await initialize_app_context(settings, instance_role="script")
        from bisheng.api.services.f048_permission_runtime import initialize_f048_worker_runtime
        from bisheng.permission.application.process_runtime import register_f048_permission_runtime_context

        register_f048_permission_runtime_context(initialize_f048_worker_runtime)
        runtime = await get_runtime(request, get_settings())
        service = (await get_admin_runtime(runtime)).admin
        reports = []
        for model_id in args.model:
            reports.append(
                await migrate_role_policies(
                    service, actor_id=args.actor, tenant_id=args.tenant, model_id=model_id, apply=args.apply
                )
            )
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    finally:
        if runtime:
            await runtime.close()
        await close_app_context()
        current_tenant_id.reset(token)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True, type=int)
    parser.add_argument("--actor", required=True, type=int)
    parser.add_argument("--model", required=True, type=int, action="append")
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args()))
