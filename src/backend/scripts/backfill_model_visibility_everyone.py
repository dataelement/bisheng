"""Give chat models without a visibility row an explicit "everyone" grant.

Why: without DSH, a chat model that has no row in ``dsh_model_visibility`` is
offered to everyone. With DSH a missing row means "nobody". Models created while
DSH was off (before rows were written for them) would therefore disappear from
every user's workbench the moment DSH is enabled. Run this once per tenant
BEFORE enabling DSH; it only adds rows, never changes an existing one.

Covers every chat (``llm``) model the tenant can see: its own providers plus
Root-shared ones, online or offline.

Run from src/backend with the live service's config. Dry-run is the default:
  python scripts/backfill_model_visibility_everyone.py --tenant-id 1
  python scripts/backfill_model_visibility_everyone.py --tenant-id 1 --apply --actor-user-id 1
Exit codes: 0 success, 2 invalid arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository  # noqa: E402
from bisheng.dsh.domain.services.profile import profile_scope  # noqa: E402
from bisheng.llm.domain.const import LLMModelType  # noqa: E402
from bisheng.llm.domain.models import LLMDao  # noqa: E402
from bisheng.llm.domain.services.llm import LLMService  # noqa: E402


async def chat_model_ids(tenant_id: int) -> list[int]:
    servers = await LLMService.acollect_visible_servers(tenant_id)
    if not servers:
        return []
    # The server set is already the tenant's authorized view (own + Root-shared).
    with bypass_tenant_filter():
        models = await LLMDao.aget_model_by_server_ids([server.id for server in servers])
    return sorted(model.id for model in models if (model.model_type or "").strip() == LLMModelType.LLM.value)


def backfill(model_ids: list[int], actor: int, apply: bool) -> dict:
    with get_sync_db_session() as session:
        repository = UnifiedPolicyRepository(session)
        missing = [model_id for model_id in model_ids if not repository.visibility(model_id)["version"]]
        if apply:
            for model_id in missing:
                repository.initialize_model_visibility(model_id, actor)
            session.commit()
    return {"chat_models": len(model_ids), "missing_rows": missing, "applied": apply}


async def run(args) -> int:
    with profile_scope(args.tenant_id):
        model_ids = await chat_model_ids(args.tenant_id)
        result = backfill(model_ids, args.actor_user_id, args.apply)
    print(json.dumps({"tenant_id": args.tenant_id, **result}, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--actor-user-id", type=int, default=1, help="recorded as updated_by in the audit trail")
    parser.add_argument("--apply", action="store_true", help="write rows (default: dry-run)")
    args = parser.parse_args()
    if args.tenant_id < 1 or args.actor_user_id < 1:
        parser.print_usage(sys.stderr)
        print("--tenant-id and --actor-user-id must be positive", file=sys.stderr)
        return 2
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
