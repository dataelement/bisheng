"""T991: retry reads compact facts and one scalar reset set, without full payloads."""

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect

from test.knowledge_unification.test_move_job_retry import accepted as accepted
from test.knowledge_unification.test_move_job_retry import actual_processing_task as actual_processing_task
from test.knowledge_unification.test_move_job_retry import fail, pipeline, retry_args
from test.knowledge_unification.test_move_job_retry import job_tenant as job_tenant
from test.knowledge_unification.test_move_job_retry import moving as moving
from test.knowledge_unification.test_move_job_retry import store as store
from test.knowledge_unification.test_move_job_retry import tenant as tenant


@pytest.mark.parametrize("count", [401, 10001])
async def test_retry_never_reads_large_snapshot_or_expires_read_projection_manifest(
    moving, accepted, monkeypatch, actual_processing_task, count
):
    built = await pipeline(moving, accepted, monkeypatch, count=count)
    async with built.sessions() as session, session.begin():
        failed = await fail(session, built)
        revision = failed.revision
        public = await built.repo.aget(session, built.job_id)
        original_manifest = public.scope_manifest
        statements = []

        def capture(_c, _cu, sql, _params, _ctx, _many):
            statements.append(sql)

        sa.event.listen(moving.engine.sync_engine, "before_cursor_execute", capture)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("retry must not recompile a complete acceptance scope")

        monkeypatch.setattr(type(built.move), "_projection", staticmethod(forbidden))
        monkeypatch.setattr(built.cutover, "_position", forbidden)
        eligibility = await built.repo.aretry_eligibility(session, built.job_id)
        assert eligibility.retryable and not eligibility.finalize_only
        assert public.scope_manifest is original_manifest and "scope_manifest" not in inspect(public).unloaded
        result = await built.repo.aretry_failed(session, built.job_id, **retry_args(revision))
        assert result.job.total_count == result.job.pending_count == count
        selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(selects) <= 10
        assert all("processing_snapshot" not in sql.partition("FROM")[0] for sql in selects)
        assert all("scope_manifest" not in sql.partition("FROM")[0] for sql in selects)
        assert all("knowledge_operation_plan" not in sql for sql in selects)
        print({"items": count, "retry_selects": len(selects), "snapshot_or_manifest_selects": 0})
