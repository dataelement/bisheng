#!/usr/bin/env python3
"""一次性脚本：修补 v2.5 多租户改造中被错写为 ``tenant_id=1`` 的子租户资源。

## 背景

早期 v2.5 分支里，下列 ORM 表把 ``tenant_id`` 字段的 Python 默认值写成
``Field(default=1, ...)``。SQLModel 实例化时立刻把字段填成 ``1``，绕过
``bisheng.core.database.tenant_filter._on_before_flush`` 的自动注入
（钩子条件 ``current_val is None or current_val == 0``）。

子租户（leaf tenant）的用户创建 Knowledge / Flow / Group 等资源时被静
默写到 ``tenant_id = 1``（root），随后 ``do_orm_execute`` 又按当前
租户过滤，子租户视角下查不到自己刚建的资源 → 工作流执行 NotFound。

模型层缺陷已在 hotfix 中修复（default 改 None）。本脚本负责修补
**已经写入 root 的脏数据**：把这些 row 的 ``tenant_id`` 改成创建者
``user_tenant.tenant_id``（取 ``is_default=1, status='active'`` 的那一条）。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印计数，不写 DB）
    python scripts/fix_tenant_id_root_leak.py

    # 真正应用
    python scripts/fix_tenant_id_root_leak.py --apply

    # 单表灰度
    python scripts/fix_tenant_id_root_leak.py --table=knowledge --apply

## 安全保证

- 仅匹配 ``row.tenant_id = 1`` 且 ``user_tenant.is_default = 1`` 且
  ``user_tenant.tenant_id != 1``。Root admin 创建的资源（默认租户即
  Root）不会被误改。
- 每张表独立事务，逐表 commit，便于失败回滚定位。
- UniqueConstraint 冲突按 MySQL 默认错误抛出，脚本中断；运维需手动
  介入。

## 不在本脚本范围

- ``failed_tuple``：是 OpenFGA 写失败的重试队列，retry_count 满后会
  自动 dead；不修复。
- ``department``：部门挂载逻辑由 F011 业务流程驱动，不能按 user 推断
  租户归属；不修复。
- ``llm_call_log`` / ``llm_token_log``：审计 / 用量日志记录"调用时的
  用户 leaf 租户"，本来就不带 default=1 的 bug；不修复。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.database import get_sync_db_session  # noqa: E402


@dataclass
class FixSpec:
    """One table to inspect / fix.

    ``user_id_col``: column on the table that links to ``user.user_id``.
        For tables without a direct user column (``llm_model``), set
        ``join_via_table`` to inherit tenant from a parent row.
    """
    table: str
    user_id_col: Optional[str] = None
    join_via_table: Optional[str] = None
    join_via_fk: Optional[str] = None  # local column on this table that points to join_via_table.id


# Order matters for join_via dependencies (parent before child).
SPECS: List[FixSpec] = [
    FixSpec('knowledge', user_id_col='user_id'),
    FixSpec('flow', user_id_col='user_id'),
    FixSpec('assistant', user_id_col='user_id'),
    FixSpec('group', user_id_col='create_user'),
    FixSpec('role', user_id_col='create_user'),
    FixSpec('llm_server', user_id_col='user_id'),
    # llm_model.tenant_id mirrors its parent llm_server.tenant_id by design
    # (see llm_server.py model comment). Fix it after llm_server.
    FixSpec('llm_model', join_via_table='llm_server', join_via_fk='server_id'),
    FixSpec('approval_request', user_id_col='applicant_user_id'),
    FixSpec('department_knowledge_space', user_id_col='created_by'),
    FixSpec('org_sync_config', user_id_col='create_user'),
    FixSpec('org_sync_log', user_id_col='trigger_user'),
]


def _scan_user_linked(spec: FixSpec) -> int:
    sql = sa_text(
        f"""
        SELECT COUNT(*) AS cnt
        FROM `{spec.table}` t
        JOIN user_tenant ut
          ON ut.user_id = t.`{spec.user_id_col}`
         AND ut.is_default = 1
         AND ut.status = 'active'
        WHERE t.tenant_id = 1
          AND ut.tenant_id != 1
        """
    )
    with get_sync_db_session() as session:
        return int(session.execute(sql).scalar() or 0)


def _scan_join_via(spec: FixSpec) -> int:
    sql = sa_text(
        f"""
        SELECT COUNT(*) AS cnt
        FROM `{spec.table}` c
        JOIN `{spec.join_via_table}` p ON p.id = c.`{spec.join_via_fk}`
        WHERE c.tenant_id = 1
          AND p.tenant_id != 1
        """
    )
    with get_sync_db_session() as session:
        return int(session.execute(sql).scalar() or 0)


def _apply_user_linked(spec: FixSpec) -> int:
    sql = sa_text(
        f"""
        UPDATE `{spec.table}` t
        JOIN user_tenant ut
          ON ut.user_id = t.`{spec.user_id_col}`
         AND ut.is_default = 1
         AND ut.status = 'active'
        SET t.tenant_id = ut.tenant_id
        WHERE t.tenant_id = 1
          AND ut.tenant_id != 1
        """
    )
    with get_sync_db_session() as session:
        result = session.execute(sql)
        session.commit()
        return result.rowcount or 0


def _apply_join_via(spec: FixSpec) -> int:
    sql = sa_text(
        f"""
        UPDATE `{spec.table}` c
        JOIN `{spec.join_via_table}` p ON p.id = c.`{spec.join_via_fk}`
        SET c.tenant_id = p.tenant_id
        WHERE c.tenant_id = 1
          AND p.tenant_id != 1
        """
    )
    with get_sync_db_session() as session:
        result = session.execute(sql)
        session.commit()
        return result.rowcount or 0


def _scan(spec: FixSpec) -> int:
    if spec.user_id_col:
        return _scan_user_linked(spec)
    return _scan_join_via(spec)


def _apply(spec: FixSpec) -> int:
    if spec.user_id_col:
        return _apply_user_linked(spec)
    return _apply_join_via(spec)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--apply', action='store_true',
                        help='Actually run the UPDATEs (default is dry-run).')
    parser.add_argument('--table', type=str, default=None,
                        help='Only process this single table.')
    args = parser.parse_args()

    specs = SPECS
    if args.table:
        specs = [s for s in SPECS if s.table == args.table]
        if not specs:
            print(f'ERROR: --table={args.table} matched none of {[s.table for s in SPECS]}')
            sys.exit(2)

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'=== fix_tenant_id_root_leak ({mode}) ===')
    print()

    total = 0
    for spec in specs:
        try:
            cnt_before = _scan(spec)
        except Exception as e:
            print(f'  {spec.table}: SCAN FAILED — {e}')
            continue
        if cnt_before == 0:
            print(f'  {spec.table}: 0 rows to fix')
            continue
        if not args.apply:
            print(f'  {spec.table}: would update {cnt_before} rows')
            total += cnt_before
            continue
        try:
            updated = _apply(spec)
        except Exception as e:
            print(f'  {spec.table}: APPLY FAILED after scanning {cnt_before} — {e}')
            print(f'  (likely a UniqueConstraint conflict; manual reconciliation '
                  f'required, then re-run --apply for the remaining tables.)')
            sys.exit(1)
        cnt_after = _scan(spec)
        print(f'  {spec.table}: updated {updated} rows '
              f'(before={cnt_before}, leftover={cnt_after})')
        total += updated

    print()
    if args.apply:
        print(f'Done. Total rows updated: {total}')
    else:
        print(f'Dry-run complete. Total rows that WOULD be updated: {total}')
        print('Re-run with --apply to actually fix.')


if __name__ == '__main__':
    main()
