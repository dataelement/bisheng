from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from bisheng.approval.domain.schemas.approval_center_schema import ApprovalGateDecision


def _pending_approval_gate(instance_id: int = 101):
    return SimpleNamespace(
        request_or_pass=AsyncMock(
            return_value=SimpleNamespace(
                decision=ApprovalGateDecision.PENDING,
                instance_id=instance_id,
                task_ids=[instance_id + 100],
                model_dump=lambda: {
                    "decision": "pending",
                    "instance_id": instance_id,
                    "task_ids": [instance_id + 100],
                },
            )
        )
    )


def _create_space_service(created_id: int = 88, name: str = "资料库"):
    return SimpleNamespace(
        validate_knowledge_space_create=AsyncMock(return_value=None),
        create_knowledge_space=AsyncMock(return_value=SimpleNamespace(id=created_id)),
        get_space_info=AsyncMock(return_value={"id": created_id, "name": name}),
    )


def _login_user(user_id: int = 11, user_name: str = "申请人", tenant_id: int = 1, is_admin: bool = False):
    return SimpleNamespace(
        user_id=user_id,
        user_name=user_name,
        tenant_id=tenant_id,
        is_admin=lambda: is_admin,
    )


def _patch_non_exempt_user(monkeypatch):
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.TenantService._is_tenant_admin",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.DepartmentDao.aget_user_admin_departments",
        AsyncMock(return_value=[]),
    )


def _patch_exception_repository(monkeypatch, instance_id: int = 501):
    create_instance = AsyncMock(side_effect=lambda row: row.model_copy(update={"id": instance_id}))
    create_exception = AsyncMock(side_effect=lambda row: row)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.ApprovalInstanceRepository.create_instance",
        create_instance,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.ApprovalInstanceRepository.create_exception",
        create_exception,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.approval_gate.ApprovalGate._notify_admins_of_exception",
        AsyncMock(return_value=None),
    )
    return create_instance, create_exception


@pytest.mark.asyncio
async def test_regular_user_public_space_create_validates_as_approval_request(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    _patch_non_exempt_user(monkeypatch)
    space_service = _create_space_service(name="公共资料库")
    approval_gate = _pending_approval_gate(100)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="公共资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PUBLIC,
            reason="申请公共知识库",
        ),
        login_user=_login_user(),
        space_service=space_service,
    )

    space_service.validate_knowledge_space_create.assert_awaited_once_with(
        name="公共资料库",
        description=None,
        icon=None,
        auth_type=AuthTypeEnum.PUBLIC.value,
        is_released=False,
        space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
        department_id=None,
        user_group_id=None,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        auto_tag_custom_tags=None,
        approval_request=True,
    )


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
    assert gate_req.payload_snapshot["space_level"] == KnowledgeSpaceLevelEnum.TEAM.value
    assert gate_req.payload_snapshot["auth_type"] == AuthTypeEnum.PUBLIC.value
    assert gate_req.payload_snapshot["is_released"] is True
    assert gate_req.payload_snapshot["create_params"]["name"] == "团队资料库"
    assert gate_req.payload_snapshot["create_params"]["user_group_id"] == 7
    assert result["decision"] == "pending"
    assert result["created"] is False
    message_service.send_generic_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_space_create_creates_exception_when_scenario_disabled(monkeypatch):
    from bisheng.approval.domain.models.approval_instance import (
        ApprovalExceptionType,
        ApprovalInstanceStatus,
    )
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = SimpleNamespace(
        validate_knowledge_space_create=AsyncMock(return_value=None),
        create_knowledge_space=AsyncMock(),
    )
    approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(side_effect=ApprovalScenarioDisabledError())
    )
    create_instance, create_exception = _patch_exception_repository(monkeypatch, instance_id=501)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_is_create_approval_exempt", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="团队资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
            space_level=KnowledgeSpaceLevelEnum.TEAM,
            user_group_id=7,
            reason="申请创建",
        ),
        login_user=SimpleNamespace(user_id=11, user_name="申请人", tenant_id=1, is_admin=lambda: False),
        space_service=space_service,
    )

    space_service.create_knowledge_space.assert_not_called()
    assert result == {
        "decision": "exception",
        "instance_id": 501,
        "task_ids": [],
        "exception_type": ApprovalExceptionType.ROUTE_MISSING,
        "created": False,
    }
    saved_instance = create_instance.await_args.args[0]
    assert saved_instance.status == ApprovalInstanceStatus.EXCEPTION
    assert saved_instance.scenario_code == "knowledge_space_create_request"
    assert saved_instance.scenario_name == "知识空间创建审批"
    assert saved_instance.business_name == "新建知识库：团队资料库"
    assert saved_instance.applicant_user_id == 11
    assert saved_instance.payload_snapshot["create_params"]["name"] == "团队资料库"
    assert saved_instance.detail_snapshot["type"] == "knowledge_space_create"
    assert saved_instance.detail_snapshot["name"] == "团队资料库"
    saved_exception = create_exception.await_args.args[0]
    assert saved_exception.instance_id == 501
    assert saved_exception.exception_type == ApprovalExceptionType.ROUTE_MISSING


@pytest.mark.asyncio
async def test_system_admin_public_space_create_requires_approval_without_creating(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = _create_space_service(name="公共资料库")
    approval_gate = _pending_approval_gate(101)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="公共资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
            space_level=KnowledgeSpaceLevelEnum.PUBLIC,
        ),
        login_user=_login_user(user_id=1, user_name="系统管理员", is_admin=True),
        space_service=space_service,
    )

    space_service.validate_knowledge_space_create.assert_awaited_once()
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
    gate_req = approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.payload_snapshot["space_level"] == KnowledgeSpaceLevelEnum.PUBLIC.value
    assert result["decision"] == "pending"
    assert result["created"] is False


@pytest.mark.asyncio
async def test_system_admin_department_space_create_requires_approval_without_creating(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = _create_space_service(name="部门资料库")
    approval_gate = _pending_approval_gate(102)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="部门资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            department_id=9,
        ),
        login_user=_login_user(user_id=1, user_name="系统管理员", is_admin=True),
        space_service=space_service,
    )

    space_service.validate_knowledge_space_create.assert_awaited_once()
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
    gate_req = approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.payload_snapshot["space_level"] == KnowledgeSpaceLevelEnum.DEPARTMENT.value
    assert gate_req.payload_snapshot["department_id"] == 9
    assert result["decision"] == "pending"
    assert result["created"] is False


@pytest.mark.asyncio
async def test_regular_user_personal_public_space_create_requires_approval_without_creating(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    _patch_non_exempt_user(monkeypatch)
    space_service = _create_space_service(name="个人公开资料库")
    approval_gate = _pending_approval_gate(103)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="个人公开资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        ),
        login_user=_login_user(),
        space_service=space_service,
    )

    space_service.validate_knowledge_space_create.assert_awaited_once()
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
    gate_req = approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.payload_snapshot["space_level"] == KnowledgeSpaceLevelEnum.PERSONAL.value
    assert gate_req.payload_snapshot["space_visibility"] == AuthTypeEnum.PUBLIC.value
    assert result["decision"] == "pending"
    assert result["created"] is False


@pytest.mark.asyncio
async def test_system_admin_personal_public_space_create_skips_approval(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    space_service = _create_space_service(created_id=91, name="个人公开资料库")
    approval_gate = _pending_approval_gate(104)
    service = ShougangApprovalService(approval_gate=approval_gate)

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="个人公开资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        ),
        login_user=_login_user(user_id=1, user_name="系统管理员", is_admin=True),
        space_service=space_service,
    )

    approval_gate.request_or_pass.assert_not_called()
    space_service.create_knowledge_space.assert_awaited_once()
    assert result["created"] is True
    assert result["space"]["id"] == 91


@pytest.mark.asyncio
async def test_tenant_admin_personal_public_space_create_skips_approval(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.TenantService._is_tenant_admin",
        AsyncMock(return_value=True),
    )
    space_service = _create_space_service(created_id=92, name="个人公开资料库")
    approval_gate = _pending_approval_gate(105)
    service = ShougangApprovalService(approval_gate=approval_gate)

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="个人公开资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        ),
        login_user=_login_user(user_id=2, user_name="租户管理员"),
        space_service=space_service,
    )

    approval_gate.request_or_pass.assert_not_called()
    space_service.create_knowledge_space.assert_awaited_once()
    assert result["created"] is True
    assert result["space"]["id"] == 92


@pytest.mark.asyncio
async def test_department_admin_personal_public_space_create_skips_approval(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.TenantService._is_tenant_admin",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.DepartmentDao.aget_user_admin_departments",
        AsyncMock(return_value=[SimpleNamespace(id=9)]),
    )
    space_service = _create_space_service(created_id=93, name="个人公开资料库")
    approval_gate = _pending_approval_gate(106)
    service = ShougangApprovalService(approval_gate=approval_gate)

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="个人公开资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        ),
        login_user=_login_user(user_id=3, user_name="部门管理员"),
        space_service=space_service,
    )

    approval_gate.request_or_pass.assert_not_called()
    space_service.create_knowledge_space.assert_awaited_once()
    assert result["created"] is True
    assert result["space"]["id"] == 93


@pytest.mark.asyncio
async def test_personal_private_space_create_skips_approval_for_regular_user(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    created_space = SimpleNamespace(id=89)
    space_service = SimpleNamespace(
        validate_knowledge_space_create=AsyncMock(return_value=None),
        create_knowledge_space=AsyncMock(return_value=created_space),
        get_space_info=AsyncMock(return_value={"id": 89, "name": "私人资料库"}),
    )
    approval_gate = SimpleNamespace(request_or_pass=AsyncMock())
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_is_create_approval_exempt", AsyncMock(return_value=False))

    result = await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="私人资料库",
            auth_type=AuthTypeEnum.PRIVATE,
            is_released=False,
            space_level=KnowledgeSpaceLevelEnum.PERSONAL,
        ),
        login_user=SimpleNamespace(user_id=11, user_name="普通用户", tenant_id=1, is_admin=lambda: False),
        space_service=space_service,
    )

    approval_gate.request_or_pass.assert_not_called()
    space_service.create_knowledge_space.assert_awaited_once()
    assert result["created"] is True
    assert result["space"]["id"] == 89


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
async def test_file_publish_target_space_requires_view_space_not_upload_file(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=20, type=KnowledgeTypeEnum.SPACE.value, name="公共空间")),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC)),
    )
    space_service = SimpleNamespace(_require_permission_id=AsyncMock(return_value=None))

    await ShougangApprovalService()._ensure_publish_target_space(20, space_service=space_service)

    space_service._require_permission_id.assert_awaited_once_with("knowledge_space", 20, "view_space")


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
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_space",
        AsyncMock(return_value=SimpleNamespace(id=20, name="公共空间", space_level=KnowledgeSpaceLevelEnum.PUBLIC.value)),
    )
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
    assert gate_req.payload_snapshot["source_space_level"] == KnowledgeSpaceLevelEnum.TEAM.value
    assert gate_req.payload_snapshot["target_space_level"] == KnowledgeSpaceLevelEnum.PUBLIC.value
    assert gate_req.payload_snapshot["source_file_id"] == 100
    assert gate_req.payload_snapshot["target_space_id"] == 20
    assert result["created"] is False


@pytest.mark.asyncio
async def test_file_publish_creates_exception_when_scenario_disabled(monkeypatch):
    from bisheng.approval.domain.models.approval_instance import (
        ApprovalExceptionType,
        ApprovalInstanceStatus,
    )
    from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.common.errcode.approval import ApprovalScenarioDisabledError
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService(
        approval_gate=SimpleNamespace(
            request_or_pass=AsyncMock(side_effect=ApprovalScenarioDisabledError())
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
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_space",
        AsyncMock(return_value=SimpleNamespace(id=20, name="公共空间", space_level=KnowledgeSpaceLevelEnum.PUBLIC.value)),
    )
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    create_instance, create_exception = _patch_exception_repository(monkeypatch, instance_id=502)

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

    assert result == {
        "decision": "exception",
        "instance_id": 502,
        "task_ids": [],
        "exception_type": ApprovalExceptionType.ROUTE_MISSING,
        "created": False,
    }
    saved_instance = create_instance.await_args.args[0]
    assert saved_instance.status == ApprovalInstanceStatus.EXCEPTION
    assert saved_instance.scenario_code == "knowledge_space_file_publish_request"
    assert saved_instance.scenario_name == "知识空间文件发布审批"
    assert saved_instance.business_name == "发布文件：制度.pdf → 公共空间"
    assert saved_instance.payload_snapshot["source_file_id"] == 100
    assert saved_instance.payload_snapshot["target_space_id"] == 20
    assert saved_instance.detail_snapshot["type"] == "knowledge_space_file_publish"
    assert saved_instance.detail_snapshot["source_file_name"] == "制度.pdf"
    saved_exception = create_exception.await_args.args[0]
    assert saved_exception.instance_id == 502
    assert saved_exception.exception_type == ApprovalExceptionType.ROUTE_MISSING


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
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_space",
        AsyncMock(return_value=SimpleNamespace(id=20, name="公共空间", space_level=KnowledgeSpaceLevelEnum.PUBLIC.value)),
    )
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


@pytest.mark.asyncio
async def test_file_publish_handler_revalidates_source_and_target_scope_before_copy(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.aget_file_by_filters",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.aquery_by_id",
        AsyncMock(
            side_effect=[
                SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value, name="团队空间"),
                SimpleNamespace(id=20, type=KnowledgeTypeEnum.SPACE.value, name="个人空间"),
            ]
        ),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.query_by_id",
        AsyncMock(return_value=SimpleNamespace(id=100, knowledge_id=10, status=KnowledgeFileStatus.SUCCESS.value)),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(
            side_effect=[
                SimpleNamespace(level=KnowledgeSpaceLevelEnum.TEAM),
                SimpleNamespace(level=KnowledgeSpaceLevelEnum.PERSONAL),
            ]
        ),
    )
    monkeypatch.setattr(handler, "_copy_file", Mock())

    with pytest.raises(ValueError, match="target space must be public or department"):
        await handler.on_approved(
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

    handler._copy_file.assert_not_called()


def test_shougang_scenarios_registered_in_default_presets():
    from bisheng.approval.domain.services.approval_registry import ApprovalRegistry

    presets = {preset.scenario_code: preset for preset in ApprovalRegistry.with_default_presets().list_presets()}

    assert "knowledge_space_create_request" in presets
    assert "knowledge_space_file_publish_request" in presets
    assert presets["knowledge_space_create_request"].condition_fields == [
        "applicant_role",
        "space_level",
        "space_visibility",
    ]
    assert presets["knowledge_space_create_request"].approver_source_types == [
        "direct_user",
        "department_admin",
    ]
    assert presets["knowledge_space_file_publish_request"].condition_fields == [
        "applicant_role",
        "source_space_level",
        "target_space_level",
        "target_space_id",
    ]
    assert presets["knowledge_space_file_publish_request"].approver_source_types == [
        "direct_user",
        "department_admin",
        "knowledge_space_owner",
        "knowledge_space_manager",
    ]
    create_field_options = {
        option.field: option.model_dump()
        for option in presets["knowledge_space_create_request"].condition_field_options
    }
    assert create_field_options["space_level"]["type"] == "select"
    assert [item["value"] for item in create_field_options["space_level"]["values"]] == [
        "public",
        "department",
        "team",
        "personal",
    ]
    assert create_field_options["space_visibility"]["type"] == "select"
    assert [item["value"] for item in create_field_options["space_visibility"]["values"]] == [
        "released",
        "public",
        "approval",
        "private",
    ]
    publish_field_options = {
        option.field: option.model_dump()
        for option in presets["knowledge_space_file_publish_request"].condition_field_options
    }
    assert publish_field_options["target_space_id"]["type"] == "selector"
    assert publish_field_options["target_space_id"]["selector_type"] == "knowledge_space_publish_target"
    assert [
        option.source_type
        for option in presets["knowledge_space_file_publish_request"].approver_source_options
    ] == [
        "direct_user",
        "department_admin",
        "knowledge_space_owner",
        "knowledge_space_manager",
    ]


@pytest.mark.asyncio
async def test_file_publish_handler_resolves_target_space_owner_and_manager(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler._resolve_space_roles_via_fga",
        AsyncMock(return_value=([31], [32, 33])),
    )

    approvers = await handler.resolve_approvers(
        {
            "sources": [
                {"type": "direct_user", "user_ids": [33, 34]},
                {"type": "knowledge_space_owner"},
                {"type": "knowledge_space_manager"},
            ]
        },
        SimpleNamespace(
            tenant_id=1,
            applicant_user_id=11,
            applicant_department_id=None,
            payload_snapshot={"target_space_id": 20},
        ),
    )

    assert approvers == [33, 34, 31, 32]
