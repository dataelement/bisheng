"""Backfill department short names from exact direct-parent name prefixes.

The script scans active departments across all tenants and sources. It only
targets rows whose short name is NULL or blank. A child is eligible when its
full name starts with its direct parent's full name and the trimmed remainder
contains 1 to 64 characters.

Run from ``src/backend``. The default mode is read-only:

    PYTHONPATH=./ .venv/bin/python scripts/backfill_department_short_names.py

Write only after reviewing the dry-run output and backing up the database:

    PYTHONPATH=./ .venv/bin/python scripts/backfill_department_short_names.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import col, select  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.department import Department  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ARGUMENT = 2
EXIT_EXECUTION = 3
MAX_SHORT_NAME_LENGTH = 64
MAX_BATCH_SIZE = 1000
MAX_SAMPLE_LIMIT = 1000


@dataclass(frozen=True)
class Derivation:
    """Result of deriving a short name from a direct parent."""

    short_name: str | None
    reason: str | None


@dataclass(frozen=True)
class BackfillCandidate:
    """Immutable snapshot used for write-time drift detection."""

    department_id: int
    tenant_id: int
    source: str
    department_name: str
    parent_id: int
    parent_name: str
    short_name: str


@dataclass(frozen=True)
class ApplyOutcome:
    """Observable outcome of one guarded write."""

    updated: bool
    reason: str | None


@dataclass(frozen=True)
class AuditSample:
    """Bounded audit sample for an eligible or skipped row."""

    department_id: int
    tenant_id: int
    source: str
    department_name: str
    parent_id: int | None
    parent_name: str | None
    candidate_short_name: str | None
    outcome: str
    reason: str | None = None


@dataclass
class BackfillReport:
    """Aggregated audit report for one complete scan."""

    scanned: int = 0
    eligible: int = 0
    would_update: int = 0
    updated: int = 0
    skipped: int = 0
    next_start_after_id: int = 0
    reason_counts: Counter[str] = field(default_factory=Counter)
    samples: list[AuditSample] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reason_counts"] = dict(sorted(self.reason_counts.items()))
        return payload


def derive_short_name(department_name: str, parent_name: str) -> Derivation:
    """Derive a short name using an exact, case-sensitive prefix match."""
    if not parent_name:
        return Derivation(short_name=None, reason="parent_name_empty")
    if not department_name.startswith(parent_name):
        return Derivation(short_name=None, reason="parent_name_not_prefix")

    short_name = department_name[len(parent_name) :].strip()
    if not short_name:
        return Derivation(short_name=None, reason="derived_short_name_empty")
    if len(short_name) > MAX_SHORT_NAME_LENGTH:
        return Derivation(short_name=None, reason="derived_short_name_too_long")
    return Derivation(short_name=short_name, reason=None)


def _has_short_name(value: str | None) -> bool:
    return value is not None and bool(value.strip())


def _resolve_department(
    department: Department,
    parent: Department | None,
) -> tuple[BackfillCandidate | None, str | None]:
    if department.status != "active":
        return None, "not_active"
    if _has_short_name(department.short_name):
        return None, "short_name_present"
    if department.parent_id is None:
        return None, "root_department"
    if parent is None:
        return None, "parent_missing"
    if department.tenant_id != parent.tenant_id:
        return None, "parent_tenant_mismatch"

    derivation = derive_short_name(department.name, parent.name)
    if derivation.reason is not None or derivation.short_name is None:
        return None, derivation.reason

    return (
        BackfillCandidate(
            department_id=int(department.id),
            tenant_id=int(department.tenant_id),
            source=department.source,
            department_name=department.name,
            parent_id=int(parent.id),
            parent_name=parent.name,
            short_name=derivation.short_name,
        ),
        None,
    )


async def _load_department(
    session: AsyncSession,
    department_id: int,
    *,
    lock: bool,
) -> Department | None:
    statement = select(Department).where(Department.id == department_id).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    return (await session.exec(statement)).first()


async def apply_candidate(
    session: AsyncSession,
    candidate: BackfillCandidate,
) -> ApplyOutcome:
    """Write one short name only if the complete derivation snapshot is current."""
    department = await _load_department(
        session,
        candidate.department_id,
        lock=True,
    )
    if department is None or department.parent_id is None:
        return ApplyOutcome(updated=False, reason="changed_before_update")

    parent = await _load_department(session, int(department.parent_id), lock=True)
    current, reason = _resolve_department(department, parent)
    if reason is not None or current != candidate:
        return ApplyOutcome(updated=False, reason="changed_before_update")

    department.short_name = candidate.short_name
    session.add(department)
    await session.flush()
    return ApplyOutcome(updated=True, reason=None)


async def _load_batch(
    session: AsyncSession,
    *,
    last_id: int,
    batch_size: int,
) -> list[Department]:
    return list(
        (
            await session.exec(
                select(Department).where(Department.id > last_id).order_by(Department.id).limit(batch_size),
            )
        ).all()
    )


async def _load_parents(
    session: AsyncSession,
    departments: Sequence[Department],
) -> dict[int, Department]:
    parent_ids = {int(department.parent_id) for department in departments if department.parent_id is not None}
    if not parent_ids:
        return {}
    parents = list(
        (
            await session.exec(
                select(Department).where(col(Department.id).in_(parent_ids)),
            )
        ).all()
    )
    return {int(parent.id): parent for parent in parents}


def _append_sample(
    report: BackfillReport,
    sample: AuditSample,
    *,
    sample_limit: int,
) -> None:
    if len(report.samples) < sample_limit:
        report.samples.append(sample)


def _record_skip(
    report: BackfillReport,
    department: Department,
    parent: Department | None,
    reason: str,
    *,
    sample_limit: int,
) -> None:
    report.skipped += 1
    report.reason_counts[reason] += 1
    _append_sample(
        report,
        AuditSample(
            department_id=int(department.id),
            tenant_id=int(department.tenant_id),
            source=department.source,
            department_name=department.name,
            parent_id=int(department.parent_id) if department.parent_id is not None else None,
            parent_name=parent.name if parent is not None else None,
            candidate_short_name=None,
            outcome="skipped",
            reason=reason,
        ),
        sample_limit=sample_limit,
    )


def _record_drift(
    report: BackfillReport,
    candidate: BackfillCandidate,
    *,
    sample_limit: int,
) -> None:
    reason = "changed_before_update"
    report.skipped += 1
    report.reason_counts[reason] += 1
    _append_sample(
        report,
        AuditSample(
            department_id=candidate.department_id,
            tenant_id=candidate.tenant_id,
            source=candidate.source,
            department_name=candidate.department_name,
            parent_id=candidate.parent_id,
            parent_name=candidate.parent_name,
            candidate_short_name=candidate.short_name,
            outcome="skipped",
            reason=reason,
        ),
        sample_limit=sample_limit,
    )


async def _backfill_department_short_names(
    session: AsyncSession,
    *,
    apply: bool,
    batch_size: int,
    sample_limit: int,
) -> BackfillReport:
    report = BackfillReport()
    last_id = 0

    while True:
        departments = await _load_batch(
            session,
            last_id=last_id,
            batch_size=batch_size,
        )
        if not departments:
            break

        parents_by_id = await _load_parents(session, departments)
        report.scanned += len(departments)

        for department in departments:
            department_id = int(department.id)
            last_id = max(last_id, department_id)
            report.next_start_after_id = last_id
            parent = parents_by_id.get(int(department.parent_id)) if department.parent_id is not None else None
            candidate, reason = _resolve_department(department, parent)
            if candidate is None:
                _record_skip(
                    report,
                    department,
                    parent,
                    reason or "unresolved",
                    sample_limit=sample_limit,
                )
                continue

            report.eligible += 1
            if not apply:
                report.would_update += 1
                _append_sample(
                    report,
                    AuditSample(
                        department_id=candidate.department_id,
                        tenant_id=candidate.tenant_id,
                        source=candidate.source,
                        department_name=candidate.department_name,
                        parent_id=candidate.parent_id,
                        parent_name=candidate.parent_name,
                        candidate_short_name=candidate.short_name,
                        outcome="would_update",
                    ),
                    sample_limit=sample_limit,
                )
                continue

            try:
                outcome = await apply_candidate(session, candidate)
            except Exception:
                await session.rollback()
                raise
            if outcome.updated:
                report.updated += 1
                _append_sample(
                    report,
                    AuditSample(
                        department_id=candidate.department_id,
                        tenant_id=candidate.tenant_id,
                        source=candidate.source,
                        department_name=candidate.department_name,
                        parent_id=candidate.parent_id,
                        parent_name=candidate.parent_name,
                        candidate_short_name=candidate.short_name,
                        outcome="updated",
                    ),
                    sample_limit=sample_limit,
                )
            else:
                _record_drift(report, candidate, sample_limit=sample_limit)

        if apply:
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    if not apply:
        await session.rollback()
    return report


async def backfill_department_short_names(
    session: AsyncSession,
    *,
    apply: bool = False,
    batch_size: int = 200,
    sample_limit: int = 20,
) -> BackfillReport:
    """Scan every tenant and optionally apply guarded short-name updates."""
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    if not 0 <= sample_limit <= MAX_SAMPLE_LIMIT:
        raise ValueError(f"sample_limit must be between 0 and {MAX_SAMPLE_LIMIT}")

    with bypass_tenant_filter():
        return await _backfill_department_short_names(
            session,
            apply=apply,
            batch_size=batch_size,
            sample_limit=sample_limit,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write eligible short names; default is a read-only dry-run",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="rows scanned per keyset batch (1-1000; default: 200)",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=20,
        help="maximum audit samples in the JSON report (0-1000; default: 20)",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate command-line arguments."""
    parser = _parser()
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    if not 0 <= args.sample_limit <= MAX_SAMPLE_LIMIT:
        parser.error(f"--sample-limit must be between 0 and {MAX_SAMPLE_LIMIT}")
    return args


async def _run(args: argparse.Namespace) -> int:
    mode = "apply" if args.apply else "dry_run"
    try:
        async with get_async_db_session() as session:
            report = await backfill_department_short_names(
                session,
                apply=args.apply,
                batch_size=args.batch_size,
                sample_limit=args.sample_limit,
            )
        print(
            json.dumps(
                {"mode": mode, **report.as_dict()},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return EXIT_OK
    except ValueError as exc:
        print(
            json.dumps(
                {"mode": mode, "error": str(exc), "error_type": type(exc).__name__},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_ARGUMENT
    except Exception as exc:
        logger.exception("Department short-name backfill failed")
        print(
            json.dumps(
                {"mode": mode, "error_type": type(exc).__name__},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_EXECUTION
    finally:
        await close_app_context()


def main() -> int:
    """Run the command-line backfill."""
    return asyncio.run(_run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
