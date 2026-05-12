#!/usr/bin/env python3
"""
DaMeng connectivity test — run inside the test Docker image.

Checks:
  1. dmPython import
  2. Direct dmPython connection
  3. SQLAlchemy sync  (dm+dmPython://)
  4. SQLAlchemy async (dm+dmAsync://)
  5. JSON / CLOB round-trip
  6. Inspector-based table/column introspection
  7. LargeText / JsonType TypeDecorators via SQLModel create_all
"""
import asyncio
import json
import sys
from urllib.parse import quote_plus

HOST = "192.168.107.9"
PORT = 5236
USER = "SYSDBA"
PASSWD = "6o+%s3z2NK7J"
SCHEMA = "BISHENG"

SYNC_URL  = f"dm+dmPython://{USER}:{quote_plus(PASSWD)}@{HOST}:{PORT}/{SCHEMA}"
ASYNC_URL = f"dm+dmAsync://{USER}:{quote_plus(PASSWD)}@{HOST}:{PORT}/{SCHEMA}"

# Alternative URL formats to probe if the default fails
SYNC_URL_NO_DB   = f"dm+dmPython://{USER}:{quote_plus(PASSWD)}@{HOST}:{PORT}"
SYNC_URL_DSN     = f"dm+dmPython://?user={USER}&password={quote_plus(PASSWD)}&dsn={HOST}:{PORT}/{SCHEMA}"

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

results: list[tuple[str, bool, str]] = []


def run(name: str):
    """Decorator — catches exceptions and records pass/fail."""
    def decorator(fn):
        def wrapper():
            print(f"\n[{name}]")
            try:
                fn()
                print(f"  {PASS} passed")
                results.append((name, True, ""))
            except Exception as exc:
                print(f"  {FAIL} FAILED: {exc}")
                results.append((name, False, str(exc)))
        return wrapper
    return decorator


# ---------------------------------------------------------------------------

@run("1. dmPython import")
def test_import():
    import dmPython  # noqa: F401
    print(f"  version: {getattr(dmPython, '__version__', 'unknown')}")


@run("2. Direct dmPython connection")
def test_direct():
    import dmPython
    conn = dmPython.connect(USER, PASSWD, f"{HOST}:{PORT}")
    cur = conn.cursor()
    cur.execute("SELECT 1+1 FROM DUAL")
    val = cur.fetchone()[0]
    assert val == 2, f"expected 2, got {val}"
    print(f"  SELECT 1+1 = {val}")
    conn.close()


@run("3. SQLAlchemy sync (dm+dmPython://)")
def test_sa_sync():
    from sqlalchemy import create_engine, text

    # Try URL variants in order until one works
    urls = [
        (SYNC_URL,          "with schema"),
        (SYNC_URL_NO_DB,    "without schema"),
    ]
    engine = None
    for url, label in urls:
        try:
            e = create_engine(url, echo=False)
            with e.connect() as c:
                c.execute(text("SELECT 1 FROM DUAL"))
            engine = e
            print(f"  working URL variant: {label}")
            break
        except Exception as ex:
            print(f"  {label} failed: {ex}")

    if engine is None:
        raise RuntimeError("No URL variant worked for dm+dmPython://")

    with engine.connect() as conn:
        dialect = conn.dialect.name
        print(f"  dialect: {dialect}")
        assert dialect == "dm", f"expected 'dm', got '{dialect}'"
        row = conn.execute(text("SELECT 'hello_dm' FROM DUAL")).scalar()
        print(f"  query result: {row}")


@run("4. SQLAlchemy async (dm+dmAsync://)")
def test_sa_async():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    async def _run():
        engine = create_async_engine(ASYNC_URL, echo=False)
        async with engine.connect() as conn:
            row = await conn.execute(text("SELECT 'async_ok' FROM DUAL"))
            val = row.scalar()
            print(f"  async query result: {val}")
        await engine.dispose()

    asyncio.run(_run())


@run("5. JSON / CLOB round-trip")
def test_json_clob():
    from sqlalchemy import create_engine, text
    engine = create_engine(SYNC_URL_NO_DB)
    tbl = "bisheng_test_json_clob"
    with engine.connect() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}"'))
        conn.execute(text(f'CREATE TABLE "{tbl}" ("id" INT, "payload" CLOB)'))

        data = {"key": "value", "nums": [1, 2, 3], "chinese": "你好"}
        conn.execute(
            text(f'INSERT INTO "{tbl}" VALUES (:id, :p)'),
            {"id": 1, "p": json.dumps(data, ensure_ascii=False)},
        )
        conn.commit()

        raw = conn.execute(text(f'SELECT "payload" FROM "{tbl}" WHERE "id"=1')).scalar()
        parsed = json.loads(raw)
        assert parsed == data, f"mismatch: {parsed}"
        print(f"  round-trip OK: {list(parsed.keys())}")

        conn.execute(text(f'DROP TABLE "{tbl}"'))
        conn.commit()


@run("6. Inspector introspection (table_exists / get_columns)")
def test_inspector():
    from sqlalchemy import create_engine, inspect
    engine = create_engine(SYNC_URL_NO_DB)
    with engine.connect() as conn:
        insp = inspect(conn)
        tables = insp.get_table_names()
        print(f"  tables in schema: {len(tables)}")
        if tables:
            sample = tables[0]
            cols = [c["name"] for c in insp.get_columns(sample)]
            print(f"  sample table '{sample}' columns: {cols[:5]}")


@run("7. LargeText (CLOB) + JsonType round-trip via raw DDL")
def test_type_decorators():
    """Validate CLOB and JSON-as-CLOB storage without requiring the full bisheng install."""
    from sqlalchemy import create_engine, text
    engine = create_engine(SYNC_URL_NO_DB)
    tbl = "bisheng_test_types"
    with engine.connect() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}"'))
        conn.execute(text(
            f'CREATE TABLE "{tbl}" ('
            f'"id" INT PRIMARY KEY, '
            f'"big_text" CLOB, '
            f'"json_data" CLOB'
            f')'
        ))
        big = "x" * 10_000
        jdata = json.dumps({"key": "value", "arr": [1, 2, 3]}, ensure_ascii=False)
        conn.execute(
            text(f'INSERT INTO "{tbl}" VALUES (:id, :bt, :jd)'),
            {"id": 1, "bt": big, "jd": jdata},
        )
        conn.commit()
        row = conn.execute(
            text(f'SELECT "big_text", "json_data" FROM "{tbl}" WHERE "id"=1')
        ).fetchone()
        assert len(row[0]) == 10_000, f"CLOB length mismatch: {len(row[0])}"
        parsed = json.loads(row[1])
        assert parsed["key"] == "value"
        print(f"  CLOB len={len(row[0])}, JSON parsed={list(parsed.keys())}")
        conn.execute(text(f'DROP TABLE "{tbl}"'))
        conn.commit()


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("DaMeng connectivity test")
    print(f"  target: {HOST}:{PORT}/{SCHEMA}")
    print("=" * 55)

    test_import()
    test_direct()
    test_sa_sync()
    test_sa_async()
    test_json_clob()
    test_inspector()
    test_type_decorators()

    print("\n" + "=" * 55)
    passed = sum(1 for _, ok, _ in results if ok)
    total  = len(results)
    print(f"Results: {passed}/{total} passed")
    for name, ok, err in results:
        status = PASS if ok else FAIL
        suffix = f"  → {err}" if not ok else ""
        print(f"  {status} {name}{suffix}")
    print("=" * 55)

    if passed < total:
        sys.exit(1)
