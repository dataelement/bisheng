#!/usr/bin/env python3
"""Execute one SQL statement against the database configured for BiSheng.

The script loads ``database_url`` through BiSheng's normal configuration path,
including encrypted-password handling and MySQL/DM8/SQLite dialect setup.

Run from ``src/backend``:

    PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
      --sql "SELECT user_id, user_name FROM user LIMIT 10"

    PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
      --sql "SELECT * FROM user WHERE user_id = :user_id" \
      --param user_id=1 --format json

    PYTHONPATH=./ .venv/bin/python scripts/execute_sql.py \
      --file /tmp/update.sql --apply

Read-only statements are allowed by default. Statements that may write data or
change schema require ``--apply`` and are committed only after successful
execution. Pass ``--config`` to select a non-default BiSheng YAML config.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, CursorResult
from sqlalchemy.exc import SQLAlchemyError
from tabulate import tabulate

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

READ_ONLY_KEYWORDS = frozenset(
    {
        "SELECT",
        "SHOW",
        "DESCRIBE",
        "DESC",
        "EXPLAIN",
        "PRAGMA",
    }
)
PARAM_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def strip_leading_comments(sql: str) -> str:
    """Remove whitespace and leading SQL comments for statement classification."""
    remaining = sql
    while True:
        remaining = remaining.lstrip()
        if remaining.startswith("--") or remaining.startswith("#"):
            line_end = remaining.find("\n")
            remaining = "" if line_end == -1 else remaining[line_end + 1 :]
            continue
        if remaining.startswith("/*"):
            comment_end = remaining.find("*/", 2)
            if comment_end == -1:
                return ""
            remaining = remaining[comment_end + 2 :]
            continue
        return remaining


def first_keyword(sql: str) -> str:
    """Return the first SQL keyword after leading comments."""
    match = re.match(r"[A-Za-z]+", strip_leading_comments(sql))
    return match.group(0).upper() if match else ""


def parse_params(raw_params: Sequence[str]) -> dict[str, Any]:
    """Parse NAME=JSON_VALUE arguments into SQLAlchemy bind parameters."""
    params: dict[str, Any] = {}
    for raw_param in raw_params:
        name, separator, raw_value = raw_param.partition("=")
        if not separator or not PARAM_NAME_PATTERN.fullmatch(name):
            raise ValueError(f"无效参数 {raw_param!r}; 参数格式必须为 NAME=JSON_VALUE")
        if name in params:
            raise ValueError(f"参数 {name!r} 重复")
        try:
            params[name] = json.loads(raw_value)
        except json.JSONDecodeError:
            params[name] = raw_value
    return params


def load_sql(sql_argument: str | None, file_argument: Path | None) -> str:
    """Load SQL from --sql, --file, or standard input."""
    if sql_argument is not None:
        sql = sql_argument
    elif file_argument is not None:
        try:
            sql = file_argument.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"无法读取 SQL 文件 {file_argument}: {exc}") from exc
    elif not sys.stdin.isatty():
        sql = sys.stdin.read()
    else:
        raise ValueError("请使用 --sql、--file, 或通过标准输入提供 SQL")

    if not sql.strip():
        raise ValueError("SQL 不能为空")
    return sql


def serialize_value(value: Any) -> Any:
    """Convert database-specific values into JSON/CSV-friendly values."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"0x{bytes(value).hex()}"
    return str(value)


def fetch_rows(
    result: CursorResult[Any],
    max_rows: int,
) -> tuple[list[str], list[list[Any]], bool]:
    """Fetch result rows up to max_rows and report whether output was truncated."""
    columns = list(result.keys())
    if max_rows == 0:
        raw_rows = result.fetchall()
        truncated = False
    else:
        raw_rows = result.fetchmany(max_rows + 1)
        truncated = len(raw_rows) > max_rows
        raw_rows = raw_rows[:max_rows]
    rows = [[serialize_value(value) for value in row] for row in raw_rows]
    return columns, rows, truncated


def print_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    output_format: str,
) -> None:
    """Print rows in the requested output format."""
    if output_format == "table":
        print(tabulate(rows, headers=columns, tablefmt="github"))
        return

    records = [dict(zip(columns, row, strict=True)) for row in rows]
    if output_format == "json":
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return
    if output_format == "jsonl":
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
        return

    writer = csv.writer(sys.stdout)
    writer.writerow(columns)
    writer.writerows(rows)


def execute_statement(
    connection: Connection,
    sql: str,
    params: dict[str, Any],
    max_rows: int,
    output_format: str,
) -> tuple[int, bool]:
    """Execute SQL and print any returned rows."""
    result = connection.execute(text(sql), params)
    if not result.returns_rows:
        return result.rowcount, False

    columns, rows, truncated = fetch_rows(result, max_rows)
    print_rows(columns, rows, output_format)
    return len(rows), truncated


def run(args: argparse.Namespace) -> int:
    """Validate arguments, connect to the configured database, and execute SQL."""
    try:
        sql = load_sql(args.sql, args.file)
        params = parse_params(args.param)
    except ValueError as exc:
        print(f"[execute_sql] 参数错误: {exc}", file=sys.stderr)
        return 2

    keyword = first_keyword(sql)
    if not keyword:
        print("[execute_sql] 无法识别 SQL 语句类型", file=sys.stderr)
        return 2
    if keyword not in READ_ONLY_KEYWORDS and not args.apply:
        print(
            f"[execute_sql] 已拒绝执行以 {keyword} 开头的非只读 SQL; 确认影响后请显式添加 --apply",
            file=sys.stderr,
        )
        return 2

    if args.config is not None:
        os.environ["config"] = args.config

    try:
        from bisheng.core.database import sync_get_database_connection

        database = sync_get_database_connection()
        with database.engine.connect() as connection:
            transaction = connection.begin()
            try:
                affected_rows, truncated = execute_statement(
                    connection=connection,
                    sql=sql,
                    params=params,
                    max_rows=args.max_rows,
                    output_format=args.format,
                )
                if args.apply:
                    transaction.commit()
                    transaction_status = "已提交"
                else:
                    transaction.rollback()
                    transaction_status = "只读事务已回滚"
            except Exception:
                transaction.rollback()
                raise
    except (SQLAlchemyError, OSError, ValueError) as exc:
        print(
            f"[execute_sql] 执行失败: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    print(
        f"[execute_sql] 执行成功, 结果行/影响行: {affected_rows}, 事务状态: {transaction_status}",
        file=sys.stderr,
    )
    if truncated:
        print(
            f"[execute_sql] 输出已截断为 {args.max_rows} 行; 使用 --max-rows 0 输出全部结果",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument("--sql", help="要执行的一条 SQL")
    source_group.add_argument(
        "--file",
        type=Path,
        help="包含一条 SQL 的 UTF-8 文件",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="NAME=JSON_VALUE",
        help="绑定参数, 可重复; 非 JSON 值按字符串处理",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "jsonl", "csv"),
        default="table",
        help="结果输出格式 (默认: table)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=1000,
        help="最大输出行数, 0 表示不限制 (默认: 1000)",
    )
    parser.add_argument(
        "--config",
        help="配置文件名或路径 (默认使用环境变量 config 或 config.yaml)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="允许执行并提交写入、DDL 或无法判定为只读的 SQL",
    )
    return parser


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    if args.max_rows < 0:
        parser.error("--max-rows 不能小于 0")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
