#!/usr/bin/env python3
"""Initialize dedicated schemas/users in this Chart's own MySQL instance only.

External databases are operator-provisioned and never receive root credentials.
SQL identifiers are constrained; account/password values are driver parameters.
"""

import argparse
import json
import re
import time
from pathlib import Path

import pymysql


def wait_connection(host, port, username, password, database, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return pymysql.connect(
                host=host,
                port=port,
                user=username,
                password=password,
                database=database,
                connect_timeout=3,
                read_timeout=5,
                write_timeout=5,
                charset="utf8mb4",
                autocommit=True,
            )
        except pymysql.Error:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    raise RuntimeError("Timed out waiting for the configured MySQL database/account")


def initialize(connection, databases):
    with connection.cursor() as cursor:
        for binding in databases:
            name, username = binding["name"], binding["username"]
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,31}", username
            ):
                raise ValueError("Database/user identifier is invalid")
            password = Path(binding["password_file"]).read_text()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci")
            cursor.execute("CREATE USER IF NOT EXISTS %s@'%%' IDENTIFIED BY %s", (username, password))
            cursor.execute(f"GRANT ALL PRIVILEGES ON `{name}`.* TO %s@'%%'", (username,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--database")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--schemas", help="Only set in the owned MySQL initializer Job")
    args = parser.parse_args()
    connection = wait_connection(
        args.host, args.port, args.username, Path(args.password_file).read_text(), args.database, args.timeout
    )
    try:
        if args.schemas:
            initialize(connection, json.loads(Path(args.schemas).read_text()))
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, pymysql.Error):
        raise SystemExit(
            "MySQL initialization/wait failed; check the dedicated database, credentials and Job configuration"
        ) from None
