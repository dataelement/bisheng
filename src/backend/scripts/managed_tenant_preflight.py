"""Read-only F009 inventory. Run from src/backend with the normal config environment."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Read-only managed tenant policy and pending-resource inventory")
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, action="append", default=[])
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.tenant_id < 1 or not 1 <= args.limit <= 1000 or any(uid < 1 for uid in args.user_id):
        parser.error("IDs must be positive and limit must be between 1 and 1000")
    from bisheng.tenant.application.managed_tenant_preflight import inspect_managed_tenant

    print(
        json.dumps(
            asyncio.run(inspect_managed_tenant(args.tenant_id, args.user_id, args.limit)), ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
