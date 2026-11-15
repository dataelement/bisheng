"""§122: native 401/1001 complete models and ANSI/MySQL bounded statements."""

import tracemalloc
from math import ceil

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect

from test.knowledge_unification.test_permission_catalog_write_repository import (
    arguments,
    capture,
    dml,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    module as module,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    prepared as prepared,
)
from test.knowledge_unification.test_permission_catalog_write_repository import (
    session_factory as session_factory,
)


@pytest.mark.parametrize("count", [401, 1001])
async def test_actual_complete_models_have_linear_sql_and_bounded_parameters(prepared, module, count, monkeypatch):
    value = await prepared(count=count)
    writer = module.F118CatalogWriteRepository()
    import bisheng.permission.migration.f118_plan as pure

    derive = pure.derive_permission_models
    calls = 0

    def derive_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return derive(*args, **kwargs)

    monkeypatch.setattr(pure, "derive_permission_models", derive_once)
    statements, remove = capture(value)
    tracemalloc.start()
    try:
        async with value.factory() as session, session.begin():
            result = await writer.astage_catalog(session, **arguments(value))
            assert len(result.models) == count
            assert not session.identity_map
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        remove()
    selects = [row for row in statements if row[0].lstrip().upper().startswith("SELECT")]
    writes = dml(statements)
    assert len(selects) <= 40 + 24 * ceil(count / 200)
    assert len(writes) <= 8 + 3 * ceil(count / 200)
    assert calls <= 4
    assert peak < 32_000_000
    for sql, parameters, context, many in statements:
        assert not any(
            word in sql.lower()
            for word in ("knowledge_file", "space_channel_member", "reference_", "permission_grant", "visible_source")
        )
        if many:
            assert len(parameters) <= 200
        if context.compiled is None:
            continue
        statement = context.compiled.statement
        for dialect in (mysql.dialect(), DefaultDialect()):
            compiled = statement.compile(dialect=dialect)
            assert "RETURNING" not in str(compiled).upper()
        for value in context.compiled.params.values():
            if isinstance(value, (list, tuple)):
                assert len(value) <= 200
    print(
        f"CATALOG native M={count} SELECT={len(selects)} DML={len(writes)} derive={calls} peak={peak} maxWriteBatch={max((len(p) for _, p, _, many in writes if many), default=1)}"
    )
