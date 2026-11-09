"""§123 complete candidate validation, bounded RRT batches and portable SQL."""

from math import ceil

import pytest
from sqlalchemy import delete, event
from sqlalchemy.dialects import mysql
from sqlalchemy.engine.default import DefaultDialect

from test.knowledge_unification import test_target_deletion_controls as controls
from test.knowledge_unification import test_target_deletion_native as native

model_owner_tenant = native.model_owner_tenant
built = native.built


@pytest.mark.parametrize("count", [401, 10001])
async def test_real_model_owner_scope_has_linear_rrt_reads_and_bounded_core_writes(built, monkeypatch, count):
    rt = native.runtime(built)
    async with built.sessions() as session:
        await native.caller(session)
        ids = await controls.add_models(session, count)
        async with session.begin_nested():
            issued = await native.receipts(built, session, *(("model", ident) for ident in ids))
            validate, visits = built.verifier.validate_owner_receipts, []

            def checked(active, values):
                visits.append(len(values))
                return validate(active, values)

            monkeypatch.setattr(built.verifier, "validate_owner_receipts", checked)
            statements, stop = native.count_sql(built.engine)
            clauses = []

            def clause(_conn, statement, _multiparams, _params, _options):
                clauses.append(statement)

            event.listen(built.engine.sync_engine, "before_execute", clause)
            try:
                assert (
                    await rt.aprepare_target_deletion(
                        session,
                        receipts=issued,
                        operation_id="scale",
                        operation_type="model_delete_server",
                        actor=native.ACTOR,
                    )
                    == count
                )
            finally:
                stop()
                event.remove(built.engine.sync_engine, "before_execute", clause)
            native.no_source_sql(statements)
            reads = [row for row in statements if "FROM resource_reference_tombstone" in row[0]]
            inserts = [
                row for row in statements if row[0].upper().startswith("INSERT INTO RESOURCE_REFERENCE_TOMBSTONE")
            ]
            assert len(reads) == len(inserts) == ceil(count / 200)
            assert max(len(params) for _, params, _ in reads) <= 202
            assert [len(params) if many else 1 for _, params, many in inserts] == [
                min(200, count - offset) for offset in range(0, count, 200)
            ]
            assert len(visits) <= 8 and sum(visits) <= 8 * count
            assert sum(visits) >= 2 * count
            for statement in clauses:
                for dialect in (mysql.dialect(), DefaultDialect()):
                    sql = str(statement.compile(dialect=dialect)).upper()
                    assert "ON DUPLICATE" not in sql and "ON CONFLICT" not in sql and "CAST(" not in sql
            prepare_visits = tuple(visits)
            visits.clear()
            await session.execute(
                delete(native.LLMModel).where(native.LLMModel.server_id == 1, native.LLMModel.tenant_id == 101)
            )
            statements, stop = native.count_sql(built.engine)
            try:
                assert (
                    await rt.afinalize_target_deletion(
                        session,
                        receipts=issued,
                        operation_id="scale",
                        operation_type="model_delete_server",
                        actor=native.ACTOR,
                    )
                    == count
                )
            finally:
                stop()
            native.no_source_sql(statements)
            reads = [row for row in statements if "FROM resource_reference_tombstone" in row[0]]
            updates = [row for row in statements if row[0].upper().startswith("UPDATE RESOURCE_REFERENCE_TOMBSTONE")]
            assert len(reads) == len(updates) == ceil(count / 200)
            assert [len(params) if many else 1 for _, params, many in updates] == [
                min(200, count - offset) for offset in range(0, count, 200)
            ]
            assert len(visits) <= 8 and sum(visits) <= 8 * count
            assert all(
                "tenant_id" in sql
                and "target_tenant_id" in sql
                and "target_type" in sql
                and "target_id" in sql
                and "operation_id" in sql
                and "stage" in sql
                for sql, _, _ in updates
            )
            print(
                {
                    "targets": count,
                    "rrt_reads_per_phase": len(reads),
                    "write_batches_per_phase": len(updates),
                    "prepare_validations": prepare_visits,
                    "finalize_validations": visits,
                    "read_parameter_peak": max(len(params) for _, params, _ in reads),
                    "source_brr_sql": 0,
                }
            )


async def test_runtime_constructor_stays_zero_io_and_preserves_two_position_arguments(built):
    statements, stop = native.count_sql(built.engine)
    try:
        result = native.ReferenceBindingRuntime(built.references, built.verifier)
        assert result.repository is built.references and result.verifier is built.verifier
        assert result.target_deletions.repository is built.references
    finally:
        stop()
    assert statements == []
