#!/usr/bin/env python3
"""Convert cross-level duplicate knowledge-space files into publish soft links.

When the same current primary file exists in multiple knowledge spaces, the copy
in the highest-level space stays the physical original (manager). Strictly lower
spaces keep the same ``knowledgefile`` id but become ``entry_type=publish``
soft links. Same-level duplicates are left untouched. A department original may
only claim team/clinic copies bound to that department or its org descendants.
Empty MD5 values fall back to ``file_name + file_size``. Unique historical
versions in a lower document stay in that space and are listed for manual review.

Default mode is a read-only dry-run that writes JSON and Markdown reports. Pass ``--apply``
only after reviewing that report. The command supports single-tenant
deployments only.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py
    PYTHONPATH=./ .venv/bin/python scripts/relink_duplicate_space_files_as_publish.py \\
      --space-id 10 --limit 20 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlmodel import col, select

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
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeDao,
    KnowledgeState,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.database.models.department import Department  # noqa: E402
from bisheng.knowledge.domain.models.department_knowledge_space import (  # noqa: E402
    DepartmentKnowledgeSpace,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_repository_impl import (  # noqa: E402
    KnowledgeDocumentRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_document_version_repository_impl import (  # noqa: E402
    KnowledgeDocumentVersionRepositoryImpl,
)
from bisheng.knowledge.domain.repositories.implementations.knowledge_file_repository_impl import (  # noqa: E402
    KnowledgeFileRepositoryImpl,
)
from bisheng.knowledge.domain.services.knowledge_document_distribution_service import (  # noqa: E402
    AttachExistingAsPublishCommand,
    KnowledgeDocumentDistributionError,
    KnowledgeDocumentDistributionService,
)
from bisheng.knowledge.domain.services.knowledge_document_permission_activation_service import (  # noqa: E402
    KnowledgeDocumentPermissionActivationService,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_SCAN_ERROR = 3
EXIT_APPLY_ERROR = 4
EXIT_REPORT_ERROR = 5
REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_REPORT_DIR = Path("migration_reports/knowledge_file_relink")
DEFAULT_TENANT_ID = 1
FILE_TYPE_FILE = FileType.FILE.value
FILE_TYPE_DIR = FileType.DIR.value
FILE_STATUS_SUCCESS = KnowledgeFileStatus.SUCCESS.value
ROOT_DIRECTORY_LABEL = "根目录"
LOGICAL_ENTRY_TYPES = frozenset(
    {
        KnowledgeFileEntryType.PUBLISH.value,
        KnowledgeFileEntryType.SHARE.value,
        KnowledgeFileEntryType.PROJECTION_TOMBSTONE.value,
    }
)
SPACE_LEVEL_RANK: dict[str, int] = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: 0,
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: 1,
    KnowledgeSpaceLevelEnum.TEAM.value: 2,
    KnowledgeSpaceLevelEnum.TEAM_KS.value: 2,
    KnowledgeSpaceLevelEnum.PERSONAL.value: 3,
}
TEAM_LIKE_LEVELS = frozenset(
    {
        KnowledgeSpaceLevelEnum.TEAM.value,
        KnowledgeSpaceLevelEnum.TEAM_KS.value,
    }
)


class PreflightError(RuntimeError):
    """Raised when safety validation must stop before any business write."""


class ReportWriteError(RuntimeError):
    """Raised when the audit checkpoint cannot be persisted safely."""


class SkipRelinkUnit(Exception):
    """Raised when one unit must be skipped without aborting the apply run."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        super().__init__(detail or reason_code)


SOURCE_HAS_DISTRIBUTION_DEPENDENTS_ERROR = "source manager has distribution dependents"
SOURCE_HAS_DISTRIBUTION_DEPENDENTS_REASON = "source_has_distribution_dependents"


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


@dataclass(frozen=True)
class SpaceSnapshot:
    space_id: int
    level: str
    name: str = ""
    department_id: int | None = None
    department_path: str = ""


@dataclass(frozen=True)
class StorageObjectSnapshot:
    kind: str
    name: str


@dataclass(frozen=True)
class FileSnapshot:
    file_id: int
    space_id: int
    file_name: str
    file_size: int
    md5: str | None
    status: int
    file_type: int
    entry_type: str | None
    create_time: str | None = None
    file_level_path: str = ""
    storage_objects: tuple[StorageObjectSnapshot, ...] = ()


@dataclass(frozen=True)
class FileDisplay:
    file_id: int
    file_name: str = ""
    space_id: int = 0
    space_name: str = ""
    space_level: str = ""
    directory: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "file_name": self.file_name,
            "space_id": self.space_id,
            "space_name": self.space_name,
            "space_level": self.space_level,
            "directory": self.directory,
        }


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
    versions: tuple[VersionSnapshot, ...] = ()


@dataclass(frozen=True)
class RelinkUnit:
    match_kind: str
    match_key: str
    origin_file_id: int
    origin_space_id: int
    origin_level: str
    source_file_id: int
    source_space_id: int
    source_level: str
    origin_file_name: str = ""
    origin_space_name: str = ""
    origin_directory: str = ""
    origin_department_id: int | None = None
    source_file_name: str = ""
    source_space_name: str = ""
    source_directory: str = ""
    source_department_id: int | None = None
    history_file_ids: tuple[int, ...] = ()
    kept_same_level_file_ids: tuple[int, ...] = ()
    history_files: tuple[FileDisplay, ...] = ()
    kept_same_level_files: tuple[FileDisplay, ...] = ()
    storage_objects: tuple[StorageObjectSnapshot, ...] = ()


@dataclass(frozen=True)
class SkippedItem:
    reason_code: str
    detail: str
    file_ids: tuple[int, ...] = ()
    match_key: str = ""
    files: tuple[FileDisplay, ...] = ()


@dataclass(frozen=True)
class RelinkPlan:
    tenant_id: int
    units: tuple[RelinkUnit, ...]
    skipped: tuple[SkippedItem, ...]
    unmatched_count: int


@dataclass(frozen=True)
class RevalidationResult:
    valid: bool
    unit: RelinkUnit | None = None
    reason_code: str = ""


class PlanReader(Protocol):
    async def build_plan(self, args: argparse.Namespace) -> RelinkPlan: ...

    async def revalidate(self, unit: RelinkUnit) -> RevalidationResult: ...


class RelinkOperations(Protocol):
    async def attach(self, unit: RelinkUnit) -> dict[str, Any]: ...

    async def delete_vectors(self, unit: RelinkUnit) -> None: ...

    async def delete_minio(self, unit: RelinkUnit) -> None: ...

    async def enqueue_projection(self, unit: RelinkUnit, *, manager_file_id: int) -> None: ...

    async def verify_linked(self, unit: RelinkUnit) -> dict[str, Any]: ...


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Convert strictly lower-level duplicate knowledge-space files into publish soft links."),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform conversion; default is read-only dry-run",
    )
    parser.add_argument(
        "--space-id",
        dest="space_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="limit scanning to these knowledge-space ids; repeatable",
    )
    parser.add_argument(
        "--file-id",
        dest="file_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="only convert these lower-space file ids; repeatable",
    )
    parser.add_argument(
        "--md5",
        dest="md5s",
        action="append",
        default=[],
        help="only groups whose MD5 match key equals this value; repeatable",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="convert at most N units after stable sort",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help=f"directory for JSON audit reports (default: {DEFAULT_REPORT_DIR})",
    )
    parser.add_argument(
        "--resume-report",
        type=Path,
        default=None,
        help="resume unfinished units from a previous apply report",
    )
    args = parser.parse_args(argv)
    if args.resume_report is not None and (args.space_ids or args.file_ids or args.md5s or args.limit is not None):
        parser.error("--resume-report cannot be combined with target range options")
    return args


def ensure_single_tenant(multi_tenant_enabled: bool) -> int:
    if multi_tenant_enabled:
        raise PreflightError("multi-tenant mode is enabled; this script only supports single-tenant deployments")
    return DEFAULT_TENANT_ID


def match_key_for_file(file: FileSnapshot) -> tuple[str, str] | None:
    """Return ``(kind, key)`` for grouping, or None when the file cannot be matched."""
    md5 = str(file.md5 or "").strip()
    if md5:
        return ("md5", md5)
    name = str(file.file_name or "").strip()
    size = int(file.file_size or 0)
    if name and size > 0:
        return ("name_size", f"{name}\0{size}")
    return None


def resolve_directory(file_level_path: str | None, folders_by_id: dict[int, str]) -> str:
    """Turn ``file_level_path`` ids into a human-readable folder path."""
    folder_ids = [int(part) for part in str(file_level_path or "").split("/") if part.isdigit()]
    if not folder_ids:
        return ROOT_DIRECTORY_LABEL
    parts: list[str] = []
    for folder_id in folder_ids:
        name = str(folders_by_id.get(folder_id) or "").strip()
        parts.append(name if name else str(folder_id))
    return "/" + "/".join(parts)


def space_level_rank(level: str) -> int | None:
    return SPACE_LEVEL_RANK.get(str(level or ""))


def parse_department_path_ids(path: str | None, department_id: int | None = None) -> tuple[int, ...]:
    ids = [int(part) for part in str(path or "").split("/") if part.isdigit()]
    if department_id is not None and int(department_id) not in ids:
        ids.append(int(department_id))
    return tuple(ids)


def department_depth(space: SpaceSnapshot) -> int:
    return len(parse_department_path_ids(space.department_path, space.department_id))


def is_department_subtree(origin: SpaceSnapshot, source: SpaceSnapshot) -> bool:
    """Return True when ``source`` is bound to ``origin``'s department or a descendant."""
    origin_dept = origin.department_id
    source_dept = source.department_id
    if origin_dept is None or source_dept is None:
        return False
    if int(origin_dept) == int(source_dept):
        return True
    return int(origin_dept) in parse_department_path_ids(source.department_path, source_dept)


def origin_can_claim(origin: SpaceSnapshot, source: SpaceSnapshot) -> bool:
    """Whether a higher-level space may be the physical original for ``source``.

    Department originals may only claim team/clinic spaces in the same org
    subtree. Public originals stay tenant-wide. Personal copies are not
    org-scoped.
    """
    origin_rank = space_level_rank(origin.level)
    source_rank = space_level_rank(source.level)
    if origin_rank is None or source_rank is None or origin_rank >= source_rank:
        return False
    if origin.level == KnowledgeSpaceLevelEnum.DEPARTMENT.value and source.level in TEAM_LIKE_LEVELS:
        return is_department_subtree(origin, source)
    return True


def _is_current_primary(
    file: FileSnapshot,
    versions_by_file: dict[int, tuple[VersionSnapshot, ...]],
) -> bool:
    versions = versions_by_file.get(file.file_id, ())
    if not versions:
        return True
    return any(item.is_primary for item in versions)


def _history_file_ids(
    file: FileSnapshot,
    versions_by_file: dict[int, tuple[VersionSnapshot, ...]],
    versions_by_document: dict[int, tuple[VersionSnapshot, ...]],
) -> tuple[int, ...]:
    versions = versions_by_file.get(file.file_id, ())
    if not versions:
        return ()
    document_id = versions[0].document_id
    return tuple(
        sorted(
            {
                int(item.file_id)
                for item in versions_by_document.get(document_id, ())
                if int(item.file_id) != int(file.file_id)
            }
        )
    )


def _origin_sort_key(file: FileSnapshot) -> tuple[str, int]:
    return (str(file.create_time or ""), int(file.file_id))


def build_relink_plan(
    inventory: Inventory,
    *,
    tenant_id: int = DEFAULT_TENANT_ID,
    space_ids: Sequence[int] | None = None,
    file_ids: Sequence[int] | None = None,
    md5s: Sequence[str] | None = None,
    limit: int | None = None,
) -> RelinkPlan:
    space_by_id = {item.space_id: item for item in inventory.spaces}
    files_by_id = {item.file_id: item for item in inventory.files}
    folders_by_id = {
        item.file_id: str(item.file_name or "")
        for item in inventory.files
        if int(item.file_type) == FILE_TYPE_DIR
    }
    for item in inventory.files:
        folders_by_id.setdefault(item.file_id, str(item.file_name or ""))

    def _display_for(file: FileSnapshot) -> FileDisplay:
        space = space_by_id.get(file.space_id)
        return FileDisplay(
            file_id=file.file_id,
            file_name=str(file.file_name or ""),
            space_id=file.space_id,
            space_name=str(space.name or "") if space else "",
            space_level=str(space.level or "") if space else "",
            directory=resolve_directory(file.file_level_path, folders_by_id),
        )

    def _display_for_id(file_id: int) -> FileDisplay:
        file = files_by_id.get(int(file_id))
        if file is None:
            return FileDisplay(file_id=int(file_id), directory=ROOT_DIRECTORY_LABEL)
        return _display_for(file)

    versions_by_file: dict[int, list[VersionSnapshot]] = {}
    versions_by_document: dict[int, list[VersionSnapshot]] = {}
    for version in inventory.versions:
        versions_by_file.setdefault(version.file_id, []).append(version)
        versions_by_document.setdefault(version.document_id, []).append(version)
    versions_by_file_t = {key: tuple(value) for key, value in versions_by_file.items()}
    versions_by_document_t = {key: tuple(value) for key, value in versions_by_document.items()}

    allowed_spaces = {int(item) for item in space_ids or []}
    allowed_files = {int(item) for item in file_ids or []}
    allowed_md5s = {str(item).strip() for item in md5s or [] if str(item).strip()}

    skipped: list[SkippedItem] = []
    unmatched_count = 0
    grouped: dict[tuple[str, str], list[FileSnapshot]] = {}
    for file in inventory.files:
        space = space_by_id.get(file.space_id)
        if space is None or space_level_rank(space.level) is None:
            skipped.append(
                SkippedItem(
                    reason_code="unknown_space_level",
                    detail="file is not in a ranked knowledge space",
                    file_ids=(file.file_id,),
                    files=(_display_for(file),),
                )
            )
            continue
        if file.file_type != FILE_TYPE_FILE or file.status != FILE_STATUS_SUCCESS:
            continue
        if file.entry_type in LOGICAL_ENTRY_TYPES:
            continue
        if not _is_current_primary(file, versions_by_file_t):
            continue
        key = match_key_for_file(file)
        if key is None:
            unmatched_count += 1
            skipped.append(
                SkippedItem(
                    reason_code="blank_match_key",
                    detail="file has empty MD5 and no usable file_name+file_size fallback",
                    file_ids=(file.file_id,),
                    files=(_display_for(file),),
                )
            )
            continue
        grouped.setdefault(key, []).append(file)

    units: list[RelinkUnit] = []
    for (kind, key), members in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        if allowed_md5s and not (kind == "md5" and key in allowed_md5s):
            continue
        unique_by_space: dict[int, FileSnapshot] = {}
        same_space_extra_files: list[FileSnapshot] = []
        for file in sorted(members, key=_origin_sort_key):
            existing = unique_by_space.get(file.space_id)
            if existing is None:
                unique_by_space[file.space_id] = file
            else:
                same_space_extra_files.append(file)
        if same_space_extra_files:
            extra_files = tuple(sorted(same_space_extra_files, key=lambda item: item.file_id))
            skipped.append(
                SkippedItem(
                    reason_code="same_space_duplicate",
                    detail="multiple current primaries in the same space share this match key; extras are ignored",
                    file_ids=tuple(item.file_id for item in extra_files),
                    match_key=key,
                    files=tuple(_display_for(item) for item in extra_files),
                )
            )
        ranked: list[tuple[int, FileSnapshot, SpaceSnapshot]] = []
        for file in unique_by_space.values():
            space = space_by_id[file.space_id]
            rank = space_level_rank(space.level)
            if rank is None:
                continue
            ranked.append((rank, file, space))
        if len(ranked) < 2:
            continue
        min_rank = min(item[0] for item in ranked)
        if all(item[0] == min_rank for item in ranked):
            skipped.append(
                SkippedItem(
                    reason_code="same_level_only",
                    detail="matching files exist only at the same space level",
                    file_ids=tuple(sorted(int(item[1].file_id) for item in ranked)),
                    match_key=key,
                    files=tuple(_display_for(item[1]) for item in sorted(ranked, key=lambda item: item[1].file_id)),
                )
            )
            continue
        ranked.sort(key=lambda item: (item[0], int(item[1].file_id)))
        for source_rank, source_file, source_space in ranked:
            if source_rank == min_rank:
                continue
            higher = [item for item in ranked if item[0] < source_rank]
            candidates = [item for item in higher if origin_can_claim(item[2], source_space)]
            if not candidates:
                if higher and source_space.level in TEAM_LIKE_LEVELS:
                    skipped.append(
                        SkippedItem(
                            reason_code="not_department_subordinate",
                            detail=(
                                "team/clinic copy is not under the department that owns "
                                "the higher-level original"
                            ),
                            file_ids=(source_file.file_id,),
                            match_key=key,
                            files=(_display_for(source_file),),
                        )
                    )
                continue
            candidates.sort(
                key=lambda item: (
                    item[0],
                    -department_depth(item[2]),
                    *_origin_sort_key(item[1]),
                )
            )
            origin_rank, origin_file, origin_space = candidates[0]
            if (
                allowed_spaces
                and origin_file.space_id not in allowed_spaces
                and source_file.space_id not in allowed_spaces
            ):
                continue
            if allowed_files and source_file.file_id not in allowed_files:
                continue
            kept_same_level = tuple(
                sorted(
                    int(item[1].file_id)
                    for item in ranked
                    if item[0] == origin_rank and int(item[1].file_id) != origin_file.file_id
                )
            )
            origin_display = _display_for(origin_file)
            source_display = _display_for(source_file)
            history_ids = _history_file_ids(
                source_file,
                versions_by_file_t,
                versions_by_document_t,
            )
            units.append(
                RelinkUnit(
                    match_kind=kind,
                    match_key=key,
                    origin_file_id=origin_file.file_id,
                    origin_space_id=origin_file.space_id,
                    origin_level=origin_space.level,
                    source_file_id=source_file.file_id,
                    source_space_id=source_file.space_id,
                    source_level=source_space.level,
                    origin_file_name=origin_display.file_name,
                    origin_space_name=origin_display.space_name,
                    origin_directory=origin_display.directory,
                    origin_department_id=origin_space.department_id,
                    source_file_name=source_display.file_name,
                    source_space_name=source_display.space_name,
                    source_directory=source_display.directory,
                    source_department_id=source_space.department_id,
                    history_file_ids=history_ids,
                    kept_same_level_file_ids=kept_same_level,
                    history_files=tuple(_display_for_id(file_id) for file_id in history_ids),
                    kept_same_level_files=tuple(_display_for_id(file_id) for file_id in kept_same_level),
                    storage_objects=source_file.storage_objects,
                )
            )

    units.sort(key=lambda item: (item.origin_file_id, item.source_file_id))
    if limit is not None:
        units = units[: int(limit)]
    return RelinkPlan(
        tenant_id=tenant_id,
        units=tuple(units),
        skipped=tuple(skipped),
        unmatched_count=unmatched_count,
    )


def _file_display_from_raw(raw: Any) -> FileDisplay:
    if isinstance(raw, FileDisplay):
        return raw
    if isinstance(raw, dict):
        return FileDisplay(
            file_id=int(raw.get("file_id") or 0),
            file_name=str(raw.get("file_name") or ""),
            space_id=int(raw.get("space_id") or 0),
            space_name=str(raw.get("space_name") or ""),
            space_level=str(raw.get("space_level") or ""),
            directory=str(raw.get("directory") or ""),
        )
    try:
        return FileDisplay(file_id=int(raw))
    except (TypeError, ValueError):
        return FileDisplay(file_id=0)


def _unit_to_dict(unit: RelinkUnit) -> dict[str, Any]:
    return {
        "match_kind": unit.match_kind,
        "match_key": unit.match_key,
        "origin_file_id": unit.origin_file_id,
        "origin_space_id": unit.origin_space_id,
        "origin_level": unit.origin_level,
        "origin_file_name": unit.origin_file_name,
        "origin_space_name": unit.origin_space_name,
        "origin_directory": unit.origin_directory,
        "origin_department_id": unit.origin_department_id,
        "source_file_id": unit.source_file_id,
        "source_space_id": unit.source_space_id,
        "source_level": unit.source_level,
        "source_file_name": unit.source_file_name,
        "source_space_name": unit.source_space_name,
        "source_directory": unit.source_directory,
        "source_department_id": unit.source_department_id,
        "history_file_ids": list(unit.history_file_ids),
        "kept_same_level_file_ids": list(unit.kept_same_level_file_ids),
        "history_files": [item.as_dict() for item in unit.history_files],
        "kept_same_level_files": [item.as_dict() for item in unit.kept_same_level_files],
        "storage_objects": [{"kind": item.kind, "name": item.name} for item in unit.storage_objects],
    }


def _unit_from_dict(raw: Any) -> RelinkUnit:
    if not isinstance(raw, dict):
        raise PreflightError("resume report unit payload is invalid")
    objects = tuple(
        StorageObjectSnapshot(kind=str(item.get("kind") or ""), name=str(item.get("name") or ""))
        for item in (raw.get("storage_objects") or [])
        if isinstance(item, dict)
    )
    return RelinkUnit(
        match_kind=str(raw.get("match_kind") or ""),
        match_key=str(raw.get("match_key") or ""),
        origin_file_id=int(raw["origin_file_id"]),
        origin_space_id=int(raw["origin_space_id"]),
        origin_level=str(raw.get("origin_level") or ""),
        source_file_id=int(raw["source_file_id"]),
        source_space_id=int(raw["source_space_id"]),
        source_level=str(raw.get("source_level") or ""),
        origin_file_name=str(raw.get("origin_file_name") or ""),
        origin_space_name=str(raw.get("origin_space_name") or ""),
        origin_directory=str(raw.get("origin_directory") or ""),
        origin_department_id=_optional_int(raw.get("origin_department_id")),
        source_file_name=str(raw.get("source_file_name") or ""),
        source_space_name=str(raw.get("source_space_name") or ""),
        source_directory=str(raw.get("source_directory") or ""),
        source_department_id=_optional_int(raw.get("source_department_id")),
        history_file_ids=tuple(int(item) for item in (raw.get("history_file_ids") or [])),
        kept_same_level_file_ids=tuple(int(item) for item in (raw.get("kept_same_level_file_ids") or [])),
        history_files=tuple(_file_display_from_raw(item) for item in (raw.get("history_files") or [])),
        kept_same_level_files=tuple(_file_display_from_raw(item) for item in (raw.get("kept_same_level_files") or [])),
        storage_objects=objects,
    )


def _refresh_summary(report: dict[str, Any]) -> None:
    units = list(report.get("units") or [])
    skipped = list(report.get("skipped") or [])
    counts = {
        "planned": 0,
        "pending": 0,
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "history_files": 0,
    }
    for entry in units:
        status = str(entry.get("status") or "planned")
        if status not in counts:
            status = "pending"
        counts[status] = counts.get(status, 0) + 1
        unit = entry.get("unit") or {}
        counts["history_files"] += len(unit.get("history_file_ids") or [])
    counts["skipped"] += len(skipped)
    report["summary"] = counts


LEVEL_LABELS = {
    "public": "公共",
    "department": "部门",
    "team": "团队",
    "team_ks": "科室",
    "personal": "个人",
}
SKIP_LABELS = {
    "same_level_only": "同级不转",
    "same_space_duplicate": "同库多份当前主版本",
    "blank_match_key": "无 MD5 且无法用文件名+大小匹配",
    "unknown_space_level": "未知库级",
    "not_department_subordinate": "非本部门下属科室/团队库",
    "plan_drift": "写入前数据已变化",
    SOURCE_HAS_DISTRIBUTION_DEPENDENTS_REASON: "下级已是有下游的 manager",
}
STATUS_LABELS = {
    "planned": "待执行",
    "pending": "待执行",
    "completed": "已完成",
    "skipped": "已跳过",
    "failed": "失败",
}
MATCH_KIND_LABELS = {
    "md5": "精确 MD5",
    "name_size": "文件名+大小",
}


def _level_label(level: Any) -> str:
    value = str(level or "")
    return LEVEL_LABELS.get(value, value or "-")


def _md_cell(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")


def _join_ids(values: Any) -> str:
    if not values:
        return "-"
    return ", ".join(str(int(item)) for item in values)


def _directory_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"/", ROOT_DIRECTORY_LABEL}:
        return ROOT_DIRECTORY_LABEL
    return _md_cell(text)


def _space_cell(name: Any, level: Any, space_id: Any) -> str:
    label = str(name or "").strip()
    level_text = _level_label(level)
    space_text = "" if space_id in (None, "", 0) else str(space_id)
    if label and space_text:
        return f"{_md_cell(label)}（{level_text}，{space_text}）"
    if label:
        return f"{_md_cell(label)}（{level_text}）"
    if space_text:
        return f"空间 {space_text}（{level_text}）"
    return level_text or "-"


def _file_name_cell(unit: dict[str, Any]) -> str:
    origin_name = str(unit.get("origin_file_name") or "").strip()
    source_name = str(unit.get("source_file_name") or "").strip()
    if origin_name and source_name and origin_name != source_name:
        return f"{_md_cell(origin_name)} → {_md_cell(source_name)}"
    return _md_cell(origin_name or source_name or "-")


def _named_file_list(items: Any, fallback_ids: Any = None) -> str:
    rows = [item for item in (items or []) if isinstance(item, dict)]
    if rows:
        parts: list[str] = []
        for item in rows:
            file_id = item.get("file_id")
            name = str(item.get("file_name") or "").strip()
            directory = _directory_label(item.get("directory"))
            label = _md_cell(name) if name else _md_cell(file_id)
            extra = "" if directory == ROOT_DIRECTORY_LABEL else f"，{directory}"
            parts.append(f"{label} (`{file_id}`{extra})")
        return ", ".join(parts)
    return _join_ids(fallback_ids)


def _skipped_file_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    files = [file for file in (item.get("files") or []) if isinstance(file, dict)]
    if files:
        return files
    file_ids = list(item.get("file_ids") or [])
    if file_ids:
        return [{"file_id": file_id} for file_id in file_ids]
    return [{}]


def _report_aggregates(report: dict[str, Any]) -> dict[str, Any]:
    skipped = list(report.get("skipped") or [])
    units = list(report.get("units") or [])
    skip_counts: dict[str, int] = {}
    for item in skipped:
        reason = str(item.get("reason_code") or "unknown")
        skip_counts[reason] = skip_counts.get(reason, 0) + 1
    level_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    history_rows: list[dict[str, Any]] = []
    for entry in units:
        if str(entry.get("status") or "") == "skipped":
            reason = str(entry.get("reason_code") or "unknown")
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
        unit = entry.get("unit") or {}
        origin_level = str(unit.get("origin_level") or "")
        source_level = str(unit.get("source_level") or "")
        pair = f"{origin_level}->{source_level}"
        level_counts[pair] = level_counts.get(pair, 0) + 1
        kind = str(unit.get("match_kind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        history_ids = list(unit.get("history_file_ids") or [])
        history_files = list(unit.get("history_files") or [])
        if history_ids or history_files:
            history_rows.append(
                {
                    "source_file_id": unit.get("source_file_id"),
                    "source_file_name": unit.get("source_file_name"),
                    "source_space_id": unit.get("source_space_id"),
                    "source_space_name": unit.get("source_space_name"),
                    "source_level": source_level,
                    "source_directory": unit.get("source_directory"),
                    "history_file_ids": history_ids,
                    "history_files": history_files,
                }
            )
    return {
        "skip_counts": skip_counts,
        "level_counts": level_counts,
        "kind_counts": kind_counts,
        "history_rows": history_rows,
        "skipped": skipped,
        "units": units,
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    """Render a human-readable Markdown audit report from the JSON payload."""
    summary = report.get("summary") or {}
    aggregates = _report_aggregates(report)
    arguments = report.get("arguments") or {}
    lines = [
        "# 跨库重复文件软链接报告",
        "",
        f"- 运行 ID：`{report.get('run_id') or '-'}`",
        f"- 模式：`{report.get('mode') or '-'}`",
        f"- 租户：`{report.get('tenant_id') if report.get('tenant_id') is not None else '-'}`",
        f"- 开始时间：{report.get('started_at') or '-'}",
        f"- 结束时间：{report.get('finished_at') or '-'}",
        f"- 更新时间：{report.get('updated_at') or '-'}",
        "",
        "## 汇总",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| 待转换 / 计划 | {int(summary.get('planned') or 0)} |",
        f"| 已完成 | {int(summary.get('completed') or 0)} |",
        f"| 已跳过 | {int(summary.get('skipped') or 0)} |",
        f"| 失败 | {int(summary.get('failed') or 0)} |",
        f"| 待处理 | {int(summary.get('pending') or 0)} |",
        f"| 下级历史版本（人工处理） | {int(summary.get('history_files') or 0)} |",
        f"| 无匹配键 | {int(report.get('unmatched_count') or 0)} |",
        "",
    ]
    if arguments:
        lines.extend(
            [
                "## 运行参数",
                "",
                "| 参数 | 值 |",
                "| --- | --- |",
            ]
        )
        for key in sorted(arguments):
            lines.append(f"| `{_md_cell(key)}` | `{_md_cell(arguments[key])}` |")
        lines.append("")

    kind_counts = aggregates["kind_counts"]
    if kind_counts:
        lines.extend(["## 匹配方式", "", "| 方式 | 数量 |", "| --- | ---: |"])
        for kind, count in sorted(kind_counts.items()):
            lines.append(f"| {MATCH_KIND_LABELS.get(kind, kind)} | {count} |")
        lines.append("")

    level_counts = aggregates["level_counts"]
    if level_counts:
        lines.extend(["## 按库级分布", "", "| 原文件库 | 软链库 | 数量 |", "| --- | --- | ---: |"])
        for pair, count in sorted(level_counts.items(), key=lambda item: (-item[1], item[0])):
            origin_level, _, source_level = pair.partition("->")
            lines.append(
                f"| {_level_label(origin_level)} | {_level_label(source_level)} | {count} |"
            )
        lines.append("")

    skip_counts = aggregates["skip_counts"]
    if skip_counts:
        lines.extend(["## 跳过原因", "", "| 原因 | 数量 |", "| --- | ---: |"])
        for reason, count in sorted(skip_counts.items()):
            lines.append(f"| {SKIP_LABELS.get(reason, reason)} | {count} |")
        lines.append("")

    history_rows = aggregates["history_rows"]
    if history_rows:
        lines.extend(
            [
                "## 下级历史版本（仅当前主版本转软链，历史需人工处理）",
                "",
                "| 当前主版本 | 文件名 | 库 | 目录 | 历史文件 |",
                "| ---: | --- | --- | --- | --- |",
            ]
        )
        for row in history_rows:
            lines.append(
                "| "
                f"{_md_cell(row['source_file_id'])} | "
                f"{_md_cell(row.get('source_file_name') or '-')} | "
                f"{_space_cell(row.get('source_space_name'), row.get('source_level'), row.get('source_space_id'))} | "
                f"{_directory_label(row.get('source_directory'))} | "
                f"{_named_file_list(row.get('history_files'), row.get('history_file_ids'))} |"
            )
        lines.append("")

    units = aggregates["units"]
    lines.extend(
        [
            "## 转换明细",
            "",
            "| 状态 | 匹配 | 文件名 | 原库 | 原目录 | 软链库 | 软链目录 | 原文件 ID | 软链文件 ID | 同级保留 | 历史版本 |",
            "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    if not units:
        lines.extend(["| - | - | - | - | - | - | - | - | - | - | - |", ""])
    else:
        for entry in units:
            unit = entry.get("unit") or {}
            status_raw = str(entry.get("status") or "")
            status = STATUS_LABELS.get(status_raw, status_raw or "-")
            reason_code = str(entry.get("reason_code") or "")
            if reason_code and status_raw in {"skipped", "failed"}:
                status = f"{status}（{SKIP_LABELS.get(reason_code, reason_code)}）"
            match_kind = MATCH_KIND_LABELS.get(str(unit.get("match_kind") or ""), str(unit.get("match_kind") or "-"))
            lines.append(
                "| "
                f"{_md_cell(status)} | "
                f"{_md_cell(match_kind)} | "
                f"{_file_name_cell(unit)} | "
                f"{_space_cell(unit.get('origin_space_name'), unit.get('origin_level'), unit.get('origin_space_id'))} | "
                f"{_directory_label(unit.get('origin_directory'))} | "
                f"{_space_cell(unit.get('source_space_name'), unit.get('source_level'), unit.get('source_space_id'))} | "
                f"{_directory_label(unit.get('source_directory'))} | "
                f"{_md_cell(unit.get('origin_file_id'))} | "
                f"{_md_cell(unit.get('source_file_id'))} | "
                f"{_named_file_list(unit.get('kept_same_level_files'), unit.get('kept_same_level_file_ids'))} | "
                f"{_named_file_list(unit.get('history_files'), unit.get('history_file_ids'))} |"
            )
        lines.append("")

    skipped = aggregates["skipped"]
    if skipped:
        lines.extend(
            [
                "## 跳过明细",
                "",
                "| 原因 | 文件名 | 库 | 目录 | 文件 ID | 说明 |",
                "| --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for item in skipped:
            reason = str(item.get("reason_code") or "")
            for file in _skipped_file_rows(item):
                lines.append(
                    "| "
                    f"{SKIP_LABELS.get(reason, reason)} | "
                    f"{_md_cell(file.get('file_name') or '-')} | "
                    f"{_space_cell(file.get('space_name'), file.get('space_level'), file.get('space_id'))} | "
                    f"{_directory_label(file.get('directory'))} | "
                    f"{_md_cell(file.get('file_id') or _join_ids(item.get('file_ids')))} | "
                    f"{_md_cell(item.get('detail'))} |"
                )
        lines.append("")

    error_type = report.get("error_type")
    if error_type:
        lines.extend(["## 错误", "", f"- 类型：`{_md_cell(error_type)}`", ""])
    return "\n".join(lines).rstrip() + "\n"


def make_run_report(
    plan: RelinkPlan,
    *,
    mode: str,
    run_id: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": mode,
        "run_id": run_id,
        "tenant_id": plan.tenant_id,
        "arguments": arguments,
        "unmatched_count": plan.unmatched_count,
        "skipped": [
            {
                "reason_code": item.reason_code,
                "detail": item.detail,
                "file_ids": list(item.file_ids),
                "match_key": item.match_key,
                "files": [file.as_dict() for file in item.files],
            }
            for item in plan.skipped
        ],
        "units": [
            {
                "status": "planned" if mode == "dry-run" else "pending",
                "reason_code": "",
                "error_type": "",
                "steps": [],
                "verification": {},
                "result": {},
                "unit": _unit_to_dict(unit),
            }
            for unit in plan.units
        ],
        "started_at": _utc_now(),
        "updated_at": None,
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
            entry["result"] = {}
    _refresh_summary(report)
    return report


class ReportStore:
    def __init__(self, report_dir: Path, run_id: str) -> None:
        self.report_dir = Path(report_dir)
        self.path = self.report_dir / f"relink-{run_id}.json"
        self.markdown_path = self.report_dir / f"relink-{run_id}.md"

    def _atomic_write(self, path: Path, text: str) -> None:
        temporary = self.report_dir / f".{path.name}.{uuid.uuid4().hex}.tmp"
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(text)
                if not text.endswith("\n"):
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                logger.warning(
                    "temporary report cleanup failed path=%s error_type=%s",
                    temporary,
                    type(cleanup_exc).__name__,
                )
            raise ReportWriteError("unable to persist the audit report") from exc

    def write(self, payload: dict[str, Any]) -> Path:
        payload["updated_at"] = _utc_now()
        _refresh_summary(payload)
        self._atomic_write(
            self.path,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        )
        self._atomic_write(self.markdown_path, render_markdown_report(payload))
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
        _unit_from_dict(entry.get("unit"))
    return payload


def _arguments_for_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "apply": bool(args.apply),
        "space_ids": list(args.space_ids or []),
        "file_ids": list(args.file_ids or []),
        "md5s": list(args.md5s or []),
        "limit": args.limit,
        "report_dir": str(args.report_dir),
        "resume_report": str(args.resume_report) if args.resume_report else None,
    }


def _step_record(entry: dict[str, Any], name: str) -> dict[str, Any]:
    step = {"name": name, "status": "running", "started_at": _utc_now()}
    entry.setdefault("steps", []).append(step)
    return step


class ApplyExecutor:
    def __init__(
        self,
        reader: PlanReader,
        operations: RelinkOperations,
        checkpoint: Callable[[], None],
    ) -> None:
        self.reader = reader
        self.operations = operations
        self.checkpoint = checkpoint

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
        except SkipRelinkUnit:
            step["status"] = "skipped"
            step["finished_at"] = _utc_now()
            raise
        except Exception as exc:
            step["status"] = "failed"
            step["error_type"] = type(exc).__name__
            step["finished_at"] = _utc_now()
            entry["status"] = "failed"
            entry["error_type"] = type(exc).__name__
            raise
        step["status"] = "completed"
        step["finished_at"] = _utc_now()
        return result

    async def run(self, report: dict[str, Any]) -> bool:
        entries = list(report.get("units") or [])
        for index, entry in enumerate(entries):
            if entry.get("status") in {"completed", "skipped"}:
                continue
            unit = _unit_from_dict(entry.get("unit"))
            try:
                revalidation = await self._run_step(
                    entry,
                    "revalidate",
                    lambda current=unit: self.reader.revalidate(current),
                )
                if not revalidation.valid:
                    entry["status"] = "skipped"
                    entry["reason_code"] = revalidation.reason_code
                    self.checkpoint()
                    continue
                current = revalidation.unit or unit
                result = await self._run_step(
                    entry,
                    "attach",
                    lambda current=current: self.operations.attach(current),
                )
                entry["result"] = result
                await self._run_step(
                    entry,
                    "delete_vectors",
                    lambda current=current: self.operations.delete_vectors(current),
                )
                await self._run_step(
                    entry,
                    "delete_minio",
                    lambda current=current: self.operations.delete_minio(current),
                )
                await self._run_step(
                    entry,
                    "enqueue_projection",
                    lambda current=current, result=result: self.operations.enqueue_projection(
                        current,
                        manager_file_id=int(result.get("manager_file_id") or current.origin_file_id),
                    ),
                )
                verification = await self._run_step(
                    entry,
                    "verify",
                    lambda current=current: self.operations.verify_linked(current),
                )
                entry["verification"] = verification
                entry["status"] = "completed"
                if current.history_file_ids:
                    entry["reason_code"] = "history_retained"
            except ReportWriteError:
                raise
            except SkipRelinkUnit as exc:
                entry["status"] = "skipped"
                entry["reason_code"] = exc.reason_code
                entry["error_type"] = ""
                self.checkpoint()
                continue
            except Exception:
                for remaining in entries[index + 1 :]:
                    if remaining.get("status") in {"planned", "pending"}:
                        remaining["status"] = "pending"
                self.checkpoint()
                return False
            self.checkpoint()
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
    create_time = model.create_time.isoformat() if model.create_time is not None else None
    return FileSnapshot(
        file_id=file_id,
        space_id=int(model.knowledge_id),
        file_name=str(model.file_name or ""),
        file_size=int(model.file_size or 0),
        md5=model.md5,
        status=int(model.status or 0),
        file_type=int(model.file_type),
        entry_type=model.entry_type,
        create_time=create_time,
        file_level_path=str(model.file_level_path or ""),
        storage_objects=tuple(storage_objects),
    )


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
                        col(KnowledgeFile.deleted_at).is_(None),
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


class BishengPlanReader:
    def __init__(self, tenant_id: int) -> None:
        self.tenant_id = int(tenant_id)

    async def _load_inventory(self, args: argparse.Namespace) -> Inventory:
        async with get_async_db_session() as session:
            scopes = list((await session.exec(select(KnowledgeSpaceScope))).all())
            space_ids = sorted({int(item.space_id) for item in scopes})
            spaces: list[Knowledge] = []
            for batch in _chunks(space_ids):
                spaces.extend(
                    list(
                        (
                            await session.exec(
                                select(Knowledge).where(
                                    col(Knowledge.id).in_(batch),
                                    Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                                    Knowledge.state == KnowledgeState.PUBLISHED.value,
                                )
                            )
                        ).all()
                    )
                )
            published = {int(item.id): item for item in spaces if item.id is not None}
            bindings = list((await session.exec(select(DepartmentKnowledgeSpace))).all())
            space_department_ids: dict[int, int] = {
                int(item.space_id): int(item.department_id) for item in bindings
            }
            for scope in scopes:
                if int(scope.space_id) not in published:
                    continue
                if (
                    _enum_value(scope.level) == KnowledgeSpaceLevelEnum.DEPARTMENT.value
                    and _enum_value(scope.owner_type) == KnowledgeSpaceOwnerTypeEnum.DEPARTMENT.value
                ):
                    space_department_ids.setdefault(int(scope.space_id), int(scope.owner_id))
            department_ids = sorted(set(space_department_ids.values()))
            departments: list[Department] = []
            for batch in _chunks(department_ids):
                departments.extend(
                    list(
                        (
                            await session.exec(
                                select(Department).where(col(Department.id).in_(batch))
                            )
                        ).all()
                    )
                )
            department_paths = {
                int(item.id): str(item.path or "")
                for item in departments
                if item.id is not None
            }
            space_snapshots = tuple(
                SpaceSnapshot(
                    space_id=int(scope.space_id),
                    level=_enum_value(scope.level),
                    name=str(published[int(scope.space_id)].name or ""),
                    department_id=space_department_ids.get(int(scope.space_id)),
                    department_path=department_paths.get(space_department_ids[int(scope.space_id)], "")
                    if int(scope.space_id) in space_department_ids
                    else "",
                )
                for scope in scopes
                if int(scope.space_id) in published
            )
            file_rows = await _load_files_by_space_ids(session, [item.space_id for item in space_snapshots])
            file_ids = [int(item.id or 0) for item in file_rows]
            versions: list[KnowledgeDocumentVersion] = []
            for batch in _chunks(file_ids):
                versions.extend(
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
            document_ids = sorted({int(item.document_id) for item in versions})
            if document_ids:
                versions = []
                for batch in _chunks(document_ids):
                    versions.extend(
                        list(
                            (
                                await session.exec(
                                    select(KnowledgeDocumentVersion).where(
                                        col(KnowledgeDocumentVersion.document_id).in_(batch)
                                    )
                                )
                            ).all()
                        )
                    )
            return Inventory(
                spaces=space_snapshots,
                files=tuple(_file_snapshot(item) for item in file_rows),
                versions=tuple(
                    VersionSnapshot(
                        version_id=int(item.id or 0),
                        document_id=int(item.document_id),
                        file_id=int(item.knowledge_file_id),
                        version_no=int(item.version_no),
                        is_primary=bool(item.is_primary),
                    )
                    for item in versions
                ),
            )

    async def build_plan(self, args: argparse.Namespace) -> RelinkPlan:
        inventory = await self._load_inventory(args)
        return build_relink_plan(
            inventory,
            tenant_id=self.tenant_id,
            space_ids=args.space_ids,
            file_ids=args.file_ids,
            md5s=args.md5s,
            limit=args.limit,
        )

    async def revalidate(self, unit: RelinkUnit) -> RevalidationResult:
        args = argparse.Namespace(
            space_ids=[],
            file_ids=[unit.source_file_id],
            md5s=[unit.match_key] if unit.match_kind == "md5" else [],
            limit=None,
        )
        plan = await self.build_plan(args)
        current = next(
            (item for item in plan.units if item.source_file_id == unit.source_file_id),
            None,
        )
        if current is None:
            return RevalidationResult(valid=False, reason_code="plan_drift")
        if (
            current.origin_file_id != unit.origin_file_id
            or current.origin_space_id != unit.origin_space_id
            or current.source_space_id != unit.source_space_id
            or current.match_kind != unit.match_kind
            or current.match_key != unit.match_key
        ):
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


def _skip_or_reraise_attach_error(exc: KnowledgeDocumentDistributionError) -> None:
    if str(exc).strip() == SOURCE_HAS_DISTRIBUTION_DEPENDENTS_ERROR:
        raise SkipRelinkUnit(
            SOURCE_HAS_DISTRIBUTION_DEPENDENTS_REASON,
            SOURCE_HAS_DISTRIBUTION_DEPENDENTS_ERROR,
        ) from exc
    raise exc


def _distribution_service(session) -> KnowledgeDocumentDistributionService:
    file_repository = KnowledgeFileRepositoryImpl(session)
    return KnowledgeDocumentDistributionService(
        session=session,
        document_repository=KnowledgeDocumentRepositoryImpl(session),
        version_repository=KnowledgeDocumentVersionRepositoryImpl(session),
        file_repository=file_repository,
        permission_activation_service=KnowledgeDocumentPermissionActivationService(
            file_repository=file_repository,
        ),
    )


class BishengRelinkOperations:
    def __init__(self, tenant_id: int = DEFAULT_TENANT_ID) -> None:
        self.tenant_id = int(tenant_id)
        self._spaces: dict[int, Knowledge] = {}

    async def _space(self, space_id: int) -> Knowledge:
        if space_id not in self._spaces:
            space = await KnowledgeDao.aquery_by_id(space_id)
            if space is None or int(space.type) != KnowledgeTypeEnum.SPACE.value:
                raise RuntimeError("target knowledge space is unavailable")
            self._spaces[space_id] = space
        return self._spaces[space_id]

    async def attach(self, unit: RelinkUnit) -> dict[str, Any]:
        async with get_async_db_session() as session:
            service = _distribution_service(session)
            try:
                result = await service.attach_existing_as_publish(
                    AttachExistingAsPublishCommand(
                        tenant_id=self.tenant_id,
                        origin_file_id=unit.origin_file_id,
                        source_file_id=unit.source_file_id,
                    )
                )
            except KnowledgeDocumentDistributionError as exc:
                _skip_or_reraise_attach_error(exc)
                raise
        return {
            "document_id": result.document_id,
            "manager_file_id": result.manager_file_id,
            "publish_entry_id": result.publish_entry_id,
            "retained_history_file_ids": list(result.retained_history_file_ids),
            "idempotent": result.idempotent,
        }

    async def delete_vectors(self, unit: RelinkUnit) -> None:
        space = await self._space(unit.source_space_id)
        await asyncio.to_thread(_delete_milvus_sync, space, unit.source_file_id)
        await asyncio.to_thread(_delete_elasticsearch_sync, space, unit.source_file_id)

    async def delete_minio(self, unit: RelinkUnit) -> None:
        storage = get_minio_storage_sync()
        for object_name in sorted({item.name for item in unit.storage_objects if item.name}):
            await asyncio.to_thread(
                storage.remove_object_sync,
                bucket_name=storage.bucket,
                object_name=object_name,
            )

    async def enqueue_projection(self, unit: RelinkUnit, *, manager_file_id: int) -> None:
        from bisheng.worker.knowledge.document_projection import enqueue_document_projection_entries
        from bisheng.worker.knowledge.portal_recommendation import (
            enqueue_portal_recommendation_projection_refresh_batch,
        )

        enqueue_document_projection_entries(
            tenant_id=self.tenant_id,
            entry_ids=[int(manager_file_id), int(unit.source_file_id)],
        )
        enqueue_portal_recommendation_projection_refresh_batch(
            file_ids=[int(unit.source_file_id), int(unit.origin_file_id)],
            deleted=False,
            tenant_id=self.tenant_id,
        )
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

        await KnowledgeSpaceContentStat.enqueue_file_stat_async([int(unit.source_file_id), int(unit.origin_file_id)])

    async def verify_linked(self, unit: RelinkUnit) -> dict[str, Any]:
        async with get_async_db_session() as session:
            source = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id == unit.source_file_id))).first()
            if source is None:
                raise KnowledgeDocumentDistributionError("converted file is missing after attach")
            if source.entry_type != KnowledgeFileEntryType.PUBLISH.value:
                raise KnowledgeDocumentDistributionError("converted file is not a publish entry")
            if source.entry_status != KnowledgeFileEntryStatus.ACTIVE.value:
                raise KnowledgeDocumentDistributionError("converted publish entry is not active")
            if source.allow_download:
                raise KnowledgeDocumentDistributionError("converted publish entry allows download")
            if (
                source.object_name is not None
                or source.preview_file_object_name is not None
                or source.thumbnails is not None
                or int(source.file_size or 0) != 0
                or source.md5 is not None
                or (source.bbox_object_name or "") != ""
            ):
                raise KnowledgeDocumentDistributionError("converted publish entry still has physical payload")
            document = None
            if source.reference_document_id is not None:
                document = (
                    await session.exec(
                        select(KnowledgeDocument).where(KnowledgeDocument.id == int(source.reference_document_id))
                    )
                ).first()
            return {
                "publish_entry_id": int(source.id),
                "document_id": int(source.reference_document_id or 0),
                "manager_space_id": int(document.knowledge_id) if document is not None else None,
                "allow_download": bool(source.allow_download),
            }


def _print_report_summary(report: dict[str, Any], path: Path, markdown_path: Path | None = None) -> None:
    summary = report.get("summary", {})
    aggregates = _report_aggregates(report)
    skip_counts = aggregates["skip_counts"]
    level_counts = aggregates["level_counts"]
    kind_counts = aggregates["kind_counts"]

    print("")
    print(f"JSON report written to: {path.resolve()}")
    if markdown_path is not None:
        print(f"Markdown report written to: {markdown_path.resolve()}")
    print(f"Run ID: {report.get('run_id')}")
    print(f"Mode: {report.get('mode')}")
    print(
        "Summary: "
        f"planned={summary.get('planned', 0)} "
        f"completed={summary.get('completed', 0)} "
        f"skipped={summary.get('skipped', 0)} "
        f"failed={summary.get('failed', 0)} "
        f"pending={summary.get('pending', 0)} "
        f"history_files={summary.get('history_files', 0)} "
        f"unmatched={report.get('unmatched_count', 0)}"
    )
    if kind_counts:
        print("Match kinds: " + ", ".join(f"{kind}={count}" for kind, count in sorted(kind_counts.items())))
    if level_counts:
        print("Planned by level:")
        for pair, count in sorted(level_counts.items(), key=lambda item: (-item[1], item[0])):
            origin_level, _, source_level = pair.partition("->")
            print(f"  {_level_label(origin_level)} -> {_level_label(source_level)}: {count}")
    if skip_counts:
        print("Skipped by reason:")
        for reason, count in sorted(skip_counts.items()):
            print(f"  {SKIP_LABELS.get(reason, reason)}: {count}")
    print("")


def _make_error_report(
    *,
    run_id: str,
    mode: str,
    arguments: dict[str, Any],
    error_type: str,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": mode,
        "run_id": run_id,
        "arguments": arguments,
        "units": [],
        "skipped": [],
        "summary": {"planned": 0, "completed": 0, "skipped": 0, "failed": 0, "pending": 0, "history_files": 0},
        "error_type": error_type,
        "exit_code": exit_code,
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "finished_at": _utc_now(),
    }


async def run(
    args: argparse.Namespace,
    *,
    reader: PlanReader | None = None,
    operations_factory: Callable[[], RelinkOperations] | None = None,
    manage_context: bool = True,
) -> int:
    run_id = _new_run_id()
    store = ReportStore(args.report_dir, run_id)
    arguments = _arguments_for_report(args)
    context_initialized = False
    tenant_id = DEFAULT_TENANT_ID
    report: dict[str, Any] | None = None
    logger.info("relink run started run_id=%s mode=%s", run_id, "apply" if args.apply else "dry-run")
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
                    _print_report_summary(report, path, store.markdown_path)
                except ReportWriteError:
                    logger.exception("relink report write failed run_id=%s phase=preflight_error", run_id)
                    return EXIT_REPORT_ERROR
                logger.error("relink preflight failed: %s", exc)
                return EXIT_INPUT_ERROR
            except Exception as exc:
                logger.exception("relink planning failed run_id=%s error_type=%s", run_id, type(exc).__name__)
                report = _make_error_report(
                    run_id=run_id,
                    mode="apply" if args.apply else "dry-run",
                    arguments=arguments,
                    error_type=type(exc).__name__,
                    exit_code=EXIT_SCAN_ERROR,
                )
                try:
                    path = store.write(report)
                    _print_report_summary(report, path, store.markdown_path)
                except ReportWriteError:
                    return EXIT_REPORT_ERROR
                return EXIT_SCAN_ERROR

            if not args.apply:
                report["finished_at"] = _utc_now()
            try:
                path = store.write(report)
            except ReportWriteError:
                logger.exception("relink report write failed run_id=%s phase=plan", run_id)
                return EXIT_REPORT_ERROR

            if not args.apply:
                _print_report_summary(report, path, store.markdown_path)
                return EXIT_OK

            operations = (operations_factory or (lambda: BishengRelinkOperations(tenant_id)))()
            executor = ApplyExecutor(actual_reader, operations, checkpoint=lambda: store.write(report))
            success = await executor.run(report)
            report["finished_at"] = _utc_now()
            try:
                path = store.write(report)
            except ReportWriteError:
                logger.exception("relink report write failed run_id=%s phase=apply", run_id)
                return EXIT_REPORT_ERROR
            _print_report_summary(report, path, store.markdown_path)
            return EXIT_OK if success else EXIT_APPLY_ERROR
    finally:
        if context_initialized:
            await close_app_context()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
