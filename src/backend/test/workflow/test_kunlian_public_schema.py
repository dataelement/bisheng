"""Published descriptor reads never expose graph and require visible permission."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi


async def test_describe_uses_visible_permission_and_only_published_descriptor(monkeypatch):
    from bisheng.workflow.application import kunlian_workflow_api as module
    from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository

    assert hasattr(PublishedRunRegistrationRepository, "describe_published"), "published schema read port missing"

    def reader(self, tenant_id, workflow_id, version_id):
        return {
            "workflow_id": workflow_id,
            "workflow_version_id": "3",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }

    monkeypatch.setattr(PublishedRunRegistrationRepository, "describe_published", reader)
    permit = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", permit)
    service = KunlianWorkflowApi(target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}))
    assert hasattr(service, "describe"), "public schema application missing"
    user = SimpleNamespace(user_id=17, tenant_id=7)
    result = await service.describe(user, "flow", version_id=None)
    assert result["workflow_version_id"] == "3"
    assert "data" not in result
    permit.assert_awaited_once_with(user, resource_type="workflow", resource_id="flow", action="visible")


def test_published_schema_reuses_real_supported_descriptor_without_graph(monkeypatch):
    from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository

    repository = PublishedRunRegistrationRepository()
    assert hasattr(repository, "describe_published"), "published schema read port missing"
    flow = SimpleNamespace(id="flow", name="Published", description="description", status=2, user_id=17)
    version = SimpleNamespace(
        id=3,
        tenant_id=7,
        description="version",
        data={
            "nodes": [
                {
                    "data": {
                        "type": "output",
                        "group_params": [{"params": [{"key": "message", "value": {"msg": "sensitive literal"}}]}],
                    }
                }
            ]
        },
    )
    session = SimpleNamespace(exec=lambda statement: SimpleNamespace(all=lambda: [version]))

    @contextmanager
    def transaction():
        yield session

    monkeypatch.setattr(repository, "transaction", transaction)
    monkeypatch.setattr(repository, "invocation_flow", lambda *args: flow)
    from bisheng.database.models.flow import FlowStatus

    flow.status = FlowStatus.ONLINE.value
    result = repository.describe_published(7, "flow", None)
    assert result["input_schema"] == {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert result["output_schema"]["properties"] == {"result": {"type": "string"}}
    assert "sensitive literal" not in str(result)


def test_unsupported_schema_uses_existing_owner_error(monkeypatch):
    from bisheng.common.errcode.flow import WorkflowRegistrationConflict
    from bisheng.workflow.domain.repositories.kunlian_registration import PublishedRunRegistrationRepository

    repository = PublishedRunRegistrationRepository()
    assert hasattr(repository, "describe_published"), "published schema read port missing"

    @contextmanager
    def transaction():
        yield object()

    monkeypatch.setattr(repository, "transaction", transaction)
    monkeypatch.setattr(repository, "invocation_flow", lambda *args: object())

    def unsupported(*args):
        raise WorkflowRegistrationConflict()

    monkeypatch.setattr(repository, "invocation_version", unsupported)
    with pytest.raises(WorkflowRegistrationConflict):
        repository.describe_published(7, "flow", None)
