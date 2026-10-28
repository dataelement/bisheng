"""Replay retained safety facts or explicitly purge one tenant's audit data.

Run from src/backend with the live service's config environment variable:
  python scripts/dsh_content_safety_maintenance.py rebuild --tenant-id 1
  python scripts/dsh_content_safety_maintenance.py rebuild --tenant-id 1 --apply
  python scripts/dsh_content_safety_maintenance.py purge-details --tenant-id 1 --before 2026-10-01T00:00:00Z
  python scripts/dsh_content_safety_maintenance.py purge-audit --tenant-id 1 --before 2026-10-01T00:00:00Z --apply
Default dry-run validates the tenant and reports the proposed bounds without
scanning or writing facts. Apply commits each bounded batch independently.
This DB-only script neither initializes middleware nor reclaims bodies or billing.

Coverage AC: AC-43, AC-48, AC-51, AC-52, AC-53.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# A standalone operations process emits only its own safe reports. Importing this
# module as a library must leave the host's logging configuration unchanged.
if __name__ == "__main__":
    import logging

    from loguru import logger

    logging.disable(logging.CRITICAL)
    logger.disable("bisheng")

_STARTUP_FAILURE = None
try:
    from sqlmodel import select

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import strict_tenant_filter
    from bisheng.core.database import get_sync_db_session
    from bisheng.database.models.tenant import Tenant
    from bisheng.dsh.domain.repositories.content_safety_maintenance import ContentSafetyMaintenanceRepository
    from bisheng.dsh.domain.repositories.model_audit_setting import DshModelAuditSettingRepository
    from bisheng.dsh.domain.services.profile import profile_scope
except Exception as error:
    # YAML/dependency errors may contain secrets; retain their type alone.
    _STARTUP_FAILURE = type(error).__name__
    settings = None


def _cutoff(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError("A timezone-aware ISO8601 cutoff is required") from None


def _arguments(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("rebuild", "purge-details", "purge-audit"):
        command = commands.add_parser(operation)
        command.add_argument("--tenant-id", type=int, required=True)
        command.add_argument("--apply", action="store_true", help="Commit writes; otherwise only show the plan")
        command.add_argument("--batch-size", type=int, default=100, help="Rows per batch, 1..100 (default: 100)")
        command.add_argument("--max-batches", type=int, default=1, help="Batches this run, 1..10000 (default: 1)")
        command.set_defaults(cursor=None, before=None)
        if operation == "rebuild":
            command.add_argument("--cursor", help="Resume with a previously committed rebuild next_cursor")
        else:
            command.add_argument("--before", type=_cutoff, required=True, help="Exclusive timezone-aware cutoff")
    args = parser.parse_args(argv)
    if args.tenant_id < 1 or not 1 <= args.batch_size <= 100 or not 1 <= args.max_batches <= 10000:
        parser.error("A positive tenant, batch size 1..100 and max-batches 1..10000 are required")
    if args.cursor is not None and (not args.cursor or len(args.cursor) > 2048):
        parser.error("Invalid rebuild cursor")
    return args


def _report(args, result):
    print(
        json.dumps({"operation": args.operation, "tenant_id": args.tenant_id, "apply": args.apply, **result}),
        flush=True,
    )


def _apply(args):
    if args.operation == "purge-audit":
        # Persist the deletion barrier before any later transaction removes rows.
        with get_sync_db_session() as session, session.begin():
            DshModelAuditSettingRepository(session).begin_cleanup(before=args.before)
    cursor = args.cursor
    for _ in range(args.max_batches):
        with get_sync_db_session() as session, session.begin():
            repository = ContentSafetyMaintenanceRepository(session)
            if args.operation == "rebuild":
                result = repository.rebuild_batch(cursor=cursor, limit=args.batch_size)
            elif args.operation == "purge-details":
                result = repository.purge_batch(details_before=args.before, limit=args.batch_size, include_audits=False)
            else:
                result = repository.purge_batch(limit=args.batch_size)
        # A failed commit must never emit a successful batch report or new cursor.
        _report(args, result)
        if args.operation == "rebuild":
            cursor = result["next_cursor"]
            if cursor is None:
                break
        elif not result["has_more"]:
            break


def main(argv=None) -> int:
    args = _arguments(argv)
    if _STARTUP_FAILURE is not None:
        print(f"Service configuration or dependencies are unavailable ({_STARTUP_FAILURE}).", file=sys.stderr)
        return 3
    if not settings.database_url:
        print("Service database configuration is required.", file=sys.stderr)
        return 3
    try:
        with profile_scope(args.tenant_id):
            with get_sync_db_session() as session, strict_tenant_filter():
                tenant = session.exec(select(Tenant.id).where(Tenant.id == args.tenant_id)).one_or_none()
            if tenant is None:
                print("Requested tenant does not exist.", file=sys.stderr)
                return 4
            if not args.apply:
                _report(
                    args,
                    {
                        "scan_performed": False,
                        "batch_size": args.batch_size,
                        "max_batches": args.max_batches,
                        "before": args.before.isoformat() if args.before is not None else None,
                        "resume_requested": args.cursor is not None,
                    },
                )
            else:
                _apply(args)
        return 0
    except ValueError:
        print("Invalid maintenance request; no failed batch is reported as successful.", file=sys.stderr)
        return 2
    except Exception as error:
        # Do not print exceptions, connection URLs, SQL, payloads or tracebacks.
        print(f"Maintenance failed ({type(error).__name__}); committed batches remain committed.", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
