"""F015 migration rehearsal: time `v310b1_f015_dsh_call_pricing` on a large dsh_model_call table.

Builds dsh_model_call in its pre-F015 shape inside a DEDICATED rehearsal database, fills it with
synthetic call rows, runs the real migration, verifies a price snapshot round-trips through the
new JSON column (MySQL JSON / DM8 CLOB), and prints the timings used to size the stop-the-world
upgrade window (features/v3.1.0-beta1/015-credit-pricing/runbook.md).

    cd src/backend/
    python scripts/rehearse_dsh_call_pricing_migration.py --url 'mysql+pymysql://user@host:3306/rehearsal_f015' --rows 1000000
    python scripts/rehearse_dsh_call_pricing_migration.py --url 'dm+dmPython://user@host:5236/?schema=REHEARSAL_F015' --rows 1000000

The database (or DM schema) name must start with ``rehearsal_``; the script refuses anything else
and drops the table it created when it finishes (``--keep`` leaves it for inspection). It never
touches a service database. Credentials belong in the URL given on the command line, not in files.

Exit codes: 0 rehearsal passed, 2 verification failed, 1 unexpected error / refused target.
"""

import argparse
import importlib.util
import os
import sys
import time
import uuid
from datetime import datetime, timedelta

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from sqlalchemy import create_engine, insert, inspect  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlmodel import Session  # noqa: E402

from bisheng.dsh.domain.models.model_call import DshModelCall  # noqa: E402

TABLE = "dsh_model_call"
NEW_COLUMNS = ("pricing", "cost_micro", "currency")
REVISION = os.path.join(_BACKEND_ROOT, "bisheng/core/database/alembic/versions/v3_1_0b1_f015_dsh_call_pricing.py")
SNAPSHOT = {
    "currency": "CNY",
    "credit_value_micro": 10000,
    "input_micro": 9000000,
    "cache_read_micro": 300000,
    "cache_write_micro": 9000000,
    "output_micro": 27000000,
}


def target_name(url) -> str:
    return (url.query.get("schema") or url.database or "").lower()


def load_revision():
    spec = importlib.util.spec_from_file_location("f015_call_pricing", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_pre_f015_table(engine) -> None:
    DshModelCall.__table__.create(engine)
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for name in NEW_COLUMNS:
            operations.drop_column(TABLE, name)


def fill(engine, rows: int, batch: int) -> float:
    started = time.monotonic()
    base = datetime(2026, 11, 1)
    columns = {column.name for column in DshModelCall.__table__.columns} - set(NEW_COLUMNS)
    statement = insert(DshModelCall.__table__)
    for offset in range(0, rows, batch):
        values = []
        for index in range(offset, min(rows, offset + batch)):
            input_tokens, output_tokens = 1_000 + index % 30_000, 50 + index % 2_000
            row = {
                "request_id": str(uuid.uuid4()),
                "tenant_id": 1 + index % 10,
                "user_id": 1 + index % 5_000,
                "session_id": str(uuid.uuid4()),
                "model_id": 1 + index % 20,
                "credit_rate": 100,
                "usage_month": "2026-11",
                "policy_version": 1,
                "event_version": 2,
                "quota_epoch": 1,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "billed_tokens": input_tokens + output_tokens,
                "cache_read_tokens": index % 3 * 500,
                "status": "SUCCEEDED",
                "usage_source": "PROVIDER",
                "started_at": base + timedelta(seconds=index),
                "ended_at": base + timedelta(seconds=index + 3),
                "settled_at": base + timedelta(seconds=index + 3),
            }
            values.append({key: value for key, value in row.items() if key in columns})
        with engine.begin() as connection:
            connection.execute(statement, values)
    return time.monotonic() - started


def migrate(engine, revision) -> float:
    started = time.monotonic()
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
    return time.monotonic() - started


def verify(engine) -> list[str]:
    problems = []
    present = {column["name"] for column in inspect(engine).get_columns(TABLE)}
    problems.extend(f"missing column {name}" for name in NEW_COLUMNS if name not in present)
    if problems:
        return problems
    request_id = str(uuid.uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            DshModelCall(
                request_id=request_id,
                tenant_id=1,
                user_id=1,
                session_id=request_id,
                model_id=1,
                usage_month="2026-11",
                policy_version=1,
                event_version=1,
                quota_epoch=1,
                status="RUNNING",
                pricing=SNAPSHOT,
                cost_micro=88_200,
                currency="CNY",
            )
        )
    with Session(engine) as session:
        row = session.get(DshModelCall, request_id)
        if row.pricing != SNAPSHOT or (row.cost_micro, row.currency) != (88_200, "CNY"):
            problems.append(f"price snapshot did not round-trip: {row.pricing!r} {row.cost_micro} {row.currency}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F015: rehearse the dsh_model_call pricing migration.")
    parser.add_argument("--url", required=True, help="SQLAlchemy URL of a dedicated rehearsal_* database")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--batch", type=int, default=10_000)
    parser.add_argument("--keep", action="store_true", help="leave the rehearsal table in place")
    args = parser.parse_args(argv)

    url = make_url(args.url)
    if not target_name(url).startswith("rehearsal_"):
        print("refused: the target database or schema name must start with rehearsal_", file=sys.stderr)
        return 1
    engine = create_engine(url)
    if inspect(engine).has_table(TABLE):
        print(f"refused: {TABLE} already exists in the rehearsal target; drop it first", file=sys.stderr)
        return 1
    revision = load_revision()
    try:
        create_pre_f015_table(engine)
        fill_seconds = fill(engine, args.rows, args.batch)
        print(f"dialect={engine.dialect.name} rows={args.rows} fill_seconds={fill_seconds:.1f}")
        upgrade_seconds = migrate(engine, revision)
        print(f"upgrade_seconds={upgrade_seconds:.2f}")
        repeat_seconds = migrate(engine, revision)
        print(f"repeat_upgrade_seconds={repeat_seconds:.2f}  (must be a no-op)")
        problems = verify(engine)
        for problem in problems:
            print(problem)
        print("rehearsal: " + ("FAILED" if problems else "passed"))
        return 2 if problems else 0
    finally:
        if not args.keep:
            DshModelCall.__table__.drop(engine, checkfirst=True)
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
