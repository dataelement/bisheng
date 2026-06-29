#!/usr/bin/env python3
"""首钢知识空间标签清理脚本

清空「标签管理」模块中的标签数据，同步清理对应的关联表。
默认只删除 business_type=knowledge_space 的标签，可通过参数扩展。

使用方法（在容器内 src/backend 目录执行）：

    # 仅统计，不删除（默认 dry-run）
    python scripts/shougang_clean_tags.py

    # 确认删除所有知识空间标签（含关联）
    python scripts/shougang_clean_tags.py --apply

    # 同时清理待审核标签（review_tag / review_tag_link）
    python scripts/shougang_clean_tags.py --apply --include-review-tags

    # 清理所有 business_type 的标签（knowledge_space + application + knowledge）
    python scripts/shougang_clean_tags.py --apply --all-types

注意：
  - 脚本会先输出将要删除的数量，输入 y 确认后再执行。
  - --apply 与 --dry-run 互斥，默认为 dry-run。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlmodel import delete, func, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.tag import Tag, TagLink
from bisheng.database.models.review_tags import ReviewTag, ReviewTagLink


async def count_tags(business_types: list[str]) -> dict:
    """Return row counts before deletion."""
    async with get_async_db_session() as session:
        tag_count = await session.scalar(
            select(func.count(Tag.id)).where(Tag.business_type.in_(business_types))
        )
        tag_link_count = await session.scalar(
            select(func.count(TagLink.id)).join(
                Tag, Tag.id == TagLink.tag_id
            ).where(Tag.business_type.in_(business_types))
        )
    return {"tag": tag_count or 0, "tag_link": tag_link_count or 0}


async def count_review_tags() -> dict:
    async with get_async_db_session() as session:
        rt_count = await session.scalar(select(func.count(ReviewTag.id)))
        rtl_count = await session.scalar(select(func.count(ReviewTagLink.id)))
    return {"review_tag": rt_count or 0, "review_tag_link": rtl_count or 0}


async def delete_tags(business_types: list[str]) -> dict:
    """Delete tags and their links for the given business_types. Returns deleted counts."""
    async with get_async_db_session() as session:
        # Collect tag ids to delete first (needed for tag_link cascade)
        tag_ids_rows = await session.exec(
            select(Tag.id).where(Tag.business_type.in_(business_types))
        )
        tag_ids = [row for row in tag_ids_rows]

        link_result = await session.exec(
            delete(TagLink).where(TagLink.tag_id.in_(tag_ids))
        )
        tag_result = await session.exec(
            delete(Tag).where(Tag.id.in_(tag_ids))
        )
        await session.commit()

    return {
        "tag": tag_result.rowcount if hasattr(tag_result, 'rowcount') else len(tag_ids),
        "tag_link": link_result.rowcount if hasattr(link_result, 'rowcount') else 0,
    }


async def delete_review_tags() -> dict:
    """Delete all review tags and their links."""
    async with get_async_db_session() as session:
        rt_ids_rows = await session.exec(select(ReviewTag.id))
        rt_ids = [row for row in rt_ids_rows]

        rtl_result = await session.exec(
            delete(ReviewTagLink).where(ReviewTagLink.tag_id.in_(rt_ids))
        )
        rt_result = await session.exec(
            delete(ReviewTag).where(ReviewTag.id.in_(rt_ids))
        )
        await session.commit()

    return {
        "review_tag": rt_result.rowcount if hasattr(rt_result, 'rowcount') else len(rt_ids),
        "review_tag_link": rtl_result.rowcount if hasattr(rtl_result, 'rowcount') else 0,
    }


async def run(args: argparse.Namespace) -> int:
    business_types = (
        ["knowledge_space", "application", "knowledge"]
        if args.all_types
        else ["knowledge_space"]
    )

    print("=" * 60)
    print("首钢知识空间标签清理脚本")
    print("=" * 60)
    print(f"  目标 business_type : {business_types}")
    print(f"  清理待审核标签     : {'是' if args.include_review_tags else '否'}")
    print(f"  执行模式           : {'【实际删除】' if args.apply else '【dry-run，仅统计】'}")
    print()

    # Count
    counts = await count_tags(business_types)
    print(f"  tag         表: {counts['tag']:>8} 条")
    print(f"  tag_link    表: {counts['tag_link']:>8} 条")

    rv_counts = {}
    if args.include_review_tags:
        rv_counts = await count_review_tags()
        print(f"  review_tag      表: {rv_counts['review_tag']:>8} 条")
        print(f"  review_tag_link 表: {rv_counts['review_tag_link']:>8} 条")
    print()

    total = counts["tag"] + counts["tag_link"] + rv_counts.get("review_tag", 0) + rv_counts.get("review_tag_link", 0)
    if total == 0:
        print("没有需要清理的数据，退出。")
        return 0

    if not args.apply:
        print("[dry-run] 以上数据将被删除。追加 --apply 参数执行实际删除。")
        return 0

    # Confirm
    answer = input("确认删除以上数据？输入 y 继续，其他键退出: ").strip().lower()
    if answer != "y":
        print("已取消。")
        return 0

    print()
    print("开始删除...")

    deleted = await delete_tags(business_types)
    print(f"  已删除 tag       : {deleted['tag']} 条")
    print(f"  已删除 tag_link  : {deleted['tag_link']} 条")

    if args.include_review_tags:
        rv_deleted = await delete_review_tags()
        print(f"  已删除 review_tag      : {rv_deleted['review_tag']} 条")
        print(f"  已删除 review_tag_link : {rv_deleted['review_tag_link']} 条")

    print()
    print("清理完成。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="实际执行删除（默认为 dry-run，只统计不删除）",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="只统计不删除（默认行为，与不加参数等价）",
    )
    parser.add_argument(
        "--all-types",
        action="store_true",
        default=False,
        help="清理所有 business_type（knowledge_space + application + knowledge），默认只清理 knowledge_space",
    )
    parser.add_argument(
        "--include-review-tags",
        action="store_true",
        default=False,
        help="同时清理待审核标签（review_tag / review_tag_link 表）",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
