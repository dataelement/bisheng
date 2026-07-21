#!/usr/bin/env python3
"""Backfill AI auto tags for knowledge-space files with too few tags.

Scans knowledge-space files, selects those whose visible tag count is below
``--min-tags`` (default: 3), then reuses the production Link A / Link B pipeline.
New tags are capped so each file's total visible tag count stays within
``--max-tags`` (default: 6).

- Link A: ``KnowledgeSpaceAutoTagService.apply_after_upload_parse``
- Link B: ``KnowledgeSpaceReviewTagService.apply_after_review_upload_parse``

File content is loaded from Elasticsearch chunks (same source as online parse
metadata). When ES content is unavailable, the script falls back to ``abstract``.

Default is dry-run. Pass ``--apply`` to invoke LLM tagging.

Usage:
    cd src/backend
    PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py
    PYTHONPATH=./ .venv/bin/python scripts/backfill_knowledge_space_auto_tags.py --apply
    bash scripts/backfill_knowledge_space_auto_tags.sh --apply --batch-size 20

    # Docker / production container (WORKDIR /app, system python):
    PYTHONPATH=./ python scripts/backfill_knowledge_space_auto_tags.py --apply
    bash scripts/backfill_knowledge_space_auto_tags.sh --apply --min-tags 3 --max-tags 6
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from langchain_core.documents import Document

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.group_resource import ResourceTypeEnum  # noqa: E402
from bisheng.database.models.review_tags import ReviewTagDao  # noqa: E402
from bisheng.database.models.tag import TagDao  # noqa: E402
from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag  # noqa: E402
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import (  # noqa: E402
    KnowledgeFile,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (  # noqa: E402
    AUTO_TAG_MAX_CONTENT,
    KnowledgeSpaceAutoTagService,
)
from bisheng.knowledge.domain.services.knowledge_space_review_tag_service import (  # noqa: E402
    KnowledgeSpaceReviewTagService,
)
from scripts.reparse_knowledge_space_files import (  # noqa: E402
    collect_candidate_files,
    print_selection_report,
)

ES_PAGE_SIZE = 200
DEFAULT_MIN_TAGS = 3
DEFAULT_MAX_TAGS = 6
DEFAULT_SCAN_BATCH_SIZE = 200
DEFAULT_PROCESS_BATCH_SIZE = 20


@dataclass
class TotalTagBudget:
    """Limit how many new tags may be appended for one file."""

    remaining: int

    def take(self, tag_names: Sequence[str]) -> list[str]:
        if self.remaining <= 0 or not tag_names:
            return []
        capped = list(tag_names)[: self.remaining]
        self.remaining -= len(capped)
        return capped


@dataclass(frozen=True)
class AutoTagRunResult:
    file_id: int
    space_id: int | None
    file_name: str
    tag_count_before: int
    link_a_applied: int
    link_b_ran: bool
    success: bool
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""


@dataclass
class ScanReport:
    scanned_files: int = 0
    under_threshold: list[KnowledgeFile] = field(default_factory=list)
    tag_counts: dict[int, int] = field(default_factory=dict)


@dataclass
class RunReport:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    success: int = 0
    failed: int = 0
    results: list[AutoTagRunResult] = field(default_factory=list)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be a non-negative integer")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="invoke Link A/B tagging; default is dry-run",
    )
    parser.add_argument(
        "--min-tags",
        type=_non_negative_int,
        default=DEFAULT_MIN_TAGS,
        help=f"process files with fewer than this many visible tags; default: {DEFAULT_MIN_TAGS}",
    )
    parser.add_argument(
        "--max-tags",
        type=_positive_int,
        default=DEFAULT_MAX_TAGS,
        help=f"cap total visible tags per file after backfill; default: {DEFAULT_MAX_TAGS}",
    )
    parser.add_argument(
        "--scan-batch-size",
        type=_positive_int,
        default=DEFAULT_SCAN_BATCH_SIZE,
        help=f"file IDs per tag-count batch query; default: {DEFAULT_SCAN_BATCH_SIZE}",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=DEFAULT_PROCESS_BATCH_SIZE,
        help=f"files processed per apply batch; default: {DEFAULT_PROCESS_BATCH_SIZE}",
    )
    parser.add_argument(
        "--concurrency",
        type=_positive_int,
        default=1,
        help="concurrent LLM workers within one apply batch; default: 1",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="maximum number of under-threshold files to process",
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
        help="folder ID whose descendant files should be included recursively",
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
        default=None,
        help="restrict scopes to one space level: public, department, team, or personal",
    )
    parser.add_argument(
        "--skip-link-b",
        action="store_true",
        help="run Link A only and never invoke Link B",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="bypass Link A/B _should_run gates (still requires SUCCESS parsed files)",
    )
    return parser.parse_args(argv)


def _patch_total_tag_budget(budget: TotalTagBudget) -> list[Any]:
    original_link_a = KnowledgeSpaceAutoTagService._append_file_tags
    original_link_b = KnowledgeSpaceReviewTagService._append_file_tags

    def append_link_a(
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
        resource_type,
    ) -> None:
        capped = budget.take(tag_names)
        if capped:
            original_link_a(space_id, file_id, capped, user_id, tenant_id, resource_type)

    def append_link_b(
        space_id: int,
        file_id: int,
        tag_names: list[str],
        user_id: int,
        tenant_id: int | None,
    ) -> None:
        capped = budget.take(tag_names)
        if capped:
            original_link_b(space_id, file_id, capped, user_id, tenant_id)

    return [
        patch.object(KnowledgeSpaceAutoTagService, "_append_file_tags", new=append_link_a),
        patch.object(KnowledgeSpaceReviewTagService, "_append_file_tags", new=append_link_b),
    ]


def count_visible_file_tags(file_ids: Sequence[int]) -> dict[int, int]:
    """Count display tags: approved tags + pending review tags, deduped by name."""
    if not file_ids:
        return {}
    resource_ids = [str(file_id) for file_id in file_ids]
    approved = TagDao.get_tags_by_resource_batch([ResourceTypeEnum.SPACE_FILE], resource_ids)
    counts: dict[int, int] = {}
    for file_id in file_ids:
        fid_str = str(file_id)
        seen_names: set[str] = set()
        total = 0
        for tag in approved.get(fid_str, []):
            name = (tag.name or "").strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen_names:
                continue
            seen_names.add(key)
            total += 1
        counts[file_id] = total

    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

    with bypass_tenant_filter():
        records = KnowledgeFileDao.get_file_by_ids(list(file_ids))
    tenant_by_file = {int(record.id): int(record.tenant_id) for record in records if record.id is not None}

    tenant_to_file_ids: dict[int, list[int]] = {}
    for file_id in file_ids:
        tenant_id = tenant_by_file.get(int(file_id))
        if tenant_id is None:
            continue
        tenant_to_file_ids.setdefault(tenant_id, []).append(int(file_id))

    for tenant_id, grouped_file_ids in tenant_to_file_ids.items():
        grouped_resource_ids = [str(file_id) for file_id in grouped_file_ids]
        pending = ReviewTagDao.get_tags_by_resource_batch(
            [ResourceTypeEnum.SPACE_FILE],
            grouped_resource_ids,
            tenant_id=tenant_id,
        )
        for file_id in grouped_file_ids:
            fid_str = str(file_id)
            seen_names = {
                (tag.name or "").strip().casefold() for tag in approved.get(fid_str, []) if (tag.name or "").strip()
            }
            total = counts.get(file_id, 0)
            for review_tag in pending.get(fid_str, []):
                if review_tag.review_status != 0:
                    continue
                name = (review_tag.name or "").strip()
                if not name:
                    continue
                key = name.casefold()
                if key in seen_names:
                    continue
                seen_names.add(key)
                total += 1
            counts[file_id] = total

    for file_id in file_ids:
        counts.setdefault(int(file_id), 0)
    return counts


def _normalize_chunk(hit: dict[str, Any]) -> dict[str, Any]:
    source = hit.get("_source") or {}
    metadata = source.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": hit.get("_id"),
        "text": source.get("text", ""),
        "metadata": metadata,
    }


def _chunk_sort_key(chunk: dict[str, Any]) -> tuple[int, int | str, str]:
    chunk_index = chunk["metadata"].get("chunk_index")
    try:
        return 0, int(chunk_index), str(chunk["id"] or "")
    except (TypeError, ValueError):
        return 1, str(chunk_index or ""), str(chunk["id"] or "")


def load_file_documents(knowledge: Knowledge, db_file: KnowledgeFile) -> list[Document]:
    """Load parsed file text from ES chunks, falling back to abstract."""
    content = ""
    if getattr(knowledge, "index_name", None):
        scroll_id: str | None = None
        client = None
        try:
            store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge)
            client = store.client
            response = client.search(
                index=knowledge.index_name,
                query={"term": {"metadata.document_id": db_file.id}},
                size=ES_PAGE_SIZE,
                scroll="1m",
                source=True,
            )
            chunks: list[dict[str, Any]] = []
            scroll_id = response.get("_scroll_id")
            while True:
                hits = response.get("hits", {}).get("hits", [])
                if not hits:
                    break
                chunks.extend(_normalize_chunk(hit) for hit in hits)
                if not scroll_id:
                    break
                response = client.scroll(scroll_id=scroll_id, scroll="1m")
                scroll_id = response.get("_scroll_id", scroll_id)
            if chunks:
                chunks.sort(key=_chunk_sort_key)
                content = "\n".join(str(chunk.get("text") or "") for chunk in chunks).strip()
        except Exception:
            content = ""
        finally:
            if client is not None and scroll_id:
                try:
                    client.clear_scroll(scroll_id=scroll_id)
                except Exception:
                    pass

    if not content and db_file.abstract:
        content = db_file.abstract.strip()
    if not content:
        return []
    return [Document(page_content=content[:AUTO_TAG_MAX_CONTENT])]


def _resolve_enable_pending_review_tags() -> bool:
    from bisheng.api.services.workstation import WorkStationService

    cfg, _inherited, _source_tenant_id, _has_override = WorkStationService.query_knowledge_space_config_with_meta()
    return bool(getattr(cfg, "review_tag_visible", True)) if cfg else True


def _link_a_skip_reason(knowledge: Knowledge | None, db_file: KnowledgeFile | None) -> str:
    if knowledge is None:
        return "knowledge not found"
    if db_file is None:
        return "file not found"
    if KnowledgeSpaceAutoTagService._should_run(knowledge, db_file):
        return ""
    if db_file.status != KnowledgeFileStatus.SUCCESS.value:
        return "file status is not SUCCESS"
    if not KnowledgeSpaceAutoTagService._resolve_library_ids(knowledge):
        return "no tag library configured"
    if KnowledgeSpaceAutoTagService._has_manual_upload_tags(db_file):
        return "manual upload tags already applied"
    return "file source or type not eligible for Link A"


def _link_b_skip_reason(knowledge: Knowledge | None, db_file: KnowledgeFile | None) -> str:
    if knowledge is None:
        return "knowledge not found"
    if db_file is None:
        return "file not found"
    if KnowledgeSpaceReviewTagService._should_run(knowledge, db_file):
        return ""
    if not getattr(knowledge, "auto_tag_enabled", False):
        return "space auto_tag_enabled is false"
    if db_file.status != KnowledgeFileStatus.SUCCESS.value:
        return "file status is not SUCCESS"
    if not KnowledgeSpaceAutoTagService._resolve_library_ids(knowledge):
        return "no tag library configured"
    return "file source or type not eligible for Link B"


def run_auto_tags_for_file(
    file_id: int,
    *,
    tag_count_before: int,
    max_total_tags: int,
    enable_link_b: bool,
    force: bool,
) -> AutoTagRunResult:
    with bypass_tenant_filter():
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao

        records = KnowledgeFileDao.get_file_by_ids([file_id])
        db_file = records[0] if records else None
        knowledge = KnowledgeDao.query_by_id(db_file.knowledge_id) if db_file else None

    if db_file is None or knowledge is None:
        return AutoTagRunResult(
            file_id=file_id,
            space_id=getattr(db_file, "knowledge_id", None),
            file_name=getattr(db_file, "file_name", ""),
            tag_count_before=tag_count_before,
            link_a_applied=0,
            link_b_ran=False,
            success=False,
            skipped=True,
            skip_reason="file or knowledge not found",
        )

    if tag_count_before >= max_total_tags:
        return AutoTagRunResult(
            file_id=file_id,
            space_id=int(knowledge.id) if knowledge is not None else None,
            file_name=getattr(db_file, "file_name", ""),
            tag_count_before=tag_count_before,
            link_a_applied=0,
            link_b_ran=False,
            success=False,
            skipped=True,
            skip_reason=f"tag count already at or above max ({max_total_tags})",
        )

    link_a_reason = _link_a_skip_reason(knowledge, db_file)
    if link_a_reason and not force:
        return AutoTagRunResult(
            file_id=file_id,
            space_id=int(knowledge.id),
            file_name=db_file.file_name,
            tag_count_before=tag_count_before,
            link_a_applied=0,
            link_b_ran=False,
            success=False,
            skipped=True,
            skip_reason=f"Link A skipped: {link_a_reason}",
        )

    documents = load_file_documents(knowledge, db_file)
    if not documents and not (db_file.abstract or "").strip():
        return AutoTagRunResult(
            file_id=file_id,
            space_id=int(knowledge.id),
            file_name=db_file.file_name,
            tag_count_before=tag_count_before,
            link_a_applied=0,
            link_b_ran=False,
            success=False,
            skipped=True,
            skip_reason="empty content (no ES chunks and no abstract)",
        )

    tag_budget = TotalTagBudget(remaining=max(max_total_tags - tag_count_before, 0))
    patches = _patch_total_tag_budget(tag_budget)
    if force:
        patches.extend(
            [
                patch.object(KnowledgeSpaceAutoTagService, "_should_run", return_value=True),
                patch.object(KnowledgeSpaceReviewTagService, "_should_run", return_value=True),
            ]
        )

    try:
        for item in patches:
            item.start()
        link_a_applied = KnowledgeSpaceAutoTagService.apply_after_upload_parse(
            knowledge=knowledge,
            db_file=db_file,
            documents=documents,
        )
        link_b_ran = False
        if (
            enable_link_b
            and tag_budget.remaining > 0
            and KnowledgeSpaceAutoTagService.should_run_link_b_after_link_a(link_a_applied)
        ):
            link_b_reason = _link_b_skip_reason(knowledge, db_file)
            if link_b_reason and not force:
                return AutoTagRunResult(
                    file_id=file_id,
                    space_id=int(knowledge.id),
                    file_name=db_file.file_name,
                    tag_count_before=tag_count_before,
                    link_a_applied=link_a_applied,
                    link_b_ran=False,
                    success=link_a_applied > 0,
                    skipped=link_a_applied <= 0,
                    skip_reason=f"Link B skipped: {link_b_reason}",
                )
            KnowledgeSpaceReviewTagService.apply_after_review_upload_parse(
                knowledge=knowledge,
                db_file=db_file,
                documents=documents,
            )
            link_b_ran = True
        return AutoTagRunResult(
            file_id=file_id,
            space_id=int(knowledge.id),
            file_name=db_file.file_name,
            tag_count_before=tag_count_before,
            link_a_applied=link_a_applied,
            link_b_ran=link_b_ran,
            success=link_a_applied > 0 or link_b_ran,
        )
    except Exception as exc:
        return AutoTagRunResult(
            file_id=file_id,
            space_id=int(knowledge.id),
            file_name=db_file.file_name,
            tag_count_before=tag_count_before,
            link_a_applied=0,
            link_b_ran=False,
            success=False,
            error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )
    finally:
        for item in reversed(patches):
            item.stop()


def scan_under_tag_threshold(
    files: Sequence[KnowledgeFile],
    *,
    min_tags: int,
    scan_batch_size: int,
    limit: int | None,
) -> ScanReport:
    report = ScanReport()
    eligible = [file for file in files if file.id is not None]
    report.scanned_files = len(eligible)

    selected: list[KnowledgeFile] = []
    for start in range(0, len(eligible), scan_batch_size):
        batch = eligible[start : start + scan_batch_size]
        batch_ids = [int(file.id) for file in batch]
        counts = count_visible_file_tags(batch_ids)
        report.tag_counts.update(counts)
        for file in batch:
            file_id = int(file.id)
            if counts.get(file_id, 0) >= min_tags:
                continue
            selected.append(file)
            if limit is not None and len(selected) >= limit:
                report.under_threshold = selected
                return report

    report.under_threshold = selected
    return report


def print_scan_report(report: ScanReport, *, min_tags: int, max_tags: int) -> None:
    print(
        f"Scan summary: scanned={report.scanned_files} "
        f"under_threshold(<{min_tags})={len(report.under_threshold)} max_total={max_tags}"
    )
    preview = report.under_threshold[:20]
    for file in preview:
        file_id = int(file.id)
        print(
            f"  file_id={file_id} space_id={file.knowledge_id} "
            f"tags={report.tag_counts.get(file_id, 0)} name={file.file_name}"
        )
    if len(report.under_threshold) > len(preview):
        print(f"  ... and {len(report.under_threshold) - len(preview)} more")


async def run_apply_batches(
    files: Sequence[KnowledgeFile],
    *,
    tag_counts: dict[int, int],
    max_total_tags: int,
    batch_size: int,
    concurrency: int,
    enable_link_b: bool,
    force: bool,
) -> RunReport:
    report = RunReport(total=len(files))
    semaphore = asyncio.Semaphore(concurrency)

    async def _run_one(db_file: KnowledgeFile) -> AutoTagRunResult:
        async with semaphore:
            file_id = int(db_file.id)
            return await asyncio.to_thread(
                run_auto_tags_for_file,
                file_id,
                tag_count_before=tag_counts.get(file_id, 0),
                max_total_tags=max_total_tags,
                enable_link_b=enable_link_b,
                force=force,
            )

    for start in range(0, len(files), batch_size):
        batch = list(files[start : start + batch_size])
        batch_no = start // batch_size + 1
        print(f"[BATCH] {batch_no} size={len(batch)} file_ids={[int(item.id) for item in batch]}")
        tasks = [_run_one(item) for item in batch if item.id is not None]
        for task in asyncio.as_completed(tasks):
            result = await task
            report.results.append(result)
            report.processed += 1
            if result.skipped:
                report.skipped += 1
                print(
                    f"[SKIP] file_id={result.file_id} space_id={result.space_id} "
                    f"tags_before={result.tag_count_before} reason={result.skip_reason or result.error}"
                )
            elif result.success:
                report.success += 1
                print(
                    f"[OK] file_id={result.file_id} space_id={result.space_id} "
                    f"tags_before={result.tag_count_before} link_a={result.link_a_applied} "
                    f"link_b={result.link_b_ran}"
                )
            else:
                report.failed += 1
                print(
                    f"[FAIL] file_id={result.file_id} space_id={result.space_id} "
                    f"tags_before={result.tag_count_before} error={result.error or 'no tags applied'}"
                )
    return report


def print_run_report(report: RunReport) -> None:
    print(
        "Run summary: "
        f"total={report.total} processed={report.processed} "
        f"success={report.success} skipped={report.skipped} failed={report.failed}"
    )


async def run(args: argparse.Namespace) -> int:
    eligible_statuses = (KnowledgeFileStatus.SUCCESS.value,)
    if args.min_tags > args.max_tags:
        print(
            f"[WARN] --min-tags ({args.min_tags}) is greater than --max-tags ({args.max_tags}); "
            "no files can be both eligible and expandable."
        )
    try:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                selection = await collect_candidate_files(
                    session,
                    space_ids=args.space_ids,
                    folder_ids=args.folder_ids,
                    file_ids=args.file_ids,
                    space_level=args.space_level,
                    eligible_statuses=eligible_statuses,
                )

        print_selection_report(selection)
        scan_report = scan_under_tag_threshold(
            selection.selected_files,
            min_tags=args.min_tags,
            scan_batch_size=args.scan_batch_size,
            limit=args.limit,
        )
        print_scan_report(scan_report, min_tags=args.min_tags, max_tags=args.max_tags)

        if not args.apply:
            print("Dry-run only. Pass --apply to run Link A/B for under-threshold files.")
            return 0

        if not scan_report.under_threshold:
            print("No files under the tag threshold.")
            return 0

        enable_link_b = _resolve_enable_pending_review_tags() and not args.skip_link_b
        if args.skip_link_b:
            print("[INFO] --skip-link-b is active: Link B will not run.")
        elif not enable_link_b:
            print("[INFO] review_tag_visible is disabled: Link B will not run.")

        run_report = await run_apply_batches(
            scan_report.under_threshold,
            tag_counts=scan_report.tag_counts,
            max_total_tags=args.max_tags,
            batch_size=args.batch_size,
            concurrency=args.concurrency,
            enable_link_b=enable_link_b,
            force=args.force,
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
