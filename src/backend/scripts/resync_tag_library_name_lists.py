#!/usr/bin/env python3
"""一次性脚本：把标签库自己那份"名字清单"对齐到 ``tag`` 表。

## 背景

一个标签库的标签名存了两份：``tag`` 表里一行一个（正式数据），标签库记录
自己身上还挂着一份名字清单（``tags`` / ``ai_tags`` / ``tag_count``，历史遗留）。

标签管理页面早期版本的删除/添加/移动只改了 ``tag`` 表，没同步那份清单，于是
两份数据会漂移。漂移有两个后果：

- 左侧标签库的**标签数显示不对**（没有标签行时，计数会回退去读那份清单）。
- 更严重：某个库被**删空**后清单还在，系统的"自愈"逻辑会把它误判成
  "当年迁移漏了这个库"，在有人打开该库详情时**照着清单把标签重建出来** ——
  也就是"删掉的标签又回来了"。

代码侧已修复（写操作会同步清单），本脚本负责清理修复之前留下的漂移。

## 两类漂移，处理方式不同

| 情况 | 处理 |
|------|------|
| **有标签行、但清单对不上** | 自动对齐。标签行是权威数据，照它重写清单没有歧义。 |
| **0 行标签、但清单非空** | **默认跳过**，必须用 ``--library <id>`` 显式点名。 |

第二种必须人工确认，因为它有两种完全相反的来源，从数据上**无法区分**：

- 这个库被人为删空了 → 清单该清掉（否则标签会复活）
- 这个库当年就没迁移过，标签**只存在于清单里** → 清掉等于删光该库所有标签

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印现状，不写库）
    python scripts/resync_tag_library_name_lists.py

    # 真正对齐"有标签行"的那些库
    python scripts/resync_tag_library_name_lists.py --apply

    # 额外处理被删空的库（确认过这些库是人为删空的）
    python scripts/resync_tag_library_name_lists.py --apply --library 2 --library 7

## 安全保证

- Dry-run 是默认行为，必须显式 ``--apply`` 才会写库。
- "0 行 + 清单非空"的库默认只报告不处理，除非被 ``--library`` 点名。
- 只改标签库自己的 ``tags`` / ``ai_tags`` / ``tag_count`` 三个字段，
  **不会新增或删除任何 ``tag`` 行**。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_database_connection, get_sync_db_session  # noqa: E402
from bisheng.knowledge.domain.services.tag_library_tag_service import TagLibraryTagService  # noqa: E402

SCAN_SQL = sa_text("""
    SELECT id, tenant_id, name, tag_count, tags, ai_tags
    FROM knowledge_space_tag_library
    ORDER BY id
""")

# Counted separately and joined in Python on purpose: matching `tag.business_id`
# against the library id inside SQL needs a cast, and casting the id to a string
# trips an "illegal mix of collations" error on MySQL.
COUNT_SQL = sa_text("""
    SELECT business_id, COUNT(*) FROM tag WHERE business_type = 'tag_library' GROUP BY business_id
""")


def _listed_names(*columns) -> int:
    """How many names the library's own list still claims.

    The columns are JSON; depending on the driver they arrive already decoded or
    still as text, so both are handled.
    """
    total = 0
    for column in columns:
        value = column
        if isinstance(value, (str, bytes)):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                continue
        if isinstance(value, list):
            total += len(value)
    return total


async def _resync(library_ids: list[int]) -> None:
    try:
        for library_id in library_ids:
            await TagLibraryTagService.sync_library_name_lists(library_id)
    finally:
        # Close the pool while the loop is still running. Left to interpreter
        # shutdown, the connections are finalised after `asyncio.run` has closed
        # the loop and print a "Event loop is closed" traceback — the work is
        # already committed by then, but a successful run looks like a failure.
        try:
            connection = await get_database_connection()
            await connection.close()
        except Exception:
            logger.debug("database pool teardown failed", exc_info=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="对齐标签库的名字清单与 tag 表")
    parser.add_argument("--apply", action="store_true", help="真正写库，默认只做 dry-run")
    parser.add_argument(
        "--library",
        type=int,
        action="append",
        default=[],
        dest="libraries",
        help="额外处理这个被删空的标签库（可重复）",
    )
    args = parser.parse_args()
    opted_in = set(args.libraries)

    with bypass_tenant_filter(), get_sync_db_session() as session:
        rows = list(session.execute(SCAN_SQL))
        counts = {str(business_id): count for business_id, count in session.execute(COUNT_SQL)}

    safe: list[tuple[int, str, int, int]] = []
    emptied: list[tuple[int, str, int]] = []
    for library_id, _tenant_id, name, tag_count, tags, ai_tags in rows:
        row_count = counts.get(str(library_id), 0)
        names = _listed_names(tags, ai_tags)
        if row_count == 0 and names > 0:
            emptied.append((library_id, name, names))
            continue
        if names != row_count or (tag_count or 0) != row_count:
            safe.append((library_id, name, row_count, names))

    print(f"标签库总数:                {len(rows)}")
    print(f"  - 清单与标签行不一致:     {len(safe)}  (可自动对齐)")
    print(f"  - 0 行但清单非空:         {len(emptied)}  (需 --library 点名)")
    print()

    if safe:
        print("可自动对齐:")
        for library_id, name, row_count, names in safe:
            print(f"  id={library_id:<4} 「{name}」 标签行={row_count} 清单={names} -> 清单改为 {row_count}")
        print()

    if emptied:
        print("被删空的库（默认不处理）:")
        for library_id, name, names in emptied:
            flag = "将处理" if library_id in opted_in else f"跳过，加 --library {library_id} 才处理"
            print(f"  id={library_id:<4} 「{name}」 标签行=0 清单={names}  [{flag}]")
        print()
        print("  提示：确认这些库确实是被人为删空的再点名。若某个库当年就没迁移过，")
        print("        标签只存在于清单里，清空清单等于删光该库所有标签。")
        print()

    targets = [library_id for library_id, _name, _rc, _n in safe]
    targets += [library_id for library_id, _name, _n in emptied if library_id in opted_in]

    unknown = opted_in - {library_id for library_id, *_ in rows}
    if unknown:
        print(f"警告：--library 指定了不存在的标签库 {sorted(unknown)}，已忽略。")
        print()

    if not args.apply:
        print("Dry-run，未写库。确认无误后加 --apply 执行。")
        return 0

    if not targets:
        print("没有需要对齐的标签库。")
        return 0

    asyncio.run(_resync(targets))
    print(f"已对齐 {len(targets)} 个标签库的名字清单。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
