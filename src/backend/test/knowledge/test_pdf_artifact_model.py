from __future__ import annotations

import inspect

from sqlalchemy import BigInteger, ForeignKeyConstraint, UniqueConstraint

from bisheng.core.config.settings import KnowledgeConf
from bisheng.core.database import tenant_filter
from bisheng.knowledge.domain.models.knowledge_file_pdf_artifact import (
    KnowledgeFilePdfArtifact,
    KnowledgeFilePdfArtifactOrigin,
    KnowledgeFilePdfArtifactStatus,
)


def test_pdf_artifact_model_has_independent_state_and_origin_contract() -> None:
    table = KnowledgeFilePdfArtifact.__table__

    assert table.name == "knowledge_file_pdf_artifact"
    assert KnowledgeFilePdfArtifactStatus.WAITING.value == 1
    assert KnowledgeFilePdfArtifactStatus.PROCESSING.value == 2
    assert KnowledgeFilePdfArtifactStatus.SUCCESS.value == 3
    assert KnowledgeFilePdfArtifactStatus.FAILED.value == 4
    assert KnowledgeFilePdfArtifactOrigin.ORIGINAL.value == 1
    assert KnowledgeFilePdfArtifactOrigin.PARSE_PREVIEW.value == 2
    assert KnowledgeFilePdfArtifactOrigin.GENERATED.value == 3
    assert isinstance(table.c.artifact_size.type, BigInteger)
    assert table.c.tenant_id.nullable is False
    assert table.c.knowledge_file_id.nullable is False


def test_pdf_artifact_model_has_unique_file_and_cascade_foreign_key() -> None:
    table = KnowledgeFilePdfArtifact.__table__
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    foreign_keys = [constraint for constraint in table.constraints if isinstance(constraint, ForeignKeyConstraint)]

    assert ("knowledge_file_id",) in unique_columns
    assert len(foreign_keys) == 1
    assert foreign_keys[0].elements[0].target_fullname == "knowledgefile.id"
    assert foreign_keys[0].ondelete == "CASCADE"


def test_pdf_artifact_model_is_preloaded_for_tenant_filtering() -> None:
    assert "bisheng.knowledge.domain.models.knowledge_file_pdf_artifact" in tenant_filter._TENANT_AWARE_MODEL_MODULES


def test_knowledge_pdf_artifact_config_defaults_and_validation() -> None:
    config = KnowledgeConf().pdf_artifact

    assert config.enabled is True
    assert config.queue_name == "knowledge_pdf_celery"
    assert config.max_retries == 3
    assert config.retry_base_seconds == 30
    assert config.retry_max_seconds == 300
    assert config.conversion_timeout_seconds == 300


def test_f063_migration_only_creates_empty_schema() -> None:
    from bisheng.core.database.alembic.versions import (
        v2_6_0_f063_knowledge_file_pdf_artifact as migration,
    )

    source = inspect.getsource(migration.upgrade).lower()

    assert migration.down_revision == "f062_add_portal_course_tables"
    assert "insert" not in source
    assert "knowledgefile" not in source.replace('"knowledgefile.id"', "")
