#!/usr/bin/env python3
r"""Move selected files between BiSheng knowledge spaces safely.

The script copies each selected file into the target space, verifies the new
database/storage/index/tag/permission state, and only then removes the source
file. The default mode is a read-only dry-run. Pass ``--apply`` to mutate data.

Run from ``src/backend``::

    PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
      --source-space-id 10 --target-space-id 20 --target-owner-id 30

    PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
      --source-space-id 10 --source-folder-id 11 \
      --source-category-code STD --source-subcategory-code STD-A \
      --target-space-id 20 --target-folder-id 21 --target-owner-id 30 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import traceback
import uuid
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from sqlmodel import col, select

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.api.services.knowledge_imp import delete_minio_files, delete_vector_files  # noqa: E402
from bisheng.approval.domain.services.shougang_approval_handler import _copy_file_tags  # noqa: E402
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.core.context.manager import close_app_context, initialize_app_context  # noqa: E402
from bisheng.core.context.tenant import (  # noqa: E402
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
    set_visible_tenant_ids,
    strict_tenant_filter,
    visible_tenant_ids,
)
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.group_resource import ResourceTypeEnum  # noqa: E402
from bisheng.database.models.review_tags import ReviewTagDao  # noqa: E402
from bisheng.database.models.tag import TagDao  # noqa: E402
from bisheng.database.models.tenant import UserTenant  # noqa: E402
from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils  # noqa: E402
from bisheng.permission.domain.schemas.tuple_operation import TupleOperation  # noqa: E402
from bisheng.permission.domain.services.permission_service import PermissionService  # noqa: E402
from bisheng.shougang_portal_config.domain.services.portal_config_service import (  # noqa: E402
    ShougangPortalConfigService,
)
from bisheng.user.domain.models.user import User  # noqa: E402
from bisheng.worker.knowledge.file_worker import copy_normal, copy_vector  # noqa: E402

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_DEPENDENCY_ERROR = 3
EXIT_APPLY_ERROR = 4

_CATEGORY_CODE_PATTERN = re.compile(r"[A-Z0-9_][A-Z0-9_-]{0,15}")


class PreflightError(RuntimeError):
    """Raised when validation must stop the whole batch before any write."""


class TargetCopyError(RuntimeError):
    """Expose a partially created target record to the compensation path."""

    def __init__(self, message: str, target_file: KnowledgeFile | None = None) -> None:
        super().__init__(message)
        self.target_file = target_file


@dataclass(frozen=True)
class SelectionFilters:
    source_space_id: int
    source_folder_prefix: str | None = None
    file_ids: frozenset[int] = frozenset()
    category_codes: frozenset[str] = frozenset()
    subcategory_codes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SkippedFile:
    source_file_id: int
    source_file_name: str
    reason_code: str
    reason: str


@dataclass
class FileMoveResult:
    source_file_id: int
    source_space_id: int
    source_file_name: str
    status: Literal["success", "skipped", "failed"]
    target_space_id: int | None = None
    target_file_id: int | None = None
    category_code: str = ""
    subcategory_code: str = ""
    source_deleted: bool = False
    target_cleanup_succeeded: bool | None = None
    reason_code: str = ""
    error: str = ""
    cleanup_errors: list[str] = field(default_factory=list)


@dataclass
class MoveRunReport:
    mode: Literal["dry-run", "apply"]
    run_id: str
    parameters: dict[str, Any]
    tenant_id: int
    results: list[FileMoveResult] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    finished_at: str = ""
    report_path: str = ""

    def summary(self) -> dict[str, int]:
        counts = {"total": len(self.results), "success": 0, "skipped": 0, "failed": 0}
        for result in self.results:
            counts[result.status] += 1
        return counts


@dataclass(frozen=True)
class TagSnapshot:
    approved_ids: tuple[int, ...] = ()
    pending_review_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class IndexSnapshot:
    milvus_count: int
    es_count: int


@dataclass(frozen=True)
class SourceSnapshot:
    tags: TagSnapshot
    permissions: tuple[dict[str, str], ...]
    indexes: IndexSnapshot
    storage_exists: dict[str, bool]


@dataclass
class PreflightPlan:
    tenant_id: int
    source_space: Knowledge
    target_space: Knowledge
    target_owner: User
    source_folder: KnowledgeFile | None
    target_folder: KnowledgeFile | None
    target_file_level_path: str
    target_level: int
    selected_files: list[KnowledgeFile]
    skipped_files: list[SkippedFile]


class MoveOperations(Protocol):
    async def copy_file(self, source_file: KnowledgeFile) -> KnowledgeFile: ...

    async def copy_tags(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None: ...

    async def write_permissions(self, target_file: KnowledgeFile) -> None: ...

    async def verify_target(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None: ...

    async def delete_source(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None: ...

    async def cleanup_target(self, target_file: KnowledgeFile) -> list[str]: ...


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _category_code(value: str) -> str:
    normalized = value.strip().upper()
    if not _CATEGORY_CODE_PATTERN.fullmatch(normalized):
        raise argparse.ArgumentTypeError("category code must contain 1-16 uppercase letters, digits, '_' or '-'")
    return normalized


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-space-id", required=True, type=_positive_int)
    parser.add_argument("--source-folder-id", type=_positive_int)
    parser.add_argument(
        "--source-file-id",
        dest="source_file_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="source file ID; can be passed multiple times",
    )
    parser.add_argument(
        "--source-category-code",
        dest="source_category_codes",
        action="append",
        type=_category_code,
        default=[],
        help="first-level category code; can be passed multiple times",
    )
    parser.add_argument(
        "--source-subcategory-code",
        dest="source_subcategory_codes",
        action="append",
        type=_category_code,
        default=[],
        help="second-level category code; can be passed multiple times",
    )
    parser.add_argument("--target-space-id", required=True, type=_positive_int)
    parser.add_argument("--target-folder-id", type=_positive_int)
    parser.add_argument("--target-owner-id", required=True, type=_positive_int)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("migration_reports/knowledge_file_move"),
        help="directory for JSON reports",
    )
    parser.add_argument("--apply", action="store_true", help="perform writes; default is dry-run")
    return parser.parse_args(argv)


def _normalize_codes(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value.strip().upper() for value in values if value and value.strip()))


def validate_category_filters(
    category_children: dict[str, frozenset[str]],
    *,
    parent_codes: Sequence[str],
    child_codes: Sequence[str],
) -> None:
    normalized_parents = _normalize_codes(parent_codes)
    normalized_children = _normalize_codes(child_codes)
    unknown_parents = [code for code in normalized_parents if code not in category_children]
    if unknown_parents:
        raise PreflightError(f"unknown first-level category codes: {unknown_parents}")

    child_to_parent = {
        child_code: parent_code for parent_code, children in category_children.items() for child_code in children
    }
    unknown_children = [code for code in normalized_children if code not in child_to_parent]
    if unknown_children:
        raise PreflightError(f"unknown second-level category codes: {unknown_children}")

    if normalized_parents:
        invalid_children = [code for code in normalized_children if child_to_parent.get(code) not in normalized_parents]
        if invalid_children:
            raise PreflightError(
                f"second-level category {invalid_children} does not belong to the selected first-level categories"
            )


def _is_in_folder(file_level_path: str | None, folder_prefix: str) -> bool:
    path = file_level_path or ""
    return path == folder_prefix or path.startswith(f"{folder_prefix}/")


def file_matches_filters(record: KnowledgeFile, filters: SelectionFilters) -> bool:
    if int(record.knowledge_id) != filters.source_space_id:
        return False
    if filters.source_folder_prefix and not _is_in_folder(record.file_level_path, filters.source_folder_prefix):
        return False
    if filters.file_ids and int(record.id or 0) not in filters.file_ids:
        return False
    category_code, _ = parse_shougang_file_encoding_codes(record)
    if filters.category_codes and category_code not in filters.category_codes:
        return False
    subcategory_code = str(record.file_subcategory_code or "").strip().upper()
    return not filters.subcategory_codes or subcategory_code in filters.subcategory_codes


def partition_candidates(
    files: Sequence[KnowledgeFile],
    *,
    versioned_file_ids: set[int],
    target_file_names: set[str],
    target_md5s: set[str],
) -> tuple[list[KnowledgeFile], list[SkippedFile]]:
    selected: list[KnowledgeFile] = []
    skipped: list[SkippedFile] = []
    seen_names = set(target_file_names)
    seen_md5s = {value for value in target_md5s if value}

    for record in sorted(files, key=lambda item: int(item.id or 0)):
        file_id = int(record.id or 0)
        if file_id in versioned_file_ids:
            skipped.append(SkippedFile(file_id, record.file_name, "versioned_file", "file has version history"))
            continue
        if record.file_name in seen_names:
            skipped.append(
                SkippedFile(file_id, record.file_name, "target_name_conflict", "target folder contains same name")
            )
            continue
        if record.md5 and record.md5 in seen_md5s:
            skipped.append(
                SkippedFile(file_id, record.file_name, "target_md5_conflict", "target space contains same MD5")
            )
            continue
        selected.append(record)
        seen_names.add(record.file_name)
        if record.md5:
            seen_md5s.add(record.md5)
    return selected, skipped


async def move_one_file(source_file: KnowledgeFile, operations: MoveOperations) -> FileMoveResult:
    category_code, _ = parse_shougang_file_encoding_codes(source_file)
    result = FileMoveResult(
        source_file_id=int(source_file.id or 0),
        source_space_id=int(source_file.knowledge_id),
        source_file_name=source_file.file_name,
        target_space_id=None,
        category_code=category_code,
        subcategory_code=str(source_file.file_subcategory_code or "").strip().upper(),
        status="failed",
    )
    target_file: KnowledgeFile | None = None
    try:
        target_file = await operations.copy_file(source_file)
        result.target_space_id = int(target_file.knowledge_id)
        result.target_file_id = int(target_file.id or 0)
        await operations.copy_tags(source_file, target_file)
        await operations.write_permissions(target_file)
        await operations.verify_target(source_file, target_file)
        await operations.delete_source(source_file, target_file)
        result.status = "success"
        result.source_deleted = True
        return result
    except Exception as exc:
        if isinstance(exc, TargetCopyError) and exc.target_file is not None:
            target_file = exc.target_file
            result.target_space_id = int(target_file.knowledge_id)
            result.target_file_id = int(target_file.id or 0)
        result.error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        if target_file is not None:
            cleanup_errors = await operations.cleanup_target(target_file)
            result.cleanup_errors = cleanup_errors
            result.target_cleanup_succeeded = not cleanup_errors
        return result


def _skipped_to_result(item: SkippedFile, source_space_id: int, target_space_id: int) -> FileMoveResult:
    return FileMoveResult(
        source_file_id=item.source_file_id,
        source_space_id=source_space_id,
        source_file_name=item.source_file_name,
        target_space_id=target_space_id,
        status="skipped",
        reason_code=item.reason_code,
        error=item.reason,
    )


def write_json_report(report: MoveRunReport, report_dir: Path) -> Path:
    report.finished_at = report.finished_at or datetime.now().astimezone().isoformat()
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / f"knowledge-file-move-{report.run_id}.json"
    report.report_path = str(output_path.resolve())
    payload = {
        "mode": report.mode,
        "run_id": report.run_id,
        "tenant_id": report.tenant_id,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "parameters": report.parameters,
        "summary": report.summary(),
        "results": [asdict(result) for result in report.results],
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return output_path


def _folder_child_path(folder: KnowledgeFile) -> str:
    return f"{folder.file_level_path or ''}/{folder.id}"


def _category_children_from_config(config: Any) -> dict[str, frozenset[str]]:
    if config is None:
        return {}
    document_types = getattr(getattr(config, "portal", None), "document_types", None) or []
    result: dict[str, frozenset[str]] = {}
    for item in document_types:
        parent_code = str(getattr(item, "code", "") or "").strip().upper()
        if not parent_code:
            continue
        result[parent_code] = frozenset(
            str(getattr(child, "code", "") or "").strip().upper()
            for child in (getattr(item, "children", None) or [])
            if str(getattr(child, "code", "") or "").strip()
        )
    return result


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


async def _load_preflight_entities(
    args: argparse.Namespace,
) -> tuple[Knowledge, Knowledge, User, KnowledgeFile | None, KnowledgeFile | None]:
    requested_ids = {args.source_space_id, args.target_space_id}
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            spaces = (
                await session.exec(
                    select(Knowledge).where(
                        col(Knowledge.id).in_(requested_ids),
                        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                    )
                )
            ).all()
            space_map = {int(space.id): space for space in spaces if space.id is not None}
            source_space = space_map.get(args.source_space_id)
            target_space = space_map.get(args.target_space_id)
            if source_space is None:
                raise PreflightError(f"source knowledge space {args.source_space_id} not found")
            if target_space is None:
                raise PreflightError(f"target knowledge space {args.target_space_id} not found")
            if args.source_space_id == args.target_space_id:
                raise PreflightError("source and target knowledge spaces must be different")

            source_tenant_id = int(source_space.tenant_id or 1)
            target_tenant_id = int(target_space.tenant_id or 1)
            if source_tenant_id != target_tenant_id:
                raise PreflightError("source and target knowledge spaces must belong to the same tenant")
            if str(source_space.model or "") != str(target_space.model or ""):
                raise PreflightError("source and target knowledge spaces use different embedding models")

            owner = (
                await session.exec(select(User).where(User.user_id == args.target_owner_id, User.delete == 0))
            ).first()
            if owner is None:
                raise PreflightError(f"target owner {args.target_owner_id} is missing or disabled")
            owner_tenant = (
                await session.exec(
                    select(UserTenant).where(
                        UserTenant.user_id == args.target_owner_id,
                        UserTenant.tenant_id == source_tenant_id,
                        UserTenant.status == "active",
                    )
                )
            ).first()
            if owner_tenant is None:
                raise PreflightError("target owner does not belong to the knowledge-space tenant")

            folder_ids = {
                folder_id for folder_id in (args.source_folder_id, args.target_folder_id) if folder_id is not None
            }
            folder_map: dict[int, KnowledgeFile] = {}
            if folder_ids:
                folders = (
                    await session.exec(
                        select(KnowledgeFile).where(
                            col(KnowledgeFile.id).in_(folder_ids),
                            KnowledgeFile.file_type == FileType.DIR.value,
                        )
                    )
                ).all()
                folder_map = {int(folder.id): folder for folder in folders if folder.id is not None}

            source_folder = folder_map.get(args.source_folder_id) if args.source_folder_id else None
            if args.source_folder_id and (
                source_folder is None or int(source_folder.knowledge_id) != args.source_space_id
            ):
                raise PreflightError("source folder does not belong to the source knowledge space")
            target_folder = folder_map.get(args.target_folder_id) if args.target_folder_id else None
            if args.target_folder_id and (
                target_folder is None or int(target_folder.knowledge_id) != args.target_space_id
            ):
                raise PreflightError("target folder does not belong to the target knowledge space")

    return source_space, target_space, owner, source_folder, target_folder


async def build_preflight_plan(args: argparse.Namespace) -> PreflightPlan:
    source_space, target_space, owner, source_folder, target_folder = await _load_preflight_entities(args)
    tenant_id = int(source_space.tenant_id or 1)
    with _tenant_scope(tenant_id):
        portal_config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
        category_children = _category_children_from_config(portal_config)
        validate_category_filters(
            category_children,
            parent_codes=args.source_category_codes,
            child_codes=args.source_subcategory_codes,
        )

        filters = SelectionFilters(
            source_space_id=args.source_space_id,
            source_folder_prefix=_folder_child_path(source_folder) if source_folder else None,
            file_ids=frozenset(args.source_file_ids),
            category_codes=frozenset(_normalize_codes(args.source_category_codes)),
            subcategory_codes=frozenset(_normalize_codes(args.source_subcategory_codes)),
        )
        async with get_async_db_session() as session:
            source_records = list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(KnowledgeFile.knowledge_id == args.source_space_id)
                        .order_by(col(KnowledgeFile.id).asc())
                    )
                ).all()
            )
            target_records = list(
                (
                    await session.exec(
                        select(KnowledgeFile).where(
                            KnowledgeFile.knowledge_id == args.target_space_id,
                            KnowledgeFile.file_type == FileType.FILE.value,
                        )
                    )
                ).all()
            )

            matched: list[KnowledgeFile] = []
            skipped: list[SkippedFile] = []
            source_ids = {int(record.id) for record in source_records if record.id is not None}
            for missing_id in sorted(set(args.source_file_ids) - source_ids):
                skipped.append(SkippedFile(missing_id, "", "file_not_in_source", "file ID is not in source space"))

            for record in source_records:
                if args.source_file_ids and int(record.id or 0) in set(args.source_file_ids):
                    if not file_matches_filters(record, filters):
                        skipped.append(
                            SkippedFile(
                                int(record.id or 0),
                                record.file_name,
                                "filter_mismatch",
                                "file does not match all filters",
                            )
                        )
                        continue
                elif not file_matches_filters(record, filters):
                    continue
                if record.file_type != FileType.FILE.value:
                    skipped.append(
                        SkippedFile(int(record.id or 0), record.file_name, "folder_record", "folders are not moved")
                    )
                    continue
                if record.status != KnowledgeFileStatus.SUCCESS.value:
                    skipped.append(
                        SkippedFile(
                            int(record.id or 0), record.file_name, "ineligible_status", "file status is not SUCCESS"
                        )
                    )
                    continue
                matched.append(record)

            matched_ids = [int(record.id) for record in matched if record.id is not None]
            versioned_ids: set[int] = set()
            if matched_ids:
                rows = (
                    await session.exec(
                        select(KnowledgeDocumentVersion.knowledge_file_id).where(
                            col(KnowledgeDocumentVersion.knowledge_file_id).in_(matched_ids)
                        )
                    )
                ).all()
                versioned_ids = {int(row) for row in rows}

        target_path = _folder_child_path(target_folder) if target_folder else ""
        target_names = {record.file_name for record in target_records if (record.file_level_path or "") == target_path}
        target_md5s = {str(record.md5) for record in target_records if record.md5}
        selected, conflict_skips = partition_candidates(
            matched,
            versioned_file_ids=versioned_ids,
            target_file_names=target_names,
            target_md5s=target_md5s,
        )
        skipped.extend(conflict_skips)

    return PreflightPlan(
        tenant_id=tenant_id,
        source_space=source_space,
        target_space=target_space,
        target_owner=owner,
        source_folder=source_folder,
        target_folder=target_folder,
        target_file_level_path=_folder_child_path(target_folder) if target_folder else "",
        target_level=int(target_folder.level or 0) + 1 if target_folder else 0,
        selected_files=selected,
        skipped_files=skipped,
    )


def _storage_object_names(file: KnowledgeFile) -> dict[str, str]:
    preview = KnowledgeUtils.resolve_preview_object_name(
        int(file.id or 0), file.file_name, file.preview_file_object_name
    )
    return {
        "original": str(file.object_name or ""),
        "converted": str(file.id or ""),
        "bbox": str(file.bbox_object_name or ""),
        "preview": str(preview or ""),
    }


def _storage_exists(file: KnowledgeFile) -> dict[str, bool]:
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

    minio = get_minio_storage_sync()
    return {
        key: bool(name and minio.object_exists_sync(minio.bucket, name))
        for key, name in _storage_object_names(file).items()
    }


def _copy_object_if_present(source_name: str, target_name: str) -> None:
    if not source_name or not target_name or source_name == target_name:
        return
    from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

    minio = get_minio_storage_sync()
    if minio.object_exists_sync(minio.bucket, source_name):
        minio.copy_object_sync(
            source_bucket=minio.bucket,
            source_object=source_name,
            dest_bucket=minio.bucket,
            dest_object=target_name,
        )


def _target_preview_object_name(source_file: KnowledgeFile, target_file: KnowledgeFile) -> str:
    canonical_name = KnowledgeUtils.get_knowledge_preview_file_object_name(
        int(target_file.id or 0),
        target_file.file_name,
    )
    if canonical_name:
        return canonical_name
    source_name = _storage_object_names(source_file)["preview"]
    if not source_name:
        return ""
    suffix = Path(source_name).suffix
    return f"preview/{target_file.id}{suffix}"


def _count_milvus_records(space: Knowledge, file_id: int) -> int:
    from bisheng.core.ai import FakeEmbeddings
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
        0,
        knowledge=space,
        embeddings=FakeEmbeddings(),
    )
    if store.col is None:
        return 0
    expression = f"document_id=={file_id} && knowledge_id=={space.id}"
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


def _count_es_records(space: Knowledge, file_id: int) -> int:
    from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag

    store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=space)
    if store is None or not store.client.indices.exists(index=space.index_name):
        return 0
    response = store.client.count(
        index=space.index_name,
        query={"bool": {"filter": [{"term": {"metadata.document_id": file_id}}]}},
    )
    return int(response.get("count", 0))


def _index_snapshot(space: Knowledge, file_id: int) -> IndexSnapshot:
    return IndexSnapshot(
        milvus_count=_count_milvus_records(space, file_id),
        es_count=_count_es_records(space, file_id),
    )


async def _tag_snapshot(file_id: int, tenant_id: int) -> TagSnapshot:
    resource_id = str(file_id)
    approved = await TagDao.aget_resource_tag_ids_batch([resource_id], ResourceTypeEnum.SPACE_FILE)
    pending = await asyncio.to_thread(
        ReviewTagDao.get_tags_by_resource_batch,
        [ResourceTypeEnum.SPACE_FILE],
        [resource_id],
        tenant_id=tenant_id,
    )
    return TagSnapshot(
        approved_ids=tuple(sorted({int(tag_id) for tag_id in approved.get(resource_id, [])})),
        pending_review_ids=tuple(
            sorted(
                {
                    int(tag.id)
                    for tag in pending.get(resource_id, [])
                    if tag.id is not None and getattr(tag, "review_status", 0) == 0
                }
            )
        ),
    )


async def _read_permission_tuples(file_id: int) -> tuple[dict[str, str], ...]:
    fga = PermissionService._get_fga()
    if fga is None:
        raise PreflightError("OpenFGA is unavailable")
    rows = await fga.read_tuples(object=f"knowledge_file:{file_id}")
    return tuple(
        {"user": str(row["user"]), "relation": str(row["relation"]), "object": str(row["object"])}
        for row in (rows or [])
    )


async def _replace_permission_tuples(file_id: int, desired: Sequence[dict[str, str]]) -> None:
    existing = await _read_permission_tuples(file_id)
    operations = [
        TupleOperation(action="delete", user=row["user"], relation=row["relation"], object=row["object"])
        for row in existing
    ]
    operations.extend(
        TupleOperation(action="write", user=row["user"], relation=row["relation"], object=row["object"])
        for row in desired
    )
    if operations:
        await PermissionService.batch_write_tuples(
            operations,
            crash_safe=True,
            raise_on_failure=True,
            stop_on_failure=True,
        )


async def _clear_tag_links(file_id: int, owner_id: int, tenant_id: int) -> None:
    resource_id = str(file_id)
    await TagDao.aupdate_resource_tags([], resource_id, ResourceTypeEnum.SPACE_FILE, owner_id)
    await ReviewTagDao.aupdate_resource_tags(
        [], resource_id, ResourceTypeEnum.SPACE_FILE, owner_id, tenant_id=tenant_id
    )


async def _restore_tag_links(file_id: int, owner_id: int, tenant_id: int, snapshot: TagSnapshot) -> None:
    resource_id = str(file_id)
    await TagDao.aupdate_resource_tags(list(snapshot.approved_ids), resource_id, ResourceTypeEnum.SPACE_FILE, owner_id)
    await ReviewTagDao.aupdate_resource_tags(
        list(snapshot.pending_review_ids),
        resource_id,
        ResourceTypeEnum.SPACE_FILE,
        owner_id,
        tenant_id=tenant_id,
    )


class BishengMoveOperations:
    def __init__(self, plan: PreflightPlan) -> None:
        self.plan = plan
        self.snapshots: dict[int, SourceSnapshot] = {}

    async def _snapshot_source(self, source_file: KnowledgeFile) -> SourceSnapshot:
        file_id = int(source_file.id or 0)
        snapshot = SourceSnapshot(
            tags=await _tag_snapshot(file_id, self.plan.tenant_id),
            permissions=await _read_permission_tuples(file_id),
            indexes=await asyncio.to_thread(_index_snapshot, self.plan.source_space, file_id),
            storage_exists=await asyncio.to_thread(_storage_exists, source_file),
        )
        self.snapshots[file_id] = snapshot
        return snapshot

    async def copy_file(self, source_file: KnowledgeFile) -> KnowledgeFile:
        snapshot = await self._snapshot_source(source_file)
        target_file = await asyncio.to_thread(
            copy_normal,
            source_file,
            self.plan.source_space,
            self.plan.target_space,
            int(self.plan.target_owner.user_id),
            target_level=self.plan.target_level,
            target_file_level_path=self.plan.target_file_level_path,
        )
        if target_file is None or target_file.id is None:
            raise TargetCopyError("copy_normal did not create a target file")
        try:
            if target_file.status != KnowledgeFileStatus.SUCCESS.value:
                raise RuntimeError(f"target file status is {target_file.status}, expected SUCCESS")
            target_file.user_id = int(self.plan.target_owner.user_id)
            target_file.user_name = self.plan.target_owner.user_name
            target_file.updater_id = int(self.plan.target_owner.user_id)
            target_file.updater_name = self.plan.target_owner.user_name

            source_preview = _storage_object_names(source_file)["preview"]
            target_preview = _target_preview_object_name(source_file, target_file)
            if snapshot.storage_exists.get("preview", False):
                await asyncio.to_thread(_copy_object_if_present, source_preview, target_preview)
                target_file.preview_file_object_name = target_preview
            else:
                target_file.preview_file_object_name = None
            target_file = await KnowledgeFileDao.async_update(target_file)
            return target_file
        except Exception as exc:
            raise TargetCopyError(str(exc), target_file) from exc

    async def copy_tags(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        await _copy_file_tags(
            source_file_id=int(source_file.id),
            target_file_id=int(target_file.id),
            user_id=int(self.plan.target_owner.user_id),
            tenant_id=self.plan.tenant_id,
        )

    def _target_permission_rows(self, target_file: KnowledgeFile) -> tuple[dict[str, str], ...]:
        parent_type = "folder" if self.plan.target_folder else "knowledge_space"
        parent_id = int(self.plan.target_folder.id) if self.plan.target_folder else int(self.plan.target_space.id)
        object_ref = f"knowledge_file:{target_file.id}"
        return (
            {"user": f"user:{self.plan.target_owner.user_id}", "relation": "owner", "object": object_ref},
            {"user": f"{parent_type}:{parent_id}", "relation": "parent", "object": object_ref},
        )

    async def write_permissions(self, target_file: KnowledgeFile) -> None:
        await _replace_permission_tuples(int(target_file.id), self._target_permission_rows(target_file))

    async def verify_target(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        current = await KnowledgeFileDao.query_by_id(int(target_file.id))
        if current is None or current.status != KnowledgeFileStatus.SUCCESS.value:
            raise RuntimeError("target database record is missing or not SUCCESS")
        if int(current.knowledge_id) != int(self.plan.target_space.id):
            raise RuntimeError("target database record belongs to the wrong knowledge space")
        if int(current.user_id or 0) != int(self.plan.target_owner.user_id):
            raise RuntimeError("target database record has the wrong owner")
        if (current.file_level_path or "") != self.plan.target_file_level_path:
            raise RuntimeError("target database record has the wrong folder path")

        snapshot = self.snapshots[int(source_file.id)]
        target_storage = await asyncio.to_thread(_storage_exists, current)
        missing_objects = [
            key for key, existed in snapshot.storage_exists.items() if existed and not target_storage.get(key, False)
        ]
        if missing_objects:
            raise RuntimeError(f"target storage objects are missing: {missing_objects}")

        target_indexes = await asyncio.to_thread(_index_snapshot, self.plan.target_space, int(current.id))
        if target_indexes.milvus_count != snapshot.indexes.milvus_count:
            raise RuntimeError(
                f"Milvus count mismatch: source={snapshot.indexes.milvus_count} target={target_indexes.milvus_count}"
            )
        if target_indexes.es_count != snapshot.indexes.milvus_count:
            raise RuntimeError(
                f"Elasticsearch count mismatch: expected={snapshot.indexes.milvus_count} target={target_indexes.es_count}"
            )

        target_tags = await _tag_snapshot(int(current.id), self.plan.tenant_id)
        if target_tags != snapshot.tags:
            raise RuntimeError("target file tags do not match the source file")
        actual_permissions = await _read_permission_tuples(int(current.id))
        expected_permissions = self._target_permission_rows(current)
        if not all(row in actual_permissions for row in expected_permissions):
            raise RuntimeError("target owner or parent permission tuple is missing")

    async def _restore_source_artifacts(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> list[str]:
        errors: list[str] = []
        snapshot = self.snapshots[int(source_file.id)]
        try:
            await asyncio.to_thread(delete_vector_files, [int(source_file.id)], self.plan.source_space)
            await asyncio.to_thread(
                copy_vector,
                self.plan.target_space,
                self.plan.source_space,
                int(target_file.id),
                int(source_file.id),
            )
        except Exception as exc:
            errors.append(f"restore source indexes: {type(exc).__name__}: {exc}")

        source_objects = _storage_object_names(source_file)
        target_objects = _storage_object_names(target_file)
        for key, existed in snapshot.storage_exists.items():
            if not existed:
                continue
            try:
                await asyncio.to_thread(_copy_object_if_present, target_objects[key], source_objects[key])
            except Exception as exc:
                errors.append(f"restore source object {key}: {type(exc).__name__}: {exc}")
        try:
            await _restore_tag_links(
                int(source_file.id),
                int(source_file.user_id or self.plan.target_owner.user_id),
                self.plan.tenant_id,
                snapshot.tags,
            )
        except Exception as exc:
            errors.append(f"restore source tags: {type(exc).__name__}: {exc}")
        try:
            await _replace_permission_tuples(int(source_file.id), snapshot.permissions)
        except Exception as exc:
            errors.append(f"restore source permissions: {type(exc).__name__}: {exc}")
        return errors

    async def delete_source(self, source_file: KnowledgeFile, target_file: KnowledgeFile) -> None:
        try:
            await asyncio.to_thread(delete_vector_files, [int(source_file.id)], self.plan.source_space)
            await asyncio.to_thread(delete_minio_files, source_file)
            await _clear_tag_links(
                int(source_file.id),
                int(source_file.user_id or self.plan.target_owner.user_id),
                self.plan.tenant_id,
            )
            await _replace_permission_tuples(int(source_file.id), ())
            await asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(source_file.id)])
        except Exception as exc:
            restore_errors = await self._restore_source_artifacts(source_file, target_file)
            detail = f"source deletion failed: {type(exc).__name__}: {exc}"
            if restore_errors:
                detail += f"; source restore errors={restore_errors}"
            raise RuntimeError(detail) from exc
        for space in (self.plan.source_space, self.plan.target_space):
            try:
                await KnowledgeDao.async_update_knowledge_update_time_by_id(int(space.id))
            except Exception:
                # The source row is already deleted at this point. A timestamp
                # refresh failure must not turn a completed move into a false
                # failure whose compensation can no longer restore that row.
                logger.exception("Failed to refresh knowledge-space update time: %s", space.id)

    async def cleanup_target(self, target_file: KnowledgeFile) -> list[str]:
        errors: list[str] = []

        async def attempt(label: str, func) -> None:
            try:
                value = func()
                if asyncio.iscoroutine(value):
                    await value
            except Exception as exc:
                logger.exception("Target compensation failed: %s", label)
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        await attempt(
            "target indexes",
            lambda: asyncio.to_thread(delete_vector_files, [int(target_file.id)], self.plan.target_space),
        )
        await attempt("target objects", lambda: asyncio.to_thread(delete_minio_files, target_file))
        await attempt(
            "target tags",
            lambda: _clear_tag_links(int(target_file.id), int(self.plan.target_owner.user_id), self.plan.tenant_id),
        )
        await attempt("target permissions", lambda: _replace_permission_tuples(int(target_file.id), ()))
        await attempt(
            "target database record",
            lambda: asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(target_file.id)]),
        )
        return errors


def _parameters_for_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source_space_id": args.source_space_id,
        "source_folder_id": args.source_folder_id,
        "source_file_ids": sorted(set(args.source_file_ids)),
        "source_category_codes": _normalize_codes(args.source_category_codes),
        "source_subcategory_codes": _normalize_codes(args.source_subcategory_codes),
        "target_space_id": args.target_space_id,
        "target_folder_id": args.target_folder_id,
        "target_owner_id": args.target_owner_id,
    }


def _print_preflight(plan: PreflightPlan, apply: bool) -> None:
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Tenant: {plan.tenant_id}")
    print(
        f"Source: {plan.source_space.id} ({plan.source_space.name}) -> "
        f"Target: {plan.target_space.id} ({plan.target_space.name})"
    )
    print(
        f"Target folder: {plan.target_folder.id if plan.target_folder else '<root>'}; "
        f"target owner: {plan.target_owner.user_id} ({plan.target_owner.user_name})"
    )
    print(f"Selected: {len(plan.selected_files)}; skipped: {len(plan.skipped_files)}")
    for record in plan.selected_files:
        print(f"[SELECTED] file_id={record.id} name={record.file_name}")
    for item in plan.skipped_files:
        print(f"[SKIPPED] file_id={item.source_file_id} code={item.reason_code} reason={item.reason}")


async def run(args: argparse.Namespace) -> int:
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    report: MoveRunReport | None = None
    context_initialized = False
    try:
        await initialize_app_context(config=settings)
        context_initialized = True
        plan = await build_preflight_plan(args)
        _print_preflight(plan, args.apply)
        report = MoveRunReport(
            mode="apply" if args.apply else "dry-run",
            run_id=run_id,
            parameters=_parameters_for_report(args),
            tenant_id=plan.tenant_id,
            results=[
                _skipped_to_result(item, args.source_space_id, args.target_space_id) for item in plan.skipped_files
            ],
        )
        if not args.apply:
            report.results.extend(
                FileMoveResult(
                    source_file_id=int(file.id),
                    source_space_id=args.source_space_id,
                    source_file_name=file.file_name,
                    target_space_id=args.target_space_id,
                    category_code=parse_shougang_file_encoding_codes(file)[0],
                    subcategory_code=str(file.file_subcategory_code or "").strip().upper(),
                    status="skipped",
                    reason_code="dry_run_selected",
                    error="selected by dry-run; no writes performed",
                )
                for file in plan.selected_files
            )
            output = write_json_report(report, args.report_dir)
            print(f"Dry-run only. Re-run with --apply after reviewing: {output.resolve()}")
            return EXIT_OK

        operations = BishengMoveOperations(plan)
        with _tenant_scope(plan.tenant_id):
            for source_file in plan.selected_files:
                result = await move_one_file(source_file, operations)
                report.results.append(result)
                print(
                    f"[{result.status.upper()}] source_file_id={result.source_file_id} "
                    f"target_file_id={result.target_file_id or '-'} error={result.error or '-'}"
                )
        output = write_json_report(report, args.report_dir)
        print(f"Report: {output.resolve()}")
        summary = report.summary()
        print(
            f"Summary: total={summary['total']} success={summary['success']} "
            f"skipped={summary['skipped']} failed={summary['failed']}"
        )
        return EXIT_APPLY_ERROR if summary["failed"] else EXIT_OK
    except PreflightError as exc:
        logger.error("Preflight failed: %s", exc)
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return EXIT_INPUT_ERROR
    except Exception as exc:
        logger.exception("Knowledge-file move script failed")
        print(f"Script failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_APPLY_ERROR if args.apply else EXIT_DEPENDENCY_ERROR
    finally:
        if report is not None and not report.report_path:
            try:
                output = write_json_report(report, args.report_dir)
                print(f"Report: {output.resolve()}")
            except OSError:
                logger.exception("Failed to write migration report")
        if context_initialized:
            await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
