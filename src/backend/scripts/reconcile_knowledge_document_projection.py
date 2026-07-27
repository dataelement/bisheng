"""检查或重新调度单个 F059 文档入口投影。

默认只读; 显式传入 ``--apply`` 才会向 knowledge Celery 队列调度任务:

    PYTHONPATH=./ .venv/bin/python \
      scripts/reconcile_knowledge_document_projection.py \
      --tenant-id 1 --entry-id 123

    PYTHONPATH=./ .venv/bin/python \
      scripts/reconcile_knowledge_document_projection.py \
      --tenant-id 1 --entry-id 123 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import (  # noqa: E402
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (  # noqa: E402
    KnowledgeFileRepositoryImpl,
)


async def inspect_entry(
    *,
    tenant_id: int,
    entry_id: int,
) -> dict:
    async with get_async_db_session() as session:
        entry = await KnowledgeFileRepositoryImpl(session).find_by_id(
            int(entry_id)
        )
    if (
        entry is None
        or int(entry.tenant_id or 0) != int(tenant_id)
        or entry.reference_document_id is None
        or entry.entry_type is None
    ):
        raise ValueError("entry does not exist in the requested tenant")
    return {
        "tenant_id": int(tenant_id),
        "entry_id": int(entry.id),
        "document_id": int(entry.reference_document_id),
        "entry_type": str(entry.entry_type),
        "entry_status": str(entry.entry_status or ""),
        "projection_status": str(entry.projection_status),
        "desired_content_generation": int(
            entry.desired_content_generation
        ),
        "applied_content_generation": int(
            entry.applied_content_generation
        ),
        "desired_entry_generation": int(
            entry.desired_entry_generation
        ),
        "applied_entry_generation": int(
            entry.applied_entry_generation
        ),
        "retry_count": int(entry.projection_retry_count),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--entry-id", type=int, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际调度投影任务; 默认只读",
    )
    args = parser.parse_args()
    if args.tenant_id <= 0 or args.entry_id <= 0:
        parser.error("tenant-id and entry-id must be positive")

    token = set_current_tenant_id(args.tenant_id)
    try:
        snapshot = asyncio.run(
            inspect_entry(
                tenant_id=args.tenant_id,
                entry_id=args.entry_id,
            )
        )
        if args.apply:
            from bisheng.worker.knowledge.document_projection import (
                process_document_projection,
            )

            task = process_document_projection.apply_async(
                kwargs={
                    "tenant_id": int(args.tenant_id),
                    "entry_id": int(args.entry_id),
                },
                headers={"tenant_id": int(args.tenant_id)},
                queue="knowledge_celery",
            )
            snapshot["dispatch_status"] = "submitted"
            snapshot["task_id"] = str(task.id)
        else:
            snapshot["dispatch_status"] = "dry_run"
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "status": "invalid_target",
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    finally:
        current_tenant_id.reset(token)


if __name__ == "__main__":
    raise SystemExit(main())
