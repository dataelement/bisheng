"""T636: original acceptance is an independent, nullable audit fact."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob


def job(**extra):
    return KnowledgeProcessingJob(
        tenant_id=101,
        space_id=1,
        kind="embedding_rebuild",
        actor_user_id=7,
        idempotency_key="one",
        request_hash="a" * 64,
        expected_model_config_revision=7,
        **extra,
    )


def test_acceptance_revision_is_a_separate_nullable_integer_without_invented_default():
    column = KnowledgeProcessingJob.__table__.c.accepted_model_config_revision
    assert isinstance(column.type, sa.Integer) and column.nullable
    assert column.default is None and column.server_default is None
    assert "accepted_model_config_revision" in str(
        CreateTable(KnowledgeProcessingJob.__table__).compile(dialect=mysql.dialect())
    )


def test_missing_trial_acceptance_is_not_guessed_from_expected_revision():
    assert job().accepted_model_config_revision is None
    assert job(expected_index_generation="g7").accepted_model_config_revision is None


def test_explicit_acceptance_survives_expected_revision_progress():
    row = job(accepted_model_config_revision=7)
    row.expected_model_config_revision = 8
    row.revision += 1
    row.state = "accepted"
    assert row.accepted_model_config_revision == 7
