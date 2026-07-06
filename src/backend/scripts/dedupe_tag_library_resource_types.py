#!/usr/bin/env python3
"""Remove duplicate tag_library rows that share the same name across resource types.

After f050 migration some libraries contain both ``system_tag`` and ``manual_tag`` rows
for the same label. This script keeps the highest-priority row per name
(system_tag > ai_auto_tag > manual_tag), remaps ``tag_link`` references, and deletes
the redundant tag rows.

Usage (from ``src/backend/``):

    # Preview only (default)
    python scripts/dedupe_tag_library_resource_types.py

    # Apply changes
    python scripts/dedupe_tag_library_resource_types.py --apply

    # Limit to one library
    python scripts/dedupe_tag_library_resource_types.py --library-id 42 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import update
from sqlmodel import delete, select

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.database import get_async_db_session
from bisheng.database.models.tag import Tag, TagBusinessTypeEnum, TagLink
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dedupe tag_library rows by tag name.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="Persist changes (default: dry-run).")
    mode.add_argument("--dry-run", action="store_true", help="Preview only (default).")
    parser.add_argument(
        "--library-id",
        type=int,
        default=None,
        help="Only process one tag library (business_id).",
    )
    return parser.parse_args()


def _group_duplicate_tags(tags: list[Tag]) -> list[tuple[Tag, list[Tag]]]:
    """Return (keeper, duplicates) for each name group with more than one row."""
    groups: dict[tuple[int | None, str, str], list[Tag]] = defaultdict(list)
    for tag in tags:
        name = (tag.name or "").strip()
        if not name or tag.id is None:
            continue
        business_id = (tag.business_id or "").strip()
        groups[(tag.tenant_id, business_id, name.lower())].append(tag)

    plans: list[tuple[Tag, list[Tag]]] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        deduped = TagLibraryTagService.dedupe_library_tags_by_name(group)
        if len(deduped) >= len(group):
            continue
        keeper = deduped[0]
        losers = [tag for tag in group if tag.id != keeper.id]
        if losers:
            plans.append((keeper, losers))
    return plans


async def _load_tag_library_tags(library_id: int | None) -> list[Tag]:
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            statement = select(Tag).where(Tag.business_type == TagBusinessTypeEnum.TAG_LIBRARY.value)
            if library_id is not None:
                statement = statement.where(Tag.business_id == str(library_id))
            return list((await session.exec(statement)).all())


async def _apply_plan(plan: tuple[Tag, list[Tag]], *, dry_run: bool) -> dict[str, int]:
    keeper, losers = plan
    loser_ids = [int(tag.id) for tag in losers if tag.id is not None]
    if not loser_ids:
        return {"tags": 0, "links_remapped": 0, "links_deleted": 0}

    if dry_run:
        with bypass_tenant_filter():
            async with get_async_db_session() as session:
                links = list((await session.exec(select(TagLink).where(TagLink.tag_id.in_(loser_ids)))).all())
        return {"tags": len(loser_ids), "links_remapped": len(links), "links_deleted": 0}

    now = datetime.now()
    with bypass_tenant_filter():
        async with get_async_db_session() as session:
            links = list((await session.exec(select(TagLink).where(TagLink.tag_id.in_(loser_ids)))).all())
            remapped = 0
            for link in links:
                existing = (
                    await session.exec(
                        select(TagLink).where(
                            TagLink.tag_id == keeper.id,
                            TagLink.resource_type == link.resource_type,
                            TagLink.resource_id == link.resource_id,
                        )
                    )
                ).first()
                if existing is not None:
                    await session.delete(link)
                else:
                    await session.exec(
                        update(TagLink).where(TagLink.id == link.id).values(tag_id=keeper.id, update_time=now)
                    )
                    remapped += 1
            await session.exec(delete(Tag).where(Tag.id.in_(loser_ids)))
            await session.commit()
    return {"tags": len(loser_ids), "links_remapped": remapped, "links_deleted": len(links) - remapped}


async def run(args: argparse.Namespace) -> int:
    dry_run = not args.apply
    tags = await _load_tag_library_tags(args.library_id)
    plans = _group_duplicate_tags(tags)

    print("=" * 60)
    print("tag_library duplicate cleanup")
    print(f"mode: {'dry-run' if dry_run else 'apply'}")
    if args.library_id is not None:
        print(f"library_id: {args.library_id}")
    print(f"duplicate groups: {len(plans)}")
    print("=" * 60)

    totals = {"tags": 0, "links_remapped": 0, "links_deleted": 0}
    for keeper, losers in plans:
        loser_names = ", ".join(f"{tag.resource_type}(id={tag.id})" for tag in losers if tag.id is not None)
        print(
            f"library={keeper.business_id} name={keeper.name!r} "
            f"keep={keeper.resource_type}(id={keeper.id}) drop=[{loser_names}]"
        )
        stats = await _apply_plan((keeper, losers), dry_run=dry_run)
        for key, value in stats.items():
            totals[key] += value

    print("-" * 60)
    print(
        "summary: "
        f"tags_to_remove={totals['tags']} "
        f"links_remapped={totals['links_remapped']} "
        f"links_deleted={totals['links_deleted']}"
    )
    if dry_run and totals["tags"]:
        print("Re-run with --apply to persist changes.")
    return 0


def main() -> int:
    return asyncio.run(run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
