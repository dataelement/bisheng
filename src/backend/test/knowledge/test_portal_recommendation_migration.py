import importlib
from datetime import datetime

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from bisheng.knowledge.domain.models.portal_recommendation_file_projection import (
    PortalRecommendationFileProjection,
)

MIGRATION_MODULE = "bisheng.core.database.alembic.versions.v2_5_0_sg_f056_portal_recommendation"


def _run(operation: str, engine: sa.Engine) -> None:
    migration = importlib.import_module(MIGRATION_MODULE)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            getattr(migration, operation)()


def test_revision_merges_the_two_current_heads():
    migration = importlib.import_module(MIGRATION_MODULE)

    assert set(migration.down_revision) == {
        "f057_message_push_outbox",
        "f058_approval_notification_outbox",
    }


def test_upgrade_creates_only_projection_constraints_and_indexes_then_downgrades():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    inspector = sa.inspect(engine)

    assert "portal_recommendation_file_projection" in inspector.get_table_names()
    assert "department_business_domain" not in inspector.get_table_names()

    projection_columns = {column["name"] for column in inspector.get_columns("portal_recommendation_file_projection")}
    assert projection_columns == {
        "id",
        "tenant_id",
        "file_id",
        "space_id",
        "business_domain_code",
        "permission_scope",
        "recommendable",
        "reason_code",
        "source_update_time",
        "projection_version",
        "create_time",
        "update_time",
    }
    projection_uniques = inspector.get_unique_constraints("portal_recommendation_file_projection")
    assert any(set(item["column_names"]) == {"tenant_id", "file_id"} for item in projection_uniques)
    projection_indexes = {
        tuple(item["column_names"]) for item in inspector.get_indexes("portal_recommendation_file_projection")
    }
    assert (
        "tenant_id",
        "business_domain_code",
        "recommendable",
        "source_update_time",
        "file_id",
    ) in projection_indexes
    assert ("tenant_id", "recommendable", "source_update_time", "file_id") in projection_indexes
    assert ("tenant_id", "space_id", "recommendable") in projection_indexes

    _run("downgrade", engine)
    assert "portal_recommendation_file_projection" not in sa.inspect(engine).get_table_names()


def test_upgrade_is_idempotent():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    _run("upgrade", engine)

    assert "portal_recommendation_file_projection" in sa.inspect(engine).get_table_names()
    assert "department_business_domain" not in sa.inspect(engine).get_table_names()


def test_full_upgrade_downgrade_cycle_and_repeated_downgrade_are_safe():
    engine = sa.create_engine("sqlite://")

    _run("upgrade", engine)
    _run("downgrade", engine)
    _run("downgrade", engine)
    _run("upgrade", engine)

    assert "portal_recommendation_file_projection" in sa.inspect(engine).get_table_names()
    assert "department_business_domain" not in sa.inspect(engine).get_table_names()


def test_projection_orm_defaults_fail_closed_and_leave_tenant_for_before_flush():
    projection = PortalRecommendationFileProjection(
        file_id=20,
        space_id=30,
        source_update_time=datetime(2026, 7, 15),
    )

    assert projection.tenant_id is None
    assert projection.permission_scope == "unknown"
    assert projection.recommendable == 0
    assert projection.reason_code == "unknown"
    assert PortalRecommendationFileProjection.__table__.c.business_domain_code.type.length == 16
    assert PortalRecommendationFileProjection.__table__.c.permission_scope.type.length == 16
    assert PortalRecommendationFileProjection.__table__.c.reason_code.type.length == 32
