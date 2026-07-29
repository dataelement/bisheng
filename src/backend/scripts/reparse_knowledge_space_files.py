#!/usr/bin/env python3
"""Reparse knowledge-space files with bounded local concurrency.

This maintenance script reruns the normal knowledge-file parse pipeline for
knowledge-space files. It is intended for operational repair after parser,
index, or metadata logic changes.

By default the script is a dry-run and only prints the files that would be
processed. Pass ``--apply`` to mutate data. Before each file is reparsed,
the script deletes only that file's existing Milvus and Elasticsearch records;
it does not delete source files or generated preview objects from MinIO.

Apply runs stream timing and progress events to a JSONL report through a
dedicated writer thread. The default path is
``./reparse_reports/reparse-{run_id}.jsonl``; use ``--report-file`` to select
another new path. Existing report files are never overwritten.

Usage:
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --report-file /var/log/bisheng/reparse.jsonl
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-id 10 --folder-id 20
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --file-id 101 --file-id 102
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-level public
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --status failed --status waiting
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --include-inflight
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --only-inflight
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.common.errcode.knowledge import KnowledgeFileFailedError  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import (  # noqa: E402
    Knowledge,
    KnowledgeDao,
    KnowledgeTypeEnum,
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

ELIGIBLE_STATUSES: tuple[int, ...] = (
    KnowledgeFileStatus.SUCCESS.value,
    KnowledgeFileStatus.FAILED.value,
    KnowledgeFileStatus.TIMEOUT.value,
    KnowledgeFileStatus.VIOLATION.value,
)

IN_FLIGHT_STATUSES: tuple[int, ...] = (
    KnowledgeFileStatus.WAITING.value,
    KnowledgeFileStatus.PROCESSING.value,
    KnowledgeFileStatus.REBUILDING.value,
)

SPACE_LEVEL_CHOICES: tuple[str, ...] = tuple(level.value for level in KnowledgeSpaceLevelEnum)
STATUS_NAME_TO_VALUE: dict[str, int] = {status.name.lower(): status.value for status in KnowledgeFileStatus}
REPORT_SCHEMA_VERSION = 1
DEFAULT_REPORT_DIR = Path("reparse_reports")
_REPORT_STOP = object()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_run_id() -> str:
    return uuid.uuid4().hex


def resolve_report_path(report_file: str | None, run_id: str) -> Path:
    if report_file:
        return Path(report_file)
    return DEFAULT_REPORT_DIR / f"reparse-{run_id}.jsonl"


class ReportWriteError(RuntimeError):
    """Raised when the JSONL report cannot be persisted safely."""


class JsonlReportWriter:
    """Serialize report events through one dedicated writer thread."""

    def __init__(self, path: Path | str, *, run_id: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self._events: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._ready = threading.Event()
        self._error_lock = threading.Lock()
        self._error: Exception | None = None
        self._started = False
        self._closed = False
        self._thread = threading.Thread(
            target=self._write_events,
            name=f"reparse-report-{run_id}",
        )

    def _set_error(self, exc: Exception) -> None:
        with self._error_lock:
            if self._error is None:
                self._error = exc

    def _raise_if_failed(self) -> None:
        with self._error_lock:
            error = self._error
        if error is None:
            return
        if isinstance(error, FileExistsError):
            message = f"report file already exists: {self.path}"
        else:
            message = f"unable to write JSONL report {self.path}: {error}"
        raise ReportWriteError(message) from error

    def _write_events(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("x", encoding="utf-8") as handle:
                self._ready.set()
                while True:
                    event = self._events.get()
                    try:
                        if event is _REPORT_STOP:
                            return
                        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
                        handle.write(line)
                        handle.write("\n")
                        handle.flush()
                    finally:
                        self._events.task_done()
        except Exception as exc:
            self._set_error(exc)
        finally:
            self._ready.set()

    def start(self) -> JsonlReportWriter:
        if self._started:
            raise ReportWriteError("JSONL report writer has already been started")
        try:
            self._thread.start()
        except RuntimeError as exc:
            raise ReportWriteError("unable to start JSONL report writer") from exc
        self._started = True
        self._ready.wait()
        try:
            self._raise_if_failed()
        except ReportWriteError:
            self._thread.join()
            raise
        return self

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        if not self._started:
            raise ReportWriteError("JSONL report writer has not been started")
        if self._closed:
            raise ReportWriteError("JSONL report writer is already closed")
        self._raise_if_failed()
        event = dict(payload or {})
        event.update(
            {
                "schema_version": REPORT_SCHEMA_VERSION,
                "run_id": self.run_id,
                "event_type": event_type,
                "timestamp": _utc_now(),
            }
        )
        self._events.put(event)

    def close(self) -> None:
        if not self._started:
            return
        if not self._closed:
            self._closed = True
            if self._thread.is_alive():
                self._events.put(_REPORT_STOP)
            self._thread.join()
        self._raise_if_failed()


@dataclass
class SelectionReport:
    selected_files: list[KnowledgeFile] = field(default_factory=list)
    skipped_missing_spaces: int = 0
    skipped_missing_folders: int = 0
    skipped_missing_files: int = 0
    skipped_non_space_records: int = 0
    skipped_folder_records: int = 0
    skipped_non_folder_records: int = 0
    skipped_space_level_records: int = 0
    skipped_status_records: int = 0
    duplicate_records: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def selected_count(self) -> int:
        return len(self.selected_files)

    @property
    def skipped_count(self) -> int:
        return (
            self.skipped_missing_spaces
            + self.skipped_missing_folders
            + self.skipped_missing_files
            + self.skipped_non_space_records
            + self.skipped_folder_records
            + self.skipped_non_folder_records
            + self.skipped_space_level_records
            + self.skipped_status_records
            + self.duplicate_records
        )


@dataclass(frozen=True)
class FileReparseResult:
    file_id: int
    knowledge_id: int | None
    file_name: str
    success: bool
    final_status: int | None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0


@dataclass
class RunReport:
    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[FileReparseResult] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform writes; default is dry-run",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=1,
        help="number of files to parse concurrently; default: 1",
    )
    parser.add_argument(
        "--report-file",
        default=None,
        help=("JSONL report path used with --apply; default: ./reparse_reports/reparse-{run_id}.jsonl"),
    )
    parser.add_argument(
        "--space-id",
        dest="space_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="knowledge-space ID to include; can be passed multiple times",
    )
    parser.add_argument(
        "--folder-id",
        dest="folder_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="folder ID whose descendant files should be included recursively; can be passed multiple times",
    )
    parser.add_argument(
        "--file-id",
        dest="file_ids",
        action="append",
        type=_positive_int,
        default=[],
        help="knowledge file ID to include; can be passed multiple times",
    )
    parser.add_argument(
        "--space-level",
        choices=SPACE_LEVEL_CHOICES,
        default=None,
        help="restrict all selected scopes to one space level: public, department, team, or personal",
    )
    parser.add_argument(
        "--status",
        dest="statuses",
        action="append",
        choices=tuple(STATUS_NAME_TO_VALUE),
        default=[],
        help="file status to include; can be passed multiple times and replaces the default status set",
    )
    parser.add_argument(
        "--include-inflight",
        dest="include_inflight",
        action="store_true",
        help=(
            "also select and reparse files whose status is WAITING, PROCESSING, or REBUILDING; "
            "by default these are skipped to avoid interfering with an active parse run"
        ),
    )
    parser.add_argument(
        "--only-inflight",
        dest="only_inflight",
        action="store_true",
        help=(
            "select ONLY files whose status is WAITING, PROCESSING, or REBUILDING, "
            "skipping SUCCESS/FAILED/TIMEOUT/VIOLATION files"
        ),
    )
    args = parser.parse_args(argv)
    if args.statuses and (args.include_inflight or args.only_inflight):
        parser.error("--status cannot be combined with --include-inflight or --only-inflight")
    return args


def resolve_eligible_statuses(args: argparse.Namespace) -> tuple[int, ...]:
    statuses: Sequence[str] = getattr(args, "statuses", ())
    if statuses:
        return tuple(dict.fromkeys(STATUS_NAME_TO_VALUE[status] for status in statuses))
    if getattr(args, "only_inflight", False):
        return IN_FLIGHT_STATUSES
    if getattr(args, "include_inflight", False):
        return ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES
    return ELIGIBLE_STATUSES


async def _get_all_space_ids(session: AsyncSession) -> set[int]:
    result = await session.exec(select(Knowledge.id).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value))
    return {int(row) for row in result.all()}


async def _get_space_ids_by_level(
    session: AsyncSession,
    space_level: KnowledgeSpaceLevelEnum | str,
) -> set[int]:
    normalized_level = KnowledgeSpaceLevelEnum(getattr(space_level, "value", space_level))
    result = await session.exec(
        select(KnowledgeSpaceScope.space_id).where(KnowledgeSpaceScope.level == normalized_level.value)
    )
    return {int(row) for row in result.all()}


async def _get_valid_requested_space_ids(
    session: AsyncSession,
    requested_space_ids: Sequence[int],
    report: SelectionReport,
    all_space_ids: set[int] | None = None,
) -> set[int]:
    requested = set(requested_space_ids)
    if all_space_ids is None:
        all_space_ids = await _get_all_space_ids(session)
    if not requested:
        return set(all_space_ids)

    valid_ids = requested & all_space_ids
    missing_or_non_space = requested - valid_ids
    if missing_or_non_space:
        report.skipped_missing_spaces += len(missing_or_non_space)
        report.warnings.append(f"ignored non-existent or non-space knowledge IDs: {sorted(missing_or_non_space)}")
    return valid_ids


def _folder_descendant_prefix(folder: KnowledgeFile) -> str:
    return f"{folder.file_level_path}/{folder.id}" if folder.file_level_path else f"/{folder.id}"


def _is_eligible_file(
    record: KnowledgeFile,
    all_space_ids: set[int],
    allowed_space_ids: set[int],
    report: SelectionReport,
    eligible_statuses: tuple[int, ...],
) -> bool:
    if record.knowledge_id not in all_space_ids:
        report.skipped_non_space_records += 1
        return False
    if record.knowledge_id not in allowed_space_ids:
        report.skipped_space_level_records += 1
        return False
    if record.file_type != FileType.FILE.value:
        report.skipped_folder_records += 1
        return False
    if record.status not in eligible_statuses:
        report.skipped_status_records += 1
        return False
    return True


def _add_candidate(
    selected: dict[int, KnowledgeFile],
    record: KnowledgeFile,
    report: SelectionReport,
) -> None:
    if record.id is None:
        return
    if record.id in selected:
        report.duplicate_records += 1
        return
    selected[record.id] = record


async def _select_space_files(
    session: AsyncSession,
    space_ids: set[int],
    eligible_statuses: tuple[int, ...],
) -> list[KnowledgeFile]:
    if not space_ids:
        return []
    result = await session.exec(
        select(KnowledgeFile)
        .where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.status).in_(eligible_statuses),
        )
        .order_by(col(KnowledgeFile.id).asc())
    )
    return list(result.all())


async def _count_space_scope_skips(
    session: AsyncSession,
    space_ids: set[int],
    report: SelectionReport,
    eligible_statuses: tuple[int, ...],
) -> None:
    if not space_ids:
        return
    folder_count = await session.scalar(
        select(func.count())
        .select_from(KnowledgeFile)
        .where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.DIR.value,
        )
    )
    ineligible_count = await session.scalar(
        select(func.count())
        .select_from(KnowledgeFile)
        .where(
            col(KnowledgeFile.knowledge_id).in_(space_ids),
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.status).notin_(eligible_statuses),
        )
    )
    report.skipped_folder_records += int(folder_count or 0)
    report.skipped_status_records += int(ineligible_count or 0)


async def _select_files_by_ids(
    session: AsyncSession,
    file_ids: Sequence[int],
) -> dict[int, KnowledgeFile]:
    if not file_ids:
        return {}
    result = await session.exec(select(KnowledgeFile).where(col(KnowledgeFile.id).in_(set(file_ids))))
    return {int(row.id): row for row in result.all() if row.id is not None}


async def _select_folder_descendants(
    session: AsyncSession,
    folder: KnowledgeFile,
    eligible_statuses: tuple[int, ...],
) -> list[KnowledgeFile]:
    prefix = _folder_descendant_prefix(folder)
    result = await session.exec(
        select(KnowledgeFile)
        .where(
            KnowledgeFile.knowledge_id == folder.knowledge_id,
            KnowledgeFile.file_type == FileType.FILE.value,
            col(KnowledgeFile.status).in_(eligible_statuses),
            or_(
                KnowledgeFile.file_level_path == prefix,
                col(KnowledgeFile.file_level_path).like(f"{prefix}/%"),
            ),
        )
        .order_by(col(KnowledgeFile.id).asc())
    )
    return list(result.all())


async def collect_candidate_files(
    session: AsyncSession,
    *,
    space_ids: Sequence[int] = (),
    folder_ids: Sequence[int] = (),
    file_ids: Sequence[int] = (),
    space_level: KnowledgeSpaceLevelEnum | str | None = None,
    eligible_statuses: tuple[int, ...] = ELIGIBLE_STATUSES,
) -> SelectionReport:
    """Collect the union of selected knowledge-space files.

    Scope arguments are unioned: passing both a space and a file includes files
    from the space plus the explicit file when it is otherwise eligible. When
    ``space_level`` is provided, it intersects that union.
    """
    report = SelectionReport()
    selected: dict[int, KnowledgeFile] = {}
    has_scope_filter = bool(space_ids or folder_ids or file_ids)

    all_space_ids = await _get_all_space_ids(session)
    allowed_space_ids = set(all_space_ids)
    if space_level is not None:
        allowed_space_ids &= await _get_space_ids_by_level(session, space_level)
    requested_space_ids = await _get_valid_requested_space_ids(
        session,
        space_ids,
        report,
        all_space_ids,
    )
    valid_space_ids = requested_space_ids & allowed_space_ids
    level_filtered_space_ids = requested_space_ids - allowed_space_ids if space_ids else set()
    if level_filtered_space_ids:
        report.skipped_space_level_records += len(level_filtered_space_ids)
        report.warnings.append(
            f"ignored knowledge-space IDs outside space level {getattr(space_level, 'value', space_level)}: "
            f"{sorted(level_filtered_space_ids)}"
        )

    if not has_scope_filter or space_ids:
        for record in await _select_space_files(session, valid_space_ids, eligible_statuses):
            _add_candidate(selected, record, report)
        await _count_space_scope_skips(session, valid_space_ids, report, eligible_statuses)

    if file_ids:
        files_by_id = await _select_files_by_ids(session, file_ids)
        missing_file_ids = set(file_ids) - set(files_by_id)
        report.skipped_missing_files += len(missing_file_ids)
        if missing_file_ids:
            report.warnings.append(f"ignored missing file IDs: {sorted(missing_file_ids)}")
        for record in files_by_id.values():
            if _is_eligible_file(record, all_space_ids, allowed_space_ids, report, eligible_statuses):
                _add_candidate(selected, record, report)

    if folder_ids:
        folders_by_id = await _select_files_by_ids(session, folder_ids)
        missing_folder_ids = set(folder_ids) - set(folders_by_id)
        report.skipped_missing_folders += len(missing_folder_ids)
        if missing_folder_ids:
            report.warnings.append(f"ignored missing folder IDs: {sorted(missing_folder_ids)}")
        for folder in folders_by_id.values():
            if folder.knowledge_id not in all_space_ids:
                report.skipped_non_space_records += 1
                continue
            if folder.knowledge_id not in allowed_space_ids:
                report.skipped_space_level_records += 1
                continue
            if folder.file_type != FileType.DIR.value:
                report.skipped_non_folder_records += 1
                continue
            for record in await _select_folder_descendants(session, folder, eligible_statuses):
                _add_candidate(selected, record, report)

    report.selected_files = sorted(selected.values(), key=lambda item: int(item.id or 0))
    return report


def _get_file_sync(file_id: int) -> KnowledgeFile | None:
    records = KnowledgeFileDao.get_file_by_ids([file_id])
    return records[0] if records else None


def _get_knowledge_sync(knowledge_id: int) -> Knowledge | None:
    return KnowledgeDao.query_by_id(knowledge_id)


def _update_file_sync(db_file: KnowledgeFile) -> KnowledgeFile:
    return KnowledgeFileDao.update(db_file)


def _mark_file_failed(file_id: int, exc: Exception) -> None:
    KnowledgeFileDao.update_file_status(
        [file_id],
        KnowledgeFileStatus.FAILED,
        KnowledgeFileFailedError(exception=exc).to_json_str(),
    )


def _delete_existing_vectors(file_id: int, knowledge: Knowledge) -> None:
    from bisheng.api.services.knowledge_imp import delete_vector_files

    delete_vector_files([file_id], knowledge)


def _run_parse_pipeline(knowledge: Knowledge, db_file: KnowledgeFile) -> None:
    from bisheng.api.services.knowledge_imp import process_file_task

    process_file_task(
        knowledge,
        db_files=[db_file],
        preview_cache_keys=[None],
        callback_url=None,
        enable_auto_tags=True,
    )


def reparse_one_file(
    file_id: int,
    *,
    force_inflight: bool = False,
    eligible_statuses: tuple[int, ...] | None = None,
) -> FileReparseResult:
    """Reparse one file and convert every failure into a result object."""
    with bypass_tenant_filter():
        db_file = _get_file_sync(file_id)
        if db_file is None:
            return FileReparseResult(file_id, None, "", False, None, "file not found")

        file_name = db_file.file_name
        knowledge_id = db_file.knowledge_id
        if db_file.file_type != FileType.FILE.value:
            return FileReparseResult(file_id, knowledge_id, file_name, False, db_file.status, "record is not a file")
        if eligible_statuses is None:
            eligible_statuses = ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES if force_inflight else ELIGIBLE_STATUSES
        if db_file.status in IN_FLIGHT_STATUSES and db_file.status not in eligible_statuses:
            return FileReparseResult(file_id, knowledge_id, file_name, False, db_file.status, "file is in-flight")
        if db_file.status not in eligible_statuses:
            return FileReparseResult(file_id, knowledge_id, file_name, False, db_file.status, "status is not eligible")

        knowledge = _get_knowledge_sync(knowledge_id)
        if not knowledge or knowledge.type != KnowledgeTypeEnum.SPACE.value:
            return FileReparseResult(
                file_id, knowledge_id, file_name, False, db_file.status, "knowledge is not a space"
            )

        db_file.status = KnowledgeFileStatus.PROCESSING.value
        db_file.remark = ""
        db_file.simhash = None
        db_file.similar_status = 0
        db_file = _update_file_sync(db_file)

        try:
            _delete_existing_vectors(file_id, knowledge)
        except Exception as exc:
            _mark_file_failed(file_id, exc)
            return FileReparseResult(
                file_id,
                knowledge_id,
                file_name,
                False,
                KnowledgeFileStatus.FAILED.value,
                f"delete vectors failed: {exc}",
            )

        try:
            _run_parse_pipeline(knowledge, db_file)
        except Exception as exc:
            _mark_file_failed(file_id, exc)
            return FileReparseResult(
                file_id,
                knowledge_id,
                file_name,
                False,
                KnowledgeFileStatus.FAILED.value,
                f"parse raised: {exc}",
            )

        updated_file = _get_file_sync(file_id)
        final_status = updated_file.status if updated_file else None
        success = final_status == KnowledgeFileStatus.SUCCESS.value
        error = "" if success else (updated_file.remark if updated_file else "file disappeared after parse")
        return FileReparseResult(file_id, knowledge_id, file_name, success, final_status, error or "parse failed")


async def run_reparse_files(
    files: Sequence[KnowledgeFile],
    *,
    concurrency: int,
    reparse_func: Callable[[int], FileReparseResult] = reparse_one_file,
    event_sink: Callable[[str, dict[str, Any]], None] | None = None,
) -> RunReport:
    executable_files = [db_file for db_file in files if db_file.id is not None]
    semaphore = asyncio.Semaphore(concurrency)
    processing_started_at = _utc_now()
    processing_started_monotonic = time.perf_counter()
    report = RunReport(
        total=len(executable_files),
        started_at=processing_started_at,
    )
    started_count = 0
    event_error: Exception | None = None

    def _emit_event(event_type: str, payload: dict[str, Any]) -> None:
        nonlocal event_error
        if event_sink is None or event_error is not None:
            return
        try:
            event_sink(event_type, payload)
        except Exception as exc:
            event_error = exc

    _emit_event(
        "processing_started",
        {
            "processing_started_at": processing_started_at,
            "total": report.total,
            "concurrency": concurrency,
        },
    )

    async def _run_one(db_file: KnowledgeFile) -> FileReparseResult:
        nonlocal started_count
        async with semaphore:
            started_count += 1
            started_at = _utc_now()
            started_monotonic = time.perf_counter()
            _emit_event(
                "file_started",
                {
                    "file_id": int(db_file.id),
                    "knowledge_id": db_file.knowledge_id,
                    "file_name": db_file.file_name,
                    "started_at": started_at,
                },
            )
            print(f"[START] file_id={db_file.id} file_name={db_file.file_name} started={started_count}/{report.total}")
            try:
                result = await asyncio.to_thread(reparse_func, int(db_file.id))
            except Exception as exc:  # pragma: no cover - defensive guard
                result = FileReparseResult(
                    int(db_file.id),
                    db_file.knowledge_id,
                    db_file.file_name,
                    False,
                    None,
                    "".join(traceback.format_exception_only(type(exc), exc)).strip(),
                )
            finished_at = _utc_now()
            return replace(
                result,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=max(0.0, time.perf_counter() - started_monotonic),
            )

    tasks = [_run_one(db_file) for db_file in executable_files]
    for task in asyncio.as_completed(tasks):
        result = await task
        report.results.append(result)
        if result.success:
            report.success += 1
        else:
            report.failed += 1
        completed = report.success + report.failed
        percent = (completed / report.total * 100) if report.total else 100.0
        progress = (
            f"duration={result.duration_seconds:.3f}s "
            f"progress={completed}/{report.total} ({percent:.1f}%) "
            f"success={report.success} failed={report.failed} "
            f"elapsed={time.perf_counter() - processing_started_monotonic:.3f}s"
        )
        if result.success:
            print(f"[SUCCESS] file_id={result.file_id} file_name={result.file_name} {progress}")
        else:
            print(f"[FAILED] file_id={result.file_id} file_name={result.file_name} error={result.error} {progress}")
        _emit_event(
            "file_completed",
            {
                "file_id": result.file_id,
                "knowledge_id": result.knowledge_id,
                "file_name": result.file_name,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "duration_seconds": result.duration_seconds,
                "success": result.success,
                "final_status": result.final_status,
                "error": result.error,
                "completed": completed,
                "total": report.total,
                "success_count": report.success,
                "failed_count": report.failed,
            },
        )
    report.finished_at = _utc_now()
    report.duration_seconds = max(0.0, time.perf_counter() - processing_started_monotonic)
    if event_error is not None:
        raise ReportWriteError("unable to emit reparse report events") from event_error
    return report


def print_selection_report(report: SelectionReport) -> None:
    print(
        "Selection summary: "
        f"selected={report.selected_count} skipped={report.skipped_count} "
        f"missing_spaces={report.skipped_missing_spaces} "
        f"missing_folders={report.skipped_missing_folders} "
        f"missing_files={report.skipped_missing_files} "
        f"non_space={report.skipped_non_space_records} "
        f"folders={report.skipped_folder_records} "
        f"non_folders={report.skipped_non_folder_records} "
        f"space_level={report.skipped_space_level_records} "
        f"ineligible_status={report.skipped_status_records} "
        f"duplicates={report.duplicate_records}"
    )
    for warning in report.warnings:
        print(f"[WARN] {warning}")


def print_run_report(report: RunReport) -> None:
    print(
        f"Run summary: total={report.total} success={report.success} "
        f"failed={report.failed} duration={report.duration_seconds:.3f}s"
    )


def _selection_report_payload(report: SelectionReport) -> dict[str, int]:
    return {
        "selected": report.selected_count,
        "skipped": report.skipped_count,
        "missing_spaces": report.skipped_missing_spaces,
        "missing_folders": report.skipped_missing_folders,
        "missing_files": report.skipped_missing_files,
        "non_space": report.skipped_non_space_records,
        "folders": report.skipped_folder_records,
        "non_folders": report.skipped_non_folder_records,
        "space_level": report.skipped_space_level_records,
        "ineligible_status": report.skipped_status_records,
        "duplicates": report.duplicate_records,
    }


def _arguments_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "apply": bool(args.apply),
        "concurrency": int(args.concurrency),
        "report_file": args.report_file,
        "space_ids": list(args.space_ids),
        "folder_ids": list(args.folder_ids),
        "file_ids": list(args.file_ids),
        "space_level": args.space_level,
        "statuses": list(args.statuses),
        "include_inflight": bool(args.include_inflight),
        "only_inflight": bool(args.only_inflight),
    }


def _print_report_error(exc: ReportWriteError) -> None:
    print(f"[REPORT FAILED] {exc}", file=sys.stderr)


async def run(args: argparse.Namespace) -> int:
    import functools

    include_inflight: bool = getattr(args, "include_inflight", False)
    only_inflight: bool = getattr(args, "only_inflight", False)
    effective_statuses = resolve_eligible_statuses(args)
    run_id = generate_run_id()
    run_started_at = _utc_now()
    run_started_monotonic = time.perf_counter()
    writer: JsonlReportWriter | None = None
    report_error: ReportWriteError | None = None
    exit_code = 1
    selection_duration_seconds = 0.0
    selection_started_monotonic = run_started_monotonic
    run_report = RunReport()

    try:
        if args.apply:
            report_path = resolve_report_path(args.report_file, run_id)
            try:
                writer = JsonlReportWriter(report_path, run_id=run_id).start()
                writer.emit(
                    "run_started",
                    {
                        "started_at": run_started_at,
                        "report_file": str(report_path),
                        "arguments": _arguments_payload(args),
                    },
                )
            except ReportWriteError as exc:
                _print_report_error(exc)
                return 3

        try:
            selection_started_at = _utc_now()
            selection_started_monotonic = time.perf_counter()
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    selection = await collect_candidate_files(
                        session,
                        space_ids=args.space_ids,
                        folder_ids=args.folder_ids,
                        file_ids=args.file_ids,
                        space_level=args.space_level,
                        eligible_statuses=effective_statuses,
                    )
            selection_finished_at = _utc_now()
            selection_duration_seconds = max(
                0.0,
                time.perf_counter() - selection_started_monotonic,
            )
            if writer is not None:
                writer.emit(
                    "selection_completed",
                    {
                        "selection_started_at": selection_started_at,
                        "selection_finished_at": selection_finished_at,
                        "selection_duration_seconds": selection_duration_seconds,
                        **_selection_report_payload(selection),
                    },
                )

            print_selection_report(selection)
            if only_inflight:
                print("[INFO] --only-inflight is active: selecting ONLY WAITING/PROCESSING/REBUILDING files.")
            elif include_inflight:
                print("[INFO] --include-inflight is active: WAITING/PROCESSING/REBUILDING files are included.")
            if args.space_level:
                print(f"[INFO] --space-level is active: {args.space_level}.")
            if args.statuses:
                print(f"[INFO] --status is active: {','.join(args.statuses)}.")

            if not args.apply:
                print("Dry-run only. Pass --apply to reparse selected files.")
                exit_code = 0
            elif not selection.selected_files:
                print("No eligible files selected.")
                run_report = RunReport()
                exit_code = 0
            else:
                reparse_func = functools.partial(
                    reparse_one_file,
                    eligible_statuses=effective_statuses,
                )
                run_report = await run_reparse_files(
                    selection.selected_files,
                    concurrency=args.concurrency,
                    reparse_func=reparse_func,
                    event_sink=writer.emit if writer is not None else None,
                )
                print_run_report(run_report)
                exit_code = 2 if run_report.failed else 0

            if writer is not None:
                finished_at = _utc_now()
                writer.emit(
                    "run_completed",
                    {
                        "started_at": run_started_at,
                        "finished_at": finished_at,
                        "run_status": ("partial_failure" if run_report.failed else "success"),
                        "selection_duration_seconds": selection_duration_seconds,
                        "processing_duration_seconds": run_report.duration_seconds,
                        "total_duration_seconds": max(
                            0.0,
                            time.perf_counter() - run_started_monotonic,
                        ),
                        "total": run_report.total,
                        "success": run_report.success,
                        "failed": run_report.failed,
                    },
                )
        except ReportWriteError as exc:
            report_error = exc
            _print_report_error(exc)
            exit_code = 3
        except Exception as exc:
            selection_duration_seconds = max(
                selection_duration_seconds,
                time.perf_counter() - selection_started_monotonic,
            )
            if writer is not None:
                try:
                    writer.emit(
                        "run_completed",
                        {
                            "started_at": run_started_at,
                            "finished_at": _utc_now(),
                            "run_status": "failed",
                            "selection_duration_seconds": selection_duration_seconds,
                            "processing_duration_seconds": run_report.duration_seconds,
                            "total_duration_seconds": max(
                                0.0,
                                time.perf_counter() - run_started_monotonic,
                            ),
                            "total": run_report.total,
                            "success": run_report.success,
                            "failed": run_report.failed,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                except ReportWriteError as report_exc:
                    report_error = report_exc
                    _print_report_error(report_exc)
            raise
        finally:
            if writer is not None:
                try:
                    writer.close()
                except ReportWriteError as exc:
                    if report_error is None:
                        _print_report_error(exc)
                    exit_code = 3
        return exit_code
    finally:
        await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
