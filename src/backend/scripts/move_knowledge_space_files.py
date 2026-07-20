#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002
r"""迁移多个来源知识空间中已分类的文件。

可通过来源文件夹 ID 及门户一、二级分类 code 缩小来源范围。默认根据分类 label
路由到公共知识空间及其根目录直属文件夹；也可同时传入两个显式目标 ID，将所有
选中文件迁移至指定的公共或部门文件夹。完整版本链作为一个迁移单元，且必须
整链命中每个已启用的过滤条件。

默认为只读 dry-run。apply 模式排他创建 JSONL 回溯记录，按迁移单元数量分批落盘，
并在第一个失败单元后停止。SIGINT 会等待当前单元结束、落盘记录，然后以退出码 130 结束。

在 ``src/backend`` 目录运行::

    PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
      --source-space-id 10 --source-space-id 11

    PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
      --source-space-id 10 --source-folder-id 100 \
      --source-category-code A --source-subcategory-code A01

    PYTHONPATH=./ .venv/bin/python scripts/move_knowledge_space_files.py \
      --source-space-id 10 --target-space-id 20 --target-folder-id 200 \
      --rollback-record-file migration_reports/move-10-to-20.jsonl \
      --batch-size 10 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from sqlmodel import col, delete, select

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.api.services.knowledge_imp import delete_minio_files, delete_vector_files  # noqa: E402
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
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync  # noqa: E402
from bisheng.database.models.group_resource import ResourceTypeEnum  # noqa: E402
from bisheng.database.models.review_tags import ReviewTagDao  # noqa: E402
from bisheng.database.models.tag import TagDao  # noqa: E402
from bisheng.knowledge.domain.constants import parse_shougang_file_encoding_codes  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
)
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_document_version import (  # noqa: E402
    KnowledgeDocumentVersion,
)
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    FileType,
    KnowledgeFile,
    KnowledgeFileDao,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (  # noqa: E402
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
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
EXIT_INTERRUPTED = 130
_LABEL_FORMAT_CHARACTER_TRANSLATION = str.maketrans("", "", "\u200b\ufeff")


class PreflightError(RuntimeError):
    """Raised when validation must stop the whole batch before any write."""


class TargetCopyError(RuntimeError):
    """Expose a partially created target record to the compensation path."""

    def __init__(self, message: str, target_file: KnowledgeFile | None = None) -> None:
        super().__init__(message)
        self.target_file = target_file


class RollbackRecordError(RuntimeError):
    """JSONL 回溯记录无法持久化。"""


ROLLBACK_RECORD_SCHEMA_VERSION = 1


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return enum_value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    raise TypeError(f"object of type {type(value).__name__} is not JSON serializable")


class RollbackJournal:
    def __init__(self, *, path: Path, run_id: str) -> None:
        self.path = Path(path).expanduser()
        self.run_id = run_id
        self._sequence = 0
        self._buffer: list[str] = []
        self._handle: Any | None = None

    def open(self) -> None:
        if self._handle is not None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            file_descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            try:
                self._handle = os.fdopen(file_descriptor, "w", encoding="utf-8")
            except Exception:
                os.close(file_descriptor)
                raise
        except FileExistsError as exc:
            raise RollbackRecordError(f"rollback record already exists: {self.path}") from exc
        except OSError as exc:
            raise RollbackRecordError(f"unable to create rollback record: {self.path}") from exc

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._handle is None:
            raise RollbackRecordError("rollback record is not open")
        self._sequence += 1
        row = {
            "schema_version": ROLLBACK_RECORD_SCHEMA_VERSION,
            "run_id": self.run_id,
            "sequence": self._sequence,
            "event_type": event_type,
            "timestamp": datetime.now().astimezone().isoformat(),
            "payload": payload,
        }
        try:
            self._buffer.append(json.dumps(row, ensure_ascii=False, sort_keys=True, default=_json_default) + "\n")
        except (TypeError, ValueError) as exc:
            raise RollbackRecordError(f"unable to serialize rollback event: {event_type}") from exc

    def flush(self) -> None:
        if self._handle is None:
            raise RollbackRecordError("rollback record is not open")
        if not self._buffer:
            return
        try:
            self._handle.writelines(self._buffer)
            self._handle.flush()
            os.fsync(self._handle.fileno())
        except OSError as exc:
            raise RollbackRecordError(f"unable to persist rollback record: {self.path}") from exc
        self._buffer.clear()

    def close(self, *, flush: bool = True) -> None:
        if self._handle is None:
            return
        try:
            if flush:
                self.flush()
        finally:
            self._handle.close()
            self._handle = None


def resolve_rollback_record_path(args: argparse.Namespace, run_id: str) -> Path:
    explicit = getattr(args, "rollback_record_file", None)
    if explicit is not None:
        return Path(explicit).expanduser()
    return Path(args.report_dir).expanduser() / f"knowledge-file-move-rollback-{run_id}.jsonl"


@dataclass(frozen=True)
class CategoryResolution:
    category_code: str = ""
    category_label: str = ""
    subcategory_code: str = ""
    subcategory_label: str = ""
    reason_code: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SourceSelection:
    folder_prefixes: tuple[str, ...] = ()
    category_codes: frozenset[str] = frozenset()
    subcategory_codes: frozenset[str] = frozenset()

    def matches(self, record: KnowledgeFile, category: CategoryResolution) -> bool:
        file_level_path = (record.file_level_path or "").rstrip("/")
        if self.folder_prefixes and not any(
            file_level_path == prefix or file_level_path.startswith(f"{prefix}/") for prefix in self.folder_prefixes
        ):
            return False
        if self.category_codes and category.category_code not in self.category_codes:
            return False
        return not self.subcategory_codes or category.subcategory_code in self.subcategory_codes


@dataclass(frozen=True)
class CategoryLabelIndex:
    parent_labels: dict[str, str]
    child_labels: dict[tuple[str, str], str]
    ambiguous_parents: frozenset[str] = frozenset()
    ambiguous_children: frozenset[tuple[str, str]] = frozenset()

    @classmethod
    def from_config(cls, config: Any) -> CategoryLabelIndex:
        parent_values: dict[str, set[str]] = defaultdict(set)
        child_values: dict[tuple[str, str], set[str]] = defaultdict(set)
        document_types = getattr(getattr(config, "portal", None), "document_types", None) or []
        for item in document_types:
            parent_code = _normalize_code(getattr(item, "code", None))
            parent_label = _normalize_label(getattr(item, "label", None))
            if not parent_code or not parent_label:
                continue
            parent_values[parent_code].add(parent_label)
            for child in getattr(item, "children", None) or []:
                child_code = _normalize_code(getattr(child, "code", None))
                child_label = _normalize_label(getattr(child, "label", None))
                if child_code and child_label:
                    child_values[(parent_code, child_code)].add(child_label)

        ambiguous_parents = frozenset(code for code, labels in parent_values.items() if len(labels) != 1)
        ambiguous_children = frozenset(key for key, labels in child_values.items() if len(labels) != 1)
        return cls(
            parent_labels={
                code: next(iter(labels)) for code, labels in parent_values.items() if code not in ambiguous_parents
            },
            child_labels={
                key: next(iter(labels)) for key, labels in child_values.items() if key not in ambiguous_children
            },
            ambiguous_parents=ambiguous_parents,
            ambiguous_children=ambiguous_children,
        )

    def resolve(self, record: KnowledgeFile) -> CategoryResolution:
        category_code, _ = parse_shougang_file_encoding_codes(record)
        category_code = _normalize_code(category_code)
        subcategory_code = _normalize_code(record.file_subcategory_code)
        if not category_code:
            return CategoryResolution(reason_code="missing_category", reason="first-level category is missing")
        if not subcategory_code:
            return CategoryResolution(
                category_code=category_code,
                reason_code="missing_subcategory",
                reason="second-level category is missing",
            )
        if category_code in self.ambiguous_parents:
            return CategoryResolution(
                category_code=category_code,
                subcategory_code=subcategory_code,
                reason_code="ambiguous_category_config",
                reason="first-level category has conflicting labels in portal config",
            )
        category_label = self.parent_labels.get(category_code, "")
        if not category_label:
            return CategoryResolution(
                category_code=category_code,
                subcategory_code=subcategory_code,
                reason_code="unknown_category",
                reason="first-level category is absent from portal config",
            )
        child_key = (category_code, subcategory_code)
        if child_key in self.ambiguous_children:
            return CategoryResolution(
                category_code=category_code,
                category_label=category_label,
                subcategory_code=subcategory_code,
                reason_code="ambiguous_subcategory_config",
                reason="second-level category has conflicting labels in portal config",
            )
        subcategory_label = self.child_labels.get(child_key, "")
        if not subcategory_label:
            return CategoryResolution(
                category_code=category_code,
                category_label=category_label,
                subcategory_code=subcategory_code,
                reason_code="unknown_subcategory",
                reason="second-level category is absent from its parent portal category",
            )
        return CategoryResolution(
            category_code=category_code,
            category_label=category_label,
            subcategory_code=subcategory_code,
            subcategory_label=subcategory_label,
        )


@dataclass(frozen=True)
class TargetContext:
    tenant_id: int
    space: Knowledge
    folder: KnowledgeFile
    owner: User
    file_level_path: str
    level: int

    @property
    def key(self) -> tuple[int, int]:
        return int(self.space.id or 0), int(self.folder.id or 0)


def build_explicit_target_context(
    *,
    tenant_id: int,
    space: Knowledge,
    scope: KnowledgeSpaceScope,
    folder: KnowledgeFile,
    owner: User,
) -> TargetContext:
    if (
        space.id is None
        or int(space.type) != KnowledgeTypeEnum.SPACE.value
        or int(space.tenant_id or 1) != tenant_id
        or int(scope.tenant_id or 1) != tenant_id
    ):
        raise PreflightError("explicit target knowledge space must belong to the source tenant")
    if int(scope.space_id) != int(space.id):
        raise PreflightError("explicit target scope does not belong to the target knowledge space")
    scope_level = str(getattr(scope.level, "value", scope.level))
    allowed_levels = {
        KnowledgeSpaceLevelEnum.PUBLIC.value,
        KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    }
    if scope_level not in allowed_levels:
        raise PreflightError("explicit target knowledge space must be public or department")
    if int(folder.knowledge_id) != int(space.id) or int(folder.file_type) != FileType.DIR.value:
        raise PreflightError("explicit target folder is missing or does not belong to the target knowledge space")
    if owner.user_id is None or int(owner.delete or 0) != 0 or int(owner.user_id) != int(space.user_id or 0):
        raise PreflightError("explicit target knowledge-space owner is missing or disabled")
    return TargetContext(
        tenant_id=tenant_id,
        space=space,
        folder=folder,
        owner=owner,
        file_level_path=_folder_child_path(folder),
        level=int(folder.level or 0) + 1,
    )


@dataclass(frozen=True)
class RouteResolution:
    target: TargetContext | None = None
    reason_code: str = ""
    reason: str = ""


@dataclass(frozen=True)
class TargetRouteIndex:
    tenant_id: int
    spaces_by_name: dict[str, tuple[Knowledge, ...]]
    folders_by_space_and_name: dict[tuple[int, str], tuple[KnowledgeFile, ...]]
    owners_by_id: dict[int, User]

    @classmethod
    def from_records(
        cls,
        tenant_id: int,
        public_spaces: Sequence[Knowledge],
        folders: Sequence[KnowledgeFile],
        owners_by_id: dict[int, User],
    ) -> TargetRouteIndex:
        spaces: dict[str, list[Knowledge]] = defaultdict(list)
        for space in sorted(public_spaces, key=lambda item: int(item.id or 0)):
            name = _normalize_label(space.name)
            if name:
                spaces[name].append(space)

        root_folders: dict[tuple[int, str], list[KnowledgeFile]] = defaultdict(list)
        for folder in sorted(folders, key=lambda item: int(item.id or 0)):
            if int(folder.file_type) != FileType.DIR.value or (folder.file_level_path or "") != "":
                continue
            name = _normalize_label(folder.file_name)
            if name:
                root_folders[(int(folder.knowledge_id), name)].append(folder)
        return cls(
            tenant_id=tenant_id,
            spaces_by_name={key: tuple(value) for key, value in spaces.items()},
            folders_by_space_and_name={key: tuple(value) for key, value in root_folders.items()},
            owners_by_id=dict(owners_by_id),
        )

    def resolve(self, category_label: str, subcategory_label: str) -> RouteResolution:
        spaces = self.spaces_by_name.get(_normalize_label(category_label), ())
        if not spaces:
            return RouteResolution(
                reason_code="target_space_not_found",
                reason="no public knowledge space matches the first-level category label",
            )
        if len(spaces) != 1:
            return RouteResolution(
                reason_code="target_space_ambiguous",
                reason="multiple public knowledge spaces match the first-level category label",
            )
        space = spaces[0]
        folders = self.folders_by_space_and_name.get(
            (int(space.id or 0), _normalize_label(subcategory_label)),
            (),
        )
        if not folders:
            return RouteResolution(
                reason_code="target_folder_not_found",
                reason="no direct root folder matches the second-level category label",
            )
        if len(folders) != 1:
            return RouteResolution(
                reason_code="target_folder_ambiguous",
                reason="multiple direct root folders match the second-level category label",
            )
        owner = self.owners_by_id.get(int(space.user_id or 0))
        if owner is None or owner.user_id is None or int(owner.delete or 0) != 0:
            return RouteResolution(
                reason_code="target_owner_invalid",
                reason="target public knowledge-space owner is missing or disabled",
            )
        folder = folders[0]
        return RouteResolution(
            target=TargetContext(
                tenant_id=self.tenant_id,
                space=space,
                folder=folder,
                owner=owner,
                file_level_path=_folder_child_path(folder),
                level=int(folder.level or 0) + 1,
            )
        )


@dataclass(frozen=True)
class SkippedFile:
    source_file_id: int
    source_space_id: int
    source_file_name: str
    reason_code: str
    reason: str
    unit_id: str = ""
    unit_type: Literal["file", "version_chain"] = "file"
    source_document_id: int | None = None
    version_no: int | None = None
    category_code: str = ""
    category_label: str = ""
    subcategory_code: str = ""
    subcategory_label: str = ""
    target_space_id: int | None = None
    target_folder_id: int | None = None


@dataclass
class FileMoveResult:
    source_file_id: int
    source_space_id: int
    source_file_name: str
    status: Literal["success", "skipped", "failed"]
    unit_id: str = ""
    unit_type: Literal["file", "version_chain"] = "file"
    source_document_id: int | None = None
    target_document_id: int | None = None
    target_version_id: int | None = None
    version_no: int | None = None
    target_space_id: int | None = None
    target_folder_id: int | None = None
    target_file_id: int | None = None
    category_code: str = ""
    category_label: str = ""
    subcategory_code: str = ""
    subcategory_label: str = ""
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
    run_status: Literal["running", "completed", "failed", "interrupted"] = "running"
    termination_reason: str = ""
    rollback_record_path: str = ""
    pending_units: int = 0

    def summary(self) -> dict[str, int]:
        counts = {"total": len(self.results), "success": 0, "skipped": 0, "failed": 0}
        for result in self.results:
            counts[result.status] += 1
        return counts


@dataclass(frozen=True)
class MigrationUnit:
    unit_id: str
    unit_type: Literal["file", "version_chain"]
    source_files: tuple[KnowledgeFile, ...]
    target: TargetContext
    category_code: str
    category_label: str
    subcategory_code: str
    subcategory_label: str
    source_document: KnowledgeDocument | None = None
    source_versions: tuple[KnowledgeDocumentVersion, ...] = ()


@dataclass
class MigrationPlan:
    tenant_id: int
    source_spaces: dict[int, Knowledge]
    selected_units: list[MigrationUnit]
    skipped_files: list[SkippedFile]


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
class StopController:
    requested: bool = False

    def request_stop(self) -> None:
        self.requested = True


@dataclass
class CompletedMigration:
    unit: MigrationUnit
    results: list[FileMoveResult]


class MoveOperations(Protocol):
    async def snapshot_unit(self, unit: MigrationUnit) -> None: ...

    async def copy_file(self, source_file: KnowledgeFile, target: TargetContext) -> KnowledgeFile: ...

    async def copy_tags(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def write_permissions(self, target_file: KnowledgeFile, target: TargetContext) -> None: ...

    async def verify_target(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def delete_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None: ...

    async def restore_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> list[str]: ...

    async def cleanup_target(self, target_file: KnowledgeFile, target: TargetContext) -> list[str]: ...


class VersionGraphStore(Protocol):
    async def create_target_graph(
        self,
        unit: MigrationUnit,
        target_files: Sequence[KnowledgeFile],
    ) -> int: ...

    async def verify_target_graph(
        self,
        unit: MigrationUnit,
        target_document_id: int,
        target_files: Sequence[KnowledgeFile],
    ) -> None: ...

    async def delete_source_graph(self, unit: MigrationUnit) -> None: ...

    async def restore_source_graph(self, unit: MigrationUnit) -> list[str]: ...

    async def delete_target_graph(self, target_document_id: int) -> list[str]: ...

    def get_target_graph_payload(self, target_document_id: int) -> dict[str, Any] | None: ...


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _category_code(value: str) -> str:
    normalized = _normalize_code(value)
    if not normalized:
        raise argparse.ArgumentTypeError("value must be a non-empty category code")
    return normalized


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source-space-id",
        dest="source_space_ids",
        required=True,
        action="append",
        type=_positive_int,
        help="来源知识空间 ID；可重复传入",
    )
    parser.add_argument(
        "--source-folder-id",
        dest="source_folder_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="递归选择该来源文件夹的子孙文件；可重复传入",
    )
    parser.add_argument(
        "--source-category-code",
        dest="source_category_codes",
        action="append",
        type=_category_code,
        default=[],
        help="按门户一级分类 code 过滤；可重复传入",
    )
    parser.add_argument(
        "--source-subcategory-code",
        dest="source_subcategory_codes",
        action="append",
        type=_category_code,
        default=[],
        help="按门户二级分类 code 过滤；可重复传入",
    )
    parser.add_argument(
        "--target-space-id",
        type=_positive_int,
        default=None,
        help="显式指定公共或部门目标知识空间 ID；必须与 --target-folder-id 同时传入",
    )
    parser.add_argument(
        "--target-folder-id",
        type=_positive_int,
        default=None,
        help="显式指定任意层级的目标文件夹 ID；必须与 --target-space-id 同时传入",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=Path("migration_reports/knowledge_file_move"),
        help="JSON 运行报告目录",
    )
    parser.add_argument(
        "--rollback-record-file",
        type=Path,
        default=None,
        help="apply 模式排他创建的 JSONL 回溯记录路径",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=10,
        help="每完成多少个迁移单元落盘一次回溯记录；默认 10",
    )
    parser.add_argument("--apply", action="store_true", help="执行真实迁移；默认为只读 dry-run")
    args = parser.parse_args(argv)
    args.source_space_ids = sorted(set(args.source_space_ids))
    args.source_folder_ids = sorted(set(args.source_folder_ids))
    args.source_category_codes = sorted(set(args.source_category_codes))
    args.source_subcategory_codes = sorted(set(args.source_subcategory_codes))
    if (args.target_space_id is None) != (args.target_folder_id is None):
        parser.error("--target-space-id and --target-folder-id must be provided together")
    return args


def _normalize_code(value: Any) -> str:
    return str(value or "").strip().upper()


def _normalize_label(value: Any) -> str:
    return str(value or "").translate(_LABEL_FORMAT_CHARACTER_TRANSLATION).strip()


def _folder_child_path(folder: KnowledgeFile) -> str:
    base = (folder.file_level_path or "").rstrip("/")
    return f"{base}/{folder.id}" if base else f"/{folder.id}"


def build_source_selection(
    args: argparse.Namespace,
    source_records: Sequence[KnowledgeFile],
    category_index: CategoryLabelIndex,
) -> SourceSelection:
    requested_folder_ids = set(getattr(args, "source_folder_ids", []) or [])
    folders_by_id = {
        int(record.id): record
        for record in source_records
        if record.id is not None and int(record.file_type) == FileType.DIR.value
    }
    missing_folder_ids = sorted(requested_folder_ids - set(folders_by_id))
    if missing_folder_ids:
        raise PreflightError(
            f"source folders not found, not directories, or outside the requested spaces: {missing_folder_ids}"
        )

    category_codes = frozenset(getattr(args, "source_category_codes", []) or [])
    subcategory_codes = frozenset(getattr(args, "source_subcategory_codes", []) or [])
    invalid_category_codes = sorted(category_codes - set(category_index.parent_labels))
    if invalid_category_codes:
        raise PreflightError(
            f"source category codes are absent or ambiguous in portal config: {invalid_category_codes}"
        )

    child_keys = set(category_index.child_labels)
    known_subcategory_codes = {subcategory_code for _, subcategory_code in child_keys}
    invalid_subcategory_codes = sorted(subcategory_codes - known_subcategory_codes)
    if invalid_subcategory_codes:
        raise PreflightError(
            f"source subcategory codes are absent or ambiguous in portal config: {invalid_subcategory_codes}"
        )
    if category_codes:
        unrelated_subcategory_codes = sorted(
            subcategory_code
            for subcategory_code in subcategory_codes
            if not any((category_code, subcategory_code) in child_keys for category_code in category_codes)
        )
        if unrelated_subcategory_codes:
            raise PreflightError(
                "source subcategory codes do not belong to the requested first-level categories: "
                f"{unrelated_subcategory_codes}"
            )

    return SourceSelection(
        folder_prefixes=tuple(
            _folder_child_path(folders_by_id[folder_id]) for folder_id in sorted(requested_folder_ids)
        ),
        category_codes=category_codes,
        subcategory_codes=subcategory_codes,
    )


def _skip_for_file(
    record: KnowledgeFile,
    reason_code: str,
    reason: str,
    *,
    unit_id: str | None = None,
    unit_type: Literal["file", "version_chain"] = "file",
    source_document_id: int | None = None,
    version_no: int | None = None,
    category: CategoryResolution | None = None,
    target: TargetContext | None = None,
) -> SkippedFile:
    category = category or CategoryResolution()
    return SkippedFile(
        source_file_id=int(record.id or 0),
        source_space_id=int(record.knowledge_id),
        source_file_name=record.file_name,
        reason_code=reason_code,
        reason=reason,
        unit_id=unit_id or f"file:{record.id}",
        unit_type=unit_type,
        source_document_id=source_document_id,
        version_no=version_no,
        category_code=category.category_code,
        category_label=category.category_label,
        subcategory_code=category.subcategory_code,
        subcategory_label=category.subcategory_label,
        target_space_id=int(target.space.id) if target else None,
        target_folder_id=int(target.folder.id) if target else None,
    )


def _version_no_by_file(versions: Sequence[KnowledgeDocumentVersion]) -> dict[int, int]:
    return {int(version.knowledge_file_id): int(version.version_no) for version in versions}


def _skip_unit(unit: MigrationUnit, reason_code: str, reason: str) -> list[SkippedFile]:
    version_numbers = _version_no_by_file(unit.source_versions)
    return [
        _skip_for_file(
            record,
            reason_code,
            reason,
            unit_id=unit.unit_id,
            unit_type=unit.unit_type,
            source_document_id=int(unit.source_document.id) if unit.source_document else None,
            version_no=version_numbers.get(int(record.id or 0)),
            category=CategoryResolution(
                category_code=unit.category_code,
                category_label=unit.category_label,
                subcategory_code=unit.subcategory_code,
                subcategory_label=unit.subcategory_label,
            ),
            target=unit.target,
        )
        for record in unit.source_files
    ]


def _resolve_single_unit(
    record: KnowledgeFile,
    source_spaces: dict[int, Knowledge],
    category_index: CategoryLabelIndex,
    target_index: TargetRouteIndex,
    source_selection: SourceSelection,
    explicit_target: TargetContext | None,
) -> tuple[MigrationUnit | None, SkippedFile | None]:
    category = category_index.resolve(record)
    if category.reason_code:
        return None, _skip_for_file(record, category.reason_code, category.reason, category=category)
    if not source_selection.matches(record, category):
        return None, _skip_for_file(
            record,
            "source_filter_mismatch",
            "file is outside the requested source folder or category filters",
            category=category,
        )
    route = (
        RouteResolution(target=explicit_target)
        if explicit_target
        else target_index.resolve(
            category.category_label,
            category.subcategory_label,
        )
    )
    if route.reason_code or route.target is None:
        return None, _skip_for_file(
            record,
            route.reason_code,
            route.reason,
            category=category,
        )
    source_space = source_spaces[int(record.knowledge_id)]
    if str(source_space.model or "") != str(route.target.space.model or ""):
        return None, _skip_for_file(
            record,
            "embedding_model_mismatch",
            "source and target knowledge spaces use different embedding models",
            category=category,
            target=route.target,
        )
    return (
        MigrationUnit(
            unit_id=f"file:{record.id}",
            unit_type="file",
            source_files=(record,),
            target=route.target,
            category_code=category.category_code,
            category_label=category.category_label,
            subcategory_code=category.subcategory_code,
            subcategory_label=category.subcategory_label,
        ),
        None,
    )


def _resolve_chain_unit(
    document_id: int,
    versions: Sequence[KnowledgeDocumentVersion],
    source_spaces: dict[int, Knowledge],
    all_files_by_id: dict[int, KnowledgeFile],
    documents_by_id: dict[int, KnowledgeDocument],
    category_index: CategoryLabelIndex,
    target_index: TargetRouteIndex,
    source_selection: SourceSelection,
    explicit_target: TargetContext | None,
) -> tuple[MigrationUnit | None, list[SkippedFile]]:
    ordered_versions = tuple(sorted(versions, key=lambda item: (int(item.version_no), int(item.id or 0))))
    document = documents_by_id.get(document_id)
    known_files = [all_files_by_id.get(int(version.knowledge_file_id)) for version in ordered_versions]
    traceable_files = [record for record in known_files if record is not None]
    version_numbers = _version_no_by_file(ordered_versions)
    unit_id = f"document:{document_id}"

    def skip_known(
        reason_code: str,
        reason: str,
        *,
        category: CategoryResolution | None = None,
    ) -> list[SkippedFile]:
        return [
            _skip_for_file(
                record,
                reason_code,
                reason,
                unit_id=unit_id,
                unit_type="version_chain",
                source_document_id=document_id,
                version_no=version_numbers.get(int(record.id or 0)),
                category=category,
            )
            for record in traceable_files
        ]

    if document is None or any(record is None for record in known_files):
        return None, skip_known("version_chain_incomplete", "version chain metadata or physical file is missing")
    source_ids = set(source_spaces)
    if int(document.knowledge_id) not in source_ids or any(
        int(record.knowledge_id) not in source_ids for record in traceable_files
    ):
        return None, skip_known(
            "version_chain_out_of_scope",
            "at least one version is outside the requested source spaces",
        )
    if any(
        int(record.file_type) != FileType.FILE.value or int(record.status or 0) != KnowledgeFileStatus.SUCCESS.value
        for record in traceable_files
    ):
        return None, skip_known(
            "version_chain_ineligible_file",
            "at least one version is not a successful physical file",
        )

    primary_versions = [version for version in ordered_versions if version.is_primary]
    version_ids = [version.id for version in ordered_versions]
    version_numbers_in_chain = [int(version.version_no) for version in ordered_versions]
    file_ids_in_chain = [int(version.knowledge_file_id) for version in ordered_versions]
    if (
        len(primary_versions) != 1
        or any(version_id is None for version_id in version_ids)
        or len(set(version_ids)) != len(version_ids)
        or any(version_no <= 0 for version_no in version_numbers_in_chain)
        or len(set(version_numbers_in_chain)) != len(version_numbers_in_chain)
        or len(set(file_ids_in_chain)) != len(file_ids_in_chain)
        or document.primary_version_id is None
        or int(document.primary_version_id) != int(primary_versions[0].id or 0)
    ):
        return None, skip_known(
            "version_chain_invalid_graph",
            "version chain must have exactly one primary version matching the document pointer",
        )

    categories = [category_index.resolve(record) for record in traceable_files]
    if any(category.reason_code for category in categories):
        return None, skip_known(
            "version_chain_classification_invalid",
            "at least one version lacks a valid first- or second-level category",
        )
    if any(
        not source_selection.matches(record, category)
        for record, category in zip(traceable_files, categories, strict=True)
    ):
        return None, skip_known(
            "version_chain_filter_mismatch",
            "at least one version is outside the requested source folder or category filters",
        )
    category_keys = {
        (
            category.category_code,
            category.subcategory_code,
            category.category_label,
            category.subcategory_label,
        )
        for category in categories
    }
    if len(category_keys) != 1:
        return None, skip_known(
            "version_chain_classification_mismatch",
            "versions in one document have different classifications",
        )
    category = categories[0]
    route = (
        RouteResolution(target=explicit_target)
        if explicit_target
        else target_index.resolve(
            category.category_label,
            category.subcategory_label,
        )
    )
    if route.reason_code or route.target is None:
        route_detail = f"{route.reason_code}: {route.reason}" if route.reason_code else route.reason
        return None, skip_known(
            "version_chain_target_unresolved",
            route_detail or "version chain cannot resolve a unique target",
            category=category,
        )
    target = route.target
    if any(
        str(source_spaces[int(record.knowledge_id)].model or "") != str(target.space.model or "")
        for record in traceable_files
    ):
        return None, skip_known(
            "embedding_model_mismatch",
            "source and target knowledge spaces use different embedding models",
        )
    return (
        MigrationUnit(
            unit_id=unit_id,
            unit_type="version_chain",
            source_files=tuple(traceable_files),
            target=target,
            category_code=category.category_code,
            category_label=category.category_label,
            subcategory_code=category.subcategory_code,
            subcategory_label=category.subcategory_label,
            source_document=document,
            source_versions=ordered_versions,
        ),
        [],
    )


def plan_migration_units(
    *,
    tenant_id: int,
    source_spaces: dict[int, Knowledge],
    source_records: Sequence[KnowledgeFile],
    all_files_by_id: dict[int, KnowledgeFile],
    documents_by_id: dict[int, KnowledgeDocument],
    versions: Sequence[KnowledgeDocumentVersion],
    category_index: CategoryLabelIndex,
    target_index: TargetRouteIndex,
    target_files: Sequence[KnowledgeFile],
    source_selection: SourceSelection | None = None,
    explicit_target: TargetContext | None = None,
) -> MigrationPlan:
    source_selection = source_selection or SourceSelection()
    eligible = sorted(
        (
            record
            for record in source_records
            if int(record.file_type) == FileType.FILE.value
            and int(record.status or 0) == KnowledgeFileStatus.SUCCESS.value
        ),
        key=lambda item: (int(item.knowledge_id), int(item.id or 0)),
    )
    versions_by_file = {int(version.knowledge_file_id): version for version in versions}
    versions_by_document: dict[int, list[KnowledgeDocumentVersion]] = defaultdict(list)
    for version in versions:
        versions_by_document[int(version.document_id)].append(version)

    preliminary: list[MigrationUnit] = []
    skipped: list[SkippedFile] = []
    handled_documents: set[int] = set()
    for record in eligible:
        version = versions_by_file.get(int(record.id or 0))
        if version is not None:
            document_id = int(version.document_id)
            if document_id in handled_documents:
                continue
            handled_documents.add(document_id)
            unit, chain_skips = _resolve_chain_unit(
                document_id,
                versions_by_document[document_id],
                source_spaces,
                all_files_by_id,
                documents_by_id,
                category_index,
                target_index,
                source_selection,
                explicit_target,
            )
            if unit is not None:
                preliminary.append(unit)
            skipped.extend(chain_skips)
            continue
        unit, file_skip = _resolve_single_unit(
            record,
            source_spaces,
            category_index,
            target_index,
            source_selection,
            explicit_target,
        )
        if unit is not None:
            preliminary.append(unit)
        elif file_skip is not None:
            skipped.append(file_skip)

    preliminary.sort(
        key=lambda unit: min((int(record.knowledge_id), int(record.id or 0)) for record in unit.source_files)
    )
    existing_names = {
        (
            int(record.knowledge_id),
            record.file_level_path or "",
            record.file_name,
        )
        for record in target_files
        if int(record.file_type) == FileType.FILE.value
    }
    existing_md5s = {
        (int(record.knowledge_id), str(record.md5))
        for record in target_files
        if int(record.file_type) == FileType.FILE.value and record.md5
    }
    reserved_names: set[tuple[int, str, str]] = set()
    reserved_md5s: set[tuple[int, str]] = set()
    selected: list[MigrationUnit] = []
    for unit in preliminary:
        space_id = int(unit.target.space.id or 0)
        unit_names = {(space_id, unit.target.file_level_path, record.file_name) for record in unit.source_files}
        unit_md5s = {(space_id, str(record.md5)) for record in unit.source_files if record.md5}
        if unit_names & existing_names:
            skipped.extend(_skip_unit(unit, "target_name_conflict", "target folder contains the same file name"))
            continue
        if unit_md5s & existing_md5s:
            skipped.extend(_skip_unit(unit, "target_md5_conflict", "target space contains the same MD5"))
            continue
        if unit_names & reserved_names:
            skipped.extend(
                _skip_unit(unit, "batch_name_conflict", "an earlier source unit reserved the same target name")
            )
            continue
        if unit_md5s & reserved_md5s:
            skipped.extend(
                _skip_unit(unit, "batch_md5_conflict", "an earlier source unit reserved the same target MD5")
            )
            continue
        selected.append(unit)
        reserved_names.update(unit_names)
        reserved_md5s.update(unit_md5s)

    skipped.sort(key=lambda item: (item.source_space_id, item.source_file_id, item.reason_code))
    return MigrationPlan(
        tenant_id=tenant_id,
        source_spaces=dict(sorted(source_spaces.items())),
        selected_units=selected,
        skipped_files=skipped,
    )


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


@contextmanager
def _sigint_stop_scope(controller: StopController, *, enabled: bool):
    if not enabled:
        yield
        return
    try:
        previous_handler = signal.getsignal(signal.SIGINT)

        def request_stop(_signum: int, _frame: Any) -> None:
            if not controller.requested:
                print("SIGINT received; finishing the current migration unit before stopping.", file=sys.stderr)
            controller.request_stop()

        signal.signal(signal.SIGINT, request_stop)
    except (ValueError, OSError):
        logger.warning("Unable to install SIGINT handler; graceful stop is unavailable in this thread")
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous_handler)


async def _load_source_spaces(source_space_ids: Sequence[int]) -> tuple[int, dict[int, Knowledge]]:
    requested_ids = set(source_space_ids)
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            rows = (
                await session.exec(
                    select(Knowledge).where(
                        col(Knowledge.id).in_(requested_ids),
                        Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                    )
                )
            ).all()
    spaces = {int(space.id): space for space in rows if space.id is not None}
    missing = sorted(requested_ids - set(spaces))
    if missing:
        raise PreflightError(f"source knowledge spaces not found or not SPACE: {missing}")
    tenant_ids = {int(space.tenant_id or 1) for space in spaces.values()}
    if len(tenant_ids) != 1:
        raise PreflightError("source knowledge spaces must belong to the same tenant")
    return next(iter(tenant_ids)), dict(sorted(spaces.items()))


async def build_migration_plan(args: argparse.Namespace) -> MigrationPlan:
    tenant_id, source_spaces = await _load_source_spaces(args.source_space_ids)
    source_ids = sorted(source_spaces)
    with _tenant_scope(tenant_id):
        portal_config = await ShougangPortalConfigService.get_config(tenant_id=tenant_id)
        category_index = CategoryLabelIndex.from_config(portal_config)
        async with get_async_db_session() as session:
            source_records = list(
                (
                    await session.exec(
                        select(KnowledgeFile)
                        .where(col(KnowledgeFile.knowledge_id).in_(source_ids))
                        .order_by(col(KnowledgeFile.knowledge_id), col(KnowledgeFile.id))
                    )
                ).all()
            )
            source_selection = build_source_selection(args, source_records, category_index)
            eligible_ids = [
                int(record.id)
                for record in source_records
                if record.id is not None
                and int(record.file_type) == FileType.FILE.value
                and int(record.status or 0) == KnowledgeFileStatus.SUCCESS.value
            ]
            initial_versions: list[KnowledgeDocumentVersion] = []
            if eligible_ids:
                initial_versions = list(
                    (
                        await session.exec(
                            select(KnowledgeDocumentVersion).where(
                                col(KnowledgeDocumentVersion.knowledge_file_id).in_(eligible_ids)
                            )
                        )
                    ).all()
                )
            document_ids = sorted({int(version.document_id) for version in initial_versions})
            versions: list[KnowledgeDocumentVersion] = []
            documents: list[KnowledgeDocument] = []
            if document_ids:
                versions = list(
                    (
                        await session.exec(
                            select(KnowledgeDocumentVersion)
                            .where(col(KnowledgeDocumentVersion.document_id).in_(document_ids))
                            .order_by(
                                col(KnowledgeDocumentVersion.document_id),
                                col(KnowledgeDocumentVersion.version_no),
                            )
                        )
                    ).all()
                )
                documents = list(
                    (
                        await session.exec(select(KnowledgeDocument).where(col(KnowledgeDocument.id).in_(document_ids)))
                    ).all()
                )
            all_files_by_id = {int(record.id): record for record in source_records if record.id is not None}
            chain_file_ids = {int(version.knowledge_file_id) for version in versions} - set(all_files_by_id)
            if chain_file_ids:
                chain_files = (
                    await session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(chain_file_ids)))
                ).all()
                all_files_by_id.update({int(record.id): record for record in chain_files if record.id is not None})

            public_scopes = (
                await session.exec(
                    select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.level == KnowledgeSpaceLevelEnum.PUBLIC.value)
                )
            ).all()
            public_space_ids = sorted({int(scope.space_id) for scope in public_scopes})
            public_spaces: list[Knowledge] = []
            target_records: list[KnowledgeFile] = []
            target_space_ids = set(public_space_ids)
            if args.target_space_id is not None:
                target_space_ids.add(int(args.target_space_id))
            if target_space_ids:
                public_spaces = list(
                    (
                        await session.exec(
                            select(Knowledge).where(
                                col(Knowledge.id).in_(sorted(target_space_ids)),
                                Knowledge.type == KnowledgeTypeEnum.SPACE.value,
                            )
                        )
                    ).all()
                )
                target_records = list(
                    (
                        await session.exec(
                            select(KnowledgeFile).where(col(KnowledgeFile.knowledge_id).in_(sorted(target_space_ids)))
                        )
                    ).all()
                )
            spaces_by_id = {int(space.id): space for space in public_spaces if space.id is not None}
            explicit_scope: KnowledgeSpaceScope | None = None
            if args.target_space_id is not None:
                explicit_scope = (
                    await session.exec(
                        select(KnowledgeSpaceScope).where(KnowledgeSpaceScope.space_id == int(args.target_space_id))
                    )
                ).first()
            owner_ids = sorted({int(space.user_id or 0) for space in public_spaces if space.user_id})
            owners: list[User] = []
            if owner_ids:
                owners = list((await session.exec(select(User).where(col(User.user_id).in_(owner_ids)))).all())

        route_public_spaces = [space for space in public_spaces if int(space.id or 0) in set(public_space_ids)]
        owners_by_id = {int(owner.user_id): owner for owner in owners if owner.user_id is not None}
        target_index = TargetRouteIndex.from_records(
            tenant_id,
            route_public_spaces,
            [record for record in target_records if int(record.file_type) == FileType.DIR.value],
            owners_by_id,
        )
        explicit_target: TargetContext | None = None
        if args.target_space_id is not None and args.target_folder_id is not None:
            explicit_space = spaces_by_id.get(int(args.target_space_id))
            explicit_folder = next(
                (record for record in target_records if int(record.id or 0) == int(args.target_folder_id)),
                None,
            )
            explicit_owner = owners_by_id.get(int(explicit_space.user_id or 0)) if explicit_space else None
            if explicit_space is None or explicit_scope is None or explicit_folder is None or explicit_owner is None:
                raise PreflightError(
                    "explicit target knowledge space, folder, scope, or active owner was not found in the source tenant"
                )
            explicit_target = build_explicit_target_context(
                tenant_id=tenant_id,
                space=explicit_space,
                scope=explicit_scope,
                folder=explicit_folder,
                owner=explicit_owner,
            )
        return plan_migration_units(
            tenant_id=tenant_id,
            source_spaces=source_spaces,
            source_records=source_records,
            all_files_by_id=all_files_by_id,
            documents_by_id={int(document.id): document for document in documents if document.id is not None},
            versions=versions,
            category_index=category_index,
            target_index=target_index,
            target_files=[record for record in target_records if int(record.file_type) == FileType.FILE.value],
            source_selection=source_selection,
            explicit_target=explicit_target,
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
    client = get_minio_storage_sync()
    return {
        key: bool(name) and bool(client.object_exists_sync(client.bucket, name))
        for key, name in _storage_object_names(file).items()
    }


def _copy_object_if_present(source_name: str, target_name: str) -> None:
    if not source_name or not target_name:
        return
    client = get_minio_storage_sync()
    if not client.object_exists_sync(client.bucket, source_name):
        return
    client.copy_object_sync(
        source_bucket=client.bucket,
        source_object=source_name,
        dest_bucket=client.bucket,
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


def _target_permission_rows(
    target_file: KnowledgeFile,
    target: TargetContext,
) -> tuple[dict[str, str], ...]:
    object_ref = f"knowledge_file:{target_file.id}"
    return (
        {"user": f"user:{target.owner.user_id}", "relation": "owner", "object": object_ref},
        {"user": f"folder:{target.folder.id}", "relation": "parent", "object": object_ref},
    )


class BishengMoveOperations:
    def __init__(self, tenant_id: int, source_spaces: dict[int, Knowledge]) -> None:
        self.tenant_id = tenant_id
        self.source_spaces = source_spaces
        self.snapshots: dict[int, SourceSnapshot] = {}
        self.target_files_by_source_id: dict[int, KnowledgeFile] = {}

    def _source_space(self, source_file: KnowledgeFile) -> Knowledge:
        try:
            return self.source_spaces[int(source_file.knowledge_id)]
        except KeyError as exc:
            raise PreflightError(f"source space {source_file.knowledge_id} is outside the plan") from exc

    async def _snapshot_source(self, source_file: KnowledgeFile) -> SourceSnapshot:
        file_id = int(source_file.id or 0)
        cached = self.snapshots.get(file_id)
        if cached is not None:
            return cached
        snapshot = SourceSnapshot(
            tags=await _tag_snapshot(file_id, self.tenant_id),
            permissions=await _read_permission_tuples(file_id),
            indexes=await asyncio.to_thread(_index_snapshot, self._source_space(source_file), file_id),
            storage_exists=await asyncio.to_thread(_storage_exists, source_file),
        )
        self.snapshots[file_id] = snapshot
        return snapshot

    async def snapshot_unit(self, unit: MigrationUnit) -> None:
        for source_file in unit.source_files:
            await self._snapshot_source(source_file)

    async def copy_file(self, source_file: KnowledgeFile, target: TargetContext) -> KnowledgeFile:
        snapshot = await self._snapshot_source(source_file)
        target_file = await asyncio.to_thread(
            copy_normal,
            source_file,
            self._source_space(source_file),
            target.space,
            int(target.owner.user_id),
            target_level=target.level,
            target_file_level_path=target.file_level_path,
        )
        if target_file is None or target_file.id is None:
            raise TargetCopyError("copy_normal did not create a target file")
        try:
            if target_file.status != KnowledgeFileStatus.SUCCESS.value:
                raise RuntimeError(f"target file status is {target_file.status}, expected SUCCESS")
            target_file.user_id = int(target.owner.user_id)
            target_file.user_name = target.owner.user_name
            target_file.updater_id = int(target.owner.user_id)
            target_file.updater_name = target.owner.user_name

            source_preview = _storage_object_names(source_file)["preview"]
            target_preview = _target_preview_object_name(source_file, target_file)
            if snapshot.storage_exists.get("preview", False):
                await asyncio.to_thread(_copy_object_if_present, source_preview, target_preview)
                target_file.preview_file_object_name = target_preview
            else:
                target_file.preview_file_object_name = None
            target_file = await KnowledgeFileDao.async_update(target_file)
            self.target_files_by_source_id[int(source_file.id)] = target_file
            return target_file
        except Exception as exc:
            raise TargetCopyError(str(exc), target_file) from exc

    async def copy_tags(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        await _restore_tag_links(
            int(target_file.id),
            int(target.owner.user_id),
            self.tenant_id,
            self.snapshots[int(source_file.id)].tags,
        )

    @staticmethod
    def _target_permission_rows(
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> tuple[dict[str, str], ...]:
        return _target_permission_rows(target_file, target)

    async def write_permissions(self, target_file: KnowledgeFile, target: TargetContext) -> None:
        await _replace_permission_tuples(
            int(target_file.id),
            self._target_permission_rows(target_file, target),
        )

    async def verify_target(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        current = await KnowledgeFileDao.query_by_id(int(target_file.id))
        if current is None or current.status != KnowledgeFileStatus.SUCCESS.value:
            raise RuntimeError("target database record is missing or not SUCCESS")
        if int(current.knowledge_id) != int(target.space.id):
            raise RuntimeError("target database record belongs to the wrong knowledge space")
        if int(current.user_id or 0) != int(target.owner.user_id):
            raise RuntimeError("target database record has the wrong owner")
        if (current.file_level_path or "") != target.file_level_path:
            raise RuntimeError("target database record has the wrong folder path")

        snapshot = self.snapshots[int(source_file.id)]
        target_storage = await asyncio.to_thread(_storage_exists, current)
        missing_objects = [
            key for key, existed in snapshot.storage_exists.items() if existed and not target_storage.get(key, False)
        ]
        if missing_objects:
            raise RuntimeError(f"target storage objects are missing: {missing_objects}")

        target_indexes = await asyncio.to_thread(_index_snapshot, target.space, int(current.id))
        if target_indexes.milvus_count != snapshot.indexes.milvus_count:
            raise RuntimeError(
                f"Milvus count mismatch: source={snapshot.indexes.milvus_count} target={target_indexes.milvus_count}"
            )
        if target_indexes.es_count != snapshot.indexes.es_count:
            raise RuntimeError(
                f"Elasticsearch count mismatch: source={snapshot.indexes.es_count} target={target_indexes.es_count}"
            )

        target_tags = await _tag_snapshot(int(current.id), self.tenant_id)
        if target_tags != snapshot.tags:
            raise RuntimeError(
                "target file tags do not match the source file: "
                f"source=approved={list(snapshot.tags.approved_ids)}, "
                f"pending={list(snapshot.tags.pending_review_ids)}; "
                f"target=approved={list(target_tags.approved_ids)}, "
                f"pending={list(target_tags.pending_review_ids)}"
            )
        actual_permissions = await _read_permission_tuples(int(current.id))
        expected_permissions = self._target_permission_rows(current, target)
        if not all(row in actual_permissions for row in expected_permissions):
            raise RuntimeError("target owner or parent permission tuple is missing")

    async def _ensure_source_record(self, source_file: KnowledgeFile) -> None:
        if await KnowledgeFileDao.query_by_id(int(source_file.id)) is not None:
            return
        clone = KnowledgeFile(**source_file.model_dump())
        async with get_async_db_session() as session:
            session.add(clone)
            await session.commit()

    async def restore_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> list[str]:
        errors: list[str] = []
        file_id = int(source_file.id)
        snapshot = self.snapshots[file_id]
        try:
            await self._ensure_source_record(source_file)
        except Exception as exc:
            errors.append(f"restore source database record: {type(exc).__name__}: {exc}")
        try:
            await asyncio.to_thread(delete_vector_files, [file_id], self._source_space(source_file))
            await asyncio.to_thread(
                copy_vector,
                target.space,
                self._source_space(source_file),
                int(target_file.id),
                file_id,
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
                file_id,
                int(source_file.user_id or target.owner.user_id),
                self.tenant_id,
                snapshot.tags,
            )
        except Exception as exc:
            errors.append(f"restore source tags: {type(exc).__name__}: {exc}")
        try:
            await _replace_permission_tuples(file_id, snapshot.permissions)
        except Exception as exc:
            errors.append(f"restore source permissions: {type(exc).__name__}: {exc}")
        return errors

    async def delete_source(
        self,
        source_file: KnowledgeFile,
        target_file: KnowledgeFile,
        target: TargetContext,
    ) -> None:
        try:
            await asyncio.to_thread(
                delete_vector_files,
                [int(source_file.id)],
                self._source_space(source_file),
            )
            await asyncio.to_thread(delete_minio_files, source_file)
            await _clear_tag_links(
                int(source_file.id),
                int(source_file.user_id or target.owner.user_id),
                self.tenant_id,
            )
            await _replace_permission_tuples(int(source_file.id), ())
            await asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(source_file.id)])
        except Exception as exc:
            restore_errors = await self.restore_source(source_file, target_file, target)
            detail = f"source deletion failed: {type(exc).__name__}: {exc}"
            if restore_errors:
                detail += f"; source restore errors={restore_errors}"
            raise RuntimeError(detail) from exc

        for space in (self._source_space(source_file), target.space):
            try:
                await KnowledgeDao.async_update_knowledge_update_time_by_id(int(space.id))
            except Exception:
                # Timestamp refresh is non-critical after the source row is deleted.
                logger.exception("Failed to refresh knowledge-space update time: %s", space.id)

    async def cleanup_target(self, target_file: KnowledgeFile, target: TargetContext) -> list[str]:
        errors: list[str] = []

        async def attempt(label: str, func: Callable[[], Any]) -> None:
            try:
                value = func()
                if asyncio.iscoroutine(value):
                    await value
            except Exception as exc:
                logger.exception("Target compensation failed: %s", label)
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        await attempt(
            "target indexes",
            lambda: asyncio.to_thread(delete_vector_files, [int(target_file.id)], target.space),
        )
        await attempt("target objects", lambda: asyncio.to_thread(delete_minio_files, target_file))
        await attempt(
            "target tags",
            lambda: _clear_tag_links(
                int(target_file.id),
                int(target.owner.user_id),
                self.tenant_id,
            ),
        )
        await attempt("target permissions", lambda: _replace_permission_tuples(int(target_file.id), ()))
        await attempt(
            "target database record",
            lambda: asyncio.to_thread(KnowledgeFileDao.delete_batch, [int(target_file.id)]),
        )
        return errors


def _model_payload(model: Any | None) -> dict[str, Any] | None:
    if model is None:
        return None
    model_dump = getattr(model, "model_dump", None)
    if not callable(model_dump):
        raise TypeError(f"{type(model).__name__} does not support model_dump")
    return model_dump(mode="json")


def _source_folder_id(file_level_path: str | None) -> int | None:
    parts = [part for part in (file_level_path or "").split("/") if part.isdigit()]
    return int(parts[-1]) if parts else None


def _target_context_payload(target: TargetContext) -> dict[str, Any]:
    return {
        "tenant_id": target.tenant_id,
        "space": _model_payload(target.space),
        "folder": _model_payload(target.folder),
        "owner": {
            "user_id": int(target.owner.user_id),
            "user_name": target.owner.user_name,
            "delete": int(target.owner.delete or 0),
        },
        "file_level_path": target.file_level_path,
        "level": target.level,
    }


def build_unit_started_payload(
    unit: MigrationUnit,
    operations: BishengMoveOperations,
) -> dict[str, Any]:
    source_files: list[dict[str, Any]] = []
    for source_file in unit.source_files:
        source_file_id = int(source_file.id or 0)
        snapshot = operations.snapshots.get(source_file_id)
        if snapshot is None:
            raise PreflightError(f"source snapshot is missing before migration: {source_file_id}")
        source_space = operations.source_spaces[int(source_file.knowledge_id)]
        source_files.append(
            {
                "record": _model_payload(source_file),
                "source_space": _model_payload(source_space),
                "source_folder_id": _source_folder_id(source_file.file_level_path),
                "file_level_path": source_file.file_level_path or "",
                "storage_object_names": _storage_object_names(source_file),
                "snapshot": asdict(snapshot),
            }
        )
    return {
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "classification": {
            "category_code": unit.category_code,
            "category_label": unit.category_label,
            "subcategory_code": unit.subcategory_code,
            "subcategory_label": unit.subcategory_label,
        },
        "source_files": source_files,
        "source_document": _model_payload(unit.source_document),
        "source_versions": [_model_payload(version) for version in unit.source_versions],
        "target": _target_context_payload(unit.target),
    }


def build_unit_succeeded_payload(
    unit: MigrationUnit,
    results: Sequence[FileMoveResult],
    operations: BishengMoveOperations,
    *,
    target_graph: dict[str, Any] | None,
) -> dict[str, Any]:
    target_files: list[dict[str, Any]] = []
    for source_file in unit.source_files:
        source_file_id = int(source_file.id or 0)
        target_file = operations.target_files_by_source_id.get(source_file_id)
        snapshot = operations.snapshots.get(source_file_id)
        if target_file is None or snapshot is None:
            raise RuntimeError(f"target or source snapshot is missing after migration: {source_file_id}")
        target_files.append(
            {
                "source_file_id": source_file_id,
                "record": _model_payload(target_file),
                "storage_object_names": _storage_object_names(target_file),
                "storage_exists": dict(snapshot.storage_exists),
                "tags": asdict(snapshot.tags),
                "indexes": asdict(snapshot.indexes),
                "permissions": list(_target_permission_rows(target_file, unit.target)),
            }
        )
    return {
        "unit_id": unit.unit_id,
        "unit_type": unit.unit_type,
        "results": [asdict(result) for result in results],
        "target": _target_context_payload(unit.target),
        "target_files": target_files,
        "target_graph": target_graph,
    }


class DatabaseVersionGraphStore:
    def __init__(self) -> None:
        self.target_graphs: dict[int, dict[str, Any]] = {}

    async def create_target_graph(
        self,
        unit: MigrationUnit,
        target_files: Sequence[KnowledgeFile],
    ) -> int:
        if unit.source_document is None or len(unit.source_versions) != len(target_files):
            raise RuntimeError("invalid version-chain migration unit")
        target_by_source = {
            int(source.id): target for source, target in zip(unit.source_files, target_files, strict=True)
        }
        async with get_async_db_session() as session:
            try:
                target_document = KnowledgeDocument(
                    knowledge_id=int(unit.target.space.id),
                    file_level_path=unit.target.file_level_path,
                    level=unit.target.level,
                    primary_version_id=None,
                    create_time=unit.source_document.create_time,
                )
                session.add(target_document)
                await session.flush()
                target_versions: list[KnowledgeDocumentVersion] = []
                primary_target_version: KnowledgeDocumentVersion | None = None
                for source_version in unit.source_versions:
                    target_file = target_by_source[int(source_version.knowledge_file_id)]
                    target_version = KnowledgeDocumentVersion(
                        document_id=int(target_document.id),
                        knowledge_file_id=int(target_file.id),
                        version_no=int(source_version.version_no),
                        is_primary=bool(source_version.is_primary),
                        create_time=source_version.create_time,
                    )
                    session.add(target_version)
                    target_versions.append(target_version)
                    if target_version.is_primary:
                        primary_target_version = target_version
                await session.flush()
                if primary_target_version is None or primary_target_version.id is None:
                    raise RuntimeError("source version chain has no primary version")
                target_document.primary_version_id = int(primary_target_version.id)
                session.add(target_document)
                await session.commit()
                await session.refresh(target_document)
                target_document_id = int(target_document.id)
                self.target_graphs[target_document_id] = {
                    "document": _model_payload(target_document),
                    "versions": [_model_payload(version) for version in target_versions],
                }
                return target_document_id
            except Exception:
                await session.rollback()
                raise

    def get_target_graph_payload(self, target_document_id: int) -> dict[str, Any] | None:
        return self.target_graphs.get(target_document_id)

    async def verify_target_graph(
        self,
        unit: MigrationUnit,
        target_document_id: int,
        target_files: Sequence[KnowledgeFile],
    ) -> None:
        target_by_source = {
            int(source.id): int(target.id) for source, target in zip(unit.source_files, target_files, strict=True)
        }
        expected = {
            (
                int(version.version_no),
                bool(version.is_primary),
                target_by_source[int(version.knowledge_file_id)],
            )
            for version in unit.source_versions
        }
        async with get_async_db_session() as session:
            document = (
                await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == target_document_id))
            ).first()
            rows = (
                await session.exec(
                    select(KnowledgeDocumentVersion)
                    .where(KnowledgeDocumentVersion.document_id == target_document_id)
                    .order_by(col(KnowledgeDocumentVersion.version_no))
                )
            ).all()
        actual = {(int(row.version_no), bool(row.is_primary), int(row.knowledge_file_id)) for row in rows}
        primary_rows = [row for row in rows if row.is_primary]
        if document is None or actual != expected or len(primary_rows) != 1:
            raise RuntimeError("target version graph does not match the source chain")
        if int(document.primary_version_id or 0) != int(primary_rows[0].id or 0):
            raise RuntimeError("target document primary_version_id is inconsistent")

    async def delete_source_graph(self, unit: MigrationUnit) -> None:
        if unit.source_document is None or unit.source_document.id is None:
            raise RuntimeError("source version document is missing")
        document_id = int(unit.source_document.id)
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == document_id)
                )
                await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def restore_source_graph(self, unit: MigrationUnit) -> list[str]:
        if unit.source_document is None or unit.source_document.id is None:
            return ["restore source graph: source document snapshot is missing"]
        document_id = int(unit.source_document.id)
        async with get_async_db_session() as session:
            try:
                existing = (
                    await session.exec(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
                ).first()
                if existing is not None:
                    return []
                session.add(KnowledgeDocument(**unit.source_document.model_dump()))
                session.add_all([KnowledgeDocumentVersion(**version.model_dump()) for version in unit.source_versions])
                await session.commit()
                return []
            except Exception as exc:
                await session.rollback()
                return [f"restore source graph: {type(exc).__name__}: {exc}"]

    async def delete_target_graph(self, target_document_id: int) -> list[str]:
        async with get_async_db_session() as session:
            try:
                await session.exec(
                    delete(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == target_document_id)
                )
                await session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.id == target_document_id))
                await session.commit()
                return []
            except Exception as exc:
                await session.rollback()
                return [f"delete target graph: {type(exc).__name__}: {exc}"]


def _result_for_source(
    source_file: KnowledgeFile,
    target: TargetContext,
    *,
    status: Literal["success", "skipped", "failed"],
    unit: MigrationUnit | None = None,
) -> FileMoveResult:
    version_number = None
    if unit is not None:
        version_number = _version_no_by_file(unit.source_versions).get(int(source_file.id or 0))
    return FileMoveResult(
        source_file_id=int(source_file.id or 0),
        source_space_id=int(source_file.knowledge_id),
        source_file_name=source_file.file_name,
        status=status,
        unit_id=unit.unit_id if unit else f"file:{source_file.id}",
        unit_type=unit.unit_type if unit else "file",
        source_document_id=(
            int(unit.source_document.id) if unit and unit.source_document and unit.source_document.id else None
        ),
        version_no=version_number,
        target_space_id=int(target.space.id),
        target_folder_id=int(target.folder.id),
        category_code=unit.category_code
        if unit
        else _normalize_code(parse_shougang_file_encoding_codes(source_file)[0]),
        category_label=unit.category_label if unit else "",
        subcategory_code=unit.subcategory_code if unit else _normalize_code(source_file.file_subcategory_code),
        subcategory_label=unit.subcategory_label if unit else "",
    )


async def move_one_file(
    source_file: KnowledgeFile,
    target: TargetContext,
    operations: MoveOperations,
) -> FileMoveResult:
    result = _result_for_source(source_file, target, status="failed")
    target_file: KnowledgeFile | None = None
    try:
        target_file = await operations.copy_file(source_file, target)
        result.target_file_id = int(target_file.id)
        await operations.copy_tags(source_file, target_file, target)
        await operations.write_permissions(target_file, target)
        await operations.verify_target(source_file, target_file, target)
        await operations.delete_source(source_file, target_file, target)
        result.status = "success"
        result.source_deleted = True
        return result
    except TargetCopyError as exc:
        target_file = exc.target_file
        result.error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"

    if target_file is not None:
        result.target_file_id = int(target_file.id)
        result.cleanup_errors = await operations.cleanup_target(target_file, target)
        result.target_cleanup_succeeded = not result.cleanup_errors
    return result


async def move_version_chain(
    unit: MigrationUnit,
    operations: MoveOperations,
    graph_store: VersionGraphStore,
) -> list[FileMoveResult]:
    if unit.unit_type != "version_chain" or unit.source_document is None:
        raise ValueError("move_version_chain requires a version_chain unit")
    target_files: list[KnowledgeFile] = []
    target_document_id: int | None = None
    target_graph_payload: dict[str, Any] | None = None
    source_graph_deleted = False
    cleanup_errors: list[str] = []
    try:
        for source_file in unit.source_files:
            try:
                target_file = await operations.copy_file(source_file, unit.target)
            except TargetCopyError as exc:
                if exc.target_file is not None and exc.target_file.id is not None:
                    target_files.append(exc.target_file)
                raise
            target_files.append(target_file)
            await operations.copy_tags(source_file, target_file, unit.target)
            await operations.write_permissions(target_file, unit.target)
            await operations.verify_target(source_file, target_file, unit.target)
        target_document_id = await graph_store.create_target_graph(unit, target_files)
        await graph_store.verify_target_graph(unit, target_document_id, target_files)
        get_target_graph_payload = getattr(graph_store, "get_target_graph_payload", None)
        if callable(get_target_graph_payload):
            target_graph_payload = get_target_graph_payload(target_document_id)
        await graph_store.delete_source_graph(unit)
        source_graph_deleted = True
        for source_file, target_file in zip(unit.source_files, target_files, strict=True):
            await operations.delete_source(source_file, target_file, unit.target)
    except Exception as exc:
        if source_graph_deleted:
            cleanup_errors.extend(await graph_store.restore_source_graph(unit))
            for source_file, target_file in zip(unit.source_files, target_files, strict=False):
                cleanup_errors.extend(await operations.restore_source(source_file, target_file, unit.target))
        if target_document_id is not None:
            cleanup_errors.extend(await graph_store.delete_target_graph(target_document_id))
        for target_file in target_files:
            cleanup_errors.extend(await operations.cleanup_target(target_file, unit.target))
        error = f"{type(exc).__name__}: {exc}"
        results: list[FileMoveResult] = []
        target_by_source = {
            int(source.id): target for source, target in zip(unit.source_files, target_files, strict=False)
        }
        target_version_ids = {
            int(version["knowledge_file_id"]): int(version["id"])
            for version in (target_graph_payload or {}).get("versions", [])
            if version.get("knowledge_file_id") is not None and version.get("id") is not None
        }
        for source_file in unit.source_files:
            result = _result_for_source(source_file, unit.target, status="failed", unit=unit)
            target_file = target_by_source.get(int(source_file.id))
            result.target_file_id = int(target_file.id) if target_file else None
            result.target_document_id = target_document_id
            result.target_version_id = target_version_ids.get(int(target_file.id)) if target_file else None
            result.target_cleanup_succeeded = not cleanup_errors
            result.error = error
            result.cleanup_errors = list(cleanup_errors)
            results.append(result)
        return results

    results = []
    target_version_ids = {
        int(version["knowledge_file_id"]): int(version["id"])
        for version in (target_graph_payload or {}).get("versions", [])
        if version.get("knowledge_file_id") is not None and version.get("id") is not None
    }
    for source_file, target_file in zip(unit.source_files, target_files, strict=True):
        result = _result_for_source(source_file, unit.target, status="success", unit=unit)
        result.target_file_id = int(target_file.id)
        result.target_document_id = target_document_id
        result.target_version_id = target_version_ids.get(int(target_file.id))
        result.source_deleted = True
        results.append(result)
    return results


def _skipped_to_result(item: SkippedFile) -> FileMoveResult:
    return FileMoveResult(
        source_file_id=item.source_file_id,
        source_space_id=item.source_space_id,
        source_file_name=item.source_file_name,
        status="skipped",
        unit_id=item.unit_id,
        unit_type=item.unit_type,
        source_document_id=item.source_document_id,
        version_no=item.version_no,
        target_space_id=item.target_space_id,
        target_folder_id=item.target_folder_id,
        category_code=item.category_code,
        category_label=item.category_label,
        subcategory_code=item.subcategory_code,
        subcategory_label=item.subcategory_label,
        reason_code=item.reason_code,
        error=item.reason,
    )


def _dry_run_results(plan: MigrationPlan) -> list[FileMoveResult]:
    results: list[FileMoveResult] = []
    for unit in plan.selected_units:
        for source_file in unit.source_files:
            result = _result_for_source(source_file, unit.target, status="skipped", unit=unit)
            result.reason_code = "dry_run_selected"
            result.error = "selected by dry-run; no writes performed"
            results.append(result)
    return results


def write_json_report(report: MoveRunReport, report_dir: Path) -> Path:
    report.finished_at = datetime.now().astimezone().isoformat()
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
        "run_status": report.run_status,
        "termination_reason": report.termination_reason,
        "rollback_record_path": report.rollback_record_path,
        "pending_units": report.pending_units,
        "summary": report.summary(),
        "results": [asdict(result) for result in report.results],
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def _parameters_for_report(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source_space_ids": list(args.source_space_ids),
        "source_folder_ids": list(args.source_folder_ids),
        "source_category_codes": list(args.source_category_codes),
        "source_subcategory_codes": list(args.source_subcategory_codes),
        "target_space_id": args.target_space_id,
        "target_folder_id": args.target_folder_id,
        "rollback_record_file": str(args.rollback_record_file) if args.rollback_record_file else None,
        "batch_size": args.batch_size,
    }


def _print_preflight(plan: MigrationPlan, apply: bool) -> None:
    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Tenant: {plan.tenant_id}")
    print(f"Source spaces: {sorted(plan.source_spaces)}")
    print(f"Selected units: {len(plan.selected_units)}; skipped files: {len(plan.skipped_files)}")
    for unit in plan.selected_units:
        print(
            f"[SELECTED] unit={unit.unit_id} type={unit.unit_type} "
            f"files={[int(file.id) for file in unit.source_files]} "
            f"target={unit.target.space.id}/{unit.target.folder.id}"
        )
    for item in plan.skipped_files:
        print(f"[SKIPPED] file_id={item.source_file_id} code={item.reason_code} reason={item.reason}")


def _failed_results_for_unit(unit: MigrationUnit, exc: Exception) -> list[FileMoveResult]:
    error = f"{type(exc).__name__}: {exc}"
    results: list[FileMoveResult] = []
    for source_file in unit.source_files:
        result = _result_for_source(source_file, unit.target, status="failed", unit=unit)
        result.error = error
        results.append(result)
    return results


def _target_graph_payload(
    graph_store: VersionGraphStore,
    results: Sequence[FileMoveResult],
) -> dict[str, Any] | None:
    target_document_id = next((result.target_document_id for result in results if result.target_document_id), None)
    get_target_graph_payload = getattr(graph_store, "get_target_graph_payload", None)
    if target_document_id is None or not callable(get_target_graph_payload):
        return None
    return get_target_graph_payload(int(target_document_id))


async def compensate_completed_migration(
    completed: CompletedMigration,
    operations: BishengMoveOperations,
    graph_store: VersionGraphStore,
    *,
    reason: str,
) -> list[str]:
    errors: list[str] = []
    target_files: list[KnowledgeFile] = []
    restored_source_ids: set[int] = set()
    for source_file in completed.unit.source_files:
        target_file = operations.target_files_by_source_id.get(int(source_file.id or 0))
        if target_file is None:
            errors.append(f"target file snapshot is missing for source file {source_file.id}")
            continue
        target_files.append(target_file)
        try:
            restore_errors = await operations.restore_source(source_file, target_file, completed.unit.target)
            errors.extend(restore_errors)
            if not restore_errors:
                restored_source_ids.add(int(source_file.id or 0))
        except Exception as exc:
            errors.append(f"restore source file {source_file.id}: {type(exc).__name__}: {exc}")

    can_cleanup_targets = len(restored_source_ids) == len(completed.unit.source_files)
    if completed.unit.unit_type == "version_chain":
        try:
            graph_restore_errors = await graph_store.restore_source_graph(completed.unit)
            errors.extend(graph_restore_errors)
            can_cleanup_targets = can_cleanup_targets and not graph_restore_errors
        except Exception as exc:
            errors.append(f"restore source graph: {type(exc).__name__}: {exc}")
            can_cleanup_targets = False
        target_document_id = next(
            (result.target_document_id for result in completed.results if result.target_document_id is not None),
            None,
        )
        if target_document_id is not None and can_cleanup_targets:
            try:
                graph_cleanup_errors = await graph_store.delete_target_graph(int(target_document_id))
                errors.extend(graph_cleanup_errors)
                can_cleanup_targets = not graph_cleanup_errors
            except Exception as exc:
                errors.append(f"delete target graph: {type(exc).__name__}: {exc}")
                can_cleanup_targets = False

    cleanup_candidates = target_files if can_cleanup_targets else []
    if target_files and not cleanup_candidates:
        errors.append("target data was preserved because source restoration was incomplete")
    for target_file in cleanup_candidates:
        try:
            errors.extend(await operations.cleanup_target(target_file, completed.unit.target))
        except Exception as exc:
            errors.append(f"cleanup target file {target_file.id}: {type(exc).__name__}: {exc}")

    for result in completed.results:
        result.status = "failed"
        result.source_deleted = False
        result.reason_code = "rollback_record_write_failed"
        result.error = reason
        result.cleanup_errors = list(errors)
        result.target_cleanup_succeeded = not errors
    return errors


async def compensate_unpersisted_migrations(
    completed_units: Sequence[CompletedMigration],
    operations: BishengMoveOperations,
    graph_store: VersionGraphStore,
    *,
    reason: str,
) -> list[str]:
    errors: list[str] = []
    for completed in reversed(completed_units):
        errors.extend(
            await compensate_completed_migration(
                completed,
                operations,
                graph_store,
                reason=reason,
            )
        )
    return errors


def release_completed_migrations(
    completed_units: Sequence[CompletedMigration],
    operations: BishengMoveOperations,
) -> None:
    for completed in completed_units:
        for source_file in completed.unit.source_files:
            source_file_id = int(source_file.id or 0)
            operations.snapshots.pop(source_file_id, None)
            operations.target_files_by_source_id.pop(source_file_id, None)


async def run(
    args: argparse.Namespace,
    *,
    stop_controller: StopController | None = None,
    install_signal_handlers: bool = True,
) -> int:
    run_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    report: MoveRunReport | None = None
    journal: RollbackJournal | None = None
    unpersisted: list[CompletedMigration] = []
    operations: BishengMoveOperations | None = None
    graph_store: VersionGraphStore | None = None
    context_initialized = False
    controller = stop_controller or StopController()
    try:
        await initialize_app_context(config=settings)
        context_initialized = True
        plan = await build_migration_plan(args)
        _print_preflight(plan, args.apply)
        report = MoveRunReport(
            mode="apply" if args.apply else "dry-run",
            run_id=run_id,
            parameters=_parameters_for_report(args),
            tenant_id=plan.tenant_id,
            results=[_skipped_to_result(item) for item in plan.skipped_files],
            pending_units=len(plan.selected_units),
        )
        if not args.apply:
            report.results.extend(_dry_run_results(plan))
            report.run_status = "completed"
            report.pending_units = 0
            output = write_json_report(report, args.report_dir)
            print(f"Dry-run only. Re-run with --apply after reviewing: {output.resolve()}")
            return EXIT_OK

        rollback_record_path = resolve_rollback_record_path(args, run_id)
        report.rollback_record_path = str(rollback_record_path.resolve())
        if rollback_record_path.exists():
            raise PreflightError(f"rollback record already exists: {rollback_record_path}")
        journal = RollbackJournal(path=rollback_record_path, run_id=run_id)
        journal.open()
        journal.append_event(
            "run_started",
            {
                "mode": "apply",
                "tenant_id": plan.tenant_id,
                "parameters": _parameters_for_report(args),
                "selected_units": len(plan.selected_units),
                "skipped_files": len(plan.skipped_files),
            },
        )
        journal.flush()

        operations = BishengMoveOperations(plan.tenant_id, plan.source_spaces)
        graph_store = DatabaseVersionGraphStore()
        with _tenant_scope(plan.tenant_id), _sigint_stop_scope(controller, enabled=install_signal_handlers):
            for unit_index, unit in enumerate(plan.selected_units):
                if controller.requested:
                    break
                try:
                    await operations.snapshot_unit(unit)
                    journal.append_event("unit_started", build_unit_started_payload(unit, operations))
                    if unit.unit_type == "version_chain":
                        unit_results = await move_version_chain(unit, operations, graph_store)
                    else:
                        unit_results = [await move_one_file(unit.source_files[0], unit.target, operations)]
                        result = unit_results[0]
                        result.unit_id = unit.unit_id
                        result.category_label = unit.category_label
                        result.subcategory_label = unit.subcategory_label
                except RollbackRecordError:
                    raise
                except Exception as exc:
                    unit_results = _failed_results_for_unit(unit, exc)

                report.results.extend(unit_results)
                report.pending_units = len(plan.selected_units) - unit_index - 1
                for result in unit_results:
                    print(
                        f"[{result.status.upper()}] source_file_id={result.source_file_id} "
                        f"target_file_id={result.target_file_id or '-'} error={result.error or '-'}"
                    )

                if any(result.status == "failed" for result in unit_results):
                    report.run_status = "failed"
                    report.termination_reason = f"migration unit failed: {unit.unit_id}"
                    journal.append_event(
                        "unit_failed",
                        {
                            "unit_id": unit.unit_id,
                            "unit_type": unit.unit_type,
                            "results": [asdict(result) for result in unit_results],
                        },
                    )
                    journal.append_event(
                        "run_failed",
                        {
                            "reason": report.termination_reason,
                            "summary": report.summary(),
                            "pending_units": report.pending_units,
                        },
                    )
                    journal.flush()
                    release_completed_migrations(unpersisted, operations)
                    unpersisted.clear()
                    return EXIT_APPLY_ERROR

                completed = CompletedMigration(unit=unit, results=list(unit_results))
                unpersisted.append(completed)
                try:
                    succeeded_payload = build_unit_succeeded_payload(
                        unit,
                        unit_results,
                        operations,
                        target_graph=_target_graph_payload(graph_store, unit_results),
                    )
                    journal.append_event("unit_succeeded", succeeded_payload)
                except RollbackRecordError:
                    raise
                except Exception as exc:
                    raise RollbackRecordError(f"unable to build rollback payload for {unit.unit_id}") from exc

                if len(unpersisted) >= args.batch_size:
                    journal.flush()
                    release_completed_migrations(unpersisted, operations)
                    unpersisted.clear()
                if controller.requested:
                    break

            if controller.requested:
                report.run_status = "interrupted"
                report.termination_reason = "SIGINT requested after the current migration unit"
                journal.append_event(
                    "run_interrupted",
                    {
                        "reason": report.termination_reason,
                        "summary": report.summary(),
                        "pending_units": report.pending_units,
                    },
                )
                journal.flush()
                release_completed_migrations(unpersisted, operations)
                unpersisted.clear()
                return EXIT_INTERRUPTED

        report.run_status = "completed"
        report.pending_units = 0
        journal.append_event("run_completed", {"summary": report.summary(), "pending_units": 0})
        journal.flush()
        release_completed_migrations(unpersisted, operations)
        unpersisted.clear()
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
    except (KeyboardInterrupt, asyncio.CancelledError) as exc:
        if report is not None:
            report.run_status = "interrupted"
            report.termination_reason = f"{type(exc).__name__}: interrupted"
        if journal is not None:
            try:
                journal.append_event(
                    "run_interrupted",
                    {"reason": report.termination_reason if report else "interrupted"},
                )
                journal.flush()
                if operations is not None:
                    release_completed_migrations(unpersisted, operations)
                unpersisted.clear()
            except RollbackRecordError:
                logger.exception("Failed to persist rollback record after interruption")
        return EXIT_INTERRUPTED
    except RollbackRecordError as exc:
        logger.exception("Rollback record failed; compensating the unpersisted migration batch")
        print(f"Rollback record failed: {exc}", file=sys.stderr)
        compensation_errors: list[str] = []
        if report is not None:
            report.run_status = "failed"
            report.termination_reason = f"RollbackRecordError: {exc}"
        if unpersisted and operations is not None and graph_store is not None and report is not None:
            with _tenant_scope(report.tenant_id):
                compensation_errors = await compensate_unpersisted_migrations(
                    unpersisted,
                    operations,
                    graph_store,
                    reason=report.termination_reason,
                )
            release_completed_migrations(unpersisted, operations)
            unpersisted.clear()
        if compensation_errors:
            print(
                "Rollback-record compensation errors: " + json.dumps(compensation_errors, ensure_ascii=False),
                file=sys.stderr,
            )
            if report is not None:
                report.termination_reason += f"; compensation_errors={compensation_errors}"
        return EXIT_APPLY_ERROR
    except Exception as exc:
        logger.exception("Knowledge-file move script failed")
        print(f"Script failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        if report is not None:
            report.run_status = "failed"
            report.termination_reason = f"{type(exc).__name__}: {exc}"
        if journal is not None and not isinstance(exc, RollbackRecordError):
            try:
                journal.append_event(
                    "run_failed",
                    {"reason": report.termination_reason if report else str(exc)},
                )
                journal.flush()
                if operations is not None:
                    release_completed_migrations(unpersisted, operations)
                unpersisted.clear()
            except RollbackRecordError:
                logger.exception("Failed to persist rollback record after script failure")
        return EXIT_APPLY_ERROR if args.apply else EXIT_DEPENDENCY_ERROR
    finally:
        if journal is not None:
            try:
                journal.close(flush=False)
            except (OSError, RollbackRecordError):
                logger.exception("Failed to close rollback record after its final checkpoint")
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
