#!/usr/bin/env python3
"""Reparse knowledge-space files with bounded local concurrency.

This maintenance script reruns the normal knowledge-file parse pipeline for
knowledge-space files. It is intended for operational repair after parser,
index, or metadata logic changes.

By default the script is a dry-run and only prints the files that would be
processed. Pass ``--apply`` to mutate data. Before each file is reparsed,
the script deletes only that file's existing Milvus and Elasticsearch records;
it does not delete source files or generated preview objects from MinIO.

Usage:
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --concurrency 4
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --space-id 10 --folder-id 20
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --file-id 101 --file-id 102
    PYTHONPATH=./ .venv/bin/python scripts/reparse_knowledge_space_files.py --apply --include-inflight
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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


@dataclass
class SelectionReport:
    selected_files: list[KnowledgeFile] = field(default_factory=list)
    skipped_missing_spaces: int = 0
    skipped_missing_folders: int = 0
    skipped_missing_files: int = 0
    skipped_non_space_records: int = 0
    skipped_folder_records: int = 0
    skipped_non_folder_records: int = 0
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


@dataclass
class RunReport:
    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[FileReparseResult] = field(default_factory=list)


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
        "--include-inflight",
        dest="include_inflight",
        action="store_true",
        help=(
            "also select and reparse files whose status is WAITING or PROCESSING; "
            "by default these are skipped to avoid interfering with an active parse run"
        ),
    )
    return parser.parse_args(argv)


async def _get_all_space_ids(session: AsyncSession) -> set[int]:
    result = await session.exec(select(Knowledge.id).where(Knowledge.type == KnowledgeTypeEnum.SPACE.value))
    return {int(row) for row in result.all()}


async def _get_valid_requested_space_ids(
    session: AsyncSession,
    requested_space_ids: Sequence[int],
    report: SelectionReport,
) -> set[int]:
    requested = set(requested_space_ids)
    if not requested:
        return await _get_all_space_ids(session)

    result = await session.exec(
        select(Knowledge.id).where(
            col(Knowledge.id).in_(requested),
            Knowledge.type == KnowledgeTypeEnum.SPACE.value,
        )
    )
    valid_ids = {int(row) for row in result.all()}
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
    report: SelectionReport,
    eligible_statuses: tuple[int, ...],
) -> bool:
    if record.knowledge_id not in all_space_ids:
        report.skipped_non_space_records += 1
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
    eligible_statuses: tuple[int, ...] = ELIGIBLE_STATUSES,
) -> SelectionReport:
    """Collect the union of selected knowledge-space files.

    Scope arguments are unioned: passing both a space and a file includes files
    from the space plus the explicit file when it is otherwise eligible.
    """
    report = SelectionReport()
    selected: dict[int, KnowledgeFile] = {}
    has_scope_filter = bool(space_ids or folder_ids or file_ids)

    all_space_ids = await _get_all_space_ids(session)
    valid_space_ids = await _get_valid_requested_space_ids(session, space_ids, report)

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
            if _is_eligible_file(record, all_space_ids, report, eligible_statuses):
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


def reparse_one_file(file_id: int, *, force_inflight: bool = False) -> FileReparseResult:
    """Reparse one file and convert every failure into a result object."""
    with bypass_tenant_filter():
        db_file = _get_file_sync(file_id)
        if db_file is None:
            return FileReparseResult(file_id, None, "", False, None, "file not found")

        file_name = db_file.file_name
        knowledge_id = db_file.knowledge_id
        if db_file.file_type != FileType.FILE.value:
            return FileReparseResult(file_id, knowledge_id, file_name, False, db_file.status, "record is not a file")
        if not force_inflight and db_file.status in IN_FLIGHT_STATUSES:
            return FileReparseResult(file_id, knowledge_id, file_name, False, db_file.status, "file is in-flight")
        eligible = ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES if force_inflight else ELIGIBLE_STATUSES
        if db_file.status not in eligible:
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
) -> RunReport:
    semaphore = asyncio.Semaphore(concurrency)
    report = RunReport(total=len(files))

    async def _run_one(db_file: KnowledgeFile) -> FileReparseResult:
        async with semaphore:
            try:
                return await asyncio.to_thread(reparse_func, int(db_file.id))
            except Exception as exc:  # pragma: no cover - defensive guard
                return FileReparseResult(
                    int(db_file.id),
                    db_file.knowledge_id,
                    db_file.file_name,
                    False,
                    None,
                    "".join(traceback.format_exception_only(type(exc), exc)).strip(),
                )

    tasks = [_run_one(db_file) for db_file in files if db_file.id is not None]
    for task in asyncio.as_completed(tasks):
        result = await task
        report.results.append(result)
        if result.success:
            report.success += 1
            print(f"[SUCCESS] file_id={result.file_id} file_name={result.file_name}")
        else:
            report.failed += 1
            print(f"[FAILED] file_id={result.file_id} file_name={result.file_name} error={result.error}")
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
        f"ineligible_status={report.skipped_status_records} "
        f"duplicates={report.duplicate_records}"
    )
    for warning in report.warnings:
        print(f"[WARN] {warning}")


def print_run_report(report: RunReport) -> None:
    print(f"Run summary: total={report.total} success={report.success} failed={report.failed}")


async def run(args: argparse.Namespace) -> int:
    import functools

    include_inflight: bool = getattr(args, "include_inflight", False)
    effective_statuses = ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES if include_inflight else ELIGIBLE_STATUSES

    try:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                selection = await collect_candidate_files(
                    session,
                    space_ids=args.space_ids,
                    folder_ids=args.folder_ids,
                    file_ids=args.file_ids,
                    eligible_statuses=effective_statuses,
                )

        print_selection_report(selection)
        if include_inflight:
            print("[INFO] --include-inflight is active: WAITING/PROCESSING files are included.")

        if not args.apply:
            print("Dry-run only. Pass --apply to reparse selected files.")
            return 0

        if not selection.selected_files:
            print("No eligible files selected.")
            return 0

        reparse_func = (
            functools.partial(reparse_one_file, force_inflight=True)
            if include_inflight
            else reparse_one_file
        )
        run_report = await run_reparse_files(
            selection.selected_files,
            concurrency=args.concurrency,
            reparse_func=reparse_func,
        )
        print_run_report(run_report)
        return 2 if run_report.failed else 0
    finally:
        await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
