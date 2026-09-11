#!/usr/bin/env python3
"""按 rollback-manifest 删除本批在 B 新建的空间与对象。不动 B 原数据。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_BACKEND_ROOT = Path("/app")
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


class _FusionRequest:
    headers: dict = {}
    client = SimpleNamespace(host="127.0.0.1")


async def rollback(manifests: list[dict], apply: bool) -> None:
    from sqlalchemy import text

    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_async_db_session
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
    from bisheng.database.constants import AdminRole
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )

    await initialize_app_context(config=settings)
    try:
        login_user = UserPayload(
            user_id=1,
            user_name="fusion-rollback",
            tenant_id=1,
            user_role=[AdminRole],
            is_global_super=True,
        )
        svc = KnowledgeSpaceService(_FusionRequest(), login_user)
        client = get_minio_storage_sync()
        for item in manifests:
            space_id = item.get("b_space_id")
            keys = item.get("b_object_keys") or []
            print(
                f"rollback a_space_id={item.get('a_space_id')} b_space_id={space_id} objects={len(keys)}"
            )
            if not apply:
                continue
            for key in keys:
                try:
                    client.minio_client_sync.remove_object(client.bucket, key)
                except Exception as exc:  # noqa: BLE001 - 对象缺失不阻断
                    print(f"  warn remove {key}: {exc}")
            if space_id:
                with bypass_tenant_filter():
                    await svc.delete_space(
                        int(space_id), force=True, migrate_free_space=False
                    )
            async with get_async_db_session() as session:
                await session.execute(
                    text(
                        "UPDATE fusion_space_map SET status='rolled_back' "
                        "WHERE a_space_id=:a AND b_space_id=:b"
                    ),
                    {"a": item.get("a_space_id"), "b": space_id},
                )
                await session.commit()
    finally:
        await close_app_context()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = [payload]
    asyncio.run(rollback(payload, args.apply))


if __name__ == "__main__":
    main()
