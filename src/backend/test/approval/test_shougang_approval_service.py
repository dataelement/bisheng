from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision


@pytest.mark.asyncio
async def test_knowledge_space_create_submit_requires_approval_without_creating(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = SimpleNamespace(
        validate_knowledge_space_create=AsyncMock(return_value=None),
        create_knowledge_space=AsyncMock(),
    )
    approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(
            return_value=SimpleNamespace(
                decision=ApprovalGateDecision.PENDING,
                instance_id=101,
                task_ids=[201],
                model_dump=lambda: {
                    "decision": "pending",
                    "instance_id": 101,
                    "task_ids": [201],
                },
            )
        )
    )
    message_service = SimpleNamespace(send_generic_approval=AsyncMock())
    service = ShougangApprovalService(
        approval_gate=approval_gate,
        message_service=message_service,
    )
    monkeypatch.setattr(service, "_is_create_approval_exempt", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[301]))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="团队资料库",
            description="资料说明",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
            space_level=KnowledgeSpaceLevelEnum.TEAM,
            user_group_id=7,
            reason="申请创建",
        ),
        login_user=SimpleNamespace(user_id=11, user_name="申请人", tenant_id=1, is_admin=lambda: False),
        space_service=space_service,
    )

    space_service.validate_knowledge_space_create.assert_awaited_once()
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
    gate_req = approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.scenario_code == "knowledge_space_create_request"
    assert gate_req.payload_snapshot["create_params"]["name"] == "团队资料库"
    assert gate_req.payload_snapshot["create_params"]["user_group_id"] == 7
    assert result["decision"] == "pending"
    assert result["created"] is False
    message_service.send_generic_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_space_create_submit_exempt_user_creates_directly(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    created_space = SimpleNamespace(id=88)
    space_service = SimpleNamespace(
        validate_knowledge_space_create=AsyncMock(return_value=None),
        create_knowledge_space=AsyncMock(return_value=created_space),
        get_space_info=AsyncMock(return_value={"id": 88, "name": "公共资料库"}),
    )
    approval_gate = SimpleNamespace(request_or_pass=AsyncMock())
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_is_create_approval_exempt", AsyncMock(return_value=True))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="公共资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
            space_level=KnowledgeSpaceLevelEnum.PUBLIC,
        ),
        login_user=SimpleNamespace(user_id=1, user_name="管理员", tenant_id=1, is_admin=lambda: True),
        space_service=space_service,
    )

    approval_gate.request_or_pass.assert_not_called()
    space_service.create_knowledge_space.assert_awaited_once()
    assert result["created"] is True
    assert result["space"]["id"] == 88


@pytest.mark.asyncio
async def test_file_publish_source_requires_upload_file_permission():
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = SimpleNamespace(_require_permission_id=AsyncMock(return_value=None))
    source_file = SimpleNamespace(
        id=100,
        knowledge_id=10,
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )

    await ShougangApprovalService()._ensure_can_publish_file(
        source_file=source_file,
        source_level=KnowledgeSpaceLevelEnum.TEAM,
        space_service=space_service,
    )

    space_service._require_permission_id.assert_awaited_once_with(
        "knowledge_file",
        100,
        "upload_file",
        space_id=10,
    )


@pytest.mark.asyncio
async def test_file_publish_submit_requires_team_or_personal_success_file(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService(
        approval_gate=SimpleNamespace(
            request_or_pass=AsyncMock(
                return_value=SimpleNamespace(
                    decision=ApprovalGateDecision.PENDING,
                    instance_id=102,
                    task_ids=[],
                    model_dump=lambda: {
                        "decision": "pending",
                        "instance_id": 102,
                        "task_ids": [],
                    },
                )
            )
        )
    )
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="团队空间"),
                SimpleNamespace(id=100, file_name="制度.pdf", status=KnowledgeFileStatus.SUCCESS.value),
                KnowledgeSpaceLevelEnum.TEAM,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_can_publish_file", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_ensure_publish_target_space", AsyncMock(return_value=SimpleNamespace(id=20, name="公共空间")))
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    result = await service.submit_file_publish(
        req=ShougangFilePublishSubmitReq(
            source_space_id=10,
            source_file_id=100,
            target_space_id=20,
            target_document_id=None,
            reason="发布到公共空间",
        ),
        login_user=SimpleNamespace(user_id=11, user_name="申请人", tenant_id=1, is_admin=lambda: False),
    )

    gate_req = service.approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.scenario_code == "knowledge_space_file_publish_request"
    assert gate_req.payload_snapshot["source_file_id"] == 100
    assert gate_req.payload_snapshot["target_space_id"] == 20
    assert result["created"] is False


@pytest.mark.asyncio
async def test_file_publish_submit_rejects_invalid_target_document(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService(approval_gate=SimpleNamespace(request_or_pass=AsyncMock()))
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="团队空间"),
                SimpleNamespace(id=100, file_name="制度.pdf", status=KnowledgeFileStatus.SUCCESS.value),
                KnowledgeSpaceLevelEnum.TEAM,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_can_publish_file", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_ensure_publish_target_space", AsyncMock(return_value=SimpleNamespace(id=20, name="公共空间")))
    version_service = SimpleNamespace(search_version_sources=AsyncMock(return_value=[]))

    with pytest.raises(HTTPException) as exc_info:
        await service.submit_file_publish(
            req=ShougangFilePublishSubmitReq(
                source_space_id=10,
                source_file_id=100,
                target_space_id=20,
                target_document_id=999,
                reason="发布到公共空间",
            ),
            login_user=SimpleNamespace(user_id=11, user_name="申请人", tenant_id=1),
            version_service=version_service,
        )

    assert exc_info.value.status_code == 400
    service.approval_gate.request_or_pass.assert_not_called()


@pytest.mark.asyncio
async def test_file_publish_query_requires_publish_permissions(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeFileDao.query_by_id",
        AsyncMock(return_value=SimpleNamespace(id=100, knowledge_id=10)),
    )
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="团队空间"),
                SimpleNamespace(
                    id=100,
                    knowledge_id=10,
                    file_type=FileType.FILE.value,
                    status=KnowledgeFileStatus.SUCCESS.value,
                ),
                KnowledgeSpaceLevelEnum.TEAM,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_publish_target_space", AsyncMock(return_value=SimpleNamespace(id=20)))
    space_service = SimpleNamespace(_require_permission_id=AsyncMock(return_value=None))
    version_service = SimpleNamespace(get_similar_candidates_for_file_in_space=AsyncMock(return_value=[]))

    await service.list_file_publish_similar_candidates(
        source_file_id=100,
        target_space_id=20,
        version_service=version_service,
        space_service=space_service,
    )

    space_service._require_permission_id.assert_any_await("knowledge_file", 100, "upload_file", space_id=10)
    service._ensure_publish_target_space.assert_awaited_once_with(20, space_service=space_service)


@pytest.mark.asyncio
async def test_create_approval_handler_is_idempotent(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceCreateApprovalHandler

    handler = KnowledgeSpaceCreateApprovalHandler()
    existing_space = SimpleNamespace(
        id=88,
        name="团队资料库",
        metadata_fields=[{"shougang_approval": {"approval_instance_id": 101}}],
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_get_spaces_by_user",
        AsyncMock(return_value=[existing_space]),
    )

    result = await handler.on_approved(
        101,
        {
            "tenant_id": 1,
            "applicant_user_id": 11,
            "applicant_user_name": "申请人",
            "create_params": {"name": "团队资料库"},
        },
    )

    assert result == {"space_id": 88, "space_name": "团队资料库", "idempotent": True}


@pytest.mark.asyncio
async def test_file_publish_handler_reuses_existing_copied_file(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    copied_file = SimpleNamespace(
        id=188,
        user_metadata={"shougang_portal_publish": {"approval_instance_id": 102}},
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.aget_file_by_filters",
        AsyncMock(return_value=[copied_file]),
    )
    monkeypatch.setattr(handler, "_copy_file", Mock())

    result = await handler.on_approved(
        102,
        {
            "tenant_id": 1,
            "applicant_user_id": 11,
            "applicant_user_name": "申请人",
            "source_space_id": 10,
            "source_file_id": 100,
            "target_space_id": 20,
        },
    )

    assert result == {"file_id": 188, "target_space_id": 20, "version": None, "idempotent": True}
    handler._copy_file.assert_not_called()


@pytest.mark.asyncio
async def test_file_publish_handler_links_existing_file_version_once(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    copied_file = SimpleNamespace(
        id=188,
        user_metadata={"shougang_portal_publish": {"approval_instance_id": 102}},
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.aget_file_by_filters",
        AsyncMock(return_value=[copied_file]),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler._link_file_as_version",
        AsyncMock(return_value={"document_id": 300}),
    )
    monkeypatch.setattr(handler, "_copy_file", Mock())

    result = await handler.on_approved(
        102,
        {
            "tenant_id": 1,
            "applicant_user_id": 11,
            "applicant_user_name": "申请人",
            "source_space_id": 10,
            "source_file_id": 100,
            "target_space_id": 20,
            "target_document_id": 300,
        },
    )

    assert result == {"file_id": 188, "target_space_id": 20, "version": {"document_id": 300}, "idempotent": True}
    handler._copy_file.assert_not_called()


def test_shougang_scenarios_registered_in_default_presets():
    from bisheng.approval.domain.services.approval_registry import ApprovalRegistry

    presets = {preset.scenario_code: preset for preset in ApprovalRegistry.with_default_presets().list_presets()}

    assert "knowledge_space_create_request" in presets
    assert "knowledge_space_file_publish_request" in presets
    assert presets["knowledge_space_create_request"].approver_source_types == ["department_admin"]
    assert presets["knowledge_space_file_publish_request"].approver_source_types == ["department_admin"]
