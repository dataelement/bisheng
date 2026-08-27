#!/usr/bin/env python3
"""Copy live tag-library tables to ``<table>_bak``.

Tables:

- ``tag`` -> ``tag_bak``
- ``knowledge_tag_library_link`` -> ``knowledge_tag_library_link_bak``
- ``knowledge_space_tag_library`` -> ``knowledge_space_tag_library_bak``

Default is dry-run. ``--apply`` creates the copies. If ``*_bak`` already
exists, pass ``--force`` to drop and recreate them.

Usage (from ``src/backend``):

    python scripts/backup_tag_library_migration.py
    python scripts/backup_tag_library_migration.py --apply
    python scripts/backup_tag_library_migration.py --apply --force
"""

from __future__ import annotations

import argparse
import os
import sys

_SCRIPTS_DIR = os.path.abspath(os.path.dirname(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_SCRIPTS_DIR, ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from tag_library_migrate_support import (  # noqa: E402
    bak_name,
    create_backup_tables,
    inspect_backup_state,
)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402


def _print_state(rows: list[dict[str, object]]) -> None:
    print("当前表状态:")
    for row in rows:
        table = str(row["table"])
        bak_rows = row["bak_rows"] if row["bak"] else "-"
        print(
            f"  {table:<32} live={row['live_rows']:<8} "
            f"{bak_name(table)}={'yes' if row['bak'] else 'no'} rows={bak_rows}  "
            f"ori={'yes' if row['ori'] else 'no'}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="把标签库相关表复制为 原表名_bak")
    parser.add_argument("--apply", action="store_true", help="真正建备份表, 默认 dry-run")
    parser.add_argument("--force", action="store_true", help="备份表已存在时先删除再重建")
    args = parser.parse_args()

    with bypass_tenant_filter(), get_sync_db_session() as session:
        state = inspect_backup_state(session)
        _print_state(state)
        if not args.apply:
            print("将执行: CREATE TABLE <表>_bak (结构+数据复制自原表)")
            print("Dry-run, 未写库。确认无误后加 --apply 执行。")
            return 0
        try:
            created = create_backup_tables(session, force=args.force)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    print("已创建备份表:")
    for row in created:
        print(f"  {row['table']} -> {row['backup']}  ({row['rows']} 行)")
    print()
    print("回滚: python scripts/rollback_tag_library_migration.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
