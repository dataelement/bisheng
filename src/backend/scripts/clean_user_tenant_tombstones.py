#!/usr/bin/env python3
"""一次性脚本：清理 ``user_tenant`` 表里的"墓碑行"。

## 背景

v2.5.1 F011 之后 ``user_tenant`` 表的权威字段是 ``is_active``：

- ``is_active=1``  → 用户当前的 leaf 租户（每用户唯一，由 uk_user_active 约束保证）
- ``is_active=NULL`` → 历史快照（mount/unmount/sync 切换 leaf 时被 demote 留下）

挂载子租户（``MOUNT_BACKFILL``）时 ``aactivate_user_tenant`` 会插入新行
``(tenant_id=新挂载点, is_active=1, is_default=1)``；后续解挂或主部门
变更触发反向 sync 时，这条行会被 demote 成 ``is_active=NULL``，但
``is_default=1`` 字段没被同步清掉，留下"两个 is_default=1 但只有一个
真正 active"的歧义状态。

这些墓碑行还会污染"租户管理"列表的用户数统计（v2.5.1 hotfix 已经把
``acount_tenant_users`` 的过滤条件改成 ``is_active=1``，从源头消除这个
症状），本脚本负责把已经写入的墓碑物理删除。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印将要删除的行，不写 DB）
    python scripts/clean_user_tenant_tombstones.py

    # 真正应用
    python scripts/clean_user_tenant_tombstones.py --apply

## 安全保证

- 仅删除满足 ``is_active IS NULL AND is_default = 1`` 的行。
- **删除前先确认**：该用户必须存在另一行 ``is_active=1`` 的当前 leaf，
  否则跳过该用户（防止把"唯一可用归属"也误删）。
- 单次事务，失败回滚。
- 不动 ``is_active=NULL AND is_default=0`` 的行——这些是普通历史记录，
  ``user_tenants_with_details`` 已经按 ``status='active'`` 过滤，前端不
  会暴露给用户。
"""

from __future__ import annotations

import argparse
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.database import get_sync_db_session  # noqa: E402


SCAN_SQL = sa_text("""
    SELECT ut.id, ut.user_id, ut.tenant_id, t.tenant_name, t.status
    FROM user_tenant ut
    LEFT JOIN tenant t ON t.id = ut.tenant_id
    WHERE ut.is_active IS NULL AND ut.is_default = 1
    ORDER BY ut.user_id, ut.id
""")

ACTIVE_USER_IDS_SQL = sa_text("""
    SELECT DISTINCT user_id FROM user_tenant WHERE is_active = 1
""")

DELETE_SQL = sa_text("DELETE FROM user_tenant WHERE id IN :ids")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true',
                        help='Actually delete rows. Default is dry-run.')
    args = parser.parse_args()

    with get_sync_db_session() as session:
        candidates = list(session.execute(SCAN_SQL))
        active_user_ids = {row[0] for row in session.execute(ACTIVE_USER_IDS_SQL)}

    if not candidates:
        print('No tombstone rows found. Nothing to do.')
        return 0

    safe_ids: list[int] = []
    skipped: list[tuple[int, int, str]] = []
    for ut_id, user_id, tenant_id, tenant_name, tenant_status in candidates:
        if user_id not in active_user_ids:
            # User has no current leaf — deleting this row would leave them
            # without any user_tenant association. Skip and let an admin
            # investigate manually.
            skipped.append((ut_id, user_id, 'user has no is_active=1 row'))
            continue
        safe_ids.append(ut_id)

    print(f'Total tombstone rows scanned: {len(candidates)}')
    print(f'  - safe to delete:           {len(safe_ids)}')
    print(f'  - skipped (no current leaf):{len(skipped)}')
    print()

    if safe_ids:
        print('Rows to delete:')
        rows_by_id = {r[0]: r for r in candidates}
        for ut_id in safe_ids:
            _id, uid, tid, tname, tstatus = rows_by_id[ut_id]
            print(f'  ut.id={_id:<6} user_id={uid:<6} '
                  f'tenant_id={tid} ({tname or "?"}, status={tstatus})')

    if skipped:
        print()
        print('Skipped rows (manual review required):')
        for ut_id, uid, reason in skipped:
            print(f'  ut.id={ut_id:<6} user_id={uid:<6} reason={reason}')

    if not args.apply:
        print()
        print('Dry-run. Re-run with --apply to delete.')
        return 0

    if not safe_ids:
        print()
        print('No safe rows to delete; exiting without changes.')
        return 0

    with get_sync_db_session() as session:
        session.execute(DELETE_SQL.bindparams(ids=tuple(safe_ids)))
        session.commit()

    print()
    print(f'Deleted {len(safe_ids)} tombstone rows.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
