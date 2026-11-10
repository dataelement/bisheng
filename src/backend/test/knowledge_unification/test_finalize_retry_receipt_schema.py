"""T660: a real zero-item finalize retry receipt retains identity/revision CHECKs."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt


@pytest.fixture
def receipts(tenant_context):
    tenant_context(101)
    engine = create_engine("sqlite://")
    KnowledgeProcessingRetryReceipt.__table__.create(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def row(**changes):
    return KnowledgeProcessingRetryReceipt(
        **{
            "tenant_id": 101,
            "actor_user_id": 7,
            "job_id": "one",
            "idempotency_key": "retry",
            "request_hash": "a" * 64,
            "actor_reference": {"user_id": 7},
            "expected_job_revision": 2,
            "accepted_job_revision": 3,
            "item_count": 0,
            **changes,
        }
    )


def test_zero_item_receipt_is_real_zero_not_a_fake_one(receipts):
    value = row()
    receipts.add(value)
    receipts.commit()
    assert receipts.get(KnowledgeProcessingRetryReceipt, value.id).item_count == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"item_count": -1},
        {"tenant_id": 0},
        {"actor_user_id": 0},
        {"expected_job_revision": -1},
        {"accepted_job_revision": 2},
    ],
)
def test_negative_count_and_invalid_identity_revision_still_reject(receipts, changes):
    receipts.add(row(**changes))
    with pytest.raises(IntegrityError):
        receipts.flush()
    receipts.rollback()
