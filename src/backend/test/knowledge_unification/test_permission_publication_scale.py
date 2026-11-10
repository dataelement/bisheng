"""Whole actual M2->M3->SQL/FGA publication complexity, not a helper benchmark."""

import json
import time
import tracemalloc

import pytest
import sqlalchemy as sa
from loguru import logger

from bisheng.permission.migration import f118_plan
from test.knowledge_unification.test_permission_publication_application import (
    app,
)
from test.knowledge_unification.test_permission_publication_application import (
    complete as complete,
)
from test.knowledge_unification.test_permission_publication_application import (
    native as native,
)
from test.knowledge_unification.test_permission_publication_application import (
    published_input as published_input,
)
from test.knowledge_unification.test_permission_publication_application import (
    raw_resource_native as raw_resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    resource_native as resource_native,
)
from test.knowledge_unification.test_permission_publication_application import (
    transport as transport,
)


@pytest.mark.parametrize(
    "published_input",
    [
        {"roots": 401},
        {"roots": 10001},
        {"tuples": 401},
        {"tuples": 10001},
        {"models": 401},
        {"models": 1001},
        {"sources": 401},
        {"sources": 10001},
    ],
    indirect=True,
)
async def test_actual_original_entry_linear_resources_tuples_models_sources(published_input, monkeypatch):
    value = published_input
    sql = {"select": 0, "dml": 0, "max_in": 0, "max_bulk": 0, "max_bind": 0}
    counters = {"actions": 0, "models": 0}
    for name, key in (("derive_action_release", "actions"), ("derive_permission_models", "models")):
        original = getattr(f118_plan, name)

        def measure(*args, _key=key, _original=original, **kwargs):
            counters[_key] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(f118_plan, name, measure)

    def capture(connection, cursor, statement, parameters, context, many):
        upper = statement.lstrip().upper()
        if upper.startswith("SELECT"):
            sql["select"] += 1
        elif upper.startswith(("UPDATE", "INSERT", "DELETE")):
            sql["dml"] += 1
        compiled = getattr(context, "compiled", None)
        if compiled is not None:
            for parameter in getattr(compiled, "post_compile_params", ()):
                if isinstance(parameter.value, (list, tuple)):
                    sql["max_in"] = max(sql["max_in"], len(parameter.value))
        if many:
            sql["max_bulk"] = max(sql["max_bulk"], len(parameters))
            sql["max_bind"] = max(sql["max_bind"], max(map(len, parameters), default=0))
        elif isinstance(parameters, (tuple, dict)):
            sql["max_bind"] = max(sql["max_bind"], len(parameters))

    sa.event.listen(value.database.engine.sync_engine, "before_cursor_execute", capture)
    logger.disable("bisheng")
    started = time.perf_counter()
    tracemalloc.start()
    try:
        report = await app(value).arun_permissions(**value.input, operator_id=7)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        logger.enable("bisheng")
        sa.event.remove(value.database.engine.sync_engine, "before_cursor_execute", capture)
    elapsed = time.perf_counter() - started
    assert report.complete
    value.sessions.assert_closed()
    options = value.options
    roots, models, sources = (
        options.get("roots", 1),
        options.get("models", len(value.before.models)),
        options.get("sources", 2),
    )
    assert sql["max_in"] <= 200 and sql["max_bulk"] <= 200
    assert sql["select"] <= 80 * roots + 80 * (sources // 200 + 1) + 40 * (models // 200 + 1) + 1000
    # Catalog compilation and canonical validation remain global, independent of
    # tenant/resource count. One complete entry includes original SQL admission.
    assert counters["actions"] <= 40 and counters["models"] <= 20
    assert value.store.scans == 3
    writes = [
        json.loads(request.content)
        for request in value.store.requests
        if request.method == "POST" and request.url.path.endswith("/write")
    ]
    assert all(
        len(row.get("writes", {}).get("tuple_keys", ())) + len(row.get("deletes", {}).get("tuple_keys", ())) <= 90
        for row in writes
    )
    print(
        {
            **options,
            **sql,
            "derive": counters,
            "full_store_scans": value.store.scans,
            "fga_batches": len(writes),
            "peak_bytes": peak,
            "elapsed_seconds": round(elapsed, 3),
        },
        flush=True,
    )
