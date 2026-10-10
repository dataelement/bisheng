"""Real read adapter rejects invalid membership without persisting anything."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.eplus.infrastructure import debug_adapters as module


@pytest.mark.parametrize(
    "user,membership",
    [
        (None, SimpleNamespace(tenant_id=7, status="active")),
        (SimpleNamespace(delete=1), SimpleNamespace(tenant_id=7, status="active")),
        (SimpleNamespace(delete=0), None),
        (SimpleNamespace(delete=0), SimpleNamespace(tenant_id=8, status="active")),
        (SimpleNamespace(delete=0), SimpleNamespace(tenant_id=7, status="disabled")),
    ],
)
async def test_reader_rejects_absent_deleted_disabled_or_cross_tenant_user(monkeypatch, user, membership):
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(module.AssistantDao, "aget_one_assistant", AsyncMock(return_value=SimpleNamespace(id="a")))
    monkeypatch.setattr(
        module.EPlusConfigRepository, "get_by_assistant_id", AsyncMock(return_value=SimpleNamespace(is_deleted=False))
    )
    monkeypatch.setattr(module.UserDao, "aget_user", AsyncMock(return_value=user))
    monkeypatch.setattr(module.UserTenantDao, "aget_active_user_tenant", AsyncMock(return_value=membership))
    session = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await module.PlatformDebugReader(session).load_context("a", 2, 1)
    assert error.value.status_code == 403
    session.commit.assert_not_awaited()


async def test_reader_returns_only_bound_valid_spaces_and_rereads_each_request(monkeypatch):
    monkeypatch.setattr(module, "get_current_tenant_id", lambda: 7)
    monkeypatch.setattr(module.AssistantDao, "aget_one_assistant", AsyncMock(return_value=SimpleNamespace(id="a")))
    monkeypatch.setattr(
        module.EPlusConfigRepository,
        "get_by_assistant_id",
        AsyncMock(return_value=SimpleNamespace(id=3, is_deleted=False, scope_version=1, bot_id="bot")),
    )
    monkeypatch.setattr(
        module.UserDao,
        "aget_user",
        AsyncMock(return_value=SimpleNamespace(delete=0, user_name="U", external_id="wecom-original")),
    )
    monkeypatch.setattr(
        module.UserTenantDao,
        "aget_active_user_tenant",
        AsyncMock(return_value=SimpleNamespace(tenant_id=7, status="active")),
    )
    ids = AsyncMock(side_effect=[[11], [12]])
    monkeypatch.setattr(module.EPlusConfigRepository, "list_space_ids", ids)
    monkeypatch.setattr(
        module.SqlSpaceReader,
        "list_valid_spaces",
        AsyncMock(
            return_value=[
                SimpleNamespace(id=11, name="Dept"),
                SimpleNamespace(id=12, name="Other"),
                SimpleNamespace(id=99, name="Unbound"),
            ]
        ),
    )
    session = AsyncMock()
    first = await module.PlatformDebugReader(session).load_context("a", 2, 1)
    second = await module.PlatformDebugReader(session).load_context("a", 2, 1)
    assert first.spaces == ({"id": 11, "name": "Dept"},)
    assert second.spaces == ({"id": 12, "name": "Other"},)
    assert first.external_user_id == "wecom-original"
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
