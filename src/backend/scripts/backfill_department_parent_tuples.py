#!/usr/bin/env python3
"""一次性脚本：把 DB 部门树的父子关系回填成 OpenFGA 的 ``department#parent`` 继承边。

## 背景

OpenFGA 模型里 ``department#admin`` 通过 ``parent`` 关系从父部门继承。但写这条
``department:{parent}#parent@department:{child}`` 边的只有 F002 手动建/移部门两处；
**SSO 同步进来的、以及早期 f006 RBAC→ReBAC 迁移进来的部门，FGA 里都没有这条边**，
导致部门 admin 的 FGA 继承对这些部门整体失效（运行期靠 DB ``parent_id`` 回退兜底）。

同步链路已修复（F014 SSO 各路径会实时维护 parent 边），但**存量**部门的边仍缺失，
由本脚本一次性按 DB 当前树形补齐。

## 做什么

遍历所有 ``status='active'`` 且 ``parent_id`` 非空的部门（全租户、全来源），对每个
发一条 ``write department:{parent_id}#parent department:{id}``，经
``PermissionService.batch_write_tuples`` 写入 OpenFGA。

**只加不删（additive）**：不删除任何已存在的边。``batch_write_tuples`` 对"重复写"
幂等（已存在视为成功），因此本脚本可安全反复运行。根部门（``parent_id`` 为空）无父边，
天然跳过。

## 运行顺序

应在 ``backfill_departments_under_single_root.py``（单根收编，定型 ``parent_id``）
**之后**运行——届时被收编部门的 ``parent_id`` 已指向默认组织根，本脚本会一并补上
``root→顶层`` 这条边。

## 用法（在 ``src/backend`` 目录下运行）

    # Dry-run（默认，只统计将写入多少条边，不调用 FGA）
    config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_department_parent_tuples.py

    # 真正写入
    config=config.yaml PYTHONPATH=./ .venv/bin/python scripts/backfill_department_parent_tuples.py --apply

## 安全

- Dry-run 是默认行为；``--apply`` 才写 FGA。
- 触达 OpenFGA，故 ``main`` 走 ``initialize_app_context`` / ``close_app_context``。
- 跨租户：运行在 ``bypass_tenant_filter()`` 下。
- 幂等、只加不删；不动 member/admin/owner 等其它关系。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from loguru import logger  # noqa: E402


async def _collect_parent_edges() -> list[tuple[int, int]]:
    """Return ``(child_id, parent_id)`` for every active department that has a
    parent — i.e. the full set of parent edges the DB tree implies.
    """
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department

    async with get_async_db_session() as session:
        rows = (
            await session.exec(
                select(Department.id, Department.parent_id).where(
                    Department.parent_id.is_not(None),
                    Department.status == "active",
                )
            )
        ).all()
    edges: list[tuple[int, int]] = []
    for row in rows:
        cid = row[0] if isinstance(row, tuple) else row.id
        pid = row[1] if isinstance(row, tuple) else row.parent_id
        if cid is None or pid is None:
            continue
        edges.append((int(cid), int(pid)))
    return edges


async def run(apply: bool) -> int:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.department.domain.services.department_change_handler import (
        DepartmentChangeHandler,
    )
    from bisheng.permission.domain.services.permission_service import (
        PermissionService,
    )

    with bypass_tenant_filter():
        edges = await _collect_parent_edges()
        if not edges:
            logger.info("没有需要回填的部门父边（无 active 且 parent_id 非空的部门）。")
            return 0

        # Reuse the tested op-builder: on_created(child, parent) yields exactly
        # one `write department:{parent}#parent department:{child}`.
        ops = []
        for child_id, parent_id in edges:
            ops.extend(DepartmentChangeHandler.on_created(child_id, parent_id))

        logger.info("待回填部门父边 {} 条（additive，幂等）。", len(ops))
        sample = edges[:8]
        logger.info(
            "样本(child->parent): {}",
            ", ".join(f"{c}->{p}" for c, p in sample),
        )

        if not apply:
            logger.info("[dry-run] 未写 FGA。确认后追加 --apply 执行。")
            return 0

        await PermissionService.batch_write_tuples(ops, crash_safe=False)
        logger.info("完成。已写入 {} 条 department#parent 边。", len(ops))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the backfill (default is dry-run).",
    )
    args = parser.parse_args()

    async def _amain() -> int:
        from bisheng.common.services.config_service import settings
        from bisheng.core.context.manager import (
            close_app_context,
            initialize_app_context,
        )

        await initialize_app_context(config=settings)
        try:
            return await run(apply=args.apply)
        finally:
            await close_app_context()

    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
