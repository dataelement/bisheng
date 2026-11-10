"""Prepare historical status and mark group projection without changing originals.

Run from src/backend with the live service's config after all writers upgrade:
  python scripts/backfill_dsh_audit_presentation.py --tenant-id 1
  python scripts/backfill_dsh_audit_presentation.py --tenant-id 1 --apply --max-batches 20
Dry-run is the default. Resume via --after-request-id and rerun from the start
to detect late rows. The independent audit task projects prepared groups later.
"""

import argparse
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.dsh.domain.repositories.model_audit_maintenance import backfill_audit_presentation  # noqa: E402
from bisheng.dsh.domain.services.profile import profile_scope  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--batch-size", default=200, type=int)
    parser.add_argument("--max-batches", default=1, type=int)
    parser.add_argument("--after-request-id", default="")
    args = parser.parse_args()
    if args.tenant_id < 1 or not 1 <= args.batch_size <= 1000 or not 1 <= args.max_batches <= 10000:
        parser.error("Positive tenant, batch size 1..1000 and max-batches 1..10000 required")
    after = args.after_request_id
    with profile_scope(args.tenant_id):
        for _ in range(args.max_batches):
            with get_sync_db_session() as session, session.begin():
                result = backfill_audit_presentation(session, after=after, limit=args.batch_size, apply=args.apply)
            print(json.dumps(result), flush=True)
            after = result["after_request_id"]
            if not result["has_more"]:
                break


if __name__ == "__main__":
    main()
