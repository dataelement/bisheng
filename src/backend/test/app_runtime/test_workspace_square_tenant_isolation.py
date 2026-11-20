"""Root and former-tenant apps never enter a child's permission scan."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.admin.application import request_admission
from bisheng.api.services import workflow as workflow_module
from bisheng.common.errcode.permission import PermissionPublishNotReadyError
from bisheng.common.request_scope import RequestScope
from bisheng.core.context.tenant import bypass_tenant_filter
from test.fixtures.tenant_filter import isolated_tenant_filter as isolated_tenant_filter


@pytest.mark.parametrize("entry", ["online", "uncategorized"])
@pytest.mark.parametrize("tenant", [1, 60, 70])
async def test_square_filters_tenant_before_loading_permission_projection(
    build_list_env, monkeypatch, isolated_tenant_filter, entry, tenant
):
    env = build_list_env
    env.enable_runtime_layer()
    by_tenant = {}
    with bypass_tenant_filter():
        for owner in (1, 60, 70):
            by_tenant[owner] = {
                env.seed_flow(tenant_id=owner).id,
                env.seed_assistant(tenant_id=owner).id,
                env.seed_app(tenant_id=owner).id,
            }
    wanted = by_tenant[tenant]

    async def check_candidates(user, *, resource_type, resource_ids, actions):
        # A foreign legacy resource with inconsistent permission ownership used
        # to fail the entire /chat/online page before tenant rejection.
        if set(resource_ids) - wanted:
            raise PermissionPublishNotReadyError(msg="Foreign projection must not be loaded")
        return {resource_id: frozenset(actions) for resource_id in resource_ids}

    check = AsyncMock(side_effect=check_candidates)
    monkeypatch.setattr(workflow_module, "batch_check_business_actions", check)
    user = SimpleNamespace(user_id=91020, tenant_id=tenant, is_global_super=False)
    admitted = request_admission.AdmittedRequest(user.user_id, tenant, tenant, RequestScope.TENANT, False)
    with request_admission.bind_admitted_scope(admitted):
        if entry == "online":
            result = await workflow_module.WorkFlowService.get_online_flows_cursor(
                user, None, 2, None, None, page_size=20, action="visible"
            )
            pages = result.data
        else:
            result = await workflow_module.WorkFlowService.get_uncategorized_flows_envelope(user, page_size=20)
            pages = result.data
    assert {row["id"] for row in pages} == wanted
    assert len(pages) == len(wanted)
    assert result.has_more is False
    assert check.await_count >= 3
