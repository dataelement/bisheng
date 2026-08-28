"""Compare DM8 catalog metadata with SQLAlchemy column reflection.

This script is read-only. It helps diagnose cases where DaMeng reports that a
column already exists while ``Inspector.get_columns()`` or BiSheng's shared
``column_exists()`` helper reports that it is missing.

Run it inside an API or worker container from ``/app`` using the same ``config``
environment variable as the running service:

    cd /app
    /app/.venv/bin/python scripts/diagnose_dm_column_reflection.py

The default target is ``knowledge.metadata_fields``. Use ``--table``,
``--column``, or ``--schema`` to inspect a different object.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import inspect, text  # noqa: E402

from bisheng.core.database.dialect_helpers import column_exists  # noqa: E402
from bisheng.core.database.manager import sync_get_database_connection  # noqa: E402


def _stringify(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _serializable_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [{str(key).lower(): _stringify(value) for key, value in row.items()} for row in rows]


def _safe_query(connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = connection.execute(text(sql), params or {}).mappings().all()
        return {"ok": True, "rows": _serializable_rows(result)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _url_schema(engine) -> str | None:
    schema = engine.url.query.get("schema")
    if isinstance(schema, (tuple, list)):
        return str(schema[0]) if schema else None
    return str(schema) if schema else None


def _unique(values: list[str | None]) -> list[str | None]:
    result: list[str | None] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _column_payload(column: dict[str, Any]) -> dict[str, Any]:
    name = _stringify(column.get("name"))
    return {
        "name": name,
        "name_length": len(name) if isinstance(name, str) else None,
        "type": _stringify(column.get("type")),
        "nullable": _stringify(column.get("nullable")),
        "default": _stringify(column.get("default")),
        "comment": _stringify(column.get("comment")),
    }


def _inspect_columns(connection, table: str, schema: str | None) -> dict[str, Any]:
    try:
        inspector = inspect(connection)
        columns = inspector.get_columns(table, schema=schema)
        return {
            "ok": True,
            "has_table": inspector.has_table(table, schema=schema),
            "columns": [_column_payload(column) for column in columns],
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _inspector_found(attempts: list[dict[str, Any]], column: str, *, schema_required: bool | None = None) -> bool:
    needle = column.casefold()
    for attempt in attempts:
        schema = attempt["schema"]
        if schema_required is True and schema is None:
            continue
        if schema_required is False and schema is not None:
            continue
        result = attempt["result"]
        if not result.get("ok"):
            continue
        names = {str(item.get("name", "")).strip().casefold() for item in result.get("columns", [])}
        if needle in names:
            return True
    return False


def diagnose(table: str, column: str, schema_override: str | None) -> tuple[int, dict[str, Any]]:
    manager = sync_get_database_connection()
    engine = manager.engine
    schema = schema_override or _url_schema(engine)
    report: dict[str, Any] = {
        "read_only": True,
        "target": {"schema": schema, "table": table, "column": column},
        "connection": {
            "dialect": engine.dialect.name,
            "url": engine.url.render_as_string(hide_password=True),
        },
    }

    try:
        with engine.connect() as connection:
            report["session"] = {
                "login_user": _safe_query(connection, "SELECT USER AS LOGIN_USER FROM DUAL"),
                "current_schema_sys_context": _safe_query(
                    connection,
                    "SELECT SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS CURRENT_SCHEMA FROM DUAL",
                ),
                "current_schema_keyword": _safe_query(
                    connection,
                    "SELECT CURRENT_SCHEMA AS CURRENT_SCHEMA FROM DUAL",
                ),
            }

            catalog_sql = """
                SELECT OWNER, TABLE_NAME, COLUMN_ID, COLUMN_NAME,
                       DATA_TYPE, DATA_LENGTH, NULLABLE
                  FROM SYS.ALL_TAB_COLUMNS
                 WHERE UPPER(TABLE_NAME) = UPPER(:table_name)
                   AND UPPER(COLUMN_NAME) = UPPER(:column_name)
            """
            catalog_params: dict[str, Any] = {
                "table_name": table,
                "column_name": column,
            }
            if schema:
                catalog_sql += " AND UPPER(OWNER) = UPPER(:owner)"
                catalog_params["owner"] = schema
            catalog_sql += " ORDER BY OWNER, TABLE_NAME, COLUMN_ID"

            table_sql = """
                SELECT OWNER, TABLE_NAME
                  FROM SYS.ALL_TABLES
                 WHERE UPPER(TABLE_NAME) = UPPER(:table_name)
            """
            table_params: dict[str, Any] = {"table_name": table}
            if schema:
                table_sql += " AND UPPER(OWNER) = UPPER(:owner)"
                table_params["owner"] = schema
            table_sql += " ORDER BY OWNER, TABLE_NAME"

            report["dm_catalog"] = {
                "matching_tables": _safe_query(connection, table_sql, table_params),
                "matching_column": _safe_query(connection, catalog_sql, catalog_params),
            }

            attempts: list[dict[str, Any]] = []
            table_candidates = _unique([table, table.upper(), table.lower()])
            schema_candidates = _unique(
                [None, schema, schema.upper() if schema else None, schema.lower() if schema else None]
            )
            for schema_candidate in schema_candidates:
                for table_candidate in table_candidates:
                    attempts.append(
                        {
                            "schema": schema_candidate,
                            "table": table_candidate,
                            "result": _inspect_columns(connection, table_candidate, schema_candidate),
                        }
                    )
            report["sqlalchemy_inspector"] = attempts

            try:
                helper_result = column_exists(connection, table, column)
                report["bisheng_column_exists"] = {"ok": True, "value": helper_result}
            except Exception as exc:
                helper_result = False
                report["bisheng_column_exists"] = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        catalog_result = report["dm_catalog"]["matching_column"]
        catalog_found = bool(catalog_result.get("ok") and catalog_result.get("rows"))
        inspector_without_schema = _inspector_found(attempts, column, schema_required=False)
        inspector_with_schema = _inspector_found(attempts, column, schema_required=True)

        if not catalog_found:
            exit_code = 3
            verdict = "CATALOG_COLUMN_NOT_FOUND"
        elif helper_result:
            exit_code = 0
            verdict = "REFLECTION_OK"
        elif inspector_with_schema and not inspector_without_schema:
            exit_code = 2
            verdict = "SCHEMA_REQUIRED_BUT_HELPER_OMITS_SCHEMA"
        else:
            exit_code = 2
            verdict = "REFLECTION_FALSE_NEGATIVE_CONFIRMED"

        report["summary"] = {
            "verdict": verdict,
            "catalog_found": catalog_found,
            "inspector_found_without_schema": inspector_without_schema,
            "inspector_found_with_schema": inspector_with_schema,
            "bisheng_column_exists": helper_result,
            "exit_code": exit_code,
        }
        return exit_code, report
    finally:
        manager.close_sync()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", default="knowledge", help="Table name to inspect (default: knowledge).")
    parser.add_argument(
        "--column",
        default="metadata_fields",
        help="Column name to inspect (default: metadata_fields).",
    )
    parser.add_argument(
        "--schema",
        help="DM owner/schema override. Defaults to the schema query parameter in database_url.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        exit_code, report = diagnose(args.table, args.column, args.schema)
    except Exception as exc:
        report = {
            "read_only": True,
            "summary": {
                "verdict": "DIAGNOSTIC_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
                "exit_code": 4,
            },
        }
        exit_code = 4
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
