"""Assistant edit permission never grants access to arbitrary linked workflow graphs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.core.context.tenant import current_tenant_id


@pytest.fixture
def harness(monkeypatch):
    from bisheng.assistant.domain.services import assistant_boundary_service as module

    flow = SimpleNamespace(
        id="private", tenant_id=1, flow_type=10, is_delete=0, data={"nodes": [], "secret": "CANARY"}, name="Private"
    )
    repo = AsyncMock(return_value=[flow])
    monkeypatch.setattr(module.AssistantBoundaryRepository, "flows", repo, raising=False)
    permission = AsyncMock()
    monkeypatch.setattr(module, "require_business_action", permission)
    token = current_tenant_id.set(1)
    try:
        yield SimpleNamespace(
            service=module.AssistantBoundaryService,
            flow=flow,
            repo=repo,
            permission=permission,
            user=SimpleNamespace(user_id=7),
        )
    finally:
        current_tenant_id.reset(token)


async def test_binding_requires_source_use_not_assistant_edit(harness):
    h = harness
    h.permission.side_effect = UnAuthorizedError()
    with pytest.raises(UnAuthorizedError):
        await h.service.authorize_flow_bindings(h.user, ["private"])
    h.permission.assert_awaited_once_with(h.user, resource_type="workflow", resource_id="private", action="use")


@pytest.mark.parametrize("change", ["missing", "tenant", "type", "deleted"])
async def test_invalid_reference_fails_before_shortcuts(harness, change):
    h = harness
    if change == "missing":
        h.repo.return_value = []
    elif change == "tenant":
        h.flow.tenant_id = 2
    elif change == "type":
        h.flow.flow_type = 5
    else:
        h.flow.is_delete = 1
    with pytest.raises(HTTPException):
        await h.service.authorize_flow_bindings(h.user, ["private"])
    h.permission.assert_not_awaited()


async def test_linked_reads_recheck_visible_and_never_return_graph(harness):
    h = harness
    rows = await h.service.flow_views(h.user, ["private"])
    assert rows[0]["id"] == "private"
    assert "data" not in rows[0] and "CANARY" not in str(rows)
    assert h.flow.data["secret"] == "CANARY"
    h.permission.assert_awaited_once_with(h.user, resource_type="workflow", resource_id="private", action="visible")
    h.permission.side_effect = UnAuthorizedError()
    assert await h.service.flow_views(h.user, ["private"]) == []


async def test_update_route_denied_flow_precedes_any_mutation(monkeypatch):
    from bisheng.api.services import assistant as module
    from bisheng.api.v1.schemas import AssistantUpdateReq
    from bisheng.assistant.domain.services.assistant_boundary_service import AssistantBoundaryService

    row = SimpleNamespace(id="own", name="old", user_id=7)
    monkeypatch.setattr(module.AssistantDao, "get_one_assistant", Mock(return_value=row))
    monkeypatch.setattr(module.AssistantService, "check_update_permission_async", AsyncMock())
    monkeypatch.setattr(AssistantBoundaryService, "authorize_flow_bindings", AsyncMock(side_effect=UnAuthorizedError()))
    persist = Mock()
    monkeypatch.setattr(module.AssistantDao, "update_assistant", persist)
    with pytest.raises(UnAuthorizedError):
        await module.AssistantService.update_assistant(
            None, SimpleNamespace(user_id=7), AssistantUpdateReq(id="own", name="new", flow_list=["private"])
        )
    assert row.name == "old"
    persist.assert_not_called()


async def test_auto_flow_suggestion_never_serializes_original_graph(monkeypatch):
    from bisheng.api.services import assistant as module
    from bisheng.database.models.flow import Flow

    source = Flow(id="a", name="Choice", data={"nodes": [], "edges": [], "secret": "SSE_CANARY"})
    monkeypatch.setattr(module.FlowDao, "aget_all_apps", AsyncMock(return_value=([{"id": "a"}], False)))
    monkeypatch.setattr(module.FlowDao, "aget_flow_by_ids", AsyncMock(return_value=[source]))
    monkeypatch.setattr(module, "batch_check_business_actions", AsyncMock(return_value={"a": {"visible"}}))
    result = await module.AssistantService.get_auto_flow_info(
        SimpleNamespace(prompt="choose"),
        SimpleNamespace(choose_tools=Mock(return_value=["Choice"])),
        SimpleNamespace(user_id=7),
    )
    assert result[0].data is None
    assert "SSE_CANARY" not in str([item.model_dump() for item in result])
    assert source.data["secret"] == "SSE_CANARY"


async def test_flow_post_route_does_not_persist_denied_reference(monkeypatch):
    from bisheng.api.services import assistant as module
    from bisheng.assistant.domain.services.assistant_boundary_service import AssistantBoundaryService

    monkeypatch.setattr(module.AssistantDao, "get_one_assistant", Mock(return_value=SimpleNamespace(id="own")))
    monkeypatch.setattr(module.AssistantService, "check_update_permission_async", AsyncMock())
    monkeypatch.setattr(AssistantBoundaryService, "authorize_flow_bindings", AsyncMock(side_effect=UnAuthorizedError()))
    persist = Mock()
    monkeypatch.setattr(module.AssistantLinkDao, "update_assistant_flow", persist)
    with pytest.raises(UnAuthorizedError):
        await module.AssistantService.update_flow_list("own", ["private"], SimpleNamespace(user_id=7))
    persist.assert_not_called()
