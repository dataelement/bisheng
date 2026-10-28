"""Run after Alembic upgrade; preview by default, --apply commits one tenant atomically."""

import argparse
import json

from bisheng.core.database import get_sync_db_session
from bisheng.dsh.domain.services.legacy_credit_migration import migrate_legacy_credits
from bisheng.dsh.domain.services.profile import profile_scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--actor-id", type=int, required=True, help="Administrator recorded in the migration audit")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if min(args.tenant_id, args.actor_id) < 1:
        parser.error("IDs must be positive")
    with profile_scope(args.tenant_id), get_sync_db_session() as session:
        result = migrate_legacy_credits(session, actor_id=args.actor_id, apply=args.apply)
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
