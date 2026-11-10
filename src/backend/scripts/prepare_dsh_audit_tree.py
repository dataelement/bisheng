"""Prepare a disposable audit conversation tree from existing metadata only.

Run from src/backend with the service's config; dry-run is the default:
  python scripts/prepare_dsh_audit_tree.py --tenant-id 1
  python scripts/prepare_dsh_audit_tree.py --tenant-id 1 --apply --max-steps 100
Each step handles at most 100 records/nodes. Progress is persisted in SQL;
rerun to resume. Upgrade all writers and prepare legacy presentation first.
No model requests, body decryptions, or changes to original audit ownership.
"""

import argparse
import asyncio
import json
import os
import sys
from contextlib import contextmanager

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.dsh.domain.repositories.model_audit_queries import DshModelAuditQueryRepository  # noqa: E402
from bisheng.dsh.domain.services.model_audit_tree import DshAuditTreeProjectionService  # noqa: E402
from bisheng.dsh.operations_runtime import repository_scope  # noqa: E402


@contextmanager
def scope():
    with repository_scope(DshModelAuditQueryRepository) as repo:
        yield repo


async def execute(args):
    service = DshAuditTreeProjectionService(scope)
    if not args.apply:
        result = await service.queries.execute(
            args.tenant_id,
            lambda repo: {"apply": False, **repo.fold_hierarchy_batch(apply=False), "progress": repo.tree_progress()},
        )
        print(json.dumps(result), flush=True)
        return
    owner = None
    for _ in range(args.max_steps):
        result = await service.step(args.tenant_id, owner=owner)
        print(json.dumps({"apply": True, **result}), flush=True)
        owner = result.get("owner")
        if not result["has_more"]:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-steps", type=int, default=1)
    args = parser.parse_args()
    if args.tenant_id < 1 or not 1 <= args.max_steps <= 10000:
        parser.error("Positive tenant and max-steps 1..10000 required")
    asyncio.run(execute(args))


if __name__ == "__main__":
    main()
