#!/usr/bin/env python3
"""一次性脚本：修复违反 INV-T1（2 层租户锁定）的嵌套挂载点。

## 背景

INV-T1 规定：``department.is_tenant_root=1`` 的节点不能落在另一个挂载点
的子树中。``TenantMountService.mount_child`` 在创建挂载时通过
``DepartmentDao.aget_ancestors_with_mount`` 校验过这一点（会抛 22001
``TenantTreeNestingForbiddenError``），但同一份校验在两条 reparent 路径
上原本缺失：

  * ``DepartmentService.amove_department`` —— UI 拖拽移动部门
  * ``DeptUpsertService.upsert_from_sync_payload`` —— SSO 同步重定父

只要先在两个独立分支上各挂一个 child tenant，再把其中一个 dept move 到
另一个 dept 子树下，就能写出嵌套挂载。前端会把内层 dept 也渲染成
"子租户"，看起来像三层租户嵌套。两条 reparent 路径已在本次提交补上
INV-T1 校验，本脚本负责清理已经写入 DB 的脏数据。

## 修复策略：把内层挂载部门"提升为外层挂载的兄弟"

每一对违规 ``(inner, outer)``（``inner.path`` 以 ``outer.path`` 开头）：

  1. 沿 inner 的祖先链找到最外层的挂载祖先 ``outer_top``。
  2. 把 inner 的 ``parent_id`` 改成 ``outer_top.parent_id``，
     ``path`` 改成 ``<outer_top.parent.path><inner.id>/``。
  3. 级联刷新 inner 子树里所有节点的 ``path``。

这种做法不丢任何租户身份 / 用户 / 资源 / 审计日志：
``user_tenant.tenant_id`` 与 ``mounted_tenant_id`` 都不动，仅 dept 树
形态恢复成"两个独立的子租户挂在 Root 部门下"。

如果某条违规找不到合法落点（``outer_top`` 没有父节点 —— 不应发生，因为
Root 部门本身禁止被挂），脚本只报告不修改。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印计划，不改 DB）
    python scripts/fix_nested_tenant_mounts.py

    # 真正执行
    python scripts/fix_nested_tenant_mounts.py --apply

可重复执行：``--apply`` 完成后再跑一次仍是 dry-run，预期"无违规"。

## 不在本脚本范围

* ``user_tenant`` / ``audit_log`` 等关联表 —— 内层 tenant 仍存在，所有
  关联记录保持不变。
* ``OpenFGA`` 元组 —— mount 点未变化，无需触发 share fan-out。
* 同时违反多重嵌套（>2 层）—— 只把每个 inner 提升到最外层 mount 之外，
  最多两轮即可收敛；脚本会在每一轮重新扫描，直到无违规。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.database import get_sync_db_session  # noqa: E402

# ----------------------------------------------------------------------------
# Detection: nested mount pairs.
#
# The JOIN is a self-join on ``path LIKE CONCAT(outer.path, '%')`` which
# produces every (inner, ancestor_with_mount) pair, not just the closest.
# Per-inner deduplication picks the OUTERMOST mounted ancestor so the
# repair places ``inner`` outside the deepest violating subtree.
# ----------------------------------------------------------------------------
_DETECT_SQL = sa_text(
    """
    SELECT
        d_inner.id              AS inner_id,
        d_inner.dept_id         AS inner_did,
        d_inner.name            AS inner_name,
        d_inner.path            AS inner_path,
        d_inner.parent_id       AS inner_parent_id,
        d_inner.mounted_tenant_id AS inner_mt,
        d_outer.id              AS outer_id,
        d_outer.dept_id         AS outer_did,
        d_outer.name            AS outer_name,
        d_outer.path            AS outer_path,
        d_outer.parent_id       AS outer_parent_id,
        d_outer.mounted_tenant_id AS outer_mt
    FROM department d_inner
    JOIN department d_outer
      ON d_inner.path LIKE CONCAT(d_outer.path, '%')
     AND d_inner.id <> d_outer.id
    WHERE d_inner.is_tenant_root = 1
      AND d_outer.is_tenant_root = 1
    ORDER BY d_inner.id, LENGTH(d_outer.path) ASC
    """
)


@dataclass
class Violation:
    inner_id: int
    inner_did: str
    inner_name: str
    inner_path: str
    inner_mt: Optional[int]
    # ``outer_top`` is the outermost mounted ancestor — the one whose
    # parent we will reparent ``inner`` under.
    outer_top_id: int
    outer_top_did: str
    outer_top_name: str
    outer_top_path: str
    outer_top_parent_id: Optional[int]
    outer_top_mt: Optional[int]


def _scan_violations() -> List[Violation]:
    """Return one Violation per (inner) dept; ``outer_top`` is the most
    distant mounted ancestor (smallest ``path`` length).
    """
    seen: Dict[int, Violation] = {}
    with get_sync_db_session() as session:
        rs = session.execute(_DETECT_SQL)
        rows = [dict(r._mapping) for r in rs.fetchall()]
    for row in rows:
        inner_id = int(row['inner_id'])
        # ORDER BY guarantees the first row per inner is the outermost.
        if inner_id in seen:
            continue
        seen[inner_id] = Violation(
            inner_id=inner_id,
            inner_did=row['inner_did'],
            inner_name=row['inner_name'],
            inner_path=row['inner_path'],
            inner_mt=row['inner_mt'],
            outer_top_id=int(row['outer_id']),
            outer_top_did=row['outer_did'],
            outer_top_name=row['outer_name'],
            outer_top_path=row['outer_path'],
            outer_top_parent_id=(
                int(row['outer_parent_id'])
                if row['outer_parent_id'] is not None else None
            ),
            outer_top_mt=row['outer_mt'],
        )
    return list(seen.values())


def _print_violation(v: Violation) -> None:
    print(
        f'  inner dept#{v.inner_id} {v.inner_name!r} '
        f'(tenant={v.inner_mt}) path={v.inner_path}'
    )
    print(
        f'      nested under outer dept#{v.outer_top_id} {v.outer_top_name!r} '
        f'(tenant={v.outer_top_mt}) path={v.outer_top_path}'
    )


# ----------------------------------------------------------------------------
# Repair: move ``inner`` to be a sibling of ``outer_top``.
# ----------------------------------------------------------------------------

_GET_PARENT_PATH_SQL = sa_text(
    'SELECT path FROM department WHERE id = :parent_id'
)

_CASCADE_PATH_SQL = sa_text(
    "UPDATE department "
    "SET path = REPLACE(path, :old_path, :new_path) "
    "WHERE path LIKE CONCAT(:old_path, '%')"
)

_REPARENT_SQL = sa_text(
    'UPDATE department '
    'SET parent_id = :new_parent_id '
    'WHERE id = :inner_id'
)


def _repair(v: Violation) -> bool:
    """Apply the repair for one violation in its own transaction.

    Returns True on success, False if the violation cannot be safely
    repaired (e.g. ``outer_top`` itself has no parent — should be
    impossible because Root depts can't be mounted).
    """
    if v.outer_top_parent_id is None:
        print(
            f'  [skip] inner dept#{v.inner_id}: outer_top has no parent — '
            f'cannot determine a legal sibling slot. Investigate manually.'
        )
        return False

    with get_sync_db_session() as session:
        new_parent_path_row = session.execute(
            _GET_PARENT_PATH_SQL.bindparams(parent_id=v.outer_top_parent_id),
        ).fetchone()
        if new_parent_path_row is None or not new_parent_path_row[0]:
            print(
                f'  [skip] inner dept#{v.inner_id}: cannot resolve '
                f'parent#{v.outer_top_parent_id} path.'
            )
            return False

        new_parent_path = new_parent_path_row[0]
        if not new_parent_path.endswith('/'):
            new_parent_path = f'{new_parent_path}/'

        old_path = v.inner_path
        new_path = f'{new_parent_path}{v.inner_id}/'

        if old_path == new_path:
            # Path already correct — only the parent_id pointer was wrong.
            session.execute(_REPARENT_SQL.bindparams(
                new_parent_id=v.outer_top_parent_id, inner_id=v.inner_id,
            ))
        else:
            # Cascade-update path for the entire subtree first; the
            # REPLACE pattern depends on ``old_path`` still being present.
            session.execute(_CASCADE_PATH_SQL.bindparams(
                old_path=old_path, new_path=new_path,
            ))
            session.execute(_REPARENT_SQL.bindparams(
                new_parent_id=v.outer_top_parent_id, inner_id=v.inner_id,
            ))

        session.commit()

    print(
        f'  [fix]  inner dept#{v.inner_id} {v.inner_name!r}: '
        f'parent_id {v.outer_top_id} → {v.outer_top_parent_id}, '
        f'path {old_path} → {new_path}'
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help='Execute repairs (default = dry-run).',
    )
    args = parser.parse_args()

    # Multi-level nesting is unlikely (mount creation has always enforced
    # INV-T1), but reparenting could theoretically chain it. Re-scan after
    # each repair pass and stop when no violation remains, capped at a
    # generous bound to avoid infinite loops on truly malformed paths.
    MAX_PASSES = 8
    total_fixed = 0
    pass_no = 0
    while True:
        pass_no += 1
        violations = _scan_violations()
        if not violations:
            if pass_no == 1:
                print('未发现 INV-T1 违规嵌套挂载。')
            else:
                print(f'\n第 {pass_no} 轮扫描：无违规，结束。')
            break

        print(f'\n=== 第 {pass_no} 轮扫描：发现 {len(violations)} 个违规 ===')
        for v in violations:
            _print_violation(v)

        if not args.apply:
            print(
                f'\n[dry-run] 共 {len(violations)} 个违规。加 --apply 真正执行。',
            )
            return 0

        print(f'\n[apply] 第 {pass_no} 轮修复：')
        fixed_in_pass = 0
        for v in violations:
            if _repair(v):
                fixed_in_pass += 1
        total_fixed += fixed_in_pass

        if fixed_in_pass == 0:
            print('  本轮无可修复项，跳出循环以避免死循环。')
            break
        if pass_no >= MAX_PASSES:
            print(f'  已达 {MAX_PASSES} 轮上限，停止。请人工介入。')
            return 2

    if args.apply:
        print(f'\n[apply] 累计修复 {total_fixed} 项。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
