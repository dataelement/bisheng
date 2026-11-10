"""Backfill audit name digests without touching originals or model names.

Run from src/backend with the live service's config. Dry-run is the default:
  python scripts/backfill_dsh_audit_model_names.py --tenant-id 1
  python scripts/backfill_dsh_audit_model_names.py --tenant-id 1 --apply --max-batches 20
Each batch commits separately; resume with the reported --after-request-id.
Finish deploying all writers before running; rerun from the start to catch late legacy rows.
"""

import argparse
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.dsh.domain.repositories.model_audit_maintenance import backfill_name_digests  # noqa: E402
from bisheng.dsh.domain.services.profile import profile_scope  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--after-request-id", default="")
    args = parser.parse_args()
    if args.tenant_id < 1 or not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 10000:
        parser.error("A positive tenant, batch size 1..1000 and max-batches 1..10000 are required")
    after = args.after_request_id
    with profile_scope(args.tenant_id):
        for _ in range(args.max_batches):
            with get_sync_db_session() as session, session.begin():
                result = backfill_name_digests(session, after=after, limit=args.batch_size, apply=args.apply)
            print(json.dumps(result), flush=True)
            after = result["after_request_id"]
            if not result["has_more"]:
                break


if __name__ == "__main__":
    main()
