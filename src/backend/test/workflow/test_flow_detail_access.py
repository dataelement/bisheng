"""Builder detail reads an explicit visible grant, or an effective edit decision."""

from unittest.mock import AsyncMock

import pytest

from bisheng.api.services import flow as service
from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.database.models.flow import Flow, FlowType


def _flow() -> Flow:
    return Flow(
        id="app-1",
        name="other",
        user_id=2,
        tenant_id=7,
        flow_type=FlowType.WORKFLOW.value,
        data={"nodes": [], "edges": []},
    )


def _patch(monkeypatch, decide):
    monkeypatch.setattr(service.FlowDao, "aget_flow_by_id", AsyncMock(return_value=_flow()))
    monkeypatch.setattr(service.FlowService, "get_logo_share_link_async", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "check_business_action", decide)


@pytest.mark.asyncio
async def test_detail_opens_on_edit_when_visible_grant_is_absent(monkeypatch):
    calls = []

    async def decide(*_args, **kwargs):
        calls.append(kwargs["action"])
        return kwargs["action"] == "edit"

    _patch(monkeypatch, decide)
    result = await service.FlowService.get_one_flow(object(), "app-1")

    assert result.data["id"] == "app-1"
    assert calls == ["visible", "edit", "share"]


@pytest.mark.asyncio
async def test_detail_stays_denied_without_visible_or_edit(monkeypatch):
    calls = []

    async def deny(*_args, **kwargs):
        calls.append(kwargs["action"])
        return False

    _patch(monkeypatch, deny)
    with pytest.raises(UnAuthorizedError):
        await service.FlowService.get_one_flow(object(), "app-1")

    assert calls == ["visible", "edit"]


@pytest.mark.asyncio
async def test_detail_keeps_an_explicit_visible_grant(monkeypatch):
    calls = []

    async def decide(*_args, **kwargs):
        calls.append(kwargs["action"])
        return kwargs["action"] == "visible"

    _patch(monkeypatch, decide)
    result = await service.FlowService.get_one_flow(object(), "app-1")

    assert result.data["id"] == "app-1"
    assert calls == ["visible", "share"]
