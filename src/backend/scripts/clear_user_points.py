#!/usr/bin/env python3
"""清空指定租户的单个账号或全部用户积分, 默认 tenant_id=1、account=wenruli。

在 src/backend 目录运行:
    .venv/bin/python scripts/clear_user_points.py
    .venv/bin/python scripts/clear_user_points.py --apply
    .venv/bin/python scripts/clear_user_points.py --tenant-id 1 --all-users
    .venv/bin/python scripts/clear_user_points.py --tenant-id 1 --all-users --apply
    .venv/bin/python scripts/clear_user_points.py --config config_3002.yaml --apply

默认只读预览。--apply 会先将待删数据备份到 ./points-backups, 再在同一事务内
删除同步记录、补扣记录、排行榜、流水和积分账户。任何错误都会回滚数据库操作。
保留登录账号、规则、说明文案和站内信。单账号模式保留文件收藏奖励档位;
--all-users 会同时清空目标租户的收藏奖励档位, 不涉及其他租户。
执行前须暂停相关积分写入、发奖、补扣、同步和刷榜任务; 本脚本不会清理 Celery 队列。
删除流水会移除对应幂等记录, 重跑历史事件可能重新发分。已提交的删除需借助备份恢复。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import MetaData, Table, delete, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

POINT_TABLES = (
    "point_sync_outbox",
    "point_pending_deduct",
    "point_rank_snapshot",
    "user_point_log",
    "user_point_account",
)
ALL_POINT_TABLES = (*POINT_TABLES[:3], "point_favorite_tier_award", *POINT_TABLES[3:])


def json_default(value: Any) -> str:
    """保留时间和精确数值的可读表示; 未知类型中止备份, 不继续删除。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"无法备份的数据类型: {type(value).__name__}")


def save_backup(directory: Path, document: dict[str, Any]) -> Path:
    """独占创建权限为 0600 的备份, 确保写入磁盘后才允许删除。"""
    content = json.dumps(document, ensure_ascii=False, indent=2, default=json_default)
    directory.mkdir(parents=True, exist_ok=True)
    target = "all_users" if document["scope"] == "all_users" else f"u{document['user_id']}"
    filename = f"points_t{document['tenant_id']}_{target}_{uuid4().hex}.json"
    path = directory / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return path.resolve()


def clear_user_points(
    engine: Engine,
    *,
    tenant_id: int = 1,
    account: str | None = None,
    all_users: bool = False,
    apply: bool = False,
    backup_dir: Path = Path("points-backups"),
) -> dict[str, Any]:
    """只操作明确租户; 单账号必须唯一匹配, 全量模式必须显式指定。"""
    if all_users and account is not None:
        raise ValueError("all_users 与 account 不能同时指定")
    if not all_users:
        account = "wenruli" if account is None else account.strip()
    if tenant_id < 1 or (not all_users and not account):
        raise ValueError("租户 ID 必须大于 0, 账号不能为空")
    point_table_names = ALL_POINT_TABLES if all_users else POINT_TABLES
    with engine.connect() as connection, connection.begin() as transaction:
        metadata = MetaData()
        # 反射真实表结构, 由数据库方言处理 user 等标识符的引用。
        required_tables = point_table_names if all_users else ("user", *point_table_names)
        tables = {name: Table(name, metadata, autoload_with=connection, resolve_fks=False) for name in required_tables}
        user_id = None
        user_name = None
        if all_users:
            # 全量按租户过滤, 同步记录即便对应流水已缺失也一并清理。
            filters = {name: tables[name].c.tenant_id == tenant_id for name in point_table_names}
        else:
            user = tables["user"]
            matches = (
                connection.execute(
                    select(user.c.user_id, user.c.user_name).where(
                        or_(user.c.user_name == account, user.c.external_id == account, user.c.external_code == account)
                    )
                )
                .mappings()
                .all()
            )
            if len(matches) != 1:
                ids = [row["user_id"] for row in matches]
                raise ValueError(f"账号 {account!r} 必须唯一匹配一个用户, 当前匹配 user_id={ids}; 未执行删除")
            user_id = int(matches[0]["user_id"])
            user_name = matches[0]["user_name"]
            filters = {
                name: (tables[name].c.tenant_id == tenant_id) & (tables[name].c.user_id == user_id)
                for name in point_table_names
                if name != "point_sync_outbox"
            }
            log = tables["user_point_log"]
            outbox = tables["point_sync_outbox"]
            filters["point_sync_outbox"] = (outbox.c.tenant_id == tenant_id) & outbox.c.log_id.in_(
                select(log.c.id).where(filters["user_point_log"])
            )
        if apply:
            # 与正常记账一致, 先锁积分账户; 完整维护仍要求外部暂停相关写入。
            connection.execute(
                select(tables["user_point_account"]).where(filters["user_point_account"]).with_for_update()
            ).all()
        counts = {
            name: connection.execute(select(func.count()).select_from(tables[name]).where(filters[name])).scalar_one()
            for name in point_table_names
        }
        result = {
            "tenant_id": tenant_id,
            "account": account,
            "user_id": user_id,
            "user_name": user_name,
            "scope": "all_users" if all_users else "single_user",
            "mode": "apply" if apply else "preview",
            "counts": counts,
            "backup_file": None,
        }
        if not apply or not any(counts.values()):
            transaction.rollback()
            result["status"] = "无需清理" if apply else "只读预览, 未删除"
            return result

        rows = {
            name: [dict(row) for row in connection.execute(select(tables[name]).where(filters[name])).mappings()]
            for name in point_table_names
        }
        if any(len(rows[name]) != counts[name] for name in point_table_names):
            raise RuntimeError("预览与备份行数不一致, 请暂停相关积分写入后重试")
        backup = save_backup(
            backup_dir,
            {**result, "created_at": datetime.now(timezone.utc), "format_version": 1, "tables": rows},
        )
        result["backup_file"] = str(backup)
        print(f"[clear_user_points] 删除前备份已保存: {backup}", file=sys.stderr)
        for name in point_table_names:
            deleted = connection.execute(delete(tables[name]).where(filters[name])).rowcount
            if deleted >= 0 and deleted != counts[name]:
                raise RuntimeError(f"{name} 实际删除 {deleted} 行, 预期 {counts[name]} 行; 回滚全部删除")
            remaining = connection.execute(
                select(func.count()).select_from(tables[name]).where(filters[name])
            ).scalar_one()
            if remaining:
                raise RuntimeError(f"{name} 仍有目标记录; 回滚全部删除")
        # 退出上下文后才报告已提交, 避免把提交失败误报为成功。
    result["status"] = "已提交"
    return result


def main() -> int:
    """加载与 execute_sql.py 相同的数据库配置, 默认不写数据库。"""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=int, default=1, help="目标租户 ID, 默认 1")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--account", help="目标账号, 未指定 --all-users 时默认 wenruli")
    target.add_argument("--all-users", action="store_true", help="清空目标租户全部用户积分, 包括收藏奖励档位")
    parser.add_argument("--config", help="配置文件名或路径, 与 execute_sql.py 相同")
    parser.add_argument("--backup-dir", type=Path, default=Path("points-backups"), help="删除前的 JSON 备份目录")
    parser.add_argument("--apply", action="store_true", help="备份后提交清空操作; 默认只读预览")
    args = parser.parse_args()
    if args.tenant_id < 1 or (args.account is not None and not args.account.strip()):
        parser.error("租户 ID 必须大于 0, 账号不能为空")
    if args.config:
        os.environ["config"] = args.config
    try:
        from bisheng.core.database import sync_get_database_connection

        report = clear_user_points(
            sync_get_database_connection().engine,
            tenant_id=args.tenant_id,
            account=args.account,
            all_users=args.all_users,
            apply=args.apply,
            backup_dir=args.backup_dir,
        )
    except ValueError as exc:
        print(f"[clear_user_points] 目标校验失败: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError, RuntimeError, TypeError) as exc:
        print(f"[clear_user_points] 执行失败, 未确认提交: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
