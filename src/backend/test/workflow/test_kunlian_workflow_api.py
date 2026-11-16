import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


async def test_management_checks_target_tenant_before_delegate_service():
    name = "bisheng.workflow.application.kunlian_workflow_api"
    assert importlib.util.find_spec(name) is not None, "formal management adapter missing"
    module = importlib.import_module(name)
    target = AsyncMock(return_value={"tenant_id": 8, "flow_type": 10})
    versions = AsyncMock()
    service = module.KunlianWorkflowApi(
        target_reader=target, flow_service=SimpleNamespace(get_version_list_by_flow=versions)
    )
    with pytest.raises(module.KunlianAccessError, match="NOT_FOUND"):
        await service.versions(SimpleNamespace(user_id=17, tenant_id=7), "f" * 32)
    versions.assert_not_called()


async def test_versions_exposes_only_metadata_not_graph_or_internal_fields():
    from bisheng.common.schemas.api import resp_200
    from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi

    original = {"id": 3, "name": "v1", "is_current": 1, "data": {"secret": "hidden"}, "user_id": 99, "tenant_id": 7}
    service = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}),
        flow_service=SimpleNamespace(
            get_version_list_by_flow=AsyncMock(return_value=resp_200({"data": [original], "total": 1}))
        ),
    )
    response = await service.versions(SimpleNamespace(user_id=17, tenant_id=7), "flow")
    assert response.data == {"data": [{"id": 3, "name": "v1", "is_current": 1}], "total": 1}
    assert original["data"] == {"secret": "hidden"}


async def test_version_requires_edit_before_graph_service(monkeypatch):
    from bisheng.common.errcode.http_error import UnAuthorizedError
    from bisheng.workflow.application import kunlian_workflow_api as module

    permission = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(module, "require_business_action", permission)
    graph_service = AsyncMock()
    service = module.KunlianWorkflowApi(flow_service=SimpleNamespace(get_version_info=graph_service))
    service._version = AsyncMock(return_value={"id": 3, "flow_id": "flow", "tenant_id": 7})
    user = SimpleNamespace(user_id=17, tenant_id=7)
    with pytest.raises(UnAuthorizedError):
        await service.version(user, "flow", 3)
    graph_service.assert_not_awaited()
    permission.assert_awaited_once_with(user, resource_type="workflow", resource_id="flow", action="edit")


async def test_edit_version_redacts_actual_sql_agent_password_without_hiding_business_input(monkeypatch):
    from copy import deepcopy

    from bisheng.common.schemas.api import resp_200
    from bisheng.workflow.application import kunlian_workflow_api as module

    graph = {
        "nodes": [
            {
                "data": {
                    "group_params": [
                        {
                            "params": [
                                {
                                    "key": "sql_agent",
                                    "value": {"db_password": "database-secret", "db_name": "reports", "open": True},
                                },
                                {"key": "user_prompt", "value": "Summarize sales"},
                                {
                                    "key": "input",
                                    "value": {"password": "ordinary-business-field", "api_key": "business-key"},
                                },
                            ]
                        }
                    ]
                }
            }
        ],
        "edges": [],
    }
    original = deepcopy(graph)
    monkeypatch.setattr(module, "require_business_action", AsyncMock())
    service = module.KunlianWorkflowApi(
        flow_service=SimpleNamespace(get_version_info=AsyncMock(return_value=resp_200({"id": 3, "data": graph})))
    )
    service._version = AsyncMock(return_value={"id": 3, "flow_id": "flow", "tenant_id": 7})
    service._version.return_value.update(name="v1", description=None, data=graph, is_delete=0)
    response = await service.version(SimpleNamespace(user_id=17, tenant_id=7), "flow", 3)
    params = response.data["data"]["nodes"][0]["data"]["group_params"][0]["params"]
    assert "db_password" not in params[0]["value"]
    assert params[0]["value"]["db_name"] == "reports"
    assert params[2]["value"] == {"password": "ordinary-business-field", "api_key": "business-key"}
    assert graph == original
