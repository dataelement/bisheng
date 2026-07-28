#!/usr/bin/env python3
"""Safely remove orphan ``knowledge_document`` rows that block F071.

An orphan document has no version linked to an existing ``knowledgefile``.
The default mode is read-only. Use ``--apply`` only after reviewing the JSON
report and backing up the database.

Run from ``src/backend``::

    PYTHONPATH=./ uv run python scripts/repair_orphan_knowledge_documents.py \
      --document-id 1
    PYTHONPATH=./ uv run python scripts/repair_orphan_knowledge_documents.py \
      --document-id 1 --apply

The script never deletes ``knowledgefile`` rows or external storage data. It
refuses to apply when a candidate is still referenced through F071's
``knowledgefile.reference_document_id`` column.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402

DOCUMENT_TABLE = "knowledge_document"
VERSION_TABLE = "knowledge_document_version"
FILE_TABLE = "knowledgefile"
SIMILARITY_TABLE = "knowledge_file_similarity_candidate"
DEFAULT_LIMIT = 100


class SchemaValidationError(RuntimeError):
    """Raised when the target database does not contain the required schema."""


class RepairBlockedError(RuntimeError):
    """Raised when applying the repair would be unsafe."""


@dataclass(frozen=True)
class OrphanDocument:
    document_id: int
    version_count: int
    dangling_version_count: int
    reference_count: int
    similarity_candidate_count: int
    reason: str
    safe_to_delete: bool


@dataclass(frozen=True)
class ScanReport:
    total_candidates: int
    returned_candidates: int
    truncated: bool
    candidates: tuple[OrphanDocument, ...]

    @property
    def blocked_count(self) -> int:
        return sum(not item.safe_to_delete for item in self.candidates)

    @property
    def safe_count(self) -> int:
        return sum(item.safe_to_delete for item in self.candidates)


@dataclass(frozen=True)
class RepairResult:
    scan: ScanReport
    deleted_documents: int
    deleted_versions: int
    deleted_similarity_candidates: int


@dataclass(frozen=True)
class _Schema:
    document: sa.Table
    version: sa.Table
    knowledge_file: sa.Table
    similarity_candidate: sa.Table | None
    reference_document_column: sa.Column[Any] | None


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _find_column(table: sa.Table, name: str) -> sa.Column[Any] | None:
    return next(
        (column for column in table.c if column.name.lower() == name.lower()),
        None,
    )


def _require_column(table: sa.Table, name: str) -> sa.Column[Any]:
    column = _find_column(table, name)
    if column is None:
        raise SchemaValidationError(f"missing required column {table.name}.{name}")
    return column


def _load_schema(connection: Connection) -> _Schema:
    inspector = sa.inspect(connection)
    table_names = {table_name.lower(): table_name for table_name in inspector.get_table_names()}
    missing = sorted(
        {
            DOCUMENT_TABLE,
            VERSION_TABLE,
            FILE_TABLE,
        }
        - set(table_names)
    )
    if missing:
        raise SchemaValidationError("missing required tables: " + ",".join(missing))

    metadata = sa.MetaData()
    document = sa.Table(
        table_names[DOCUMENT_TABLE],
        metadata,
        autoload_with=connection,
    )
    version = sa.Table(
        table_names[VERSION_TABLE],
        metadata,
        autoload_with=connection,
    )
    knowledge_file = sa.Table(
        table_names[FILE_TABLE],
        metadata,
        autoload_with=connection,
    )
    similarity_candidate = None
    if SIMILARITY_TABLE in table_names:
        similarity_candidate = sa.Table(
            table_names[SIMILARITY_TABLE],
            metadata,
            autoload_with=connection,
        )

    for table, columns in (
        (document, ("id",)),
        (version, ("id", "document_id", "knowledge_file_id")),
        (knowledge_file, ("id",)),
    ):
        for column_name in columns:
            _require_column(table, column_name)

    if similarity_candidate is not None:
        _require_column(similarity_candidate, "candidate_document_id")

    return _Schema(
        document=document,
        version=version,
        knowledge_file=knowledge_file,
        similarity_candidate=similarity_candidate,
        reference_document_column=_find_column(
            knowledge_file,
            "reference_document_id",
        ),
    )


def _candidate_predicate(
    schema: _Schema,
    document_ids: tuple[int, ...] | None,
) -> tuple[sa.ColumnElement[bool], ...]:
    document_id = _require_column(schema.document, "id")
    version_document_id = _require_column(schema.version, "document_id")
    version_file_id = _require_column(schema.version, "knowledge_file_id")
    file_id = _require_column(schema.knowledge_file, "id")

    live_version_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(
            schema.version.join(
                schema.knowledge_file,
                version_file_id == file_id,
            )
        )
        .where(version_document_id == document_id)
    )
    predicates: list[sa.ColumnElement[bool]] = [~live_version_exists]
    if document_ids:
        predicates.append(document_id.in_(document_ids))
    return tuple(predicates)


def _count(
    connection: Connection,
    table: sa.FromClause,
    predicate: sa.ColumnElement[bool],
) -> int:
    return int(connection.scalar(sa.select(sa.func.count()).select_from(table).where(predicate)) or 0)


def scan_orphan_documents(
    connection: Connection,
    *,
    document_ids: tuple[int, ...] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> ScanReport:
    """Return documents that have no version linked to an existing file."""

    if limit <= 0:
        raise ValueError("limit must be positive")

    schema = _load_schema(connection)
    document_id = _require_column(schema.document, "id")
    predicates = _candidate_predicate(schema, document_ids)
    total_candidates = int(
        connection.scalar(sa.select(sa.func.count()).select_from(schema.document).where(*predicates)) or 0
    )
    candidate_ids = [
        int(value)
        for value in connection.scalars(
            sa.select(document_id).where(*predicates).order_by(document_id.asc()).limit(limit)
        )
    ]

    version_document_id = _require_column(schema.version, "document_id")
    reference_column = schema.reference_document_column
    candidates: list[OrphanDocument] = []
    for current_document_id in candidate_ids:
        version_count = _count(
            connection,
            schema.version,
            version_document_id == current_document_id,
        )
        reference_count = 0
        if reference_column is not None:
            reference_count = _count(
                connection,
                schema.knowledge_file,
                reference_column == current_document_id,
            )

        similarity_count = 0
        if schema.similarity_candidate is not None:
            similarity_document_id = _require_column(
                schema.similarity_candidate,
                "candidate_document_id",
            )
            similarity_count = _count(
                connection,
                schema.similarity_candidate,
                similarity_document_id == current_document_id,
            )

        if reference_count:
            reason = "referenced_by_knowledgefile"
            safe_to_delete = False
        elif version_count:
            reason = "all_versions_reference_missing_files"
            safe_to_delete = True
        else:
            reason = "no_versions"
            safe_to_delete = True

        candidates.append(
            OrphanDocument(
                document_id=current_document_id,
                version_count=version_count,
                dangling_version_count=version_count,
                reference_count=reference_count,
                similarity_candidate_count=similarity_count,
                reason=reason,
                safe_to_delete=safe_to_delete,
            )
        )

    return ScanReport(
        total_candidates=total_candidates,
        returned_candidates=len(candidates),
        truncated=total_candidates > len(candidates),
        candidates=tuple(candidates),
    )


def repair_orphan_documents(
    connection: Connection,
    *,
    document_ids: tuple[int, ...] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> RepairResult:
    """Delete a fully revalidated set of safe orphan documents atomically."""

    initial_scan = scan_orphan_documents(
        connection,
        document_ids=document_ids,
        limit=limit,
    )
    if initial_scan.truncated:
        raise RepairBlockedError(f"{initial_scan.total_candidates} candidates exceed --limit={limit}")
    blocked = [item.document_id for item in initial_scan.candidates if not item.safe_to_delete]
    if blocked:
        raise RepairBlockedError(
            "documents still referenced by knowledgefile: " + ",".join(str(item) for item in blocked)
        )

    safe_ids = tuple(item.document_id for item in initial_scan.candidates if item.safe_to_delete)
    if not safe_ids:
        return RepairResult(
            scan=initial_scan,
            deleted_documents=0,
            deleted_versions=0,
            deleted_similarity_candidates=0,
        )

    schema = _load_schema(connection)
    document_id = _require_column(schema.document, "id")
    connection.execute(
        sa.select(document_id).where(document_id.in_(safe_ids)).order_by(document_id.asc()).with_for_update()
    ).all()

    revalidated = scan_orphan_documents(
        connection,
        document_ids=safe_ids,
        limit=len(safe_ids),
    )
    revalidated_safe_ids = tuple(item.document_id for item in revalidated.candidates if item.safe_to_delete)
    if revalidated.truncated or revalidated.blocked_count or revalidated_safe_ids != safe_ids:
        raise RepairBlockedError("candidate state changed during apply; retry after inspection")

    deleted_similarity_candidates = 0
    if schema.similarity_candidate is not None:
        similarity_document_id = _require_column(
            schema.similarity_candidate,
            "candidate_document_id",
        )
        connection.execute(sa.delete(schema.similarity_candidate).where(similarity_document_id.in_(safe_ids)))
        deleted_similarity_candidates = sum(item.similarity_candidate_count for item in revalidated.candidates)

    version_document_id = _require_column(schema.version, "document_id")
    connection.execute(sa.delete(schema.version).where(version_document_id.in_(safe_ids)))
    connection.execute(sa.delete(schema.document).where(document_id.in_(safe_ids)))

    remaining_documents = _count(
        connection,
        schema.document,
        document_id.in_(safe_ids),
    )
    remaining_versions = _count(
        connection,
        schema.version,
        version_document_id.in_(safe_ids),
    )
    remaining_similarity_candidates = 0
    if schema.similarity_candidate is not None:
        similarity_document_id = _require_column(
            schema.similarity_candidate,
            "candidate_document_id",
        )
        remaining_similarity_candidates = _count(
            connection,
            schema.similarity_candidate,
            similarity_document_id.in_(safe_ids),
        )
    if remaining_documents or remaining_versions or remaining_similarity_candidates:
        raise RepairBlockedError("orphan rows remain after apply; transaction must roll back")

    return RepairResult(
        scan=initial_scan,
        deleted_documents=len(safe_ids),
        deleted_versions=sum(item.dangling_version_count for item in revalidated.candidates),
        deleted_similarity_candidates=deleted_similarity_candidates,
    )


def _scan_payload(report: ScanReport) -> dict[str, Any]:
    return {
        "total_candidates": report.total_candidates,
        "returned_candidates": report.returned_candidates,
        "safe_count": report.safe_count,
        "blocked_count": report.blocked_count,
        "truncated": report.truncated,
        "candidates": [asdict(item) for item in report.candidates],
    }


def _run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    document_ids = tuple(sorted(set(args.document_ids))) if args.document_ids else None
    with bypass_tenant_filter():
        with get_sync_db_session() as session:
            connection = session.connection()
            if not args.apply:
                report = scan_orphan_documents(
                    connection,
                    document_ids=document_ids,
                    limit=args.limit,
                )
                blocked = bool(report.blocked_count or report.truncated)
                status = "blocked" if blocked else "ready"
                return {
                    "mode": "dry-run",
                    "status": status,
                    **_scan_payload(report),
                }, 2 if blocked else 0

            try:
                result = repair_orphan_documents(
                    connection,
                    document_ids=document_ids,
                    limit=args.limit,
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
            return {
                "mode": "apply",
                "status": "applied",
                **_scan_payload(result.scan),
                "deleted_documents": result.deleted_documents,
                "deleted_versions": result.deleted_versions,
                "deleted_similarity_candidates": (result.deleted_similarity_candidates),
            }, 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--document-id",
        dest="document_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="Only inspect this document ID; repeat to select multiple IDs.",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=DEFAULT_LIMIT,
        help=f"Maximum candidates to inspect (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete safe orphan rows; default is read-only.",
    )
    args = parser.parse_args()

    try:
        payload, exit_code = _run(args)
    except (RepairBlockedError, SchemaValidationError) as exc:
        payload = {
            "mode": "apply" if args.apply else "dry-run",
            "status": "blocked",
            "error": str(exc),
        }
        exit_code = 2
    except Exception as exc:
        payload = {
            "mode": "apply" if args.apply else "dry-run",
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        exit_code = 3

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
