"""T941: portable, private subject index facts leave ordinary processing rows unchanged."""

import pytest
from sqlalchemy import BigInteger, String, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable
from sqlmodel import Session, create_engine, select

from bisheng.knowledge.domain.models.knowledge_processing_job import KnowledgeProcessingJob
from bisheng.knowledge.domain.models.knowledge_processing_retry import KnowledgeProcessingRetryReceipt
from bisheng.knowledge.domain.schemas.processing_job import JobAccepted, ProcessingJobRead

_MODELS = (KnowledgeProcessingJob, KnowledgeProcessingRetryReceipt)
_FIELDS = ("actor_subject_type", "actor_subject_id")


def job(kind="move_index", **changes):
    return KnowledgeProcessingJob(
        **{
            "tenant_id": 101,
            "space_id": 23,
            "kind": kind,
            "actor_user_id": 11,
            "actor_reference": {"original": "untouched"},
            "idempotency_key": "original",
            "request_hash": "a" * 64,
            "expected_model_config_revision": 7,
            **changes,
        }
    )


def retry(job_id, **changes):
    return KnowledgeProcessingRetryReceipt(
        **{
            "tenant_id": 101,
            "job_id": job_id,
            "idempotency_key": "retry",
            "request_hash": "b" * 64,
            "actor_user_id": 12,
            "actor_reference": {"different": "original-retry"},
            "expected_job_revision": 3,
            "accepted_job_revision": 4,
            "item_count": 0,
            **changes,
        }
    )


@pytest.fixture
def database(tenant_context):
    tenant_context(101)
    engine = create_engine("sqlite://")
    for model in _MODELS:
        model.__table__.create(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("model", _MODELS)
def test_subject_columns_are_explicit_nullable_portable_and_have_no_invented_default(model):
    table = model.__table__
    subject_type = table.c.actor_subject_type
    subject_id = table.c.actor_subject_id
    assert isinstance(subject_type.type, String) and subject_type.type.length == 32
    assert isinstance(subject_id.type, BigInteger)
    for column in (subject_type, subject_id):
        assert column.nullable and column.default is None and column.server_default is None
    ddl = str(CreateTable(table).compile(dialect=mysql.dialect()))
    assert "actor_subject_type VARCHAR(32)" in ddl and "actor_subject_id BIGINT" in ddl


@pytest.mark.parametrize("model", _MODELS)
def test_model_dump_excludes_real_subject_facts_even_when_explicitly_included(model):
    values = {"actor_subject_type": "service_account", "actor_subject_id": 7}
    row = job(**values) if model is KnowledgeProcessingJob else retry("one", **values)
    assert row.actor_subject_type == "service_account" and row.actor_subject_id == 7
    assert not set(_FIELDS) & row.model_dump().keys()
    assert row.model_dump(include=set(_FIELDS)) == {}
    assert not set(_FIELDS) & row.model_dump(mode="python").keys()


def test_retry_subject_index_is_real_nonunique_and_uses_the_frozen_column_order(database):
    index = next(
        index for index in KnowledgeProcessingRetryReceipt.__table__.indexes if index.name == "ix_kpr_job_subject"
    )
    expected = ["tenant_id", "job_id", "actor_subject_id", "actor_subject_type", "accepted_job_revision", "id"]
    assert not index.unique and [column.name for column in index.columns] == expected
    actual = next(
        item
        for item in inspect(database).get_indexes("knowledge_processing_retry_receipt")
        if item["name"] == "ix_kpr_job_subject"
    )
    assert not actual["unique"] and actual["column_names"] == expected
    assert not any(
        set(_FIELDS) & {column.name for column in index.columns} for index in KnowledgeProcessingJob.__table__.indexes
    )


@pytest.mark.parametrize("kind", ["embedding_rebuild", "file_reprocess", "file_resplit", "metadata_schema_change"])
def test_original_four_kinds_and_retry_rows_roundtrip_null_without_subject_inference(database, kind):
    value = job(kind)
    receipt = retry(value.id)
    with Session(database, expire_on_commit=False) as session:
        session.add_all([value, receipt])
        session.commit()
    with Session(database, expire_on_commit=False) as session:
        restored = session.get(KnowledgeProcessingJob, value.id)
        retried = session.get(KnowledgeProcessingRetryReceipt, receipt.id)
        assert restored.kind == kind and restored.actor_user_id == 11
        assert retried.actor_user_id == 12 and retried.item_count == 0
        for row in (restored, retried):
            assert row.actor_subject_type is None and row.actor_subject_id is None
        assert restored.actor_reference == {"original": "untouched"}
        assert retried.actor_reference == {"different": "original-retry"}


@pytest.mark.parametrize("subject_type", ["user", "service_account"])
def test_explicit_subject_survives_audit_changes_and_large_ids_without_collapsing_types(database, subject_type):
    identifier = 2**40 + 7
    value = job(actor_subject_type=subject_type, actor_subject_id=identifier)
    receipt = retry(value.id, actor_subject_type=subject_type, actor_subject_id=identifier)
    with Session(database, expire_on_commit=False) as session:
        session.add_all([value, receipt])
        session.commit()
    with Session(database, expire_on_commit=False) as session:
        restored = session.get(KnowledgeProcessingJob, value.id)
        restored.actor_user_id = 99
        session.commit()
        actual = session.exec(
            select(KnowledgeProcessingJob.actor_subject_type, KnowledgeProcessingJob.actor_subject_id)
        ).one()
        assert actual == (subject_type, identifier)
        actual_retry = session.get(KnowledgeProcessingRetryReceipt, receipt.id)
        assert (actual_retry.actor_subject_type, actual_retry.actor_subject_id) == (subject_type, identifier)
        assert actual_retry.actor_user_id == 12


def test_repeated_real_retry_subjects_do_not_create_an_accidental_unique_constraint(database):
    first = retry("one", actor_subject_type="service_account", actor_subject_id=7)
    second = retry(
        "one",
        idempotency_key="retry-two",
        expected_job_revision=4,
        accepted_job_revision=5,
        actor_subject_type="service_account",
        actor_subject_id=7,
    )
    with Session(database, expire_on_commit=False) as session:
        session.add_all([first, second])
        session.commit()
        rows = session.exec(
            select(KnowledgeProcessingRetryReceipt).order_by(KnowledgeProcessingRetryReceipt.accepted_job_revision)
        ).all()
        assert len(rows) == 2
        assert [row.actor_subject_id for row in rows] == [7, 7]
        assert [row.actor_user_id for row in rows] == [12, 12]


def test_original_public_job_dtos_do_not_gain_subject_or_credential_fields():
    assert set(JobAccepted.model_fields) == {"job_id", "accepted", "state", "reused"}
    assert not {"actor_subject_type", "actor_subject_id", "actor_reference"} & ProcessingJobRead.model_fields.keys()
