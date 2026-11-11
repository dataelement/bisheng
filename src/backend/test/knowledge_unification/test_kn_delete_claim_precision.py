"""Exercise immediate confirmed deletion across MySQL DATETIME(0) rounding."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from bisheng.knowledge.domain.models import knowledge_space_delete_job as model
from bisheng.knowledge.domain.schemas.processing_job import ProcessingCreateRequest
from test.knowledge_unification import test_kn_delete_plan as native

deletion_tenant, db, context, service, application = (
    native.deletion_tenant,
    native.db,
    native.context,
    native.service,
    native.application,
)


@pytest.mark.parametrize("microsecond", [100000, 500000, 900000])
async def test_confirm_claims_immediately_after_native_second_precision_rounding(
    application, context, monkeypatch, microsecond
):
    instant = datetime.now(UTC).replace(microsecond=microsecond)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return instant

    monkeypatch.setattr(model, "datetime", FixedDatetime)
    # MySQL without TIME_TRUNCATE_FRACTIONAL rounds fractional DATETIME writes.
    # SQLite otherwise preserves microseconds and misses the initial-claim bug.
    async with context.db.engine.begin() as connection:
        await connection.execute(
            text("""
            CREATE TRIGGER native_delete_due_second_precision
            AFTER INSERT ON knowledge_space_delete_job
            BEGIN
              UPDATE knowledge_space_delete_job
              SET next_attempt_at = datetime(
                NEW.next_attempt_at,
                CASE WHEN CAST(substr(NEW.next_attempt_at, 21, 6) AS INTEGER) >= 500000
                  THEN '+1 second' ELSE '+0 seconds' END
              )
              WHERE id = NEW.id;
            END
        """)
        )
    plan = await application.aprecheck(identity=application.user, space_id=2, operation="knowledge_space_clear")
    result = await application.aconfirm(
        identity=application.user,
        space_id=2,
        request=ProcessingCreateRequest(
            confirmation_id=plan.confirmation_id,
            plan_digest=plan.plan_digest,
            idempotency_key="first-native-claim",
        ),
    )
    assert result["state"] == "succeeded" and not result["accepted"]
    async with context.db.sessions() as session:
        job = await session.get(model.KnowledgeSpaceDeleteJob, plan.confirmation_id)
        assert job.attempts == 1
        assert job.business_phase == "finalized"
        assert job.completed_steps == ["fga", "minio", "es", "milvus"]
        assert job.last_error is None and job.lease_until is None
    application.permission_runtime.project_delete.assert_not_awaited()
