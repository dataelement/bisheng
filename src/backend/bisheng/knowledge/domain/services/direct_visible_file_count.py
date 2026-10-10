"""按文件列表同一套可见性, 统计当前目录这一层的文件数."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from bisheng.knowledge.domain.models.knowledge_space_file import build_child_order_cursor_key

# 和子目录列表的权限扫描批次一致. 目录经常超过几百个文件时, 应改成预先算好的可见数量.
_BATCH_SIZE = 100
_ORDER_FIELD = "update_time"


async def count_visible_direct_files(
    *,
    list_batch: Callable[[list | None], Awaitable[list[Any]]],
    filter_visible: Callable[[list[Any]], Awaitable[list[Any]]],
    batch_size: int = _BATCH_SIZE,
) -> int:
    """只数当前目录这一层、且当前用户可见的文件.

    list_batch 按游标返回下一批直接子文件. filter_visible 与文件列表使用同一套权限和状态过滤.
    """
    total = 0
    cursor: list | None = None
    while True:
        batch = await list_batch(cursor)
        if not batch:
            break
        visible = await filter_visible(batch)
        total += len(visible)
        if len(batch) < batch_size:
            break
        cursor = build_child_order_cursor_key(batch[-1], _ORDER_FIELD)
    return total
