#!/usr/bin/env python3
"""Migrate legacy knowledge_space tags into bound tag libraries.

For each Tag / ReviewTag with business_type=knowledge_space, move it to the first
tag library bound to that knowledge space. TagLink / ReviewTagLink rows are remapped;
duplicate links are dropped.

Usage (from src/backend):

    # Dry-run (default): print counts only
    python scripts/migrate_knowledge_space_tags_to_library.py

    # Apply migration after review
    python scripts/migrate_knowledge_space_tags_to_library.py --apply

    # Also migrate pending review tags
    python scripts/migrate_knowledge_space_tags_to_library.py --apply --include-review-tags
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger
from sqlmodel import select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.models.knowledge_tag_library_link import KnowledgeTagLibraryLinkDao


class MigrationStats:
    def __init__(self) -> None:
        self.tags_total = 0
        self.tags_migrated = 0
        self.tags_merged = 0
        self.tags_skipped_no_library = 0
        self.tag_links_updated = 0
        self.tag_links_dropped = 0
        self.review_tags_total = 0
        self.review_tags_migrated = 0
        self.review_tags_merged = 0
        self.review_tags_skipped_no_library = 0
        self.review_tag_links_updated = 0
        self.review_tag_links_dropped = 0


async def _find_library_tag(
    session,
    *,
    tenant_id: int | None,
    library_id: int,
    tag_name: str,
) -> Tag | None:
    return (
        await session.exec(
            select(Tag)
            .where(
                Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                Tag.business_id == str(library_id),
                Tag.tenant_id == tenant_id,
                Tag.name == tag_name,
            )
            .limit(1)
        )
    ).first()


async def _find_library_review_tag(
    session,
    *,
    tenant_id: int | None,
    library_id: int,
    tag_name: str,
) -> ReviewTag | None:
    return (
        await session.exec(
            select(ReviewTag)
            .where(
                ReviewTag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value,
                ReviewTag.business_id == str(library_id),
                ReviewTag.tenant_id == tenant_id,
                ReviewTag.name == tag_name,
                ReviewTag.is_deleted == False,  # noqa: E712
            )
            .limit(1)
        )
    ).first()


async def _remap_tag_links(session, *, old_tag_id: int, new_tag_id: int, stats: MigrationStats, apply: bool) -> None:
    links = (await session.exec(select(TagLink).where(TagLink.tag_id == old_tag_id))).all()
    existing_targets = {
        (link.resource_id, link.resource_type)
        for link in (await session.exec(select(TagLink).where(TagLink.tag_id == new_tag_id))).all()
    }
    for link in links:
        key = (link.resource_id, link.resource_type)
        if key in existing_targets:
            stats.tag_links_dropped += 1
            if apply:
                await session.delete(link)
            continue
        stats.tag_links_updated += 1
        if apply:
            link.tag_id = new_tag_id
            session.add(link)
            existing_targets.add(key)


async def _remap_review_tag_links(
    session, *, old_tag_id: int, new_tag_id: int, stats: MigrationStats, apply: bool
) -> None:
    links = (await session.exec(select(ReviewTagLink).where(ReviewTagLink.tag_id == old_tag_id))).all()
    existing_targets = {
        (link.resource_id, link.resource_type)
        for link in (await session.exec(select(ReviewTagLink).where(ReviewTagLink.tag_id == new_tag_id))).all()
    }
    for link in links:
        key = (link.resource_id, link.resource_type)
        if key in existing_targets:
            stats.review_tag_links_dropped += 1
            if apply:
                await session.delete(link)
            continue
        stats.review_tag_links_updated += 1
        if apply:
            link.tag_id = new_tag_id
            session.add(link)
            existing_targets.add(key)


async def migrate_tags(*, apply: bool, stats: MigrationStats) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            legacy_tags = (
                await session.exec(select(Tag).where(Tag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE.value))
            ).all()
            stats.tags_total = len(legacy_tags)

            for legacy_tag in legacy_tags:
                space_id_raw = legacy_tag.business_id or ""
                if not str(space_id_raw).isdigit():
                    stats.tags_skipped_no_library += 1
                    continue
                space_id = int(space_id_raw)
                library_ids = KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(space_id)
                if not library_ids:
                    stats.tags_skipped_no_library += 1
                    continue

                library_id = library_ids[0]
                tag_name = (legacy_tag.name or "").strip()
                if not tag_name or legacy_tag.id is None:
                    stats.tags_skipped_no_library += 1
                    continue

                target = await _find_library_tag(
                    session,
                    tenant_id=legacy_tag.tenant_id,
                    library_id=library_id,
                    tag_name=tag_name,
                )
                if target and target.id is not None:
                    stats.tags_merged += 1
                    target_id = int(target.id)
                elif apply:
                    stats.tags_migrated += 1
                    target = Tag(
                        name=tag_name,
                        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                        business_id=str(library_id),
                        user_id=legacy_tag.user_id,
                        tenant_id=legacy_tag.tenant_id,
                        resource_type=legacy_tag.resource_type,
                    )
                    session.add(target)
                    await session.flush()
                    target_id = int(target.id)
                else:
                    stats.tags_migrated += 1
                    link_count = len((await session.exec(select(TagLink).where(TagLink.tag_id == legacy_tag.id))).all())
                    stats.tag_links_updated += link_count
                    continue

                await _remap_tag_links(
                    session,
                    old_tag_id=int(legacy_tag.id),
                    new_tag_id=target_id,
                    stats=stats,
                    apply=apply,
                )
                if apply:
                    await session.delete(legacy_tag)

            if apply:
                await session.commit()


async def migrate_review_tags(*, apply: bool, stats: MigrationStats) -> None:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            legacy_tags = (
                await session.exec(
                    select(ReviewTag).where(
                        ReviewTag.business_type == TagBusinessTypeEnum.KNOWLEDGE_SPACE.value,
                        ReviewTag.is_deleted == False,  # noqa: E712
                    )
                )
            ).all()
            stats.review_tags_total = len(legacy_tags)

            for legacy_tag in legacy_tags:
                space_id_raw = legacy_tag.business_id or ""
                if not str(space_id_raw).isdigit():
                    stats.review_tags_skipped_no_library += 1
                    continue
                space_id = int(space_id_raw)
                library_ids = KnowledgeTagLibraryLinkDao.list_library_ids_by_knowledge(space_id)
                if not library_ids:
                    stats.review_tags_skipped_no_library += 1
                    continue

                library_id = library_ids[0]
                tag_name = (legacy_tag.name or "").strip()
                if not tag_name or legacy_tag.id is None:
                    stats.review_tags_skipped_no_library += 1
                    continue

                target = await _find_library_review_tag(
                    session,
                    tenant_id=legacy_tag.tenant_id,
                    library_id=library_id,
                    tag_name=tag_name,
                )
                if target and target.id is not None:
                    stats.review_tags_merged += 1
                    target_id = int(target.id)
                elif apply:
                    stats.review_tags_migrated += 1
                    target = ReviewTag(
                        name=tag_name,
                        business_type=TagBusinessTypeEnum.TAG_LIBRARY.value,
                        business_id=str(library_id),
                        user_id=legacy_tag.user_id,
                        tenant_id=legacy_tag.tenant_id,
                        resource_type=legacy_tag.resource_type,
                        review_status=legacy_tag.review_status,
                        reject_reason=legacy_tag.reject_reason,
                        review_time=legacy_tag.review_time,
                        remark=legacy_tag.remark,
                    )
                    session.add(target)
                    await session.flush()
                    target_id = int(target.id)
                else:
                    stats.review_tags_migrated += 1
                    link_count = len(
                        (await session.exec(select(ReviewTagLink).where(ReviewTagLink.tag_id == legacy_tag.id))).all()
                    )
                    stats.review_tag_links_updated += link_count
                    continue

                await _remap_review_tag_links(
                    session,
                    old_tag_id=int(legacy_tag.id),
                    new_tag_id=target_id,
                    stats=stats,
                    apply=apply,
                )
                if apply:
                    legacy_tag.is_deleted = True
                    session.add(legacy_tag)

            if apply:
                await session.commit()


def _print_stats(stats: MigrationStats, *, include_review: bool) -> None:
    print(f"  legacy tag rows              : {stats.tags_total:>8}")
    print(f"    -> new library tags         : {stats.tags_migrated:>8}")
    print(f"    -> merged to existing       : {stats.tags_merged:>8}")
    print(f"    -> skipped (no library)    : {stats.tags_skipped_no_library:>8}")
    print(f"  tag_link remapped            : {stats.tag_links_updated:>8}")
    print(f"  tag_link dropped (duplicate) : {stats.tag_links_dropped:>8}")
    if include_review:
        print(f"  legacy review_tag rows       : {stats.review_tags_total:>8}")
        print(f"    -> new library review tags : {stats.review_tags_migrated:>8}")
        print(f"    -> merged to existing       : {stats.review_tags_merged:>8}")
        print(f"    -> skipped (no library)    : {stats.review_tags_skipped_no_library:>8}")
        print(f"  review_tag_link remapped     : {stats.review_tag_links_updated:>8}")
        print(f"  review_tag_link dropped      : {stats.review_tag_links_dropped:>8}")


async def run(args: argparse.Namespace) -> int:
    stats = MigrationStats()
    print("=" * 60)
    print("knowledge_space -> tag_library migration")
    print("=" * 60)
    print(f"  include review tags : {'yes' if args.include_review_tags else 'no'}")
    print(f"  mode                : {'APPLY' if args.apply else 'DRY-RUN'}")
    print()

    await migrate_tags(apply=False, stats=stats)
    if args.include_review_tags:
        await migrate_review_tags(apply=False, stats=stats)

    _print_stats(stats, include_review=args.include_review_tags)
    print()

    actionable = stats.tags_total + (stats.review_tags_total if args.include_review_tags else 0)
    if actionable == 0:
        print("Nothing to migrate.")
        return 0

    if not args.apply:
        print("[dry-run] Re-run with --apply to execute.")
        return 0

    answer = input("Confirm migration? Type y to continue: ").strip().lower()
    if answer != "y":
        print("Cancelled.")
        return 0

    apply_stats = MigrationStats()
    await migrate_tags(apply=True, stats=apply_stats)
    if args.include_review_tags:
        await migrate_review_tags(apply=True, stats=apply_stats)

    print()
    _print_stats(apply_stats, include_review=args.include_review_tags)
    logger.info("Migration completed.")
    print("Migration completed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", default=False, help="Execute migration")
    mode.add_argument("--dry-run", action="store_true", default=False, help="Count only (default)")
    parser.add_argument(
        "--include-review-tags",
        action="store_true",
        default=False,
        help="Also migrate review_tag rows scoped to knowledge_space",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
