#!/usr/bin/env python3
"""Swap live tables with ``<table>_bak`` copies.

For each backed-up table:

1. rename live ``<table>`` to ``<table>_ori``
2. rename ``<table>_bak`` to ``<table>``

Default is dry-run. ``--apply`` performs the rename. Leftover ``*_ori``
tables from a previous rollback must be dropped with ``--force``.

Usage (from ``src/backend``):

    python scripts/rollback_tag_library_migration.py
    python scripts/rollback_tag_library_migration.py --apply
    python scripts/rollback_tag_library_migration.py --apply --force
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

from loguru import logger  # noqa: E402
from tag_library_migrate_support import (  # noqa: E402
    bak_name,
    distinct_library_tenant_ids,
    inspect_backup_state,
    ori_name,
    rename_backup_into_place,
)

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402
from bisheng.knowledge.domain.services.tag_library_tag_service import (  # noqa: E402
    TagLibraryTagService,
)


def _print_state(rows: list[dict[str, object]]) -> None:
    print("当前表状态:")
    for row in rows:
        table = str(row["table"])
        print(
            f"  {table:<32} live_rows={row['live_rows']}  "
            f"{bak_name(table)}={'yes' if row['bak'] else 'no'} "
            f"bak_rows={row['bak_rows'] if row['bak'] else '-'}  "
            f"{ori_name(table)}={'yes' if row['ori'] else 'no'}"
        )
    print()
    print("将执行:")
    for row in rows:
        table = str(row["table"])
        print(f"  {table} -> {ori_name(table)}")
        print(f"  {bak_name(table)} -> {table}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="用 原表名_bak 换回原表, 现表改名为 原表名_ori")
    parser.add_argument("--apply", action="store_true", help="真正改表名, 默认 dry-run")
    parser.add_argument("--force", action="store_true", help="已有 _ori 表时先删除再改名")
    args = parser.parse_args()

    with bypass_tenant_filter(), get_sync_db_session() as session:
        state = inspect_backup_state(session)
        _print_state(state)
        missing_bak = [bak_name(str(row["table"])) for row in state if not row["bak"]]
        if missing_bak:
            print("缺少备份表: " + ", ".join(missing_bak), file=sys.stderr)
            print("请先运行: python scripts/backup_tag_library_migration.py --apply", file=sys.stderr)
            if not args.apply:
                return 1
        if not args.apply:
            print("Dry-run, 未写库。确认无误后加 --apply 执行。")
            return 0
        try:
            pairs = rename_backup_into_place(session, force=args.force)
            session.expire_all()
            tenant_ids = distinct_library_tenant_ids(session)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    for tenant_id in tenant_ids or [None]:
        try:
            TagLibraryTagService.invalidate_link_b_tenant_catalog_cache_sync(tenant_id)
        except Exception:
            logger.exception("failed to invalidate tag resolver catalog cache for tenant_id={}", tenant_id)

    print("已回滚 (现表已改为 *_ori, 备份表已改回原名):")
    for live, ori, bak in pairs:
        print(f"  {live} <- {bak}  (旧现表现为 {ori})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
