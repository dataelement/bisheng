#!/usr/bin/env python3
"""一次性脚本：把所有"误挂为根"的部门收编到默认组织根部门下，保证全平台只有一个根部门。

## 背景

历史上 SSO 网关同步的顶层部门（``parent_external_id`` 为空）被挂为
``parent_id=None``，于是它们变成了与"默认组织"(``BS@root``) 平级的兄弟根部门。
这导致两类问题：

- 全平台出现多个根部门，与"单根"约束相悖；
- 这些部门及其成员的物化 ``path`` 不以默认组织根的 ``path`` 为前缀，
  在按 ``Department.path LIKE '{root_path}%'`` 圈定租户成员时被整体漏算。

同步逻辑已修复（顶层部门改挂到默认组织根下），但**增量推送里没被重推到的存量
部门不会自动修复**，需本脚本一次性收编。

## 做什么

把默认租户(``ROOT_TENANT_ID``)下、除默认组织根之外的所有 ``active`` 根部门
(``parent_id IS NULL``) 收编到默认组织根下：

- 设 ``parent_id = 默认组织根.id``；
- 级联重写整棵子树的 ``path``（把旧前缀 ``/<id>/`` 改成 ``/<root_id>/<id>/``）。

**不区分 source**（local / wecom / feishu / dingtalk 一视同仁），根本目的是单根。
不触碰挂载状态（``is_tenant_root`` / ``mounted_tenant_id``）。

## 幂等

收编后这些部门的 ``parent_id`` 不再为 ``None``，重复运行会被选择条件自然跳过。

## 用法（在 ``src/backend`` 目录下运行）

    # Dry-run（默认，只扫描并打印将被收编的部门，不写库）
    python scripts/backfill_departments_under_single_root.py

    # 真正应用
    python scripts/backfill_departments_under_single_root.py --apply

## 为什么不写 OpenFGA parent tuple

部门父子的 ``department#parent`` tuple 只在 F002 手动建/移部门时写入；SSO 同步
路径(``aupsert_by_external_id``)从不写。因此 SSO 部门在 FGA 里本就没有 parent
tuple，本脚本改挂父节点也无 tuple 可删/可补。部门管理员"管辖子树"的判权不依赖
FGA parent 继承，而是看 DB ``path``(子树可见性/隐式管辖走 ``path LIKE``；admin
check 失败时沿 ``parent_id`` 逐级回退兜底)。所以**改对 ``parent_id`` + ``path``
就等于改对了权限链**，无需触碰 FGA。这也与修复后的同步路径(同样只改 DB)保持一致。

## 安全

- Dry-run 是默认行为；``--apply`` 才写库。
- 仅 DB 操作，无需 OpenFGA / Redis / Milvus 初始化。
- 跨租户上下文：运行在 ``bypass_tenant_filter()`` 下。
- 仅改 ``parent_id`` + 子树 ``path``；不动挂载状态、不动各部门的 member/admin tuple。
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


def _rebased_path(root_path: str, old_path: str) -> str:
    """Prefix a mis-rooted subtree path with the default-org root path.

    ``root_path='/1/'`` + ``old_path='/5/'`` → ``'/1/5/'``. ``old_path`` is
    the department's current (root-level) materialised path, always of the
    form ``/<id>/``.
    """
    return root_path.rstrip("/") + old_path


async def _collect_extra_roots(root):
    """Return active root departments (``parent_id IS NULL``) in the default
    tenant that are NOT the default-org root itself — i.e. the mis-rooted
    departments to collapse.
    """
    from sqlmodel import select

    from bisheng.core.database import get_async_db_session
    from bisheng.database.models.department import Department
    from bisheng.database.models.tenant import ROOT_TENANT_ID

    async with get_async_db_session() as session:
        rows = (
            await session.exec(
                select(Department).where(
                    Department.parent_id.is_(None),
                    Department.id != root.id,
                    Department.tenant_id == ROOT_TENANT_ID,
                    Department.status == "active",
                )
            )
        ).all()
    return list(rows)


async def run(apply: bool) -> int:
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.database.models.department import DepartmentDao
    from bisheng.database.models.tenant import ROOT_TENANT_ID

    with bypass_tenant_filter():
        root = await DepartmentDao.aget_tenant_root_via_pointer(ROOT_TENANT_ID)
        if root is None:
            logger.error("默认组织根部门未初始化（tenant.root_dept_id 为空）。请先确认初始化已完成后再运行本脚本。")
            return 2
        root_path = root.path or ""
        if not root_path.startswith("/"):
            logger.error(
                "默认组织根部门 path 异常: id=%s path=%r，中止。",
                root.id,
                root_path,
            )
            return 3

        extras = await _collect_extra_roots(root)
        if not extras:
            logger.info("没有需要收编的根部门，全平台已是单根（root id=%s）。", root.id)
            return 0

        logger.info(
            "默认组织根: id=%s path=%s。发现 %d 个误挂为根的部门待收编:",
            root.id,
            root_path,
            len(extras),
        )
        plan = []
        for d in extras:
            old_path = d.path or ""
            expected = f"/{d.id}/"
            if old_path != expected:
                # The subtree LIKE/replace anchors on the STORED path; a
                # malformed root path means descendants can't be rebased
                # reliably. Surface it instead of silently corrupting.
                logger.warning(
                    "跳过 path 异常的根部门 id=%s name=%r path=%r（期望 %r），请人工核查。",
                    d.id,
                    d.name,
                    old_path,
                    expected,
                )
                continue
            new_path = _rebased_path(root_path, old_path)
            plan.append((d, old_path, new_path))
            logger.info(
                "  - id=%s name=%r source=%s  path %s -> %s, parent_id None -> %s",
                d.id,
                d.name,
                getattr(d, "source", None),
                old_path,
                new_path,
                root.id,
            )

        if not apply:
            logger.info(
                "[dry-run] 未写库。确认无误后追加 --apply 执行（共 %d 个）。",
                len(plan),
            )
            return 0

        collapsed = 0
        for d, old_path, new_path in plan:
            changed = await DepartmentDao.areparent_root_under(
                dept_id=int(d.id),
                old_path=old_path,
                new_path=new_path,
                new_parent_id=int(root.id),
            )
            collapsed += 1
            logger.info("已收编 id=%s（含子树 %d 行 path 重写）。", d.id, changed)
        logger.info("完成。共收编 %d 个根部门到默认组织根下。", collapsed)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the backfill (default is dry-run).",
    )
    args = parser.parse_args()
    return asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    sys.exit(main())
