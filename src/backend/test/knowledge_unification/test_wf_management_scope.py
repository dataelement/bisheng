"""Management writes use the server-resolved tenant pin, not JWT home tenant.

覆盖 AC: AC-87, AC-88, AC-89. Uses the real management ContextVar and actual
Service/SQL paths; identity and permission checks remain separate boundaries.
"""

import pytest

from bisheng.api.services import flow as flow_service
from bisheng.api.services import workflow as workflow_service
from bisheng.api.v1.schemas import FlowVersionCreate
from bisheng.core.context.tenant import current_tenant_id, management_tenant_scope, set_current_tenant_id
from test.knowledge_unification import test_wf_create as create_fixtures
from test.knowledge_unification import test_wf_current as current_fixtures
from test.knowledge_unification import test_wf_save as save_fixtures

store = create_fixtures.store
tenant = create_fixtures.tenant
bindings = create_fixtures.bindings
saved = save_fixtures.saved
configured = current_fixtures.configured
rows = create_fixtures.rows


@pytest.mark.parametrize("operation", ["create", "new_version", "save", "current", "publish", "delete_version"])
async def test_management_write_uses_pinned_tenant_even_when_identity_home_is_root(configured, operation):
    configured.user.tenant_id = 1
    token = set_current_tenant_id(1)
    try:
        with management_tenant_scope(101):
            if operation == "create":
                result = await create_fixtures.create(configured, name="pinned-root", saved_data={})
                root = next(row for row in rows(configured, "flow") if row["id"] == result.data.id)
                assert root["tenant_id"] == 101
            elif operation == "new_version":
                result = await flow_service.FlowService.create_new_version(
                    configured.user, "wf", FlowVersionCreate(name="pinned-version", data={})
                )
                assert result.data.tenant_id == 101
            elif operation == "save":
                result = await save_fixtures.save(configured, 2, None, name="pinned-save")
                assert result.data.name == "pinned-save"
            elif operation == "current":
                assert (
                    await flow_service.FlowService.change_current_version(configured.request, configured.user, "wf", 2)
                ).status_code == 200
            elif operation == "publish":
                await workflow_service.WorkFlowService.update_flow_status(configured.user, "wf", 2, 2)
            else:
                assert (await flow_service.FlowService.delete_version(configured.user, 2)).status_code == 200
    finally:
        current_tenant_id.reset(token)
    assert configured.user.tenant_id == 1
    assert all(row["tenant_id"] == 101 for row in rows(configured, "business_reference_set"))
    assert all(row["tenant_id"] == 101 for row in rows(configured, "business_resource_reference"))
