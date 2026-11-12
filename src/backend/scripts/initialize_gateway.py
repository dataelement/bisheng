#!/usr/bin/env python3
"""Initialize the bundled Gateway SQL contract, or verify a matching schema.

No root access or migration of unknown nonempty databases. Matching versioned
SQL and image are selected by the release image-set, not guessed at startup.
"""

import argparse
import re
from pathlib import Path

import pymysql
from initialize_mysql import wait_connection


def expected_schema(sql):
    result = {}
    for name, block in re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\n\);", sql, re.S | re.I):
        columns = {}
        for line in block.splitlines():
            match = re.match(r"\s*(\w+)\s+(INT|BIGINT|TINYINT|VARCHAR\(\d+\)|TEXT|DATETIME)(?=\s|,|$)", line, re.I)
            if match:
                columns[match[1]] = match[2].upper()
        result[name] = columns
    if not result or any(not value for value in result.values()):
        raise ValueError("Gateway SQL contract is invalid")
    return result


def initialize(connection, sql, *, verify_only=False):
    expected = expected_schema(sql)
    with connection.cursor() as cursor:
        cursor.execute("SHOW TABLES")
        names = {row[0] for row in cursor.fetchall()}
        if names:
            if names != set(expected):
                raise RuntimeError("Nonempty Gateway schema needs explicit version upgrade")
            for name, columns in expected.items():
                cursor.execute(f"SHOW COLUMNS FROM `{name}`")
                actual = {row[0]: row[1].upper().replace("INTEGER", "INT") for row in cursor.fetchall()}
                normalized = {
                    key: re.sub(r"^(INT|BIGINT|TINYINT)\(\d+\)", r"\1", value) for key, value in actual.items()
                }
                if normalized != columns:
                    raise RuntimeError("Gateway schema does not match the bundled version")
            return True
        if verify_only:
            return False
        statements = re.sub(r"(?m)^\s*--.*$", "", sql).split(";")
        for statement in statements:
            statement = statement.strip()
            if statement.upper().startswith("CREATE TABLE"):
                cursor.execute(statement)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--database", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--sql", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--wait-only", action="store_true")
    args = parser.parse_args()
    connection = wait_connection(
        args.host, args.port, args.username, Path(args.password_file).read_text(), args.database, args.timeout
    )
    try:
        sql = Path(args.sql).read_text()
        if args.wait_only:
            import time

            deadline = time.monotonic() + args.timeout
            while True:
                if initialize(connection, sql, verify_only=True):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Gateway schema initialization did not complete")
                time.sleep(2)
        else:
            initialize(connection, sql)
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, pymysql.Error):
        raise SystemExit(
            "Gateway initialization refused; inspect the matching SQL/image contract and dedicated database"
        ) from None
