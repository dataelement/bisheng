#!/usr/bin/env python3
"""
mysql_to_dm_migrate.py — Copy all data from MySQL to DaMeng.

Prerequisites:
  1. DaMeng schema already exists (run alembic upgrade head first):
       BISHENG_DATABASE_URL="dm+dmPython://..." uv run alembic upgrade head
  2. This script copies data only — tables must already exist on DaMeng.

Usage:
    uv run python scripts/mysql_to_dm_migrate.py \\
        --src "mysql+pymysql://user:pass@host/db" \\
        --dst "dm+dmPython://SYSDBA:pass@host:5236/BISHENG" \\
        [--tables t1,t2]      # migrate only these tables
        [--skip   t1,t2]      # additional tables to skip
        [--batch-size 500]    # rows per INSERT batch (default 500)
        [--resume-from TABLE] # skip tables before TABLE (use after a failure)
        [--truncate]          # DELETE FROM dst table before inserting
        [--dry-run]           # analyse only, no writes
        [--no-verify]         # skip row-count check at the end
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-8s  %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('migrate')

# Never migrate these tables — they are managed by Alembic on DaMeng separately
DEFAULT_SKIP: Set[str] = {'alembic_version'}


# ---------------------------------------------------------------------------
# Value conversion: MySQL → DaMeng
# ---------------------------------------------------------------------------

def to_dm(value: Any, col_type: str) -> Any:
    """Convert a MySQL column value to a DaMeng-compatible Python value.

    Key differences handled here:
    - JSON  : MySQL returns dict/list; DaMeng stores as CLOB text.
    - bytes : edge-case from MySQL BIT / BINARY columns.
    """
    if value is None:
        return None
    if col_type == 'json':
        # MySQL JSON type → Python dict/list; must be serialised for DaMeng CLOB
        if isinstance(value, (dict, list, bool, int, float)):
            return json.dumps(value, ensure_ascii=False)
        return value  # already a string somehow — pass through
    if isinstance(value, (bytes, bytearray)):
        return value.decode('utf-8', errors='replace')
    return value


# ---------------------------------------------------------------------------
# Table ordering: topological sort by FK dependency
# ---------------------------------------------------------------------------

def _build_fk_map(src_insp, tables: List[str]) -> Dict[str, Set[str]]:
    table_set = set(tables)
    fk_map: Dict[str, Set[str]] = {t: set() for t in tables}
    for tbl in tables:
        try:
            for fk in src_insp.get_foreign_keys(tbl):
                ref = fk.get('referred_table')
                if ref and ref in table_set and ref != tbl:
                    fk_map[tbl].add(ref)
        except Exception:
            pass
    return fk_map


def topo_sort(tables: List[str], fk_map: Dict[str, Set[str]]) -> List[str]:
    """Return tables in FK dependency order (parent tables first)."""
    visited: Set[str] = set()
    result: List[str] = []

    def visit(tbl: str, stack: Set[str]) -> None:
        if tbl in visited:
            return
        if tbl in stack:          # cycle — emit as-is
            if tbl not in visited:
                result.append(tbl)
                visited.add(tbl)
            return
        stack.add(tbl)
        for dep in fk_map.get(tbl, set()):
            visit(dep, stack)
        stack.discard(tbl)
        if tbl not in visited:
            result.append(tbl)
            visited.add(tbl)

    for t in tables:
        visit(t, set())
    return result


# ---------------------------------------------------------------------------
# Primary-key detection for cursor-based pagination
# ---------------------------------------------------------------------------

def single_int_pk(src_insp, table_name: str) -> Optional[str]:
    """Return the PK column name if the table has exactly one integer PK, else None."""
    try:
        pk_cols = src_insp.get_pk_constraint(table_name).get('constrained_columns', [])
        if len(pk_cols) != 1:
            return None
        col_name = pk_cols[0]
        for col in src_insp.get_columns(table_name):
            if col['name'] == col_name:
                type_name = type(col['type']).__name__.lower()
                if 'int' in type_name:
                    return col_name
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Per-table migration
# ---------------------------------------------------------------------------

def migrate_table(
    src_conn: Connection,
    dst_conn: Connection,
    src_insp,
    table_name: str,
    batch_size: int,
    truncate: bool,
    dry_run: bool,
) -> Tuple[int, int]:
    """
    Copy all rows of table_name from MySQL to DaMeng.
    Returns (rows_copied, src_total).
    """
    columns = src_insp.get_columns(table_name)
    col_names: List[str] = [c['name'] for c in columns]
    col_types: Dict[str, str] = {
        c['name']: type(c['type']).__name__.lower() for c in columns
    }

    src_total: int = src_conn.execute(
        text(f'SELECT COUNT(*) FROM `{table_name}`')
    ).scalar() or 0
    log.info(f'    rows in source : {src_total:,}')

    if dry_run:
        return 0, src_total

    if truncate:
        log.info(f'    truncating target table...')
        dst_conn.execute(text(f'DELETE FROM "{table_name}"'))
        dst_conn.commit()

    if src_total == 0:
        return 0, 0

    # DaMeng INSERT statement.
    # All identifiers are double-quoted to handle reserved words (key, value, …).
    # Bind-parameter names are prefixed with "p_" to avoid clashing with reserved
    # words inside the DaMeng SQL parser (e.g.  :key  might be misinterpreted).
    dm_cols   = ', '.join(f'"{c}"'  for c in col_names)
    dm_params = ', '.join(f':p_{c}' for c in col_names)
    insert_sql = text(f'INSERT INTO "{table_name}" ({dm_cols}) VALUES ({dm_params})')

    def make_row(raw_row) -> Dict[str, Any]:
        return {
            f'p_{c}': to_dm(v, col_types[c])
            for c, v in zip(col_names, raw_row)
        }

    pk_col = single_int_pk(src_insp, table_name)
    rows_copied = 0

    if pk_col:
        # Cursor-based pagination — efficient even for very large tables
        last_pk: Any = -1
        while True:
            rows = src_conn.execute(
                text(
                    f'SELECT * FROM `{table_name}` '
                    f'WHERE `{pk_col}` > :lpk '
                    f'ORDER BY `{pk_col}` '
                    f'LIMIT :n'
                ),
                {'lpk': last_pk, 'n': batch_size},
            ).fetchall()
            if not rows:
                break

            dst_conn.execute(insert_sql, [make_row(r) for r in rows])
            dst_conn.commit()

            last_pk = rows[-1][col_names.index(pk_col)]
            rows_copied += len(rows)
            log.info(f'    copied : {rows_copied:,} / {src_total:,}   (last {pk_col}={last_pk})')
    else:
        # OFFSET-based fallback for tables without a single-int PK
        offset = 0
        while offset < src_total:
            rows = src_conn.execute(
                text(f'SELECT * FROM `{table_name}` LIMIT :n OFFSET :off'),
                {'n': batch_size, 'off': offset},
            ).fetchall()
            if not rows:
                break

            dst_conn.execute(insert_sql, [make_row(r) for r in rows])
            dst_conn.commit()

            offset += len(rows)
            rows_copied += len(rows)
            log.info(f'    copied : {rows_copied:,} / {src_total:,}')

    return rows_copied, src_total


# ---------------------------------------------------------------------------
# Post-migration: sequence reset
# ---------------------------------------------------------------------------

def print_sequence_reset(dst_conn: Connection, tables: List[str]) -> None:
    """
    After migrating rows with explicit IDs, DaMeng's IDENTITY sequences are
    still at their initial value.  The next application INSERT will try to use
    ID=1 and hit a PK conflict.  Print the DDL to fix each sequence.
    """
    lines: List[str] = []
    for tbl in tables:
        try:
            max_id = dst_conn.execute(
                text(f'SELECT MAX("id") FROM "{tbl}"')
            ).scalar()
            if max_id is not None:
                next_val = int(max_id) + 1
                lines.append(
                    f'ALTER TABLE "{tbl}" '
                    f'MODIFY "id" INT IDENTITY({next_val}, 1);'
                )
        except Exception:
            pass  # table has no "id" column or is empty

    if not lines:
        return

    sep = '=' * 60
    print(f'\n-- {sep}')
    print('-- Run the following on DaMeng to reset IDENTITY sequences.')
    print('-- This prevents PK conflicts on the next INSERT from the app.')
    print(f'-- {sep}')
    for line in lines:
        print(line)
    print(f'-- {sep}\n')


# ---------------------------------------------------------------------------
# Post-migration: row-count verification
# ---------------------------------------------------------------------------

def verify(src_conn: Connection, dst_conn: Connection, tables: List[str]) -> bool:
    log.info('--- Row-count verification ---')
    all_ok = True
    for tbl in tables:
        try:
            src_n = src_conn.execute(text(f'SELECT COUNT(*) FROM `{tbl}`')).scalar()
            dst_n = dst_conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
            match = src_n == dst_n
            flag = '✓' if match else '✗ MISMATCH'
            log.info(f'  {tbl:<48} src={src_n:>8,}  dst={dst_n:>8,}  {flag}')
            if not match:
                all_ok = False
        except Exception as e:
            log.warning(f'  {tbl}: verification error — {e}')
    return all_ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description='Copy all data from MySQL to DaMeng (schema must already exist).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('--src', required=True, metavar='URL',
                    help='MySQL URL  e.g. mysql+pymysql://user:pass@host/db')
    ap.add_argument('--dst', required=True, metavar='URL',
                    help='DaMeng URL  e.g. dm+dmPython://SYSDBA:pass@host:5236/BISHENG')
    ap.add_argument('--tables', metavar='T1,T2',
                    help='Migrate only these tables (comma-separated)')
    ap.add_argument('--skip', metavar='T1,T2',
                    help='Skip these tables (on top of alembic_version)')
    ap.add_argument('--batch-size', type=int, default=500, metavar='N',
                    help='Rows per INSERT batch (default: 500)')
    ap.add_argument('--resume-from', metavar='TABLE',
                    help='Skip tables that come before TABLE in the ordered list')
    ap.add_argument('--truncate', action='store_true',
                    help='DELETE rows from DaMeng table before inserting')
    ap.add_argument('--dry-run', action='store_true',
                    help='Print analysis only — write nothing to DaMeng')
    ap.add_argument('--no-verify', action='store_true',
                    help='Skip row-count comparison at the end')
    args = ap.parse_args()

    src_engine: Engine = create_engine(args.src)
    dst_engine: Engine = create_engine(args.dst)

    skip: Set[str] = DEFAULT_SKIP.copy()
    if args.skip:
        skip.update(t.strip() for t in args.skip.split(','))

    with src_engine.connect() as src_conn, dst_engine.connect() as dst_conn:
        src_insp = inspect(src_conn)

        # Determine table list
        if args.tables:
            tables = [t.strip() for t in args.tables.split(',')]
        else:
            tables = [t for t in src_insp.get_table_names() if t not in skip]

        # Sort so parent tables are migrated before their children
        tables = topo_sort(tables, _build_fk_map(src_insp, tables))

        log.info(f'Tables to migrate : {len(tables)}')
        if args.dry_run:
            log.info('DRY RUN — no data will be written')

        # Resume support
        if args.resume_from:
            if args.resume_from in tables:
                idx = tables.index(args.resume_from)
                skipped = tables[:idx]
                tables = tables[idx:]
                log.info(f'Resuming from "{args.resume_from}" (skipping {len(skipped)} tables)')
            else:
                log.warning(f'--resume-from "{args.resume_from}" not found; starting from beginning')

        start = datetime.now()
        total_copied = 0

        for i, table_name in enumerate(tables, 1):
            log.info(f'[{i:>3}/{len(tables)}] {table_name}')
            try:
                copied, total = migrate_table(
                    src_conn, dst_conn, src_insp,
                    table_name,
                    batch_size=args.batch_size,
                    truncate=args.truncate,
                    dry_run=args.dry_run,
                )
                total_copied += copied
                log.info(f'          done   {copied:,} rows')
            except Exception as exc:
                log.error(f'          FAILED : {exc}')
                log.error(f'Re-run with --resume-from {table_name} to retry from this table.')
                sys.exit(1)

        elapsed = (datetime.now() - start).total_seconds()
        log.info(
            f'Finished in {elapsed:.1f}s — '
            f'{total_copied:,} rows copied across {len(tables)} tables'
        )

        if not args.dry_run:
            print_sequence_reset(dst_conn, tables)

        if not args.no_verify and not args.dry_run:
            ok = verify(src_conn, dst_conn, tables)
            if not ok:
                log.error('Row-count mismatch — check the output above.')
                sys.exit(2)

    log.info('Migration complete.')


if __name__ == '__main__':
    main()
