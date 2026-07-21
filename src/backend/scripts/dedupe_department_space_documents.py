#!/usr/bin/env python3
r"""Remove department-space documents duplicated in public spaces.

The script compares the current successful FILE records in public and
department knowledge spaces by exact, non-empty MD5. A matching department
document becomes one deletion unit containing its complete version chain. The
default mode is a read-only dry-run that writes a JSON report. Pass ``--apply``
only after reviewing that report and arranging a maintenance window.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py
    PYTHONPATH=./ .venv/bin/python scripts/dedupe_department_space_documents.py \
      --department-space-id 10 --limit 20 --apply

This maintenance command intentionally rejects deployments with multi-tenancy
enabled. It never treats a report as authority for a new database or external
resource deletion.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from sqlmodel import col, delete, func, or_, select, update

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import (  # noqa: E402
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    strict_tenant_filter,
    visible_tenant_ids,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync  # noqa: E402
from bisheng.database.models.group_resource import (  # noqa: E402
    ResourceTypeEnum as TagLinkResourceTypeEnum,
)
from bisheng.database.models.review_tags import ReviewTagLink  # noqa: E402
from bisheng.database.models.tag import TagLink  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file_similarity_candidate import (  # noqa: E402
    KnowledgeFileSimilarityCandidate,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (  # noqa: E402
    PortalRecommendationFileProjection,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils  # noqa: E402
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation  # noqa: E402
from bisheng.permission.domain.services.permission_service import PermissionService  # noqa: E402
from bisheng.share_link.domain.models.share_link import (  # noqa: E402
    ResourceTypeEnum as ShareResourceTypeEnum,
)
from bisheng.share_link.domain.models.share_link import (  # noqa: E402
    ShareLink,
)

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_SCAN_ERROR = 3
EXIT_APPLY_ERROR = 4
EXIT_REPORT_ERROR = 5
REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_REPORT_DIR = Path("migration_reports/knowledge_file_dedup")
DEFAULT_TENANT_ID = 1
FILE_TYPE_FILE = 1
FILE_STATUS_SUCCESS = 2


def _enum_value(value: Any) -> str:
    """Return the persisted value for string-like enums and raw strings."""

    return str(getattr(value, "value", value))


class PreflightError(RuntimeError):
    """Raised when safety validation must stop before any business write."""


class ReportWriteError(RuntimeError):
    """Raised when the audit checkpoint cannot be persisted safely."""


class ResidualDataError(RuntimeError):
    """Raised when post-delete verification finds target data."""


@dataclass(frozen=True)
class SpaceSnapshot:
    space_id: int
    level: str


@dataclass(frozen=True)
class StorageObjectSnapshot:
    kind: str
    name: str


@dataclass(frozen=True)
class FileSnapshot:
    file_id: int
    space_id: int
    file_type: int
    status: int
    md5: str | None
    storage_objects: tuple[StorageObjectSnapshot, ...] = ()


@dataclass(frozen=True)
class DocumentSnapshot:
    document_id: int
    space_id: int
    primary_version_id: int | None


@dataclass(frozen=True)
class VersionSnapshot:
    version_id: int
    document_id: int
    file_id: int
    version_no: int
    is_primary: bool


@dataclass(frozen=True)
class Inventory:
    spaces: tuple[SpaceSnapshot, ...]
    files: tuple[FileSnapshot, ...]
    documents: tuple[DocumentSnapshot, ...]
    versions: tuple[VersionSnapshot, ...]


@dataclass(frozen=True)
class PublicWitness:
    space_id: int
    file_id: int
    document_id: int | None
    version_id: int | None
    md5: str


@dataclass(frozen=True)
class SkippedItem:
    space_id: int
    file_id: int
    reason_code: str
    reason: str


@dataclass(frozen=True)
class DeletionUnit:
    unit_key: str
    department_space_id: int
    primary_file_id: int
    document_id: int | None
    primary_version_id: int | None
    md5: str
    public_witnesses: tuple[PublicWitness, ...]
    physical_files: tuple[FileSnapshot, ...]
    versions: tuple[VersionSnapshot, ...]
    plan_fingerprint: str = ""
    impact_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DeduplicationPlan:
    tenant_id: int
    public_space_ids: tuple[int, ...]
    department_space_ids: tuple[int, ...]
    units: tuple[DeletionUnit, ...]
    skipped: tuple[SkippedItem, ...]
    blank_md5_count: int
    public_candidate_count: int
    department_candidate_count: int


@dataclass(frozen=True)
class RevalidationResult:
    valid: bool
    unit: DeletionUnit | None = None
    reason_code: str = ""


@dataclass(frozen=True)
class _CurrentCandidate:
    file: FileSnapshot
    document: DocumentSnapshot | None
    primary_version: VersionSnapshot | None
    physical_files: tuple[FileSnapshot, ...]
    versions: tuple[VersionSnapshot, ...]


class PlanReader(Protocol):
    async def build_plan(self, args: argparse.Namespace) -> DeduplicationPlan: ...

    async def revalidate(self, unit: DeletionUnit) -> RevalidationResult: ...


class DeleteOperations(Protocol):
    async def delete_milvus(self, file: FileSnapshot) -> None: ...

    async def delete_elasticsearch(self, file: FileSnapshot) -> None: ...

    async def delete_minio(self, file: FileSnapshot) -> None: ...

    async def clear_permissions(self, file_id: int) -> None: ...

    async def verify_external_absent(self, unit: DeletionUnit) -> dict[str, Any]: ...

    async def delete_database_records(self, unit: DeletionUnit) -> None: ...

    async def invalidate_derived_state(self, unit: DeletionUnit) -> None: ...

    async def verify_deleted(self, unit: DeletionUnit) -> dict[str, Any]: ...

    async def target_records_exist(self, unit: DeletionUnit) -> bool: ...


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete department-space documents whose current MD5 exists in a public space.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform irreversible deletion; default is read-only dry-run",
    )
    parser.add_argument(
        "--department-space-id",
        dest="department_space_ids",
        action="append",
        type=_positive_int,
        default=[],
        metavar="ID",
        help="limit department targets to this space; repeatable",
    )
    parser.add_argument(
        "--file-id",
        dest="file_ids",
        action="append",
        type=_positive_int,
        default=[],
        metavar="ID",
        help="limit targets to this department current file; repeatable",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        metavar="N",
        help="process at most N stable-sorted deletion units",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help=f"JSON report directory (default: {DEFAULT_REPORT_DIR})",
    )
    parser.add_argument(
        "--resume-report",
        type=Path,
        default=None,
        metavar="PATH",
        help="resume failed/pending steps from a prior apply report",
    )
    args = parser.parse_args(argv)
    if args.resume_report is not None and not args.apply:
        parser.error("--resume-report requires --apply")
    if args.resume_report is not None and (args.department_space_ids or args.file_ids or args.limit is not None):
        parser.error("--resume-report cannot be combined with target range options")
    return args


def ensure_single_tenant(multi_tenant_enabled: bool) -> int:
    if multi_tenant_enabled:
        raise PreflightError("multi-tenant mode is enabled; this script only supports single-tenant deployments")
    return DEFAULT_TENANT_ID


def _graph_reason(
    document_id: int,
    *,
    documents_by_id: dict[int, DocumentSnapshot],
    versions_by_document: dict[int, list[VersionSnapshot]],
    versions_by_file: dict[int, list[VersionSnapshot]],
    files_by_id: dict[int, FileSnapshot],
) -> tuple[str, str]:
    document = documents_by_id.get(document_id)
    if document is None:
        return "document_missing", "version row references a missing logical document"
    versions = versions_by_document.get(document_id, [])
    if not versions:
        return "version_chain_empty", "logical document has no version rows"
    version_ids = [item.version_id for item in versions]
    if len(version_ids) != len(set(version_ids)):
        return "duplicate_version_id", "logical document has duplicate version IDs"
    version_numbers = [item.version_no for item in versions]
    if len(version_numbers) != len(set(version_numbers)):
        return "duplicate_version_number", "logical document has duplicate version numbers"
    for version in versions:
        if len(versions_by_file.get(version.file_id, [])) != 1:
            return "file_version_link_invalid", "physical file must belong to exactly one version row"
        file = files_by_id.get(version.file_id)
        if file is None:
            return "version_file_missing", "version row references a missing physical file"
        if file.space_id != document.space_id:
            return "cross_space_version_chain", "version chain contains files from another space"
        if file.file_type != FILE_TYPE_FILE:
            return "version_chain_contains_non_file", "version chain contains a folder record"
    primary_versions = [item for item in versions if item.is_primary]
    if len(primary_versions) != 1:
        return "primary_version_count_invalid", "logical document must have exactly one primary version"
    if document.primary_version_id != primary_versions[0].version_id:
        return "primary_pointer_mismatch", "logical document primary pointer does not match the primary version"
    return "", ""


def _current_candidates(
    inventory: Inventory,
    candidate_space_ids: set[int],
) -> tuple[list[_CurrentCandidate], list[SkippedItem], int]:
    files_by_id = {item.file_id: item for item in inventory.files}
    documents_by_id = {item.document_id: item for item in inventory.documents}
    versions_by_document: dict[int, list[VersionSnapshot]] = defaultdict(list)
    versions_by_file: dict[int, list[VersionSnapshot]] = defaultdict(list)
    for version in inventory.versions:
        versions_by_document[version.document_id].append(version)
        versions_by_file[version.file_id].append(version)
    for values in versions_by_document.values():
        values.sort(key=lambda item: (item.version_no, item.version_id))

    graph_cache: dict[int, tuple[str, str]] = {}
    candidates: list[_CurrentCandidate] = []
    skipped: list[SkippedItem] = []
    blank_md5_count = 0
    reported_graphs: set[tuple[int, str]] = set()

    for file in sorted(inventory.files, key=lambda item: (item.space_id, item.file_id)):
        if file.space_id not in candidate_space_ids:
            continue
        file_versions = versions_by_file.get(file.file_id, [])
        document: DocumentSnapshot | None = None
        primary_version: VersionSnapshot | None = None
        chain_files: tuple[FileSnapshot, ...] = (file,)
        chain_versions: tuple[VersionSnapshot, ...] = ()

        if len(file_versions) > 1:
            if file.file_type == FILE_TYPE_FILE and file.status == FILE_STATUS_SUCCESS:
                skipped.append(
                    SkippedItem(
                        space_id=file.space_id,
                        file_id=file.file_id,
                        reason_code="file_version_link_invalid",
                        reason="physical file belongs to multiple version rows",
                    )
                )
            continue
        if file_versions:
            version = file_versions[0]
            reason_code, reason = graph_cache.setdefault(
                version.document_id,
                _graph_reason(
                    version.document_id,
                    documents_by_id=documents_by_id,
                    versions_by_document=versions_by_document,
                    versions_by_file=versions_by_file,
                    files_by_id=files_by_id,
                ),
            )
            if reason_code:
                graph_key = (version.document_id, reason_code)
                if (
                    graph_key not in reported_graphs
                    and file.file_type == FILE_TYPE_FILE
                    and file.status == FILE_STATUS_SUCCESS
                ):
                    skipped.append(
                        SkippedItem(
                            space_id=file.space_id,
                            file_id=file.file_id,
                            reason_code=reason_code,
                            reason=reason,
                        )
                    )
                    reported_graphs.add(graph_key)
                continue
            document = documents_by_id[version.document_id]
            chain_versions = tuple(versions_by_document[version.document_id])
            primary_version = next(item for item in chain_versions if item.is_primary)
            if file.file_id != primary_version.file_id:
                continue
            chain_files = tuple(
                sorted(
                    (files_by_id[item.file_id] for item in chain_versions),
                    key=lambda item: item.file_id,
                )
            )

        if file.file_type != FILE_TYPE_FILE or file.status != FILE_STATUS_SUCCESS:
            continue
        md5 = "" if file.md5 is None else str(file.md5)
        if not md5.strip():
            blank_md5_count += 1
            skipped.append(
                SkippedItem(
                    space_id=file.space_id,
                    file_id=file.file_id,
                    reason_code="blank_md5",
                    reason="current successful file has an empty MD5",
                )
            )
            continue
        candidates.append(
            _CurrentCandidate(
                file=file,
                document=document,
                primary_version=primary_version,
                physical_files=chain_files,
                versions=chain_versions,
            )
        )
    return candidates, skipped, blank_md5_count


def fingerprint_unit(unit: DeletionUnit) -> str:
    payload = {
        "department_space_id": unit.department_space_id,
        "primary_file_id": unit.primary_file_id,
        "document_id": unit.document_id,
        "primary_version_id": unit.primary_version_id,
        "md5": unit.md5,
        "public_witnesses": [
            [item.space_id, item.file_id, item.document_id, item.version_id, item.md5]
            for item in sorted(unit.public_witnesses, key=lambda value: (value.space_id, value.file_id))
        ],
        "physical_files": [
            [item.file_id, item.space_id] for item in sorted(unit.physical_files, key=lambda value: value.file_id)
        ],
        "versions": [
            [item.version_id, item.document_id, item.file_id, item.version_no, item.is_primary]
            for item in sorted(unit.versions, key=lambda value: (value.version_no, value.version_id))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_deduplication_plan(
    inventory: Inventory,
    *,
    department_space_ids: Sequence[int] = (),
    file_ids: Sequence[int] = (),
    limit: int | None = None,
    tenant_id: int = DEFAULT_TENANT_ID,
) -> DeduplicationPlan:
    public_space_ids = {item.space_id for item in inventory.spaces if _enum_value(item.level) == "public"}
    all_department_space_ids = {item.space_id for item in inventory.spaces if _enum_value(item.level) == "department"}
    requested_department_ids = {int(value) for value in department_space_ids}
    if requested_department_ids:
        invalid_spaces = sorted(requested_department_ids - all_department_space_ids)
        if invalid_spaces:
            raise PreflightError(f"department knowledge spaces not found or not department: {invalid_spaces}")
        selected_department_ids = requested_department_ids
    else:
        selected_department_ids = set(all_department_space_ids)

    candidate_space_ids = public_space_ids | all_department_space_ids
    current, skipped, blank_md5_count = _current_candidates(inventory, candidate_space_ids)
    public_candidates = [item for item in current if item.file.space_id in public_space_ids]
    all_department_candidates = [item for item in current if item.file.space_id in all_department_space_ids]
    requested_file_ids = {int(value) for value in file_ids}
    department_current_ids = {item.file.file_id for item in all_department_candidates}
    if requested_file_ids:
        invalid_files = sorted(requested_file_ids - department_current_ids)
        if invalid_files:
            raise PreflightError(f"file IDs are not department current files: {invalid_files}")

    department_candidates = [
        item
        for item in all_department_candidates
        if item.file.space_id in selected_department_ids
        and (not requested_file_ids or item.file.file_id in requested_file_ids)
    ]
    witnesses_by_md5: dict[str, list[PublicWitness]] = defaultdict(list)
    for candidate in public_candidates:
        md5 = str(candidate.file.md5)
        witnesses_by_md5[md5].append(
            PublicWitness(
                space_id=candidate.file.space_id,
                file_id=candidate.file.file_id,
                document_id=(candidate.document.document_id if candidate.document else None),
                version_id=(candidate.primary_version.version_id if candidate.primary_version else None),
                md5=md5,
            )
        )
    for witnesses in witnesses_by_md5.values():
        witnesses.sort(key=lambda item: (item.space_id, item.file_id))

    units_by_key: dict[str, DeletionUnit] = {}
    for candidate in department_candidates:
        md5 = str(candidate.file.md5)
        witnesses = tuple(witnesses_by_md5.get(md5, []))
        if not witnesses:
            continue
        if candidate.document is None:
            unit_key = f"legacy-file:{candidate.file.file_id}"
            document_id = None
            primary_version_id = None
        else:
            unit_key = f"document:{candidate.document.document_id}"
            document_id = candidate.document.document_id
            primary_version_id = candidate.primary_version.version_id if candidate.primary_version else None
        unit = DeletionUnit(
            unit_key=unit_key,
            department_space_id=candidate.file.space_id,
            primary_file_id=candidate.file.file_id,
            document_id=document_id,
            primary_version_id=primary_version_id,
            md5=md5,
            public_witnesses=witnesses,
            physical_files=tuple(sorted(candidate.physical_files, key=lambda item: item.file_id)),
            versions=tuple(sorted(candidate.versions, key=lambda item: (item.version_no, item.version_id))),
        )
        unit = replace(unit, plan_fingerprint=fingerprint_unit(unit))
        previous = units_by_key.get(unit_key)
        if previous is not None and previous.plan_fingerprint != unit.plan_fingerprint:
            skipped.append(
                SkippedItem(
                    space_id=candidate.file.space_id,
                    file_id=candidate.file.file_id,
                    reason_code="duplicate_unit_conflict",
                    reason="multiple current candidates produced conflicting document units",
                )
            )
            units_by_key.pop(unit_key, None)
            continue
        units_by_key[unit_key] = unit

    units = sorted(
        units_by_key.values(),
        key=lambda item: (
            item.department_space_id,
            item.document_id or 0,
            item.primary_file_id,
        ),
    )
    if limit is not None:
        units = units[:limit]
    skipped.sort(key=lambda item: (item.space_id, item.file_id, item.reason_code))
    return DeduplicationPlan(
        tenant_id=int(tenant_id),
        public_space_ids=tuple(sorted(public_space_ids)),
        department_space_ids=tuple(sorted(selected_department_ids)),
        units=tuple(units),
        skipped=tuple(skipped),
        blank_md5_count=blank_md5_count,
        public_candidate_count=len(public_candidates),
        department_candidate_count=len(department_candidates),
    )


def _storage_object_to_dict(item: StorageObjectSnapshot) -> dict[str, Any]:
    return {"kind": item.kind, "name": item.name}


def _file_to_dict(item: FileSnapshot) -> dict[str, Any]:
    return {
        "file_id": item.file_id,
        "space_id": item.space_id,
        "file_type": item.file_type,
        "status": item.status,
        "md5": item.md5,
        "storage_objects": [_storage_object_to_dict(value) for value in item.storage_objects],
    }


def deletion_unit_to_dict(unit: DeletionUnit) -> dict[str, Any]:
    return {
        "unit_key": unit.unit_key,
        "department_space_id": unit.department_space_id,
        "primary_file_id": unit.primary_file_id,
        "document_id": unit.document_id,
        "primary_version_id": unit.primary_version_id,
        "md5": unit.md5,
        "public_witnesses": [asdict(item) for item in unit.public_witnesses],
        "physical_files": [_file_to_dict(item) for item in unit.physical_files],
        "versions": [asdict(item) for item in unit.versions],
        "plan_fingerprint": unit.plan_fingerprint,
        "impact_counts": dict(sorted(unit.impact_counts.items())),
    }


def _required_positive_int(payload: dict[str, Any], key: str) -> int:
    try:
        value = int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PreflightError(f"resume report has invalid {key}") from exc
    if value <= 0:
        raise PreflightError(f"resume report has invalid {key}")
    return value


def deletion_unit_from_dict(payload: dict[str, Any]) -> DeletionUnit:
    if not isinstance(payload, dict):
        raise PreflightError("resume report unit must be an object")
    department_space_id = _required_positive_int(payload, "department_space_id")
    primary_file_id = _required_positive_int(payload, "primary_file_id")
    md5 = str(payload.get("md5") or "")
    if not md5.strip():
        raise PreflightError("resume report unit has an empty MD5")

    witnesses: list[PublicWitness] = []
    for raw in payload.get("public_witnesses") or []:
        if not isinstance(raw, dict):
            raise PreflightError("resume report public witness must be an object")
        witness = PublicWitness(
            space_id=_required_positive_int(raw, "space_id"),
            file_id=_required_positive_int(raw, "file_id"),
            document_id=int(raw["document_id"]) if raw.get("document_id") is not None else None,
            version_id=int(raw["version_id"]) if raw.get("version_id") is not None else None,
            md5=str(raw.get("md5") or ""),
        )
        if witness.md5 != md5:
            raise PreflightError("resume report public witness MD5 does not match the target")
        witnesses.append(witness)
    if not witnesses:
        raise PreflightError("resume report unit has no public witness")

    files: list[FileSnapshot] = []
    for raw in payload.get("physical_files") or []:
        if not isinstance(raw, dict):
            raise PreflightError("resume report physical file must be an object")
        objects = tuple(
            StorageObjectSnapshot(kind=str(item.get("kind") or ""), name=str(item.get("name") or ""))
            for item in (raw.get("storage_objects") or [])
            if isinstance(item, dict) and str(item.get("name") or "")
        )
        file = FileSnapshot(
            file_id=_required_positive_int(raw, "file_id"),
            space_id=_required_positive_int(raw, "space_id"),
            file_type=int(raw.get("file_type") or 0),
            status=int(raw.get("status") or 0),
            md5=raw.get("md5"),
            storage_objects=objects,
        )
        if file.space_id != department_space_id:
            raise PreflightError("resume report contains a cross-space target file")
        files.append(file)
    if not files or primary_file_id not in {item.file_id for item in files}:
        raise PreflightError("resume report target files do not contain the primary file")

    target_ids = {item.file_id for item in files}
    witness_ids = {item.file_id for item in witnesses}
    if target_ids & witness_ids:
        raise PreflightError("resume report target overlaps a public witness")

    versions = tuple(
        VersionSnapshot(
            version_id=_required_positive_int(raw, "version_id"),
            document_id=_required_positive_int(raw, "document_id"),
            file_id=_required_positive_int(raw, "file_id"),
            version_no=_required_positive_int(raw, "version_no"),
            is_primary=bool(raw.get("is_primary")),
        )
        for raw in (payload.get("versions") or [])
        if isinstance(raw, dict)
    )
    document_id = int(payload["document_id"]) if payload.get("document_id") is not None else None
    primary_version_id = int(payload["primary_version_id"]) if payload.get("primary_version_id") is not None else None
    unit = DeletionUnit(
        unit_key=str(payload.get("unit_key") or ""),
        department_space_id=department_space_id,
        primary_file_id=primary_file_id,
        document_id=document_id,
        primary_version_id=primary_version_id,
        md5=md5,
        public_witnesses=tuple(sorted(witnesses, key=lambda item: (item.space_id, item.file_id))),
        physical_files=tuple(sorted(files, key=lambda item: item.file_id)),
        versions=tuple(sorted(versions, key=lambda item: (item.version_no, item.version_id))),
        plan_fingerprint=str(payload.get("plan_fingerprint") or ""),
        impact_counts={str(key): int(value) for key, value in (payload.get("impact_counts") or {}).items()},
    )
    expected_key = f"document:{document_id}" if document_id is not None else f"legacy-file:{primary_file_id}"
    if unit.unit_key != expected_key:
        raise PreflightError("resume report unit key does not match its target")
    if unit.plan_fingerprint != fingerprint_unit(unit):
        raise PreflightError("resume report unit fingerprint mismatch")
    return unit


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refresh_summary(report: dict[str, Any]) -> None:
    counts = dict.fromkeys(("planned", "completed", "skipped", "failed", "pending"), 0)
    for item in report.get("units", []):
        status = str(item.get("status") or "planned")
        if status in counts:
            counts[status] += 1
    report["summary"] = {
        **counts,
        "integrity_skipped": sum(
            1
            for item in report.get("skipped", [])
            if str(item.get("reason_code") or "").endswith("invalid") or "version" in str(item.get("reason_code") or "")
        ),
        "blank_md5": int(report.get("preflight", {}).get("blank_md5_count", 0)),
    }


def make_run_report(
    plan: DeduplicationPlan,
    *,
    mode: Literal["dry-run", "apply"],
    run_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "arguments": arguments,
        "preflight": {
            "tenant_id": plan.tenant_id,
            "multi_tenant_enabled": False,
            "public_space_ids": list(plan.public_space_ids),
            "department_space_ids": list(plan.department_space_ids),
            "public_candidate_count": plan.public_candidate_count,
            "department_candidate_count": plan.department_candidate_count,
            "blank_md5_count": plan.blank_md5_count,
        },
        "public_witness_summary": {
            "file_count": len({witness.file_id for unit in plan.units for witness in unit.public_witnesses}),
            "md5_count": len({unit.md5 for unit in plan.units}),
        },
        "units": [
            {
                "unit": deletion_unit_to_dict(unit),
                "status": "planned",
                "reason_code": "",
                "error_type": "",
                "retriable": True,
                "steps": [],
                "verification": {},
            }
            for unit in plan.units
        ],
        "skipped": [asdict(item) for item in plan.skipped],
        "errors": [],
        "verification": {},
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "finished_at": None,
    }
    _refresh_summary(report)
    return report


def make_resume_report(source: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    report = json.loads(json.dumps(source))
    report["run_id"] = run_id
    report["resumed_from_run_id"] = str(source.get("run_id") or "")
    report["started_at"] = _utc_now()
    report["updated_at"] = _utc_now()
    report["finished_at"] = None
    report["errors"] = []
    for entry in report.get("units", []):
        entry["source_status"] = entry.get("status")
        entry["source_steps"] = entry.get("steps", [])
        if entry.get("status") not in {"completed", "skipped"}:
            entry["status"] = "pending"
            entry["reason_code"] = ""
            entry["error_type"] = ""
            entry["steps"] = []
            entry["verification"] = {}
    _refresh_summary(report)
    return report


class ReportStore:
    def __init__(self, report_dir: Path, run_id: str) -> None:
        self.report_dir = Path(report_dir)
        self.path = self.report_dir / f"dedupe-{run_id}.json"

    def write(self, payload: dict[str, Any]) -> Path:
        payload["updated_at"] = _utc_now()
        _refresh_summary(payload)
        temporary = self.report_dir / f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                # Cleanup is best-effort; preserve diagnostics without masking the write failure.
                logger.warning(
                    "temporary report cleanup failed path=%s error_type=%s",
                    temporary,
                    type(cleanup_exc).__name__,
                )
            raise ReportWriteError("unable to persist the audit report") from exc
        return self.path


def load_resume_report(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            raise PreflightError("resume report is larger than 50 MiB")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError("resume report does not exist") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError("resume report cannot be read as JSON") from exc
    if not isinstance(payload, dict):
        raise PreflightError("resume report root must be an object")
    if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise PreflightError("resume report schema is not supported")
    if payload.get("mode") != "apply":
        raise PreflightError("only an apply report can be resumed")
    units = payload.get("units")
    if not isinstance(units, list):
        raise PreflightError("resume report units must be a list")
    allowed_statuses = {"planned", "pending", "failed", "skipped", "completed"}
    for entry in units:
        if not isinstance(entry, dict) or entry.get("status") not in allowed_statuses:
            raise PreflightError("resume report has an invalid unit status")
        deletion_unit_from_dict(entry.get("unit"))
    return payload


def _step_record(entry: dict[str, Any], name: str) -> dict[str, Any]:
    step = {"name": name, "status": "running", "started_at": _utc_now()}
    entry.setdefault("steps", []).append(step)
    return step


class ApplyExecutor:
    def __init__(
        self,
        reader: PlanReader,
        operations: DeleteOperations,
        checkpoint: Callable[[], None],
    ) -> None:
        self.reader = reader
        self.operations = operations
        self.checkpoint = checkpoint
        self.run_id = ""

    async def _run_step(
        self,
        entry: dict[str, Any],
        name: str,
        operation: Callable[[], Any],
    ) -> Any:
        step = _step_record(entry, name)
        self.checkpoint()
        try:
            result = operation()
            if asyncio.iscoroutine(result):
                result = await result
        except ReportWriteError:
            raise
        except Exception as exc:
            step["status"] = "failed"
            step["error_type"] = type(exc).__name__
            step["finished_at"] = _utc_now()
            self.checkpoint()
            raise
        step["status"] = "completed"
        step["finished_at"] = _utc_now()
        self.checkpoint()
        return result

    async def process_entry(self, entry: dict[str, Any]) -> bool:
        planned = deletion_unit_from_dict(entry["unit"])
        logger.info(
            "dedupe unit started run_id=%s unit_key=%s space_id=%s file_id=%s",
            self.run_id,
            planned.unit_key,
            planned.department_space_id,
            planned.primary_file_id,
        )
        try:
            revalidated = await self.reader.revalidate(planned)
        except Exception as exc:
            entry["status"] = "failed"
            entry["error_type"] = type(exc).__name__
            entry["retriable"] = True
            self.checkpoint()
            logger.exception(
                "dedupe unit revalidation failed run_id=%s unit_key=%s space_id=%s file_id=%s error_type=%s",
                self.run_id,
                planned.unit_key,
                planned.department_space_id,
                planned.primary_file_id,
                type(exc).__name__,
            )
            return False
        if not revalidated.valid or revalidated.unit is None:
            entry["status"] = "skipped"
            entry["reason_code"] = revalidated.reason_code or "plan_drift"
            entry["retriable"] = False
            self.checkpoint()
            logger.info(
                "dedupe unit skipped run_id=%s unit_key=%s space_id=%s file_id=%s reason_code=%s",
                self.run_id,
                planned.unit_key,
                planned.department_space_id,
                planned.primary_file_id,
                entry["reason_code"],
            )
            return True

        unit = revalidated.unit
        target_ids = {item.file_id for item in unit.physical_files}
        witness_ids = {item.file_id for item in unit.public_witnesses}
        if target_ids & witness_ids:
            raise PreflightError("validated deletion unit overlaps a public witness")
        entry["unit"] = deletion_unit_to_dict(unit)
        entry["status"] = "pending"
        self.checkpoint()
        try:
            for file in sorted(unit.physical_files, key=lambda item: item.file_id):
                await self._run_step(
                    entry,
                    f"milvus_delete:{file.file_id}",
                    lambda file=file: self.operations.delete_milvus(file),
                )
                await self._run_step(
                    entry,
                    f"elasticsearch_delete:{file.file_id}",
                    lambda file=file: self.operations.delete_elasticsearch(file),
                )
                await self._run_step(
                    entry,
                    f"minio_delete:{file.file_id}",
                    lambda file=file: self.operations.delete_minio(file),
                )
                await self._run_step(
                    entry,
                    f"openfga_delete:{file.file_id}",
                    lambda file_id=file.file_id: self.operations.clear_permissions(file_id),
                )
            external = await self._run_step(
                entry,
                "external_verify",
                lambda: self.operations.verify_external_absent(unit),
            )
            entry["verification"].update(external or {})
            await self._run_step(
                entry,
                "database_delete",
                lambda: self.operations.delete_database_records(unit),
            )
            await self._run_step(
                entry,
                "derived_invalidation",
                lambda: self.operations.invalidate_derived_state(unit),
            )
            verification = await self._run_step(
                entry,
                "post_delete_verify",
                lambda: self.operations.verify_deleted(unit),
            )
            entry["verification"].update(verification or {})
        except ReportWriteError:
            raise
        except Exception as exc:
            entry["status"] = "failed"
            entry["error_type"] = type(exc).__name__
            entry["retriable"] = True
            self.checkpoint()
            logger.exception(
                "dedupe unit failed run_id=%s unit_key=%s space_id=%s file_id=%s error_type=%s",
                self.run_id,
                unit.unit_key,
                unit.department_space_id,
                unit.primary_file_id,
                type(exc).__name__,
            )
            return False
        entry["status"] = "completed"
        entry["reason_code"] = ""
        entry["error_type"] = ""
        entry["retriable"] = False
        self.checkpoint()
        logger.info(
            "dedupe unit completed run_id=%s unit_key=%s space_id=%s file_id=%s",
            self.run_id,
            unit.unit_key,
            unit.department_space_id,
            unit.primary_file_id,
        )
        return True

    async def execute(self, report: dict[str, Any]) -> bool:
        self.run_id = str(report.get("run_id") or "")
        entries = report.get("units", [])
        for index, entry in enumerate(entries):
            if entry.get("status") == "completed":
                continue
            if not await self.process_entry(entry):
                for remaining in entries[index + 1 :]:
                    if remaining.get("status") == "planned":
                        remaining["status"] = "pending"
                self.checkpoint()
                return False
        return True


class ResumeExecutor:
    def __init__(
        self,
        reader: PlanReader,
        operations: DeleteOperations,
        checkpoint: Callable[[], None],
    ) -> None:
        self.reader = reader
        self.operations = operations
        self.checkpoint = checkpoint

    async def execute(self, report: dict[str, Any]) -> bool:
        entries = report.get("units", [])
        apply_executor = ApplyExecutor(self.reader, self.operations, self.checkpoint)
        apply_executor.run_id = str(report.get("run_id") or "")
        for index, entry in enumerate(entries):
            if entry.get("status") in {"completed", "skipped"}:
                continue
            unit = deletion_unit_from_dict(entry["unit"])
            try:
                target_exists = await self.operations.target_records_exist(unit)
                if target_exists:
                    success = await apply_executor.process_entry(entry)
                else:
                    entry["status"] = "pending"
                    self.checkpoint()
                    await apply_executor._run_step(
                        entry,
                        "derived_invalidation",
                        lambda unit=unit: self.operations.invalidate_derived_state(unit),
                    )
                    verification = await apply_executor._run_step(
                        entry,
                        "post_delete_verify",
                        lambda unit=unit: self.operations.verify_deleted(unit),
                    )
                    entry["verification"].update(verification or {})
                    entry["status"] = "completed"
                    entry["retriable"] = False
                    self.checkpoint()
                    success = True
            except ReportWriteError:
                raise
            except Exception as exc:
                entry["status"] = "failed"
                entry["error_type"] = type(exc).__name__
                entry["retriable"] = True
                self.checkpoint()
                logger.exception(
                    "dedupe resume unit failed run_id=%s unit_key=%s space_id=%s file_id=%s error_type=%s",
                    apply_executor.run_id,
                    unit.unit_key,
                    unit.department_space_id,
                    unit.primary_file_id,
                    type(exc).__name__,
                )
                success = False
            if not success:
                for remaining in entries[index + 1 :]:
                    if remaining.get("status") in {"planned", "pending"}:
                        remaining["status"] = "pending"
                self.checkpoint()
                return False
        return True


@contextmanager
def _tenant_scope(tenant_id: int):
    tenant_token = set_current_tenant_id(tenant_id)
    visible_token = set_visible_tenant_ids(frozenset({tenant_id}))
    try:
        with strict_tenant_filter():
            yield
    finally:
        visible_tenant_ids.reset(visible_token)
        current_tenant_id.reset(tenant_token)


def _chunks(values: Sequence[int], size: int = 500) -> list[list[int]]:
    normalized = sorted({int(value) for value in values})
    return [normalized[index : index + size] for index in range(0, len(normalized), size)]


def _file_snapshot(model: KnowledgeFile) -> FileSnapshot:
    file_id = int(model.id or 0)
    preview = KnowledgeUtils.resolve_preview_object_name(
        file_id,
        model.file_name,
        model.preview_file_object_name,
    )
    raw_objects = (
        ("original", model.object_name),
        ("converted", str(file_id)),
        ("bbox", model.bbox_object_name),
        ("preview", preview),
        ("thumbnail", model.thumbnails),
    )
    storage_objects: list[StorageObjectSnapshot] = []
    seen_names: set[str] = set()
    for kind, raw_name in raw_objects:
        name = str(raw_name or "")
        if not name or name in seen_names:
            continue
        storage_objects.append(StorageObjectSnapshot(kind=kind, name=name))
        seen_names.add(name)
    return FileSnapshot(
        file_id=file_id,
        space_id=int(model.knowledge_id),
        file_type=int(model.file_type),
        status=int(model.status or 0),
        md5=model.md5,
        storage_objects=tuple(storage_objects),
    )


async def _load_files_by_ids(session, file_ids: Sequence[int]) -> list[KnowledgeFile]:
    rows: list[KnowledgeFile] = []
    for batch in _chunks(file_ids):
        rows.extend(
            list(
                (
                    await session.exec(
                        select(KnowledgeFile).where(col(KnowledgeFile.id).in_(batch)).order_by(col(KnowledgeFile.id))
                    )
                ).all()
            )
        )
    return rows


async def _load_files_by_space_ids(session, space_ids: Sequence[int]) -> list[KnowledgeFile]:
    normalized = sorted({int(value) for value in space_ids})
    if not normalized:
        return []
    rows: list[KnowledgeFile] = []
    last_id = 0
    while True:
        batch = list(
            (
                await session.exec(
                    select(KnowledgeFile)
                    .where(
                        col(KnowledgeFile.knowledge_id).in_(normalized),
                        KnowledgeFile.id > last_id,
                    )
                    .order_by(col(KnowledgeFile.id))
                    .limit(1000)
                )
            ).all()
        )
        if not batch:
            break
        rows.extend(batch)
        last_id = int(batch[-1].id)
    return rows


async def _load_versions_by_file_ids(
    session,
    file_ids: Sequence[int],
) -> list[KnowledgeDocumentVersion]:
    rows: list[KnowledgeDocumentVersion] = []
    for batch in _chunks(file_ids):
        rows.extend(
            list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion).where(
                            col(KnowledgeDocumentVersion.knowledge_file_id).in_(batch)
                        )
                    )
                ).all()
            )
        )
    return rows


async def _load_versions_by_document_ids(
    session,
    document_ids: Sequence[int],
) -> list[KnowledgeDocumentVersion]:
    rows: list[KnowledgeDocumentVersion] = []
    for batch in _chunks(document_ids):
        rows.extend(
            list(
                (
                    await session.exec(
                        select(KnowledgeDocumentVersion)
                        .where(col(KnowledgeDocumentVersion.document_id).in_(batch))
                        .order_by(
                            col(KnowledgeDocumentVersion.document_id),
                            col(KnowledgeDocumentVersion.version_no),
                        )
                    )
                ).all()
            )
        )
    return rows


async def _load_documents_by_ids(
    session,
    document_ids: Sequence[int],
) -> list[KnowledgeDocument]:
    rows: list[KnowledgeDocument] = []
    for batch in _chunks(document_ids):
        rows.extend(
            list((await session.exec(select(KnowledgeDocument).where(col(KnowledgeDocument.id).in_(batch)))).all())
        )
    return rows


async def _build_inventory_from_seed_files(
    session,
    spaces: Sequence[SpaceSnapshot],
    seed_files: Sequence[KnowledgeFile],
    *,
    extra_document_ids: Sequence[int] = (),
) -> Inventory:
    files_by_id = {int(item.id): item for item in seed_files if item.id is not None}
    initial_versions = await _load_versions_by_file_ids(session, list(files_by_id))
    document_ids = {int(item.document_id) for item in initial_versions} | {
        int(value) for value in extra_document_ids if value is not None
    }
    versions = await _load_versions_by_document_ids(session, sorted(document_ids))
    documents = await _load_documents_by_ids(session, sorted(document_ids))
    chain_file_ids = {int(item.knowledge_file_id) for item in versions} - set(files_by_id)
    if chain_file_ids:
        chain_files = await _load_files_by_ids(session, sorted(chain_file_ids))
        files_by_id.update({int(item.id): item for item in chain_files if item.id is not None})
    return Inventory(
        spaces=tuple(sorted(spaces, key=lambda item: item.space_id)),
        files=tuple(
            _file_snapshot(item) for item in sorted(files_by_id.values(), key=lambda value: int(value.id or 0))
        ),
        documents=tuple(
            DocumentSnapshot(
                document_id=int(item.id),
                space_id=int(item.knowledge_id),
                primary_version_id=(int(item.primary_version_id) if item.primary_version_id is not None else None),
            )
            for item in sorted(documents, key=lambda value: int(value.id or 0))
            if item.id is not None
        ),
        versions=tuple(
            VersionSnapshot(
                version_id=int(item.id),
                document_id=int(item.document_id),
                file_id=int(item.knowledge_file_id),
                version_no=int(item.version_no),
                is_primary=bool(item.is_primary),
            )
            for item in sorted(
                versions,
                key=lambda value: (int(value.document_id), int(value.version_no), int(value.id or 0)),
            )
            if item.id is not None
        ),
    )


async def _read_file_tuples(file_id: int) -> tuple[dict[str, str], ...]:
    fga = PermissionService._get_fga()
    if fga is None:
        if bool(getattr(settings.openfga, "enabled", False)):
            raise RuntimeError("OpenFGA is enabled but unavailable")
        return ()
    rows = await fga.read_tuples(object=f"knowledge_file:{file_id}")
    return tuple(
        {
            "user": str(row["user"]),
            "relation": str(row["relation"]),
            "object": str(row["object"]),
        }
        for row in (rows or [])
    )


async def _clear_file_tuples(file_id: int) -> None:
    rows = await _read_file_tuples(file_id)
    if not rows:
        return
    operations = [
        TupleOperation(
            action="delete",
            user=row["user"],
            relation=row["relation"],
            object=row["object"],
        )
        for row in rows
    ]
    await PermissionService.batch_write_tuples(
        operations,
        crash_safe=True,
        raise_on_failure=True,
        stop_on_failure=True,
    )


class BishengPlanReader:
    def __init__(self, tenant_id: int = DEFAULT_TENANT_ID) -> None:
        self.tenant_id = int(tenant_id)

    @staticmethod
    async def _load_space_snapshots(session) -> tuple[list[SpaceSnapshot], dict[int, Knowledge]]:
        scope_rows = list(
            (
                await session.exec(
                    select(KnowledgeSpaceScope).where(
                        col(KnowledgeSpaceScope.level).in_(
                            [
                                KnowledgeSpaceLevelEnum.PUBLIC.value,
                                KnowledgeSpaceLevelEnum.DEPARTMENT.value,
                            ]
                        )
                    )
                )
            ).all()
        )
        scope_by_space = {int(item.space_id): item for item in scope_rows}
        spaces: list[Knowledge] = []
        for batch in _chunks(list(scope_by_space)):
            spaces.extend(
                list(
                    (
                        await session.exec(
                            select(Knowledge).where(
                                col(Knowledge.id).in_(batch),
                                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            )
                        )
                    ).all()
                )
            )
        knowledge_by_id = {int(item.id): item for item in spaces if item.id is not None}
        snapshots = [
            SpaceSnapshot(space_id=space_id, level=_enum_value(scope_by_space[space_id].level))
            for space_id in sorted(knowledge_by_id)
        ]
        return snapshots, knowledge_by_id

    async def _enrich_impacts(
        self,
        session,
        plan: DeduplicationPlan,
    ) -> DeduplicationPlan:
        all_file_ids = sorted({file.file_id for unit in plan.units for file in unit.physical_files})
        if not all_file_ids:
            return plan
        resource_ids = [str(value) for value in all_file_ids]
        tag_rows = list(
            (
                await session.exec(
                    select(TagLink).where(
                        col(TagLink.resource_id).in_(resource_ids),
                        TagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                    )
                )
            ).all()
        )
        review_rows = list(
            (
                await session.exec(
                    select(ReviewTagLink).where(
                        col(ReviewTagLink.resource_id).in_(resource_ids),
                        ReviewTagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                    )
                )
            ).all()
        )
        share_rows = list(
            (
                await session.exec(
                    select(ShareLink).where(
                        col(ShareLink.resource_id).in_(resource_ids),
                        ShareLink.resource_type == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                    )
                )
            ).all()
        )
        similarity_rows = list(
            (
                await session.exec(
                    select(KnowledgeFileSimilarityCandidate).where(
                        or_(
                            col(KnowledgeFileSimilarityCandidate.source_file_id).in_(all_file_ids),
                            col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(all_file_ids),
                        )
                    )
                )
            ).all()
        )
        projection_rows = list(
            (
                await session.exec(
                    select(PortalRecommendationFileProjection).where(
                        col(PortalRecommendationFileProjection.file_id).in_(all_file_ids)
                    )
                )
            ).all()
        )
        favorite_rows = list(
            (await session.exec(select(KnowledgeFile).where(KnowledgeFile.file_source == "favorite_reference"))).all()
        )
        favorite_source_ids: list[int] = []
        for row in favorite_rows:
            metadata = row.user_metadata if isinstance(row.user_metadata, dict) else {}
            favorite = metadata.get("favorite_reference") if isinstance(metadata, dict) else None
            if not isinstance(favorite, dict):
                continue
            try:
                favorite_source_ids.append(int(favorite.get("source_file_id") or 0))
            except (TypeError, ValueError):
                # Malformed legacy metadata only affects this report count; the record is preserved.
                continue

        enriched: list[DeletionUnit] = []
        for unit in plan.units:
            unit_ids = {item.file_id for item in unit.physical_files}
            permission_count = 0
            for file_id in sorted(unit_ids):
                permission_count += len(await _read_file_tuples(file_id))
            impact_counts = {
                "physical_files": len(unit_ids),
                "storage_objects": sum(len(item.storage_objects) for item in unit.physical_files),
                "openfga_tuples": permission_count,
                "tag_links": sum(int(row.resource_id) in unit_ids for row in tag_rows),
                "review_tag_links": sum(int(row.resource_id) in unit_ids for row in review_rows),
                "share_links": sum(int(row.resource_id) in unit_ids for row in share_rows),
                "similarity_candidates": sum(
                    int(row.source_file_id) in unit_ids or int(row.candidate_file_id) in unit_ids
                    for row in similarity_rows
                ),
                "recommendation_projections": sum(int(row.file_id) in unit_ids for row in projection_rows),
                "favorite_references_preserved": sum(value in unit_ids for value in favorite_source_ids),
            }
            enriched.append(replace(unit, impact_counts=impact_counts))
        return replace(plan, units=tuple(enriched))

    async def build_plan(self, args: argparse.Namespace) -> DeduplicationPlan:
        async with get_async_db_session() as session:
            spaces, _knowledge_by_id = await self._load_space_snapshots(session)
            public_ids = [item.space_id for item in spaces if item.level == "public"]
            department_ids = [item.space_id for item in spaces if item.level == "department"]
            requested_department_ids = sorted({int(value) for value in args.department_space_ids})
            loaded_department_ids = requested_department_ids or department_ids
            seed_files = await _load_files_by_space_ids(
                session,
                [*public_ids, *loaded_department_ids],
            )
            inventory = await _build_inventory_from_seed_files(session, spaces, seed_files)
            plan = build_deduplication_plan(
                inventory,
                department_space_ids=args.department_space_ids,
                file_ids=args.file_ids,
                limit=args.limit,
                tenant_id=self.tenant_id,
            )
            return await self._enrich_impacts(session, plan)

    async def revalidate(self, unit: DeletionUnit) -> RevalidationResult:
        scope_space_ids = sorted({unit.department_space_id, *(item.space_id for item in unit.public_witnesses)})
        seed_file_ids = sorted(
            {
                *(item.file_id for item in unit.physical_files),
                *(item.file_id for item in unit.public_witnesses),
            }
        )
        async with get_async_db_session() as session:
            scope_rows = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceScope).where(col(KnowledgeSpaceScope.space_id).in_(scope_space_ids))
                    )
                ).all()
            )
            scope_by_space = {int(item.space_id): item for item in scope_rows}
            valid_spaces: list[Knowledge] = []
            for batch in _chunks(scope_space_ids):
                valid_spaces.extend(
                    list(
                        (
                            await session.exec(
                                select(Knowledge).where(
                                    col(Knowledge.id).in_(batch),
                                    Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                                )
                            )
                        ).all()
                    )
                )
            valid_ids = {int(item.id) for item in valid_spaces if item.id is not None}
            spaces = [
                SpaceSnapshot(space_id=space_id, level=_enum_value(scope_by_space[space_id].level))
                for space_id in sorted(valid_ids & set(scope_by_space))
            ]
            seed_files = await _load_files_by_ids(session, seed_file_ids)
            inventory = await _build_inventory_from_seed_files(
                session,
                spaces,
                seed_files,
                extra_document_ids=([unit.document_id] if unit.document_id is not None else []),
            )
        try:
            plan = build_deduplication_plan(
                inventory,
                department_space_ids=[unit.department_space_id],
                file_ids=[unit.primary_file_id],
                tenant_id=self.tenant_id,
            )
        except PreflightError:
            return RevalidationResult(valid=False, reason_code="target_no_longer_current")
        current = next((item for item in plan.units if item.unit_key == unit.unit_key), None)
        if current is None:
            return RevalidationResult(valid=False, reason_code="no_longer_duplicate")
        if current.plan_fingerprint != unit.plan_fingerprint:
            return RevalidationResult(valid=False, reason_code="plan_drift")
        return RevalidationResult(valid=True, unit=current)


def _milvus_store(space: Knowledge):
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    return KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        0,
        knowledge=space,
        embeddings=FakeEmbeddings(),
    )


def _es_store(space: Knowledge):
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    return KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)


def _delete_milvus_sync(space: Knowledge, file_id: int) -> None:
    store = _milvus_store(space)
    if store.col is not None:
        store.col.delete(expr=f"document_id in [{int(file_id)}]", timeout=10)


def _delete_elasticsearch_sync(space: Knowledge, file_id: int) -> None:
    store = _es_store(space)
    if store is None or not store.client.indices.exists(index=space.index_name):
        return
    store.client.delete_by_query(
        index=space.index_name,
        query={"terms": {"metadata.document_id": [int(file_id)]}},
    )


def _count_milvus_sync(space: Knowledge, file_id: int) -> int:
    store = _milvus_store(space)
    if store.col is None:
        return 0
    expression = f"document_id=={int(file_id)} && knowledge_id=={int(space.id)}"
    if hasattr(store.col, "query_iterator"):
        iterator = store.col.query_iterator(expr=expression, output_fields=["pk"], batch_size=1000)
        count = 0
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                count += len(batch)
        finally:
            iterator.close()
        return count
    return len(store.col.query(expr=expression, output_fields=["pk"], limit=16384))


def _count_elasticsearch_sync(space: Knowledge, file_id: int) -> int:
    store = _es_store(space)
    if store is None or not store.client.indices.exists(index=space.index_name):
        return 0
    response = store.client.count(
        index=space.index_name,
        query={"bool": {"filter": [{"term": {"metadata.document_id": int(file_id)}}]}},
    )
    return int(response.get("count", 0))


class BishengDeleteOperations:
    def __init__(self, tenant_id: int = DEFAULT_TENANT_ID) -> None:
        self.tenant_id = int(tenant_id)
        self._spaces: dict[int, Knowledge] = {}

    async def _space(self, space_id: int) -> Knowledge:
        if space_id not in self._spaces:
            space = await KnowledgeDao.aquery_by_id(space_id)
            if space is None or int(space.type) != KnowledgeTypeEnum.SPACE.value:
                raise RuntimeError("target knowledge space is unavailable")
            async with get_async_db_session() as session:
                scope = (
                    await session.exec(select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == space_id))
                ).first()
            if scope is None or _enum_value(scope.level) != "department":
                raise PreflightError("external deletion target is no longer a department space")
            self._spaces[space_id] = space
        return self._spaces[space_id]

    async def delete_milvus(self, file: FileSnapshot) -> None:
        space = await self._space(file.space_id)
        await asyncio.to_thread(_delete_milvus_sync, space, file.file_id)

    async def delete_elasticsearch(self, file: FileSnapshot) -> None:
        space = await self._space(file.space_id)
        await asyncio.to_thread(_delete_elasticsearch_sync, space, file.file_id)

    async def delete_minio(self, file: FileSnapshot) -> None:
        storage = get_minio_storage_sync()
        for object_name in sorted({item.name for item in file.storage_objects if item.name}):
            await asyncio.to_thread(
                storage.remove_object_sync,
                bucket_name=storage.bucket,
                object_name=object_name,
            )

    async def clear_permissions(self, file_id: int) -> None:
        await _clear_file_tuples(file_id)

    async def verify_external_absent(self, unit: DeletionUnit) -> dict[str, Any]:
        storage = get_minio_storage_sync()
        evidence: dict[str, Any] = {
            "milvus_records": {},
            "elasticsearch_records": {},
            "storage_objects_present": [],
            "openfga_tuples": {},
        }
        for file in sorted(unit.physical_files, key=lambda item: item.file_id):
            space = await self._space(file.space_id)
            milvus_count = await asyncio.to_thread(_count_milvus_sync, space, file.file_id)
            es_count = await asyncio.to_thread(_count_elasticsearch_sync, space, file.file_id)
            tuples = await _read_file_tuples(file.file_id)
            evidence["milvus_records"][str(file.file_id)] = milvus_count
            evidence["elasticsearch_records"][str(file.file_id)] = es_count
            evidence["openfga_tuples"][str(file.file_id)] = len(tuples)
            for item in file.storage_objects:
                exists = await asyncio.to_thread(
                    storage.object_exists_sync,
                    storage.bucket,
                    item.name,
                )
                if exists:
                    evidence["storage_objects_present"].append(item.name)
        if (
            any(evidence["milvus_records"].values())
            or any(evidence["elasticsearch_records"].values())
            or evidence["storage_objects_present"]
            or any(evidence["openfga_tuples"].values())
        ):
            raise ResidualDataError("external resources remain after deletion")
        evidence["external_absent"] = True
        return evidence

    async def delete_database_records(self, unit: DeletionUnit) -> None:
        target_ids = sorted({item.file_id for item in unit.physical_files})
        witness_ids = {item.file_id for item in unit.public_witnesses}
        if set(target_ids) & witness_ids:
            raise PreflightError("database deletion target overlaps a public witness")
        resource_ids = [str(value) for value in target_ids]
        version_ids = sorted({item.version_id for item in unit.versions})
        async with get_async_db_session() as session:
            try:
                protected_space_ids = sorted(
                    {unit.department_space_id, *(item.space_id for item in unit.public_witnesses)}
                )
                scopes = list(
                    (
                        await session.exec(
                            select(KnowledgeSpaceScope)
                            .where(col(KnowledgeSpaceScope.space_id).in_(protected_space_ids))
                            .with_for_update()
                        )
                    ).all()
                )
                scope_by_space = {int(item.space_id): _enum_value(item.level) for item in scopes}
                if scope_by_space.get(unit.department_space_id) != "department":
                    raise PreflightError("database deletion target is no longer a department space")
                if any(scope_by_space.get(item.space_id) != "public" for item in unit.public_witnesses):
                    raise PreflightError("a public witness is no longer in a public space")

                witness_by_id = {item.file_id: item for item in unit.public_witnesses}
                witnesses = list(
                    (
                        await session.exec(
                            select(KnowledgeFile)
                            .where(col(KnowledgeFile.id).in_(sorted(witness_by_id)))
                            .with_for_update()
                        )
                    ).all()
                )
                if {int(item.id) for item in witnesses} != set(witness_by_id):
                    raise PreflightError("a public witness disappeared before database deletion")
                for witness in witnesses:
                    expected = witness_by_id[int(witness.id)]
                    if (
                        int(witness.knowledge_id) != expected.space_id
                        or int(witness.file_type) != FILE_TYPE_FILE
                        or int(witness.status or 0) != FILE_STATUS_SUCCESS
                        or witness.md5 != expected.md5
                    ):
                        raise PreflightError("a public witness changed before database deletion")

                current = list(
                    (
                        await session.exec(
                            select(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids)).with_for_update()
                        )
                    ).all()
                )
                if {int(item.id) for item in current} != set(target_ids):
                    raise RuntimeError("target database snapshot changed before delete")
                if any(int(item.knowledge_id) != unit.department_space_id for item in current):
                    raise PreflightError("target database snapshot contains a cross-space file")
                if unit.document_id is not None:
                    document = (
                        await session.exec(
                            select(KnowledgeDocument).where(KnowledgeDocument.id == unit.document_id).with_for_update()
                        )
                    ).first()
                    if (
                        document is None
                        or int(document.knowledge_id) != unit.department_space_id
                        or document.primary_version_id != unit.primary_version_id
                    ):
                        raise PreflightError("logical document changed before database deletion")
                    locked_versions = list(
                        (
                            await session.exec(
                                select(KnowledgeDocumentVersion)
                                .where(KnowledgeDocumentVersion.document_id == unit.document_id)
                                .with_for_update()
                            )
                        ).all()
                    )
                    actual_versions = {
                        (
                            int(item.id),
                            int(item.document_id),
                            int(item.knowledge_file_id),
                            int(item.version_no),
                            bool(item.is_primary),
                        )
                        for item in locked_versions
                    }
                    expected_versions = {
                        (
                            item.version_id,
                            item.document_id,
                            item.file_id,
                            item.version_no,
                            item.is_primary,
                        )
                        for item in unit.versions
                    }
                    if actual_versions != expected_versions or {
                        int(item.knowledge_file_id) for item in locked_versions
                    } != set(target_ids):
                        raise PreflightError("version chain changed before database deletion")
                else:
                    legacy_versions = list(
                        (
                            await session.exec(
                                select(KnowledgeDocumentVersion)
                                .where(col(KnowledgeDocumentVersion.knowledge_file_id).in_(target_ids))
                                .with_for_update()
                            )
                        ).all()
                    )
                    if legacy_versions:
                        raise PreflightError("legacy target gained a version relation before database deletion")
                await session.exec(
                    delete(TagLink).where(
                        col(TagLink.resource_id).in_(resource_ids),
                        TagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                    )
                )
                await session.exec(
                    delete(ReviewTagLink).where(
                        col(ReviewTagLink.resource_id).in_(resource_ids),
                        ReviewTagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                    )
                )
                await session.exec(
                    delete(ShareLink).where(
                        col(ShareLink.resource_id).in_(resource_ids),
                        ShareLink.resource_type == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                    )
                )
                await session.exec(
                    delete(KnowledgeFileSimilarityCandidate).where(
                        or_(
                            col(KnowledgeFileSimilarityCandidate.source_file_id).in_(target_ids),
                            col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(target_ids),
                        )
                    )
                )
                await session.exec(
                    delete(PortalRecommendationFileProjection).where(
                        col(PortalRecommendationFileProjection.file_id).in_(target_ids)
                    )
                )
                if unit.document_id is not None:
                    await session.exec(
                        update(KnowledgeDocument)
                        .where(KnowledgeDocument.id == unit.document_id)
                        .values(primary_version_id=None)
                    )
                    if version_ids:
                        await session.exec(
                            delete(KnowledgeDocumentVersion).where(col(KnowledgeDocumentVersion.id).in_(version_ids))
                        )
                    await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == unit.document_id))
                await session.exec(delete(KnowledgeFile).where(col(KnowledgeFile.id).in_(target_ids)))
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def invalidate_derived_state(self, unit: DeletionUnit) -> None:
        file_ids = sorted({item.file_id for item in unit.physical_files})
        await KnowledgeDao.async_update_knowledge_update_time_by_id(unit.department_space_id)
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
        from bisheng.worker.knowledge.portal_recommendation import (
            enqueue_portal_recommendation_projection_refresh_batch,
        )

        await KnowledgeSpaceContentStat.enqueue_file_stat_async(file_ids)
        enqueue_portal_recommendation_projection_refresh_batch(
            file_ids=file_ids,
            deleted=True,
            tenant_id=self.tenant_id,
        )

    async def _verify_database_absent(self, unit: DeletionUnit) -> dict[str, int]:
        target_ids = sorted({item.file_id for item in unit.physical_files})
        resource_ids = [str(value) for value in target_ids]
        async with get_async_db_session() as session:
            counts = {
                "knowledge_files": int(
                    await session.scalar(select(func.count()).where(col(KnowledgeFile.id).in_(target_ids))) or 0
                ),
                "tag_links": int(
                    await session.scalar(
                        select(func.count()).where(
                            col(TagLink.resource_id).in_(resource_ids),
                            TagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                        )
                    )
                    or 0
                ),
                "review_tag_links": int(
                    await session.scalar(
                        select(func.count()).where(
                            col(ReviewTagLink.resource_id).in_(resource_ids),
                            ReviewTagLink.resource_type == TagLinkResourceTypeEnum.SPACE_FILE.value,
                        )
                    )
                    or 0
                ),
                "share_links": int(
                    await session.scalar(
                        select(func.count()).where(
                            col(ShareLink.resource_id).in_(resource_ids),
                            ShareLink.resource_type == ShareResourceTypeEnum.KNOWLEDGE_SPACE_FILE,
                        )
                    )
                    or 0
                ),
                "similarity_candidates": int(
                    await session.scalar(
                        select(func.count()).where(
                            or_(
                                col(KnowledgeFileSimilarityCandidate.source_file_id).in_(target_ids),
                                col(KnowledgeFileSimilarityCandidate.candidate_file_id).in_(target_ids),
                            )
                        )
                    )
                    or 0
                ),
                "recommendation_projections": int(
                    await session.scalar(
                        select(func.count()).where(col(PortalRecommendationFileProjection.file_id).in_(target_ids))
                    )
                    or 0
                ),
            }
            if unit.document_id is not None:
                counts["documents"] = int(
                    await session.scalar(select(func.count()).where(KnowledgeDocument.id == unit.document_id)) or 0
                )
                counts["versions"] = int(
                    await session.scalar(
                        select(func.count()).where(KnowledgeDocumentVersion.document_id == unit.document_id)
                    )
                    or 0
                )
            else:
                counts["documents"] = 0
                counts["versions"] = 0
        return counts

    async def _verify_public_witnesses(self, unit: DeletionUnit) -> None:
        witness_ids = sorted({item.file_id for item in unit.public_witnesses})
        witness_by_id = {item.file_id: item for item in unit.public_witnesses}
        async with get_async_db_session() as session:
            files = list(
                (await session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(witness_ids)))).all()
            )
            scopes = list(
                (
                    await session.exec(
                        select(KnowledgeSpaceScope).where(
                            col(KnowledgeSpaceScope.space_id).in_([int(item.knowledge_id) for item in files])
                        )
                    )
                ).all()
            )
        scope_by_space = {int(item.space_id): _enum_value(item.level) for item in scopes}
        if {int(item.id) for item in files} != set(witness_ids):
            raise ResidualDataError("a public witness is missing after deletion")
        for file in files:
            expected = witness_by_id[int(file.id)]
            if (
                int(file.knowledge_id) != expected.space_id
                or scope_by_space.get(int(file.knowledge_id)) != "public"
                or int(file.file_type) != FILE_TYPE_FILE
                or int(file.status or 0) != FILE_STATUS_SUCCESS
                or file.md5 != expected.md5
            ):
                raise ResidualDataError("a public witness changed during deletion")

    async def verify_deleted(self, unit: DeletionUnit) -> dict[str, Any]:
        database_counts = await self._verify_database_absent(unit)
        if any(database_counts.values()):
            raise ResidualDataError("database resources remain after deletion")
        await self._verify_public_witnesses(unit)
        external = await self.verify_external_absent(unit)
        return {
            "database_absent": True,
            "database_counts": database_counts,
            "public_witnesses_unchanged": True,
            **external,
        }

    async def target_records_exist(self, unit: DeletionUnit) -> bool:
        target_ids = sorted({item.file_id for item in unit.physical_files})
        async with get_async_db_session() as session:
            count = await session.scalar(select(func.count()).where(col(KnowledgeFile.id).in_(target_ids)))
        return bool(count)


def _arguments_for_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "apply": bool(args.apply),
        "department_space_ids": sorted({int(value) for value in args.department_space_ids}),
        "file_ids": sorted({int(value) for value in args.file_ids}),
        "limit": args.limit,
        "resume_report": str(args.resume_report.resolve()) if args.resume_report else None,
    }


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _make_error_report(
    *,
    run_id: str,
    mode: str,
    arguments: dict[str, Any],
    error_type: str,
    exit_code: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "arguments": arguments,
        "preflight": {},
        "public_witness_summary": {},
        "units": [],
        "skipped": [],
        "errors": [{"error_type": error_type, "exit_code": exit_code}],
        "verification": {},
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "finished_at": _utc_now(),
    }
    _refresh_summary(report)
    return report


def _print_report_summary(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary", {})
    print(f"Run ID: {report.get('run_id')}")
    print(f"Report: {path.resolve()}")
    print(
        "Summary: "
        f"planned={summary.get('planned', 0)} "
        f"completed={summary.get('completed', 0)} "
        f"skipped={summary.get('skipped', 0)} "
        f"failed={summary.get('failed', 0)} "
        f"pending={summary.get('pending', 0)}"
    )


async def run(
    args: argparse.Namespace,
    *,
    reader: PlanReader | None = None,
    operations_factory: Callable[[], DeleteOperations] | None = None,
    manage_context: bool = True,
) -> int:
    run_id = _new_run_id()
    store = ReportStore(args.report_dir, run_id)
    arguments = _arguments_for_report(args)
    context_initialized = False
    tenant_id = DEFAULT_TENANT_ID
    report: dict[str, Any] | None = None
    logger.info("dedupe run started run_id=%s mode=%s", run_id, "apply" if args.apply else "dry-run")
    try:
        if manage_context:
            await initialize_app_context(config=settings)
            context_initialized = True
            tenant_id = ensure_single_tenant(bool(settings.multi_tenant.enabled))
        scope = _tenant_scope(tenant_id) if manage_context else nullcontext()
        with scope:
            actual_reader = reader or BishengPlanReader(tenant_id)
            try:
                if args.resume_report is not None:
                    source = load_resume_report(args.resume_report)
                    report = make_resume_report(source, run_id=run_id)
                else:
                    plan = await actual_reader.build_plan(args)
                    report = make_run_report(
                        plan,
                        mode="apply" if args.apply else "dry-run",
                        run_id=run_id,
                        arguments=arguments,
                    )
            except PreflightError as exc:
                report = _make_error_report(
                    run_id=run_id,
                    mode="apply" if args.apply else "dry-run",
                    arguments=arguments,
                    error_type=type(exc).__name__,
                    exit_code=EXIT_INPUT_ERROR,
                )
                try:
                    path = store.write(report)
                    _print_report_summary(report, path)
                except ReportWriteError:
                    logger.exception("dedupe report write failed run_id=%s phase=preflight_error", run_id)
                    return EXIT_REPORT_ERROR
                return EXIT_INPUT_ERROR
            except Exception as exc:
                logger.exception(
                    "dedupe planning failed run_id=%s error_type=%s",
                    run_id,
                    type(exc).__name__,
                )
                report = _make_error_report(
                    run_id=run_id,
                    mode="apply" if args.apply else "dry-run",
                    arguments=arguments,
                    error_type=type(exc).__name__,
                    exit_code=EXIT_SCAN_ERROR,
                )
                try:
                    path = store.write(report)
                    _print_report_summary(report, path)
                except ReportWriteError:
                    logger.exception("dedupe report write failed run_id=%s phase=planning_error", run_id)
                    return EXIT_REPORT_ERROR
                return EXIT_SCAN_ERROR

            try:
                store.write(report)
            except ReportWriteError:
                logger.exception("dedupe report write failed run_id=%s phase=initial_checkpoint", run_id)
                return EXIT_REPORT_ERROR
            if not args.apply:
                report["finished_at"] = _utc_now()
                try:
                    path = store.write(report)
                except ReportWriteError:
                    logger.exception("dedupe report write failed run_id=%s phase=dry_run_final", run_id)
                    return EXIT_REPORT_ERROR
                _print_report_summary(report, path)
                return EXIT_OK

            try:
                operations = (
                    operations_factory() if operations_factory is not None else BishengDeleteOperations(tenant_id)
                )
            except Exception as exc:
                logger.exception(
                    "dedupe delete adapter initialization failed run_id=%s error_type=%s",
                    run_id,
                    type(exc).__name__,
                )
                report["errors"].append({"error_type": type(exc).__name__})
                for entry in report.get("units", []):
                    if entry.get("status") == "planned":
                        entry["status"] = "pending"
                report["finished_at"] = _utc_now()
                try:
                    path = store.write(report)
                    _print_report_summary(report, path)
                except ReportWriteError:
                    logger.exception("dedupe report write failed run_id=%s phase=adapter_error", run_id)
                    return EXIT_REPORT_ERROR
                return EXIT_APPLY_ERROR

            def checkpoint() -> None:
                store.write(report)

            executor = (
                ResumeExecutor(actual_reader, operations, checkpoint)
                if args.resume_report is not None
                else ApplyExecutor(actual_reader, operations, checkpoint)
            )
            try:
                success = await executor.execute(report)
            except ReportWriteError:
                logger.exception("dedupe report write failed run_id=%s phase=apply_checkpoint", run_id)
                return EXIT_REPORT_ERROR
            report["finished_at"] = _utc_now()
            try:
                path = store.write(report)
            except ReportWriteError:
                logger.exception("dedupe report write failed run_id=%s phase=apply_final", run_id)
                return EXIT_REPORT_ERROR
            _print_report_summary(report, path)
            return EXIT_OK if success else EXIT_APPLY_ERROR
    except PreflightError as exc:
        report = _make_error_report(
            run_id=run_id,
            mode="apply" if args.apply else "dry-run",
            arguments=arguments,
            error_type=type(exc).__name__,
            exit_code=EXIT_INPUT_ERROR,
        )
        try:
            path = store.write(report)
            _print_report_summary(report, path)
        except ReportWriteError:
            logger.exception("dedupe report write failed run_id=%s phase=safety_error", run_id)
            return EXIT_REPORT_ERROR
        return EXIT_INPUT_ERROR
    except Exception as exc:
        logger.exception(
            "dedupe script failed run_id=%s error_type=%s",
            run_id,
            type(exc).__name__,
        )
        if report is None:
            report = _make_error_report(
                run_id=run_id,
                mode="apply" if args.apply else "dry-run",
                arguments=arguments,
                error_type=type(exc).__name__,
                exit_code=EXIT_SCAN_ERROR,
            )
        try:
            path = store.write(report)
            _print_report_summary(report, path)
        except ReportWriteError:
            logger.exception("dedupe report write failed run_id=%s phase=unhandled_error", run_id)
            return EXIT_REPORT_ERROR
        return EXIT_SCAN_ERROR
    finally:
        if context_initialized:
            await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
