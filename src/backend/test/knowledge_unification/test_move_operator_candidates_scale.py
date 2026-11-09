"""Outer paging of actual candidate SQL is one bounded scalar SELECT per page."""

import math

import pytest
import sqlalchemy as sa
from sqlalchemy.sql import operators, visitors

from test.knowledge_unification import test_move_operator_candidates as candidates

database = candidates.database


@pytest.mark.parametrize("count", [401, 10001])
@pytest.mark.parametrize("sparse", [False, True])
async def test_outer_paging_uses_exact_keys_and_linear_scalar_sql(database, count, sparse, record_property):
    ids = tuple(range(count, 0, -1))
    present = {ident for ident in ids if not sparse or ident % 3 == 0}
    await candidates.insert(database, [candidates.row(ident, operator=ident + 100) for ident in present])
    captured = []

    def capture(connection, cursor, sql, parameters, context, many):
        captured.append((context.compiled.statement, parameters, dict(context.compiled_parameters[0])))

    sa.event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
    bridge = candidates.api().KnowledgeMoveProjectionApplication(repository=candidates.repository())
    result = []
    async with database.sessions() as session, session.begin():
        for offset in range(0, count, 200):
            page = ids[offset : offset + 200]
            before = len(captured)
            result.extend(
                await bridge.alist_operator_candidates(
                    session,
                    job_id=candidates.native.JOB,
                    targets=tuple(("knowledge_file", str(ident)) for ident in page),
                )
            )
            assert len(captured) == before + 1
            statement, parameters, bindings = captured[-1]
            assert statement.is_select and len(statement.get_final_froms()) == 1
            assert statement.get_final_froms()[0].name == "permission_projection_operation"
            assert set(statement.selected_columns.keys()) == {
                "id",
                "tenant_id",
                "idempotency_key",
                "operation_type",
                "scope_type",
                "scope_key",
                "operator_id",
            }
            predicates = list(visitors.iterate(statement.whereclause))
            assert any(
                isinstance(p, sa.sql.elements.BinaryExpression)
                and getattr(p.left, "name", None) == "tenant_id"
                and p.operator is operators.eq
                and p.right.value == 101
                for p in predicates
            )
            assert any(
                isinstance(p, sa.sql.elements.BinaryExpression)
                and getattr(p.left, "name", None) == "idempotency_key"
                and p.operator is operators.in_op
                for p in predicates
            )
            # Compiled statements may be cached from a prior page. Check the
            # actual execution bindings, never the cached IN node's old value.
            assert {value for value in bindings.values() if type(value) is str} == {
                candidates.native.api().operation_key(candidates.native.JOB, "knowledge_file", ident) for ident in page
            }
            assert {value for value in bindings.values() if type(value) is int} == {101}
            assert len(parameters) <= 201
    assert [(int(r.resource_id), r.operator_id) for r in result] == [
        (ident, ident + 100) for ident in ids if ident in present
    ]
    assert len(captured) == math.ceil(count / 200)
    record_property("native_targets", count)
    record_property("native_candidate_selects", len(captured))
    print(
        f"candidate targets={count} sparse={sparse} selects={len(captured)} max_parameters={max(len(p) for _, p, _ in captured)}"
    )
