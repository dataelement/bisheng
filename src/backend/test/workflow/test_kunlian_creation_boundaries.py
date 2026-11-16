"""Version source ownership and graph-vs-authenticated-identity boundaries."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.schemas.api import resp_200
from bisheng.workflow.application.kunlian_workflow_api import KunlianWorkflowApi


@pytest.mark.parametrize(
    "source",
    [
        {"id": 5, "flow_id": "other", "tenant_id": 7},
        {"id": 5, "flow_id": "flow", "tenant_id": 8},
    ],
)
async def test_new_version_rejects_source_outside_selected_workflow(source):
    from bisheng.open_api.domain.services.kunlian_credential import KunlianAccessError

    owner = AsyncMock(return_value=resp_200({"id": 6}))
    service = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}),
        flow_service=SimpleNamespace(create_new_version=owner),
    )
    service.reader = SimpleNamespace(get_version=lambda version_id: source)
    with pytest.raises(KunlianAccessError, match="NOT_FOUND"):
        await service.create_version(
            SimpleNamespace(user_id=17, tenant_id=7), "flow", SimpleNamespace(original_version_id=5, flow_type=10)
        )
    owner.assert_not_awaited()


async def test_new_version_accepts_source_from_same_workflow():
    owner = AsyncMock(return_value=resp_200({"id": 6}))
    service = KunlianWorkflowApi(
        target_reader=AsyncMock(return_value={"tenant_id": 7, "flow_type": 10}),
        flow_service=SimpleNamespace(create_new_version=owner),
    )
    service.reader = SimpleNamespace(get_version=lambda version_id: {"id": 5, "flow_id": "flow", "tenant_id": 7})
    result = await service.create_version(
        SimpleNamespace(user_id=17, tenant_id=7), "flow", SimpleNamespace(original_version_id=5, flow_type=10)
    )
    assert result.data["id"] == 6
    owner.assert_awaited_once()


async def test_graph_identity_fields_do_not_override_workflow_creator_or_tenant():
    from bisheng.workflow.application.kunlian_workflow_creation import create_registered_workflow
    from bisheng.workflow.domain.schemas.kunlian_workflow_api import workflow_create_dto

    captured = []

    class Repository:
        def find_creation(self, *args):
            return None

        def create(self, key, digest, flow):
            captured.append(flow)
            return flow, 1, True

    graph = {"nodes": [], "edges": [], "user_id": 999, "tenant_id": 888, "is_global_super": True}
    body = workflow_create_dto({"name": "new", "data": graph})
    await create_registered_workflow(
        Repository(),
        SimpleNamespace(user_id=17, tenant_id=7),
        body,
        "request",
        AsyncMock(),
        AsyncMock(),
        workflow_management=True,
    )
    assert (captured[0].user_id, captured[0].tenant_id) == (17, 7)
    assert captured[0].data == graph
