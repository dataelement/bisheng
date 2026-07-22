#!/usr/bin/env python3
"""Remove the industry-intelligence tag from files whose category is not NEW.

The Shougang file category ``NEW`` maps to the label ``行业情报``. This script
finds knowledge-space file links for a given tag name (default: ``行业情报``)
and deletes only those links whose file category is **not** ``NEW``.

Tag definitions in ``tag`` / ``review_tag`` are kept; only ``tag_link`` /
``review_tag_link`` rows are removed.

Usage (from ``src/backend/``):

    # Preview only (default)
    python scripts/remove_industry_intelligence_tag_mismatch.py

    # Apply deletions
    python scripts/remove_industry_intelligence_tag_mismatch.py --apply

    # Also remove pending review-tag links
    python scripts/remove_industry_intelligence_tag_mismatch.py --apply --include-review-tags

    # Limit scope
    python scripts/remove_industry_intelligence_tag_mismatch.py --tenant-id 1 --space-id 12 --file-id 1580
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import delete, select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_async_db_session  # noqa: E402
from bisheng.database.models.group_resource import ResourceTypeEnum  # noqa: E402
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink  # noqa: E402
from bisheng.database.models.tag import Tag, TagLink  # noqa: E402
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile  # noqa: E402
from bisheng.knowledge.domain.services.knowledge_space_auto_tag_service import (  # noqa: E402
    KnowledgeSpaceAutoTagService,
)

DEFAULT_TAG_NAME = "行业情报"
DEFAULT_CATEGORY_CODE = "NEW"
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class LinkCandidate:
    link_id: int
    file_id: int
    file_name: str | None
    category_code: str | None
    knowledge_id: int | None
    tenant_id: int | None


@dataclass
class ScanReport:
    tag_ids: list[int] = field(default_factory=list)
    review_tag_ids: list[int] = field(default_factory=list)
    scanned_tag_links: int = 0
    scanned_review_tag_links: int = 0
    kept_on_target_category: int = 0
    to_remove: list[LinkCandidate] = field(default_factory=list)
    review_to_remove: list[LinkCandidate] = field(default_factory=list)
    orphan_links: int = 0
    orphan_review_links: int = 0


@dataclass
class ApplyReport:
    tag_links_deleted: int = 0
    review_tag_links_deleted: int = 0


def normalize_category_code(value: str | None) -> str | None:
    return KnowledgeSpaceAutoTagService._normalize_category_code(value)


def resolve_file_category_code(db_file: KnowledgeFile) -> str | None:
    return KnowledgeSpaceAutoTagService._resolve_file_category_code(db_file)


def should_remove_tag_for_file(
    file_category_code: str | None,
    *,
    target_category_code: str = DEFAULT_CATEGORY_CODE,
) -> bool:
    normalized_target = normalize_category_code(target_category_code)
    normalized_file = normalize_category_code(file_category_code)
    if not normalized_target:
        return normalized_file is not None
    return normalized_file != normalized_target


def _parse_file_id(resource_id: str) -> int | None:
    raw = (resource_id or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


async def _load_tag_ids(session, *, tag_name: str, include_review_tags: bool) -> tuple[list[int], list[int]]:
    tag_rows = (await session.exec(select(Tag.id).where(Tag.name == tag_name, Tag.id.is_not(None)))).all()
    tag_ids = [int(row) for row in tag_rows if row is not None]

    review_tag_ids: list[int] = []
    if include_review_tags:
        review_rows = (
            await session.exec(
                select(ReviewTag.id).where(
                    ReviewTag.name == tag_name,
                    ReviewTag.id.is_not(None),
                    ReviewTag.is_deleted == False,  # noqa: E712
                )
            )
        ).all()
        review_tag_ids = [int(row) for row in review_rows if row is not None]
    return tag_ids, review_tag_ids


async def _load_files_by_ids(session, file_ids: Sequence[int]) -> dict[int, KnowledgeFile]:
    if not file_ids:
        return {}
    rows = (await session.exec(select(KnowledgeFile).where(KnowledgeFile.id.in_(list(file_ids))))).all()
    return {int(row.id): row for row in rows if row.id is not None}


def _build_candidate(
    *,
    link_id: int,
    file_id: int,
    db_file: KnowledgeFile | None,
    target_category_code: str,
) -> tuple[LinkCandidate | None, str]:
    if db_file is None:
        return None, "orphan"

    category_code = resolve_file_category_code(db_file)
    candidate = LinkCandidate(
        link_id=link_id,
        file_id=file_id,
        file_name=getattr(db_file, "file_name", None),
        category_code=category_code,
        knowledge_id=getattr(db_file, "knowledge_id", None),
        tenant_id=getattr(db_file, "tenant_id", None),
    )
    if should_remove_tag_for_file(category_code, target_category_code=target_category_code):
        return candidate, "remove"
    return candidate, "keep"


def _matches_scope(
    candidate: LinkCandidate,
    *,
    tenant_id: int | None,
    space_id: int | None,
    file_id: int | None,
) -> bool:
    if file_id is not None and candidate.file_id != file_id:
        return False
    if space_id is not None and candidate.knowledge_id != space_id:
        return False
    if tenant_id is not None and candidate.tenant_id != tenant_id:
        return False
    return True


async def _scan_tag_links(
    session,
    *,
    tag_ids: list[int],
    target_category_code: str,
    tenant_id: int | None,
    space_id: int | None,
    file_id: int | None,
    batch_size: int,
    limit: int | None,
) -> tuple[list[LinkCandidate], list[LinkCandidate], int, int]:
    if not tag_ids:
        return [], [], 0, 0

    to_remove: list[LinkCandidate] = []
    kept_samples: list[LinkCandidate] = []
    scanned = 0
    orphan_links = 0
    offset = 0

    while True:
        if limit is not None and scanned >= limit:
            break

        page_size = batch_size
        if limit is not None:
            page_size = min(page_size, limit - scanned)

        statement = (
            select(TagLink.id, TagLink.resource_id)
            .where(
                TagLink.tag_id.in_(tag_ids),
                TagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
            )
            .order_by(TagLink.id)
            .offset(offset)
            .limit(page_size)
        )
        rows = list((await session.exec(statement)).all())
        if not rows:
            break

        file_ids = [_parse_file_id(resource_id) for _, resource_id in rows]
        valid_file_ids = [file_id for file_id in file_ids if file_id is not None]
        files_by_id = await _load_files_by_ids(session, valid_file_ids)

        for link_id, resource_id in rows:
            scanned += 1
            parsed_file_id = _parse_file_id(resource_id)
            if parsed_file_id is None:
                orphan_links += 1
                continue

            candidate, action = _build_candidate(
                link_id=int(link_id),
                file_id=parsed_file_id,
                db_file=files_by_id.get(parsed_file_id),
                target_category_code=target_category_code,
            )
            if candidate is None:
                orphan_links += 1
                continue
            if not _matches_scope(candidate, tenant_id=tenant_id, space_id=space_id, file_id=file_id):
                continue
            if action == "remove":
                to_remove.append(candidate)
            elif len(kept_samples) < 20:
                kept_samples.append(candidate)

        offset += len(rows)
        if len(rows) < page_size:
            break

    return to_remove, kept_samples, scanned, orphan_links


async def _scan_review_tag_links(
    session,
    *,
    review_tag_ids: list[int],
    target_category_code: str,
    tenant_id: int | None,
    space_id: int | None,
    file_id: int | None,
    batch_size: int,
    limit: int | None,
) -> tuple[list[LinkCandidate], list[LinkCandidate], int, int]:
    if not review_tag_ids:
        return [], [], 0, 0

    to_remove: list[LinkCandidate] = []
    kept_samples: list[LinkCandidate] = []
    scanned = 0
    orphan_links = 0
    offset = 0

    while True:
        if limit is not None and scanned >= limit:
            break

        page_size = batch_size
        if limit is not None:
            page_size = min(page_size, limit - scanned)

        statement = (
            select(ReviewTagLink.id, ReviewTagLink.resource_id)
            .where(
                ReviewTagLink.tag_id.in_(review_tag_ids),
                ReviewTagLink.resource_type == ResourceTypeEnum.SPACE_FILE.value,
                ReviewTagLink.is_deleted == False,  # noqa: E712
            )
            .order_by(ReviewTagLink.id)
            .offset(offset)
            .limit(page_size)
        )
        rows = list((await session.exec(statement)).all())
        if not rows:
            break

        file_ids = [_parse_file_id(resource_id) for _, resource_id in rows]
        valid_file_ids = [file_id for file_id in file_ids if file_id is not None]
        files_by_id = await _load_files_by_ids(session, valid_file_ids)

        for link_id, resource_id in rows:
            scanned += 1
            parsed_file_id = _parse_file_id(resource_id)
            if parsed_file_id is None:
                orphan_links += 1
                continue

            candidate, action = _build_candidate(
                link_id=int(link_id),
                file_id=parsed_file_id,
                db_file=files_by_id.get(parsed_file_id),
                target_category_code=target_category_code,
            )
            if candidate is None:
                orphan_links += 1
                continue
            if not _matches_scope(candidate, tenant_id=tenant_id, space_id=space_id, file_id=file_id):
                continue
            if action == "remove":
                to_remove.append(candidate)
            elif len(kept_samples) < 20:
                kept_samples.append(candidate)

        offset += len(rows)
        if len(rows) < page_size:
            break

    return to_remove, kept_samples, scanned, orphan_links


async def scan_mismatched_links(
    *,
    tag_name: str,
    target_category_code: str,
    include_review_tags: bool,
    tenant_id: int | None,
    space_id: int | None,
    file_id: int | None,
    batch_size: int,
    limit: int | None,
) -> ScanReport:
    report = ScanReport()
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            report.tag_ids, report.review_tag_ids = await _load_tag_ids(
                session,
                tag_name=tag_name,
                include_review_tags=include_review_tags,
            )

            to_remove, kept, scanned, orphan_links = await _scan_tag_links(
                session,
                tag_ids=report.tag_ids,
                target_category_code=target_category_code,
                tenant_id=tenant_id,
                space_id=space_id,
                file_id=file_id,
                batch_size=batch_size,
                limit=limit,
            )
            report.to_remove = to_remove
            report.scanned_tag_links = scanned
            report.orphan_links = orphan_links
            report.kept_on_target_category = len(kept)

            if include_review_tags:
                review_to_remove, _, review_scanned, review_orphans = await _scan_review_tag_links(
                    session,
                    review_tag_ids=report.review_tag_ids,
                    target_category_code=target_category_code,
                    tenant_id=tenant_id,
                    space_id=space_id,
                    file_id=file_id,
                    batch_size=batch_size,
                    limit=limit,
                )
                report.review_to_remove = review_to_remove
                report.scanned_review_tag_links = review_scanned
                report.orphan_review_links = review_orphans

    return report


async def apply_removals(
    *,
    to_remove: Sequence[LinkCandidate],
    review_to_remove: Sequence[LinkCandidate],
) -> ApplyReport:
    report = ApplyReport()
    tag_link_ids = [item.link_id for item in to_remove]
    review_link_ids = [item.link_id for item in review_to_remove]

    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            if tag_link_ids:
                result = await session.exec(delete(TagLink).where(TagLink.id.in_(tag_link_ids)))
                report.tag_links_deleted = result.rowcount if hasattr(result, "rowcount") else len(tag_link_ids)
            if review_link_ids:
                result = await session.exec(delete(ReviewTagLink).where(ReviewTagLink.id.in_(review_link_ids)))
                report.review_tag_links_deleted = (
                    result.rowcount if hasattr(result, "rowcount") else len(review_link_ids)
                )
            await session.commit()
    return report


def _print_scan_report(report: ScanReport, *, tag_name: str, target_category_code: str, apply: bool) -> None:
    print("=" * 72)
    print("清除非「行业情报」分类文件上的「行业情报」标签")
    print("=" * 72)
    print(f"  标签名称           : {tag_name}")
    print(f"  保留分类 code      : {target_category_code}")
    print(f"  执行模式           : {'【实际删除】' if apply else '【dry-run，仅统计】'}")
    print(f"  命中 tag.id        : {report.tag_ids}")
    if report.review_tag_ids:
        print(f"  命中 review_tag.id : {report.review_tag_ids}")
    print()
    print(f"  扫描 tag_link      : {report.scanned_tag_links}")
    print(f"  保留(分类={target_category_code}) : {report.kept_on_target_category}+")
    print(f"  待删除 tag_link    : {len(report.to_remove)}")
    print(f"  无效/缺失文件 link : {report.orphan_links}")
    if report.review_tag_ids or report.scanned_review_tag_links:
        print(f"  扫描 review_tag_link : {report.scanned_review_tag_links}")
        print(f"  待删除 review_tag_link : {len(report.review_to_remove)}")
        print(f"  无效/缺失 review link : {report.orphan_review_links}")
    print()

    if report.to_remove:
        print("待删除示例 (最多 20 条):")
        for item in report.to_remove[:20]:
            print(
                f"  file_id={item.file_id} space_id={item.knowledge_id} "
                f"category={item.category_code or '-'} name={item.file_name or '-'}"
            )
        if len(report.to_remove) > 20:
            print(f"  ... 另有 {len(report.to_remove) - 20} 条")
        print()

    total_remove = len(report.to_remove) + len(report.review_to_remove)
    if total_remove == 0:
        print("没有需要清理的关联记录。")
        return

    if not apply:
        print("[dry-run] 以上 tag_link / review_tag_link 将被删除。追加 --apply 执行。")


async def run(args: argparse.Namespace) -> int:
    try:
        report = await scan_mismatched_links(
            tag_name=args.tag_name,
            target_category_code=args.category_code,
            include_review_tags=args.include_review_tags,
            tenant_id=args.tenant_id,
            space_id=args.space_id,
            file_id=args.file_id,
            batch_size=args.batch_size,
            limit=args.limit,
        )
        _print_scan_report(
            report,
            tag_name=args.tag_name,
            target_category_code=args.category_code,
            apply=args.apply,
        )

        total_remove = len(report.to_remove) + len(report.review_to_remove)
        if total_remove == 0 or not args.apply:
            return 0

        answer = input("确认删除以上关联记录？输入 y 继续，其他键退出: ").strip().lower()
        if answer != "y":
            print("已取消。")
            return 0

        deleted = await apply_removals(
            to_remove=report.to_remove,
            review_to_remove=report.review_to_remove,
        )
        print()
        print(f"  已删除 tag_link        : {deleted.tag_links_deleted}")
        print(f"  已删除 review_tag_link : {deleted.review_tag_links_deleted}")
        print("清理完成。")
        return 0
    finally:
        await close_app_context()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="实际执行删除（默认 dry-run）")
    mode.add_argument("--dry-run", action="store_true", help="只统计不删除（默认行为）")
    parser.add_argument("--tag-name", default=DEFAULT_TAG_NAME, help=f"要清理的标签名，默认 {DEFAULT_TAG_NAME}")
    parser.add_argument(
        "--category-code",
        default=DEFAULT_CATEGORY_CODE,
        help=f"保留标签的文件分类 code，默认 {DEFAULT_CATEGORY_CODE}",
    )
    parser.add_argument(
        "--include-review-tags",
        action="store_true",
        help="同时清理 review_tag_link 中的待审核关联",
    )
    parser.add_argument("--tenant-id", type=int, default=None, help="仅处理指定租户")
    parser.add_argument("--space-id", type=int, default=None, help="仅处理指定知识空间 knowledge_id")
    parser.add_argument("--file-id", type=int, default=None, help="仅处理指定文件")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="扫描分页大小")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描多少条 link（调试用）")
    return parser.parse_args(argv)


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    sys.exit(main())
