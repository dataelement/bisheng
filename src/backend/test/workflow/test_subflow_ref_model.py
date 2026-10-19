"""F086 T03: the subflow reference table is tenant-aware."""

from sqlmodel import SQLModel

from bisheng.core.database import tenant_filter


def test_subflow_ref_module_is_registered_for_tenant_filter():
    assert "bisheng.workflow.domain.models.subflow_ref" in tenant_filter._TENANT_AWARE_MODEL_MODULES


def test_subflow_ref_table_is_discovered_as_tenant_aware():
    tenant_filter._force_import_all_models()
    discovered = tenant_filter._discover_tenant_aware_tables()
    assert "workflow_subflow_ref" in discovered
    table = SQLModel.metadata.tables["workflow_subflow_ref"]
    assert table.c.tenant_id.nullable is False
    assert {c.name for c in table.c} == {
        "id",
        "tenant_id",
        "parent_flow_id",
        "child_flow_id",
        "create_time",
        "update_time",
    }


def test_subflow_ref_table_is_found_by_model_discovery():
    from bisheng.core.database.model_discovery import discover_sqlmodel_module_names

    assert "bisheng.workflow.domain.models.subflow_ref" in discover_sqlmodel_module_names()
