"""Cross-lane schema and migration checks against the frozen F118 contract."""

from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from bisheng.core.database.model_discovery import discover_sqlmodel_module_names
from bisheng.core.database.tenant_filter import _TENANT_AWARE_MODEL_MODULES

MIGRATION = "bisheng.core.database.alembic.versions.f118_knowledge_unification"
NEW_MODEL_MODULES = (
    "bisheng.knowledge.domain.models.knowledge_processing_job",
    "bisheng.knowledge.domain.models.knowledge_processing_item",
    "bisheng.knowledge.domain.models.knowledge_operation_plan",
    "bisheng.knowledge.domain.models.knowledge_unification_run",
    "bisheng.resource_reference.domain.models.business_resource_reference",
    "bisheng.resource_reference.domain.models.business_reference_set",
    "bisheng.resource_reference.domain.models.resource_reference_tombstone",
)


def test_all_new_tables_are_discoverable_and_tenant_registered():
    discovered = set(discover_sqlmodel_module_names())
    registered = set(_TENANT_AWARE_MODEL_MODULES)
    for name in NEW_MODEL_MODULES:
        assert name in discovered
        assert name in registered
        module = import_module(name)
        tables = [obj.__table__ for obj in vars(module).values() if isinstance(obj, type) and hasattr(obj, "__table__")]
        assert tables
        assert all("tenant_id" in table.columns for table in tables)


def test_existing_table_upgrade_is_repeatable_without_converting_rows(f118_engine):
    migration = import_module(MIGRATION)
    with f118_engine.begin() as connection:
        connection.execute(text("CREATE TABLE knowledge (id INTEGER PRIMARY KEY, type INTEGER, model VARCHAR(64))"))
        connection.execute(text("CREATE TABLE permission_model (id INTEGER PRIMARY KEY, model_key VARCHAR(64))"))
        connection.execute(text("INSERT INTO knowledge (id,type,model) VALUES (7,0,'original-model')"))
        connection.execute(text("INSERT INTO permission_model (id,model_key) VALUES (9,'original-viewer')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        row = connection.execute(
            text("SELECT type,model,processing_config_version,model_config_revision,migration_origin FROM knowledge")
        ).one()
        assert tuple(row) == (0, "original-model", 0, 0, None)
        assert tuple(
            connection.execute(
                text("SELECT model_key,visibility_only_resource_types,visibility_level FROM permission_model")
            ).one()
        ) == ("original-viewer", None, None)
        columns = {column["name"] for column in inspect(connection).get_columns("knowledge")}
        assert {"processing_defaults", "index_generation", "migration_origin"} <= columns


def test_downgrade_cannot_silently_drop_grant_or_migration_provenance():
    with pytest.raises(RuntimeError, match="complete maintenance backup"):
        import_module(MIGRATION).downgrade()


@pytest.mark.parametrize(
    "name",
    ["processing_defaults", "processing_config_version", "model_config_revision", "index_generation", "migration_origin"],
)
def test_internal_orm_metadata_does_not_expand_legacy_wire_models(name):
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeBase

    assert name in Knowledge.model_fields
    assert name not in KnowledgeBase.model_fields
