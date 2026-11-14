"""T1028: one graph Catalog compile and linear mode summaries, no SQL."""

import tracemalloc
from collections import Counter

import pytest
import sqlalchemy as sa

from bisheng.permission.migration import f118_plan as plans
from test.knowledge_unification import test_migration_permission_inventory as native
from test.knowledge_unification.test_permission_namespace_resource import original as original
from test.knowledge_unification.test_permission_namespace_resource import storage as storage


@pytest.mark.parametrize("count", [401, 10001])
async def test_native_graph_modes_do_not_recompile_catalog_or_keep_all_after_rows(original, monkeypatch, count):
    engine, before_catalog, _ = original
    catalog = native.mapped(before_catalog)
    compiled = plans.ResourceRetirementPlanner(catalog_plan=catalog)
    counters = Counter()
    for name in ("derive_permission_models", "_namespace_applicability"):
        actual = getattr(plans, name)

        def tracked(*args, _actual=actual, _name=name, **kwargs):
            counters[_name] += 1
            return _actual(*args, **kwargs)

        monkeypatch.setattr(plans, name, tracked)
    statements = []

    def capture(_conn, _cursor, sql, _params, _ctx, _many):
        statements.append(sql)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", capture)
    tracemalloc.start()
    try:
        verifier = native.make(catalog)
        native.start(verifier, catalog)
        for ident in range(1, count + 1):
            before = plans.PermissionResourceBaseline(
                101,
                "knowledge_library",
                str(ident),
                plans.ResourceModeBaseline(ident, 101, "knowledge_library", str(ident), "CUSTOM"),
                (),
                (),
                (),
            )
            native.feed(verifier, "baseline", "resources", 101, native.physical(before))
        for ident in range(1, count + 1):
            native.feed(
                verifier,
                "baseline",
                "permission",
                101,
                native.record_from_row(
                    plans.ResourceModeBaseline(ident, 101, "knowledge_library", str(ident), "CUSTOM")
                ),
            )
        for row in (*catalog.after_actions, *catalog.after_models):
            native.feed(verifier, "plan", "catalog", None, native.record_from_row(row))
        for row in native.producer().catalog_namespace_records(compiled):
            native.feed(verifier, "plan", "permission_namespace", None, row)
        for ident in range(1, count + 1):
            mode = plans.ResourceModeBaseline(ident, 101, "knowledge_library", str(ident), "CUSTOM")
            before = plans.PermissionResourceBaseline(101, "knowledge_library", str(ident), mode, (), (), ())
            plan = compiled.build(before=before, namespace_target=native.replace(mode, resource_type="knowledge_space"))
            for section, row in native.producer().namespace_plan_records(plan):
                native.feed(verifier, "plan", section, 101, row)
        verifier.finish()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        sa.event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements == []
    assert counters == {"derive_permission_models": 2, "_namespace_applicability": 2}
    assert verifier._collector is None and verifier._after is None
    assert len(verifier._summaries) == count
    print({"modes": count, "sql": len(statements), "compiles": dict(counters), "peak_bytes": peak})
