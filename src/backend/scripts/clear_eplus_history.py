"""Back up, then clear all E+ conversation turns without changing configuration.

Run from the backend root with the live service's config environment:
  python scripts/clear_eplus_history.py --all-tenants --backup /data/eplus-history.json
  python scripts/clear_eplus_history.py --all-tenants --backup /data/eplus-history.json \
    --apply --workers-stopped --confirm CLEAR_ALL_EPLUS_HISTORY

The default only exports a backup. Apply requires that exact unchanged backup
and stopped E+ workers. Inbound deduplication rows and conversation sequence
counters are deliberately preserved. No Redis or other infrastructure is used.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import signal
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Column, MetaData, Table, delete, inspect, select

_BACKEND_ROOT = str(Path(__file__).resolve().parent.parent)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def encode_value(value):
    """Preserve typed values in a JSON backup without printing message contents."""
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    raise TypeError(f"Unsupported backup type: {type(value).__name__}")


def cleanup(connection, *, tenant_id, backup_path, apply=False, workers_stopped=False):
    """Execute inside the caller's transaction; fail closed on snapshot changes."""
    if tenant_id is not None and tenant_id <= 0:
        raise RuntimeError("tenant-id must be positive")
    if apply and not workers_stopped:
        raise RuntimeError("Stop ALL E+ workers before apply; pass --workers-stopped")
    # DM index reflection mutates immutable SQLAlchemy C-extension Rows.
    # This data-only operation needs column types, never indexes or foreign keys.
    columns = inspect(connection).get_columns("eplus_turn")
    table = Table("eplus_turn", MetaData(), *(Column(item["name"], item["type"]) for item in columns))
    if not {"id", "tenant_id", "conversation_id", "status"}.issubset(table.c.keys()):
        raise RuntimeError("Unexpected eplus_turn schema; no writes performed")
    statement = select(table).order_by(table.c.id)
    if tenant_id is not None:
        statement = statement.where(table.c.tenant_id == tenant_id)
    rows = [dict(row) for row in connection.execute(statement).mappings()]
    if any(row["status"] not in {"SUCCEEDED", "FAILED", "CANCELLED"} for row in rows):
        raise RuntimeError("Found non-terminal turns; drain messages before stopping workers")
    identity = connection.engine.url.render_as_string(hide_password=True)
    snapshot = json.loads(
        json.dumps(
            {
                "format": "eplus-turn-backup-v1",
                "table": "eplus_turn",
                "database_fingerprint": hashlib.sha256(identity.encode()).hexdigest(),
                "tenant_id": tenant_id,
                "rows": rows,
            },
            default=encode_value,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    path = Path(backup_path)
    if not apply:
        # Exclusive creation prevents overwriting the only recovery copy.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        if json.loads(path.read_text(encoding="utf-8")) != snapshot:
            raise RuntimeError("Backup verification failed; no writes performed")
        return len(rows)
    if json.loads(path.read_text(encoding="utf-8")) != snapshot:
        raise RuntimeError("Backup does not match current database/scope/rows; create a NEW backup")
    deleted = 0
    for offset in range(0, len(rows), 200):
        chunk = rows[offset : offset + 200]
        statement = delete(table).where(table.c.id.in_([row["id"] for row in chunk]))
        if tenant_id is not None:
            statement = statement.where(table.c.tenant_id == tenant_id)
        else:
            # Explicit cross-tenant mode still limits each batch to backed-up tenants.
            tenants = {row["tenant_id"] for row in chunk}
            if None in tenants:
                raise RuntimeError("Found NULL tenant_id; resolve invalid records before cleanup")
            statement = statement.where(table.c.tenant_id.in_(tenants))
        result = connection.execute(statement)
        if result.rowcount != len(chunk):
            raise RuntimeError("Delete count mismatch; transaction must roll back")
        deleted += result.rowcount
    statement = select(table.c.id)
    if tenant_id is not None:
        statement = statement.where(table.c.tenant_id == tenant_id)
    if connection.execute(statement).first() is not None:
        raise RuntimeError("Rows remain or new messages arrived; transaction must roll back")
    return deleted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tenant-id", type=int)
    scope.add_argument("--all-tenants", action="store_true")
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workers-stopped", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.apply and args.confirm != "CLEAR_ALL_EPLUS_HISTORY":
        parser.error("--apply requires --confirm CLEAR_ALL_EPLUS_HISTORY")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    def deadline(_signum, _frame):
        raise TimeoutError("Maintenance deadline exceeded")

    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(args.timeout)
    try:
        # Lazy imports let --help and isolated tests work without service config.
        from bisheng.common.services.config_service import settings  # noqa: F401
        from bisheng.core.context.tenant import bypass_tenant_filter
        from bisheng.core.database import get_sync_db_session

        with bypass_tenant_filter(), get_sync_db_session() as session:
            try:
                count = cleanup(
                    session.connection(),
                    tenant_id=args.tenant_id,
                    backup_path=args.backup,
                    apply=args.apply,
                    workers_stopped=args.workers_stopped,
                )
                if args.apply:
                    session.commit()
                else:
                    session.rollback()
            except BaseException:
                session.rollback()
                raise
        print(
            json.dumps(
                {
                    "mode": "deleted" if args.apply else "backup_only",
                    "turn_count": count,
                    "tenant_id": args.tenant_id,
                    "all_tenants": args.all_tenants,
                    "backup": str(args.backup.resolve()),
                }
            )
        )
        return 0
    except (RuntimeError, TimeoutError, FileNotFoundError, FileExistsError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Driver errors may contain credentials or message bodies; only expose type.
        print(f"STOP: {type(exc).__name__}; no successful completion. Inspect locally.", file=sys.stderr)
        return 3
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    sys.exit(main())
