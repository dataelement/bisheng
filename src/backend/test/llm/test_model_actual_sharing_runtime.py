"""Runtime model reads never confuse inherited defaults with actual sharing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.llm.domain import share_fallback as fallback


@pytest.fixture(autouse=True)
def execution_tenant():
    previous = get_current_tenant_id()
    set_current_tenant_id(101)
    yield
    set_current_tenant_id(previous)


@pytest.mark.parametrize("sync", [True, False])
@pytest.mark.parametrize("kind", ["model", "server"])
async def test_runtime_root_sharing_is_checked_fresh_after_revocation(monkeypatch, sync, kind):
    row = SimpleNamespace(id=11 if kind == "model" else 2, server_id=2, tenant_id=1)
    relation = SimpleNamespace(
        list_resource_ids_sync=Mock(return_value=["2"]), list_resource_ids=AsyncMock(return_value=["2"])
    )
    monkeypatch.setattr(fallback, "get_permission_relation_api_sync", lambda: relation)
    monkeypatch.setattr(fallback, "get_permission_relation_api", AsyncMock(return_value=relation))
    name = f"{'get' if sync else 'aget'}_{kind}_by_id"
    lookup = Mock(return_value=row) if sync else AsyncMock(return_value=row)
    monkeypatch.setattr(fallback.LLMDao, name, lookup)
    method = getattr(fallback, f"{name}_with_share_fallback")
    assert (method(row.id, cache=True) if sync else await method(row.id, cache=True)) is row
    relation.list_resource_ids_sync.return_value = []
    relation.list_resource_ids.return_value = []
    assert (method(row.id, cache=True) if sync else await method(row.id, cache=True)) is None
    assert all(call.kwargs["cache"] is False for call in lookup.call_args_list)


@pytest.mark.parametrize("sync", [True, False])
@pytest.mark.parametrize("owner,allowed", [(101, True), (202, False), (1, False)])
async def test_runtime_owner_or_actual_relation_is_required(monkeypatch, sync, owner, allowed):
    row = SimpleNamespace(id=11, server_id=2, tenant_id=owner)
    relation = SimpleNamespace(
        list_resource_ids_sync=Mock(return_value=[]), list_resource_ids=AsyncMock(return_value=[])
    )
    monkeypatch.setattr(fallback, "get_permission_relation_api_sync", lambda: relation)
    monkeypatch.setattr(fallback, "get_permission_relation_api", AsyncMock(return_value=relation))
    name = "get_model_by_id" if sync else "aget_model_by_id"
    monkeypatch.setattr(fallback.LLMDao, name, Mock(return_value=row) if sync else AsyncMock(return_value=row))
    result = (
        fallback.get_model_by_id_with_share_fallback(11)
        if sync
        else await fallback.aget_model_by_id_with_share_fallback(11)
    )
    assert (result is row) is allowed


@pytest.mark.parametrize("sync", [True, False])
async def test_single_tenant_without_ambient_context_retains_root_compatibility(monkeypatch, sync):
    from bisheng.common.services.config_service import settings

    set_current_tenant_id(None)
    monkeypatch.setattr(settings.multi_tenant, "enabled", False)
    row = SimpleNamespace(id=11, server_id=2, tenant_id=1)
    name = "get_model_by_id" if sync else "aget_model_by_id"
    monkeypatch.setattr(fallback.LLMDao, name, Mock(return_value=row) if sync else AsyncMock(return_value=row))
    result = (
        fallback.get_model_by_id_with_share_fallback(11)
        if sync
        else await fallback.aget_model_by_id_with_share_fallback(11)
    )
    assert result is row


@pytest.mark.parametrize("sync", [True, False])
async def test_multi_tenant_without_execution_context_is_refused(monkeypatch, sync):
    from bisheng.common.errcode.tenant import NoTenantContextError
    from bisheng.common.services.config_service import settings

    set_current_tenant_id(None)
    monkeypatch.setattr(settings.multi_tenant, "enabled", True)
    row = SimpleNamespace(id=11, server_id=2, tenant_id=1)
    name = "get_model_by_id" if sync else "aget_model_by_id"
    monkeypatch.setattr(fallback.LLMDao, name, Mock(return_value=row) if sync else AsyncMock(return_value=row))
    with pytest.raises(NoTenantContextError):
        if sync:
            fallback.get_model_by_id_with_share_fallback(11)
        else:
            await fallback.aget_model_by_id_with_share_fallback(11)


@pytest.mark.parametrize("intent,actual_children", [(False, [101]), (True, [])])
async def test_root_provider_detail_dispatches_to_sharing_status_instance(monkeypatch, intent, actual_children):
    from bisheng.common.dependencies.user_deps import UserPayload
    from bisheng.database.models.tenant import TenantDao
    from bisheng.llm.application import model_sharing_status
    from bisheng.llm.domain.models.llm_server import LLMServer
    from bisheng.llm.domain.services import llm as service

    set_current_tenant_id(1)
    user = UserPayload(user_id=7, user_name="root-admin", tenant_id=1, user_role=[], is_global_super=True)
    server = LLMServer(id=2, tenant_id=1, name="provider", type="openai")
    calls = []

    class Status:
        async def aget(self, *, identity, server_id, include_coverage=True):
            assert self is not None
            calls.append((identity, server_id, include_coverage))
            return {"enabled": intent}

    monkeypatch.setattr(model_sharing_status, "ModelSharingStatusService", Status)
    monkeypatch.setattr(service.LLMDao, "aget_server_by_id", AsyncMock(return_value=server))
    monkeypatch.setattr(service.LLMDao, "aget_model_by_server_ids", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "_check_is_global_super", AsyncMock(return_value=True))
    monkeypatch.setattr(service.ResourceShareService, "list_sharing_children", AsyncMock(return_value=actual_children))
    monkeypatch.setattr(TenantDao, "aget_by_id", AsyncMock(return_value=None))
    detail = await service.LLMService.get_one_llm(server.id, operator=user)
    assert detail.share_to_children is intent and not detail.is_root_shared_readonly
    assert calls == [(user, server.id, False)]
