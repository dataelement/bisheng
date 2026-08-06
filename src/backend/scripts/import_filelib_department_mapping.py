#!/usr/bin/env python3
"""Import filelib department mapping rows from CSV into ``filelib_department_mapping``.

CSV columns (header names are case-sensitive):

- ``external_department_id`` (required) — upstream department id used by filelib sync
- ``external_department_name`` (optional)
- ``org_code`` (required) — maps to ``department.external_id``

Extra columns such as ``ORG_ID`` are ignored.

Default is dry-run (no DB writes). Pass ``--apply`` to upsert rows keyed by
``external_department_id``.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/import_filelib_department_mapping.py \
      --csv /path/ORG_ORGANIZATION_org_code_8digits.csv

    PYTHONPATH=./ .venv/bin/python scripts/import_filelib_department_mapping.py \
      --csv /path/ORG_ORGANIZATION_org_code_8digits.csv --apply

    bash scripts/import_filelib_department_mapping.sh \
      --csv /path/ORG_ORGANIZATION_org_code_8digits.csv --apply
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import select  # noqa: E402

from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.open_endpoints.domain.models.filelib_department_mapping import (  # noqa: E402
    FilelibDepartmentMapping,
)

REQUIRED_COLUMNS = ("external_department_id", "org_code")


@dataclass(frozen=True)
class MappingRow:
    external_department_id: str
    external_department_name: str | None
    org_code: str


@dataclass
class ImportStats:
    csv_rows: int = 0
    skipped_invalid: int = 0
    duplicate_rows_dropped: int = 0
    unique_rows: int = 0
    to_insert: int = 0
    to_update: int = 0
    inserted: int = 0
    updated: int = 0


def _normalize_cell(value: object | None) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _load_csv_rows(csv_path: Path) -> tuple[list[MappingRow], ImportStats]:
    stats = ImportStats()
    parsed: list[MappingRow] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row")

        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

        for raw in reader:
            stats.csv_rows += 1
            external_department_id = _normalize_cell(raw.get("external_department_id"))
            org_code = _normalize_cell(raw.get("org_code"))
            external_department_name = _normalize_cell(raw.get("external_department_name")) or None

            if not external_department_id or not org_code:
                stats.skipped_invalid += 1
                continue

            parsed.append(
                MappingRow(
                    external_department_id=external_department_id,
                    external_department_name=external_department_name,
                    org_code=org_code,
                )
            )

    deduped: dict[str, MappingRow] = {}
    for row in parsed:
        if row.external_department_id in deduped:
            stats.duplicate_rows_dropped += 1
        deduped[row.external_department_id] = row

    stats.unique_rows = len(deduped)
    return list(deduped.values()), stats


async def _import_rows(rows: list[MappingRow], *, apply: bool) -> ImportStats:
    stats = ImportStats(unique_rows=len(rows))

    async with get_async_db_session() as session:
        existing_rows = await session.exec(select(FilelibDepartmentMapping))
        existing_by_external_id = {
            item.external_department_id: item for item in existing_rows.all()
        }

        for row in rows:
            existing = existing_by_external_id.get(row.external_department_id)
            if existing is None:
                stats.to_insert += 1
                if apply:
                    session.add(
                        FilelibDepartmentMapping(
                            external_department_id=row.external_department_id,
                            external_department_name=row.external_department_name,
                            org_code=row.org_code,
                        )
                    )
                    stats.inserted += 1
                continue

            needs_update = (
                existing.org_code != row.org_code
                or existing.external_department_name != row.external_department_name
            )
            if not needs_update:
                continue

            stats.to_update += 1
            if apply:
                existing.org_code = row.org_code
                existing.external_department_name = row.external_department_name
                session.add(existing)
                stats.updated += 1

        if apply and (stats.inserted or stats.updated):
            await session.commit()

    return stats


def _merge_stats(load_stats: ImportStats, import_stats: ImportStats) -> ImportStats:
    load_stats.to_insert = import_stats.to_insert
    load_stats.to_update = import_stats.to_update
    load_stats.inserted = import_stats.inserted
    load_stats.updated = import_stats.updated
    return load_stats


def _print_summary(stats: ImportStats, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[import_filelib_department_mapping] mode={mode}")
    print(f"  csv_rows={stats.csv_rows}")
    print(f"  skipped_invalid={stats.skipped_invalid}")
    print(f"  duplicate_rows_dropped={stats.duplicate_rows_dropped}")
    print(f"  unique_rows={stats.unique_rows}")
    print(f"  to_insert={stats.to_insert}")
    print(f"  to_update={stats.to_update}")
    if apply:
        print(f"  inserted={stats.inserted}")
        print(f"  updated={stats.updated}")


async def _run(csv_path: Path, *, apply: bool) -> int:
    rows, stats = _load_csv_rows(csv_path)
    import_stats = await _import_rows(rows, apply=apply)
    stats = _merge_stats(stats, import_stats)
    _print_summary(stats, apply=apply)

    if stats.unique_rows == 0:
        print("[import_filelib_department_mapping] no valid rows to import.", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        required=True,
        type=Path,
        help="CSV file with external_department_id, external_department_name, org_code",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write rows to filelib_department_mapping (default: dry-run only)",
    )
    args = parser.parse_args()

    csv_path = args.csv.expanduser().resolve()
    if not csv_path.is_file():
        print(f"[import_filelib_department_mapping] CSV not found: {csv_path}", file=sys.stderr)
        return 1

    try:
        return asyncio.run(_run(csv_path, apply=args.apply))
    except ValueError as exc:
        print(f"[import_filelib_department_mapping] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
