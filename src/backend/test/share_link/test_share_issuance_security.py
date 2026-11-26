"""Grant issuance must authorize every resource encoded into a share token."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.permission.application import business_authorization
from bisheng.share_link.api.schemas.share_link_schema import GenerateShareLinkRequest
from bisheng.share_link.domain.services.share_link_service import ShareLinkService


def actor():
    return SimpleNamespace(user_id=11, tenant_id=7)


@pytest.mark.parametrize("resource_type", ["workflow", "assistant"])
async def test_unauthorized_app_share_never_saves(monkeypatch, resource_type):
    monkeypatch.setattr(business_authorization, "require_business_action", AsyncMock(side_effect=UnAuthorizedError()))
    monkeypatch.setattr(
        "bisheng.database.models.flow.FlowDao.aget_flow_by_id",
        AsyncMock(return_value=SimpleNamespace(id="app", tenant_id=7, flow_type=10, is_delete=0)),
    )
    monkeypatch.setattr(
        "bisheng.database.models.assistant.AssistantDao.aget_one_assistant",
        AsyncMock(return_value=SimpleNamespace(id="app", tenant_id=7, is_delete=0)),
    )
    monkeypatch.setattr("bisheng.database.models.session.MessageSessionDao.async_get_one", AsyncMock(return_value=None))
    repository = SimpleNamespace(save=AsyncMock())
    with pytest.raises(UnAuthorizedError):
        await ShareLinkService(repository).generate_share_link(
            GenerateShareLinkRequest(resource_type=resource_type, resource_id="app"), actor()
        )
    repository.save.assert_not_awaited()


@pytest.mark.parametrize("subject_type", [None, "public_v3", "service_account"])
async def test_foreign_or_api_session_cannot_be_shared(monkeypatch, subject_type):
    monkeypatch.setattr(
        "bisheng.database.models.session.MessageSessionDao.async_get_one",
        AsyncMock(
            return_value=SimpleNamespace(
                chat_id="chat",
                tenant_id=7,
                user_id=22 if subject_type is None else 11,
                api_subject_type=subject_type,
                is_delete=False,
                flow_id="app",
                flow_type=15,
            )
        ),
    )
    repository = SimpleNamespace(save=AsyncMock())
    with pytest.raises(UnAuthorizedError):
        await ShareLinkService(repository).generate_share_link(
            GenerateShareLinkRequest(resource_type="workbench_chat", resource_id="chat"), actor()
        )
    repository.save.assert_not_awaited()


@pytest.fixture
def owned_boundary(monkeypatch):
    monkeypatch.setattr(
        "bisheng.share_link.domain.services.share_target_authorization.get_current_tenant_id", lambda: 7
    )
    session = SimpleNamespace(
        chat_id="chat", tenant_id=7, user_id=11, api_subject_type=None, is_delete=False, flow_id="app", flow_type=10
    )
    monkeypatch.setattr(
        "bisheng.database.models.session.MessageSessionDao.async_get_one",
        AsyncMock(side_effect=lambda rid: session if rid == "chat" else None),
    )
    resource = SimpleNamespace(id="app", tenant_id=7, flow_type=10, is_delete=0)
    monkeypatch.setattr("bisheng.database.models.flow.FlowDao.aget_flow_by_id", AsyncMock(return_value=resource))
    monkeypatch.setattr(
        "bisheng.database.models.assistant.AssistantDao.aget_one_assistant", AsyncMock(return_value=resource)
    )
    permission = AsyncMock()
    monkeypatch.setattr(business_authorization, "require_business_action", permission)
    return session, resource, permission


@pytest.mark.parametrize("shape", ["direct", "conversation"])
async def test_authorized_workflow_share_preserves_both_request_shapes(owned_boundary, shape):
    repository = SimpleNamespace(save=AsyncMock(side_effect=lambda value: value))
    request = GenerateShareLinkRequest(
        resource_type="workflow",
        resource_id="chat" if shape == "conversation" else "app",
        meta_data={"flowId": "app"} if shape == "conversation" else None,
    )
    result = await ShareLinkService(repository).generate_share_link(request, actor())
    assert result.resource_id == request.resource_id
    assert result.tenant_id == 7
    assert owned_boundary[2].await_count == 1
    assert owned_boundary[2].await_args.args[0].user_id == 11
    assert owned_boundary[2].await_args.kwargs == {"resource_type": "workflow", "resource_id": "app", "action": "share"}
    repository.save.assert_awaited_once()


@pytest.mark.parametrize("metadata", [{"flowId": "foreign"}, {"versionId": "foreign"}])
async def test_direct_share_cannot_smuggle_another_target(owned_boundary, metadata):
    repository = SimpleNamespace(save=AsyncMock())
    with pytest.raises(UnAuthorizedError):
        await ShareLinkService(repository).generate_share_link(
            GenerateShareLinkRequest(resource_type="workflow", resource_id="app", meta_data=metadata), actor()
        )
    repository.save.assert_not_awaited()


async def test_foreign_tenant_app_cannot_use_superadmin_shortcut(owned_boundary):
    owned_boundary[1].tenant_id = 8
    repository = SimpleNamespace(save=AsyncMock())
    with pytest.raises(UnAuthorizedError):
        await ShareLinkService(repository).generate_share_link(
            GenerateShareLinkRequest(resource_type="workflow", resource_id="app"), actor()
        )
    owned_boundary[2].assert_not_awaited()
    repository.save.assert_not_awaited()


async def test_editable_capability_requires_edit_action(owned_boundary):
    repository = SimpleNamespace(save=AsyncMock(side_effect=lambda value: value))
    await ShareLinkService(repository).generate_share_link(
        GenerateShareLinkRequest(resource_type="workflow", resource_id="app", share_mode="editable"), actor()
    )
    assert [call.kwargs["action"] for call in owned_boundary[2].await_args_list] == ["share", "edit"]


async def test_workbench_metadata_also_requires_actual_app_share(owned_boundary):
    repository = SimpleNamespace(save=AsyncMock(side_effect=lambda value: value))
    await ShareLinkService(repository).generate_share_link(
        GenerateShareLinkRequest(resource_type="workbench_chat", resource_id="chat", meta_data={"flowId": "app"}),
        actor(),
    )
    assert owned_boundary[2].await_args.kwargs == {"resource_type": "workflow", "resource_id": "app", "action": "share"}


async def test_own_workbench_without_app_export_stays_supported(owned_boundary):
    owned_boundary[0].flow_type = 15
    owned_boundary[0].flow_id = ""
    repository = SimpleNamespace(save=AsyncMock(side_effect=lambda value: value))
    await ShareLinkService(repository).generate_share_link(
        GenerateShareLinkRequest(resource_type="workbench_chat", resource_id="chat", meta_data={"flowId": ""}), actor()
    )
    repository.save.assert_awaited_once()
    owned_boundary[2].assert_not_awaited()


async def test_conversation_metadata_cannot_substitute_app(owned_boundary):
    repository = SimpleNamespace(save=AsyncMock())
    with pytest.raises(UnAuthorizedError):
        await ShareLinkService(repository).generate_share_link(
            GenerateShareLinkRequest(resource_type="workflow", resource_id="chat", meta_data={"flowId": "foreign"}),
            actor(),
        )
    repository.save.assert_not_awaited()


@pytest.mark.parametrize("version_session,allowed", [("chat", True), ("foreign", False)])
async def test_version_metadata_binds_to_real_owned_parent(monkeypatch, owned_boundary, version_session, allowed):
    owned_boundary[0].flow_type = 15
    monkeypatch.setattr(
        "bisheng.linsight.domain.models.linsight_session_version.LinsightSessionVersionDao.get_by_id",
        AsyncMock(return_value=SimpleNamespace(session_id=version_session, tenant_id=7, user_id=11)),
    )
    repository = SimpleNamespace(save=AsyncMock(side_effect=lambda value: value))
    request = GenerateShareLinkRequest(
        resource_type="linsight_session", resource_id="chat", meta_data={"versionId": "v1"}
    )
    if allowed:
        await ShareLinkService(repository).generate_share_link(request, actor())
        repository.save.assert_awaited_once()
    else:
        with pytest.raises(UnAuthorizedError):
            await ShareLinkService(repository).generate_share_link(request, actor())
        repository.save.assert_not_awaited()
