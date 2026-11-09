"""§119 native target/slot scaling, real SQL bindings and validation counts."""

import math

import pytest
import sqlalchemy as sa

from test.knowledge_unification import test_move_reference_ownership as base
from test.knowledge_unification.test_move_execution_fixtures import logical, pipeline

store, tenant, moving, accepted = base.store, base.tenant, base.moving, base.accepted


@pytest.mark.parametrize("count", [401, 10001])
@pytest.mark.parametrize("slots", [1, 3])
async def test_full_scope_linear_sql_and_no_full_scope_validation_per_slot_page(
    moving, accepted, monkeypatch, count, slots
):
    built = await pipeline(moving, accepted, monkeypatch, count=count - 2)
    ids = tuple(row.file_id for row in built.confirmed.scope.files)
    assert len(ids) == count
    # Two different real sources, multiple slots per exact target, without a Source by Target scan.
    rows = [
        base.binding(n + 1, file_id, source_id=f"source-{slot % 2}")
        for n, (file_id, slot) in enumerate((ident, slot) for ident in ids for slot in range(slots))
    ]
    await base.seed(built, rows=rows)
    rt = base.compose(built)
    counts = {"scope": 0, "owner_receipts": 0, "logical": 0, "peak_page": 0}
    original_scope = rt.repo._check_scope
    original_receipts = rt.runtime.verifier.validate_owner_receipts
    original_logical = built.cutover.assert_logical_current
    original_page = rt.repo._inbound_owner_rows

    def checked_scope(*args, **kwargs):
        counts["scope"] += 1
        return original_scope(*args, **kwargs)

    def checked_receipts(*args, **kwargs):
        counts["owner_receipts"] += 1
        return original_receipts(*args, **kwargs)

    def checked_logical(*args, **kwargs):
        counts["logical"] += 1
        return original_logical(*args, **kwargs)

    def checked_page(rows):
        page = original_page(rows)
        counts["peak_page"] = max(counts["peak_page"], len(page))
        return page

    monkeypatch.setattr(rt.repo, "_check_scope", checked_scope)
    monkeypatch.setattr(rt.runtime.verifier, "validate_owner_receipts", checked_receipts)
    monkeypatch.setattr(built.cutover, "assert_logical_current", checked_logical)
    monkeypatch.setattr(rt.repo, "_inbound_owner_rows", checked_page)
    sql = []

    def capture(connection, cursor, statement, parameters, context, many):
        sql.append((statement, parameters, context.compiled))

    async with built.sessions() as session, session.begin():
        async with session.begin_nested():
            receipt = await logical(session, built)
            engine = session.bind.sync_engine
            sa.event.listen(engine, "before_cursor_execute", capture)
            try:
                assert (
                    await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime)
                    == slots * count
                )
            finally:
                sa.event.remove(engine, "before_cursor_execute", capture)
    updates = [row for row in sql if row[0].startswith("UPDATE business_resource_reference")]
    reads = [row for row in sql if row[0].startswith("SELECT")]
    assert counts == {"scope": 6, "owner_receipts": 10, "logical": 2, "peak_page": 200}
    assert len(sql) <= 20 + 40 * math.ceil(count / 200)
    assert max(len(params) for _, params, _ in sql) <= 406
    for _statement, _parameters, compiled in sql:
        for values in (compiled.params or {}).values():
            if isinstance(values, (tuple, list)):
                assert len(values) <= 200
    assert max(len(params) for _, params, _ in updates) <= 406
    assert len(updates) >= math.ceil(slots * count / 200)
    for _statement, _parameters, compiled in updates:
        # Compare compiled WHERE expression, not merely a substring appearing in SET.
        where = compiled.statement.whereclause
        columns = {node.name for node in sa.sql.visitors.iterate(where) if isinstance(node, sa.Column)}
        assert {"id", "tenant_id", "target_tenant_id", "target_type", "target_id", "target_space_id"} <= columns
        assert set(compiled.statement._values) == {"target_space_id"}
    assert not any("record_kind = 'root_guard'" in text for text, _, _ in sql)
    assert all(
        "source_revision" in statement for statement, _, _ in reads if "JOIN business_reference_set" in statement
    )
    initial_counts = counts.copy()
    # A second call must execute the checks but no UPDATE even with many slots.
    rt = base.compose(built)
    async with built.sessions() as session, session.begin():
        receipt = await logical(session, built)
        sql.clear()
        sa.event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            assert await rt.owner.amove_file_ownership(session, logical=receipt, reference_runtime=rt.runtime) == 0
        finally:
            sa.event.remove(session.bind.sync_engine, "before_cursor_execute", capture)
    assert not any(statement.startswith("UPDATE") for statement, _, _ in sql)
    print(
        dict(
            count=count,
            slots=slots * count,
            selects=len(reads),
            updates=len(updates),
            max_params=max(len(params) for _, params, _ in reads + updates),
            **initial_counts,
        )
    )
