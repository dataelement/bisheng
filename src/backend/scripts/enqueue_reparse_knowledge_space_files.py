#!/usr/bin/env python3
"""Enqueue knowledge-space files for worker-based reparse.

This maintenance script reuses the candidate-selection behavior from
``reparse_knowledge_space_files.py``. By default it is a dry-run and only
prints the files that would be enqueued. Pass ``--apply`` to move each still
eligible file to ``WAITING`` and publish ``retry_knowledge_file_celery`` to
the ``knowledge_celery`` queue.

The script reports broker publication only. It does not wait for workers or
claim that parsing has completed.

Usage:
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --apply
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --apply --space-id 10
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --folder-id 20
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --file-id 101
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --space-level department
    PYTHONPATH=./ .venv/bin/python scripts/enqueue_reparse_knowledge_space_files.py --status failed
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import (  # noqa: E402
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
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
from scripts.reparse_knowledge_space_files import (  # noqa: E402
    SPACE_LEVEL_CHOICES,
    STATUS_NAME_TO_VALUE,
    SelectionReport,
    collect_candidate_files,
    print_selection_report,
    resolve_eligible_statuses,
)


class EnqueueOutcome(str, Enum):
    ENQUEUED = "enqueued"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FileStateSnapshot:
    status: int
    remark: str | None
    simhash: str | None
    similar_status: int


@dataclass(frozen=True)
class FileEnqueueResult:
    file_id: int
    tenant_id: int | None
    file_name: str
    outcome: EnqueueOutcome
    task_id: str = ""
    error: str = ""
    rollback_error: str = ""


@dataclass
class EnqueueRunReport:
    selected: int = 0
    enqueued: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[FileEnqueueResult] = field(default_factory=list)


FetchFile = Callable[[int], KnowledgeFile | None]
FetchKnowledge = Callable[[int], Knowledge | None]
UpdateFile = Callable[[KnowledgeFile], KnowledgeFile]
PublishTask = Callable[[int, int], str]
EnqueueFile = Callable[..., FileEnqueueResult]


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
        help="update selected files and publish retry tasks; default is dry-run",
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
        help=("also select WAITING, PROCESSING, or REBUILDING files; this can duplicate work already being processed"),
    )
    parser.add_argument(
        "--only-inflight",
        dest="only_inflight",
        action="store_true",
        help=("select only WAITING, PROCESSING, or REBUILDING files; this can duplicate work already being processed"),
    )
    args = parser.parse_args(argv)
    if args.statuses and (args.include_inflight or args.only_inflight):
        parser.error("--status cannot be combined with --include-inflight or --only-inflight")
    return args


def _get_file_sync(file_id: int) -> KnowledgeFile | None:
    records = KnowledgeFileDao.get_file_by_ids([file_id])
    return records[0] if records else None


def _get_knowledge_sync(knowledge_id: int) -> Knowledge | None:
    return KnowledgeDao.query_by_id(knowledge_id)


def _update_file_sync(db_file: KnowledgeFile) -> KnowledgeFile:
    return KnowledgeFileDao.update(db_file)


def publish_retry_task(file_id: int, tenant_id: int, *, task: Any = None) -> str:
    """Publish one retry task while preventing tenant-context overwrite."""
    from bisheng.knowledge.domain.services.knowledge_parse_dispatch_service import (
        KnowledgeParseAttemptKind,
        dispatch_knowledge_parse_task_sync,
    )

    if task is None:
        from bisheng.worker.knowledge.file_worker import retry_knowledge_file_celery

        task = retry_knowledge_file_celery

    tenant_token = set_current_tenant_id(tenant_id)
    try:
        return dispatch_knowledge_parse_task_sync(
            attempt_kind=KnowledgeParseAttemptKind.RETRY,
            file_id=file_id,
            task=task,
        )
    finally:
        current_tenant_id.reset(tenant_token)


def _restore_snapshot(db_file: KnowledgeFile, snapshot: FileStateSnapshot) -> None:
    db_file.status = snapshot.status
    db_file.remark = snapshot.remark
    db_file.simhash = snapshot.simhash
    db_file.similar_status = snapshot.similar_status


def _result_for_record(
    file_id: int,
    db_file: KnowledgeFile | None,
    outcome: EnqueueOutcome,
    error: str,
) -> FileEnqueueResult:
    return FileEnqueueResult(
        file_id=file_id,
        tenant_id=db_file.tenant_id if db_file else None,
        file_name=db_file.file_name if db_file else "",
        outcome=outcome,
        error=error,
    )


def enqueue_one_file(
    file_id: int,
    *,
    eligible_statuses: tuple[int, ...],
    fetch_file: FetchFile | None = None,
    fetch_knowledge: FetchKnowledge | None = None,
    update_file: UpdateFile | None = None,
    publish_task: PublishTask | None = None,
) -> FileEnqueueResult:
    """Prepare and enqueue one file, compensating state on publish failure."""
    fetch_file = fetch_file or _get_file_sync
    fetch_knowledge = fetch_knowledge or _get_knowledge_sync
    update_file = update_file or _update_file_sync
    publish_task = publish_task or publish_retry_task

    with bypass_tenant_filter():
        db_file = fetch_file(file_id)
        if db_file is None:
            return _result_for_record(file_id, None, EnqueueOutcome.SKIPPED, "file not found")
        if db_file.file_type != FileType.FILE.value:
            return _result_for_record(file_id, db_file, EnqueueOutcome.SKIPPED, "record is not a file")
        if db_file.status not in eligible_statuses:
            return _result_for_record(file_id, db_file, EnqueueOutcome.SKIPPED, "status is no longer eligible")

        knowledge = fetch_knowledge(db_file.knowledge_id)
        if knowledge is None or knowledge.type != KnowledgeTypeEnum.SPACE.value:
            return _result_for_record(file_id, db_file, EnqueueOutcome.SKIPPED, "knowledge is not a space")
        if db_file.tenant_id is None:
            return _result_for_record(file_id, db_file, EnqueueOutcome.FAILED, "file tenant_id is missing")

        snapshot = FileStateSnapshot(
            status=db_file.status,
            remark=db_file.remark,
            simhash=db_file.simhash,
            similar_status=db_file.similar_status,
        )
        db_file.status = KnowledgeFileStatus.WAITING.value
        db_file.remark = ""
        db_file.simhash = None
        db_file.similar_status = 0

        try:
            db_file = update_file(db_file)
        except Exception as exc:
            _restore_snapshot(db_file, snapshot)
            return _result_for_record(
                file_id,
                db_file,
                EnqueueOutcome.FAILED,
                f"state update failed: {exc}",
            )

        try:
            task_id = publish_task(file_id, int(db_file.tenant_id))
        except Exception as exc:
            publish_error = f"publish failed: {exc}"
            _restore_snapshot(db_file, snapshot)
            try:
                update_file(db_file)
            except Exception as rollback_exc:
                return FileEnqueueResult(
                    file_id=file_id,
                    tenant_id=db_file.tenant_id,
                    file_name=db_file.file_name,
                    outcome=EnqueueOutcome.FAILED,
                    error=publish_error,
                    rollback_error=f"rollback failed: {rollback_exc}",
                )
            return FileEnqueueResult(
                file_id=file_id,
                tenant_id=db_file.tenant_id,
                file_name=db_file.file_name,
                outcome=EnqueueOutcome.FAILED,
                error=publish_error,
            )

        return FileEnqueueResult(
            file_id=file_id,
            tenant_id=db_file.tenant_id,
            file_name=db_file.file_name,
            outcome=EnqueueOutcome.ENQUEUED,
            task_id=task_id,
        )


def run_enqueue_files(
    files: Sequence[KnowledgeFile],
    *,
    eligible_statuses: tuple[int, ...],
    enqueue_func: EnqueueFile = enqueue_one_file,
) -> EnqueueRunReport:
    report = EnqueueRunReport(selected=len(files))
    for db_file in files:
        if db_file.id is None:
            result = FileEnqueueResult(
                file_id=0,
                tenant_id=db_file.tenant_id,
                file_name=db_file.file_name,
                outcome=EnqueueOutcome.FAILED,
                error="selected record has no file ID",
            )
        else:
            try:
                result = enqueue_func(
                    int(db_file.id),
                    eligible_statuses=eligible_statuses,
                )
            except Exception as exc:
                result = FileEnqueueResult(
                    file_id=int(db_file.id),
                    tenant_id=db_file.tenant_id,
                    file_name=db_file.file_name,
                    outcome=EnqueueOutcome.FAILED,
                    error=f"enqueue raised: {exc}",
                )

        report.results.append(result)
        if result.outcome == EnqueueOutcome.ENQUEUED:
            report.enqueued += 1
            print(
                f"[ENQUEUED] file_id={result.file_id} tenant_id={result.tenant_id} "
                f"file_name={result.file_name} task_id={result.task_id}"
            )
        elif result.outcome == EnqueueOutcome.SKIPPED:
            report.skipped += 1
            print(
                f"[SKIPPED] file_id={result.file_id} tenant_id={result.tenant_id} "
                f"file_name={result.file_name} reason={result.error}"
            )
        else:
            report.failed += 1
            rollback_suffix = f" rollback_error={result.rollback_error}" if result.rollback_error else ""
            print(
                f"[FAILED] file_id={result.file_id} tenant_id={result.tenant_id} "
                f"file_name={result.file_name} error={result.error}{rollback_suffix}"
            )
    return report


def print_run_report(report: EnqueueRunReport) -> None:
    print(
        "Enqueue summary: "
        f"selected={report.selected} enqueued={report.enqueued} "
        f"skipped={report.skipped} failed={report.failed}"
    )


def exit_code_for_report(report: EnqueueRunReport) -> int:
    return 2 if report.failed else 0


def apply_selection(
    selection: SelectionReport,
    *,
    apply: bool,
    eligible_statuses: tuple[int, ...],
    enqueue_func: EnqueueFile = enqueue_one_file,
) -> EnqueueRunReport | None:
    if not apply:
        print("Dry-run only. Pass --apply to update selected files and enqueue retry tasks.")
        return None
    if not selection.selected_files:
        print("No eligible files selected.")
        return EnqueueRunReport()

    report = run_enqueue_files(
        selection.selected_files,
        eligible_statuses=eligible_statuses,
        enqueue_func=enqueue_func,
    )
    print_run_report(report)
    return report


async def collect_selection(args: argparse.Namespace) -> tuple[SelectionReport, tuple[int, ...]]:
    effective_statuses = resolve_eligible_statuses(args)
    try:
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

        print_selection_report(selection)
        if args.only_inflight:
            print("[WARN] --only-inflight may enqueue files that already have active parse tasks.")
        elif args.include_inflight:
            print("[WARN] --include-inflight may enqueue files that already have active parse tasks.")
        if args.space_level:
            print(f"[INFO] --space-level is active: {args.space_level}.")
        if args.statuses:
            print(f"[INFO] --status is active: {','.join(args.statuses)}.")
        return selection, effective_statuses
    finally:
        await close_app_context()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selection, effective_statuses = asyncio.run(collect_selection(args))
    report = apply_selection(
        selection,
        apply=args.apply,
        eligible_statuses=effective_statuses,
    )
    return exit_code_for_report(report) if report is not None else 0


if __name__ == "__main__":
    sys.exit(main())
