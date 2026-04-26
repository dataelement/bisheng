#!/usr/bin/env python3
"""一次性脚本：扫描 department 与 tenant 表之间的「孤儿挂载」状态。

v2.5 早期分支可能写出过 `is_tenant_root=1 AND mounted_tenant_id IS NULL`
的半成品行；前端在 dept tree 上仍会渲染「取消挂载」按钮，但后端
`unmount_child` 会以 22002 / HTTP 400 拒绝（dept.mounted_tenant_id 为空）。
本脚本扫出这种行以及指向已不存在 / 已归档的 tenant 行，并可选地清理。

报告分三类：
  A) is_tenant_root=1 AND mounted_tenant_id IS NULL          —— 脏标记
  B) is_tenant_root=1 AND mounted_tenant_id 指向不存在的 tenant —— FK 已断
  C) is_tenant_root=1 AND tenant.status IN ('archived','orphaned','disabled')
     —— 数据合法，仅作信息提示

用法（在 src/backend 目录）::

    # 预览（默认）
    python scripts/scan_orphan_tenant_mounts.py

    # 真正修复 A/B：把 is_tenant_root 置 0 且 mounted_tenant_id 置 NULL
    python scripts/scan_orphan_tenant_mounts.py --apply

C 类不做任何处理 —— 那是 unmount 已完成后保留的归档关系。

注意：本脚本只改 department.is_tenant_root / mounted_tenant_id 两列；
不动 tenant 行、不动 OpenFGA 元组（A 类本就没成功写过 tenant）。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.database import get_sync_db_session  # noqa: E402

_REPORT_SQL = sa_text(
    """
    SELECT
        d.id           AS dept_id,
        d.name         AS dept_name,
        d.parent_id    AS parent_id,
        d.is_tenant_root,
        d.mounted_tenant_id,
        t.id           AS tenant_id,
        t.tenant_code,
        t.tenant_name,
        t.status       AS tenant_status
    FROM department d
    LEFT JOIN tenant t ON t.id = d.mounted_tenant_id
    WHERE d.is_tenant_root = 1
       OR d.mounted_tenant_id IS NOT NULL
    ORDER BY d.id
    """
)

_FIX_SQL = sa_text(
    'UPDATE department '
    'SET is_tenant_root = 0, mounted_tenant_id = NULL '
    'WHERE id = :dept_id'
)


def _classify(row: Dict[str, Any]) -> str:
    """Return 'A' / 'B' / 'C' / 'OK'."""
    if row['is_tenant_root'] != 1:
        # mounted_tenant_id pointing at a tenant but flag cleared — also
        # broken (we don't expect this), bucket it as B for repair.
        return 'B' if row['mounted_tenant_id'] else 'OK'
    if row['mounted_tenant_id'] is None:
        return 'A'
    if row['tenant_id'] is None:
        return 'B'
    if row['tenant_status'] in ('archived', 'orphaned', 'disabled'):
        return 'C'
    return 'OK'


def _print_row(label: str, row: Dict[str, Any]) -> None:
    print(
        f'  [{label}] dept#{row["dept_id"]:<5} {row["dept_name"][:24]:<24} '
        f'is_tenant_root={row["is_tenant_root"]} '
        f'mounted_tenant_id={row["mounted_tenant_id"]!s:<5} '
        f'tenant.status={row["tenant_status"]}'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply', action='store_true',
        help='Execute UPDATEs for category A/B (default = dry-run).',
    )
    args = parser.parse_args()

    buckets: Dict[str, List[Dict[str, Any]]] = {'A': [], 'B': [], 'C': []}
    with get_sync_db_session() as session:
        rs = session.execute(_REPORT_SQL)
        rows = [dict(r._mapping) for r in rs.fetchall()]

    for row in rows:
        bucket = _classify(row)
        if bucket in buckets:
            buckets[bucket].append(row)

    print(f'共扫描 department × tenant 关联行 {len(rows)} 条。\n')
    print(f'A) is_tenant_root=1 AND mounted_tenant_id IS NULL  ({len(buckets["A"])})')
    for r in buckets['A']:
        _print_row('A', r)
    print(f'\nB) is_tenant_root=1 AND mounted_tenant_id 指向已删除 tenant  ({len(buckets["B"])})')
    for r in buckets['B']:
        _print_row('B', r)
    print(f'\nC) is_tenant_root=1 AND tenant.status 非 active  ({len(buckets["C"])})')
    for r in buckets['C']:
        _print_row('C', r)

    fixable = buckets['A'] + buckets['B']
    if not fixable:
        print('\n无需修复（A/B 均为空）。')
        return 0

    if not args.apply:
        print(
            f'\n[dry-run] 将清理 {len(fixable)} 条 (A+B)。'
            f' 加 --apply 真正执行。',
        )
        return 0

    with get_sync_db_session() as session:
        for r in fixable:
            session.execute(_FIX_SQL.bindparams(dept_id=r['dept_id']))
        session.commit()
    print(f'\n[apply] 已清理 {len(fixable)} 条孤儿挂载标记。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
