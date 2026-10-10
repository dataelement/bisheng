from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.common.errcode.http_error import UnAuthorizedError
from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from bisheng.open_mcp import application
from bisheng.open_mcp.contracts import (
    KnowledgeCreateInput,
    KnowledgeFileUploadInput,
    KnowledgeListInput,
)


@pytest.mark.asyncio
async def test_list_knowledge_dispatches_kb_without_touching_http_endpoint(monkeypatch):
    user = SimpleNamespace(user_id=7, user_name="f067")
    service = AsyncMock(return_value={"data": []})
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application.KnowledgeService, "get_knowledge", service)

    command = KnowledgeListInput(type=0, page_size=5)
    result = await application.list_knowledge(
        request=application.current_request(),
        command=command,
        version_repo=object(),
        doc_repo=object(),
    )

    assert result == {"data": []}
    assert service.await_args.args[2].value == 0
    assert service.await_args.kwargs["page_size"] == 5


@pytest.mark.asyncio
async def test_list_knowledge_dispatches_space_to_existing_space_service(monkeypatch):
    user = SimpleNamespace(user_id=7, user_name="f067")
    list_spaces = AsyncMock(return_value={"data": []})
    space_service = SimpleNamespace(alist_mine_and_joined_cursor=list_spaces)
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application, "_space_service", lambda *args: space_service)

    result = await application.list_knowledge(
        request=application.current_request(),
        command=KnowledgeListInput(type=3, name="space"),
        version_repo=object(),
        doc_repo=object(),
    )

    assert result == {"data": []}
    assert list_spaces.await_args.kwargs["name"] == "space"


@pytest.mark.asyncio
async def test_create_kb_preserves_frozen_public_unreleased_semantics(monkeypatch):
    user = SimpleNamespace(user_id=7, user_name="f067")
    created = SimpleNamespace(id=67)
    create = AsyncMock(return_value=created)
    convert = AsyncMock(return_value=[{"id": 67}])
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application.KnowledgeService, "acreate_knowledge", create)
    monkeypatch.setattr(application.KnowledgeService, "aconvert_knowledge_read", convert)

    result = await application.create_knowledge(
        request=application.current_request(),
        command=KnowledgeCreateInput(
            name="f067",
            type=0,
            model="embedding",
            auth_type="private",
            is_released=True,
        ),
        version_repo=object(),
        doc_repo=object(),
    )

    command = create.await_args.args[2]
    assert command.auth_type == AuthTypeEnum.PUBLIC
    assert command.is_released is False
    assert result == {"id": 67}


@pytest.mark.asyncio
async def test_upload_kb_uses_managed_temporary_path_and_disables_callback(monkeypatch, tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"f067")
    user = SimpleNamespace(user_id=7, user_name="f067")
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(
        application.KnowledgeDao,
        "aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(type=0)),
    )
    monkeypatch.setattr(
        application.QuotaService,
        "get_knowledge_space_upload_limit_bytes",
        AsyncMock(return_value=1024),
    )
    process = AsyncMock(return_value=[{"id": 7, "knowledge_id": 67, "file_name": "f067.txt", "file_type": 1}])
    monkeypatch.setattr(application.KnowledgeService, "aprocess_knowledge_file", process)

    result = await application.upload_knowledge_file(
        request=application.current_request(),
        command=KnowledgeFileUploadInput(
            knowledge_id=67,
            file_name="f067.txt",
            content_base64="ZjA2Nw==",
        ),
        path=str(source),
        file_name="f067.txt",
        version_repo=object(),
        doc_repo=object(),
    )

    process_command = process.await_args.kwargs["req_data"]
    assert process_command.callback_url is None
    assert process_command.file_list[0].file_path == str(source)
    assert process.await_args.kwargs["upload_limit_bytes"] == 1024
    assert result["id"] == 7


@pytest.mark.asyncio
async def test_upload_preflight_rejects_kb_without_write_before_file_materialization(monkeypatch):
    user = SimpleNamespace(user_id=7, user_name="f067")
    row = SimpleNamespace(id=67, user_id=8, type=0, tenant_id=1)
    permission = AsyncMock(side_effect=UnAuthorizedError())
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(application.KnowledgeService.permission_service, "ensure_knowledge_write_async", permission)

    with pytest.raises(HTTPException) as exc_info:
        await application.ensure_upload_allowed(
            request=application.current_request(),
            command=KnowledgeFileUploadInput(
                knowledge_id=67,
                file_name="f067.txt",
                content_base64="ZjA2Nw==",
            ),
            version_repo=object(),
            doc_repo=object(),
        )

    assert exc_info.value.status_code == 403
    permission.assert_awaited_once_with(login_user=user, owner_user_id=8, knowledge_id=67)


@pytest.mark.asyncio
async def test_upload_preflight_checks_space_folder_and_tenant(monkeypatch):
    user = SimpleNamespace(user_id=7, user_name="f067")
    row = SimpleNamespace(id=67, type=3, tenant_id=1)
    require_action = AsyncMock()
    get_folder = AsyncMock(return_value=SimpleNamespace(id=9))
    ensure_tenant = Mock()
    service = SimpleNamespace(
        _require_action=require_action,
        _get_folder_for_action=get_folder,
        _ensure_space_async_task_tenant_consistency=ensure_tenant,
    )
    monkeypatch.setattr(application, "get_open_api_operator_async", AsyncMock(return_value=user))
    monkeypatch.setattr(application.KnowledgeDao, "aquery_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(application, "_space_service", lambda *args: service)

    await application.ensure_upload_allowed(
        request=application.current_request(),
        command=KnowledgeFileUploadInput(
            knowledge_id=67,
            parent_id=9,
            file_name="f067.txt",
            content_base64="ZjA2Nw==",
        ),
        version_repo=object(),
        doc_repo=object(),
    )

    require_action.assert_awaited_once_with("folder", 9, "upload_file")
    get_folder.assert_awaited_once_with(67, 9)
    ensure_tenant.assert_called_once_with(row, "upload_file")
