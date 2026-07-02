import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import ANY, AsyncMock, Mock

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
async def test_regular_user_public_level_space_create_is_rejected_without_approval_record(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.common.errcode.knowledge_space import SpaceCreatePublicDeniedError
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    _patch_non_exempt_user(monkeypatch)
    space_service = _create_space_service(name="公共资料库")

    async def _validate_public_create(**kwargs):
        if kwargs["approval_request"]:
            return None
        raise SpaceCreatePublicDeniedError()

    space_service.validate_knowledge_space_create.side_effect = _validate_public_create
    approval_gate = _pending_approval_gate(100)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    with pytest.raises(SpaceCreatePublicDeniedError):
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
        approval_request=False,
    )
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_not_called()


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
    assert "business_domain_codes" not in gate_req.payload_snapshot
    assert gate_req.payload_snapshot["create_params"]["name"] == "团队资料库"
    assert gate_req.payload_snapshot["create_params"]["user_group_id"] is None
    assert "business_domain_codes" not in gate_req.payload_snapshot["create_params"]
    assert result["decision"] == "pending"
    assert result["created"] is False
    message_service.send_generic_approval.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_space_create_team_without_user_group_is_validated_before_approval(monkeypatch):
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
    approval_gate = _pending_approval_gate()
    message_service = SimpleNamespace(send_generic_approval=AsyncMock())
    service = ShougangApprovalService(
        approval_gate=approval_gate,
        message_service=message_service,
    )
    monkeypatch.setattr(service, "_is_create_approval_exempt", AsyncMock(return_value=False))
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[301]))

    await service.submit_knowledge_space_create(
        req=ShougangKnowledgeSpaceCreateSubmitReq(
            name="团队资料库",
            auth_type=AuthTypeEnum.PUBLIC,
            is_released=True,
            space_level=KnowledgeSpaceLevelEnum.TEAM,
            reason="申请创建",
        ),
        login_user=SimpleNamespace(user_id=11, user_name="申请人", tenant_id=1, is_admin=lambda: False),
        space_service=space_service,
    )

    validate_kwargs = space_service.validate_knowledge_space_create.await_args.kwargs
    assert validate_kwargs["space_level"] == KnowledgeSpaceLevelEnum.TEAM.value
    assert validate_kwargs["user_group_id"] is None
    assert "business_domain_codes" not in validate_kwargs
    assert validate_kwargs["approval_request"] is True
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
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
    assert "business_domain_codes" not in saved_instance.payload_snapshot
    assert "business_domain_codes" not in saved_instance.payload_snapshot["create_params"]
    assert saved_instance.detail_snapshot["type"] == "knowledge_space_create"
    assert saved_instance.detail_snapshot["name"] == "团队资料库"
    assert "business_domain_codes" not in saved_instance.detail_snapshot
    saved_exception = create_exception.await_args.args[0]
    assert saved_exception.instance_id == 501
    assert saved_exception.exception_type == ApprovalExceptionType.ROUTE_MISSING


@pytest.mark.asyncio
async def test_system_admin_public_level_space_create_skips_approval_and_creates_directly(monkeypatch):
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
    assert space_service.validate_knowledge_space_create.await_args.kwargs["approval_request"] is False
    space_service.create_knowledge_space.assert_awaited_once()
    approval_gate.request_or_pass.assert_not_called()
    assert result["decision"] == "pass"
    assert result["created"] is True
    assert result["space"]["id"] == 88


@pytest.mark.asyncio
async def test_regular_user_department_space_create_is_rejected_without_approval_record(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangKnowledgeSpaceCreateSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import (
        ShougangApprovalService,
    )
    from bisheng.common.errcode.knowledge_space import SpaceCreateDepartmentDeniedError
    from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    _patch_non_exempt_user(monkeypatch)
    space_service = _create_space_service(name="部门资料库")

    async def _validate_department_create(**kwargs):
        if kwargs["approval_request"]:
            return None
        raise SpaceCreateDepartmentDeniedError()

    space_service.validate_knowledge_space_create.side_effect = _validate_department_create
    approval_gate = _pending_approval_gate(102)
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    with pytest.raises(SpaceCreateDepartmentDeniedError):
        await service.submit_knowledge_space_create(
            req=ShougangKnowledgeSpaceCreateSubmitReq(
                name="部门资料库",
                auth_type=AuthTypeEnum.PUBLIC,
                is_released=False,
                space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                department_id=9,
                reason="申请业务域知识库",
            ),
            login_user=_login_user(),
            space_service=space_service,
        )

    space_service.validate_knowledge_space_create.assert_awaited_once_with(
        name="部门资料库",
        description=None,
        icon=None,
        auth_type=AuthTypeEnum.PUBLIC.value,
        is_released=False,
        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT.value,
        department_id=9,
        user_group_id=None,
        auto_tag_enabled=False,
        auto_tag_library_id=None,
        auto_tag_custom_tags=None,
        approval_request=False,
    )
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_not_called()


@pytest.mark.asyncio
async def test_system_admin_department_space_create_skips_approval_and_creates_directly(monkeypatch):
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
    assert space_service.validate_knowledge_space_create.await_args.kwargs["approval_request"] is False
    space_service.create_knowledge_space.assert_awaited_once()
    approval_gate.request_or_pass.assert_not_called()
    assert result["decision"] == "pass"
    assert result["created"] is True
    assert result["space"]["id"] == 88


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
async def test_department_admin_personal_public_space_create_uses_approval_gate(monkeypatch):
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
    space_service = _create_space_service(created_id=93, name="个人公开资料库")
    approval_gate = SimpleNamespace(
        request_or_pass=AsyncMock(
            return_value=SimpleNamespace(
                decision=ApprovalGateDecision.PASS,
                instance_id=106,
                task_ids=[],
                model_dump=lambda: {
                    "decision": "pass",
                    "instance_id": 106,
                    "task_ids": [],
                },
            )
        )
    )
    service = ShougangApprovalService(approval_gate=approval_gate)
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))

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

    space_service.validate_knowledge_space_create.assert_awaited_once()
    validate_kwargs = space_service.validate_knowledge_space_create.await_args.kwargs
    assert validate_kwargs["approval_request"] is True
    space_service.create_knowledge_space.assert_not_called()
    approval_gate.request_or_pass.assert_awaited_once()
    gate_req = approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.payload_snapshot["space_level"] == KnowledgeSpaceLevelEnum.PERSONAL.value
    assert result["decision"] == "pass"
    assert result["instance_id"] == 106
    assert result["created"] is False


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
async def test_file_publish_source_requires_publish_file_permission():
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
        "knowledge_space",
        10,
        "publish_file",
    )


@pytest.mark.asyncio
async def test_file_publish_rules_allow_department_source_to_public_target(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    source_file = SimpleNamespace(
        id=100,
        knowledge_id=10,
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
    )
    space_service = SimpleNamespace(_require_permission_id=AsyncMock(return_value=None))
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=20, type=KnowledgeTypeEnum.SPACE.value, name="公共空间")),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC)),
    )

    service = ShougangApprovalService()
    await service._ensure_can_publish_file(
        source_file=source_file,
        source_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        space_service=space_service,
    )
    await service._ensure_publish_target_space(
        20,
        source_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
        space_service=space_service,
    )

    space_service._require_permission_id.assert_any_await("knowledge_space", 10, "publish_file")
    space_service._require_permission_id.assert_any_await("knowledge_space", 20, "view_space")


@pytest.mark.asyncio
async def test_file_publish_target_space_validation_does_not_mutate_knowledge_model(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    target_space = Knowledge(id=20, name="公共空间", type=KnowledgeTypeEnum.SPACE.value)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=target_space),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC)),
    )

    result = await ShougangApprovalService()._ensure_publish_target_space(
        20,
        source_level=KnowledgeSpaceLevelEnum.TEAM,
        space_service=SimpleNamespace(_require_permission_id=AsyncMock(return_value=None)),
    )

    assert result is target_space


@pytest.mark.asyncio
async def test_file_publish_rules_reject_personal_source_to_personal_target(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=20, type=KnowledgeTypeEnum.SPACE.value, name="个人空间")),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=None),
    )

    with pytest.raises(HTTPException, match="目标知识空间类型不允许发布"):
        await ShougangApprovalService()._ensure_publish_target_space(
            20,
            source_level=KnowledgeSpaceLevelEnum.PERSONAL,
            space_service=SimpleNamespace(_require_permission_id=AsyncMock(return_value=None)),
        )


@pytest.mark.parametrize(
    ("source_level", "target_level"),
    [
        ("PERSONAL", "PUBLIC"),
        ("PERSONAL", "DEPARTMENT"),
        ("PERSONAL", "TEAM"),
        ("TEAM", "PUBLIC"),
        ("TEAM", "DEPARTMENT"),
        ("DEPARTMENT", "PUBLIC"),
    ],
)
def test_file_publish_matrix_allows_required_pairs(source_level, target_level):
    from bisheng.approval.domain.services import shougang_approval_handler as handler_mod
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    source = getattr(KnowledgeSpaceLevelEnum, source_level)
    target = getattr(KnowledgeSpaceLevelEnum, target_level)

    assert ShougangApprovalService._is_file_publish_pair_allowed(source, target) is True
    assert handler_mod._file_publish_pair_allowed(source, target) is True


@pytest.mark.parametrize(
    ("source_level", "target_level"),
    [
        ("PERSONAL", "PERSONAL"),
        ("TEAM", "TEAM"),
        ("TEAM", "PERSONAL"),
        ("DEPARTMENT", "DEPARTMENT"),
        ("DEPARTMENT", "TEAM"),
        ("DEPARTMENT", "PERSONAL"),
        ("PUBLIC", "PUBLIC"),
        ("PUBLIC", "DEPARTMENT"),
        ("PUBLIC", "TEAM"),
        ("PUBLIC", "PERSONAL"),
    ],
)
def test_file_publish_matrix_rejects_disallowed_pairs(source_level, target_level):
    from bisheng.approval.domain.services import shougang_approval_handler as handler_mod
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    source = getattr(KnowledgeSpaceLevelEnum, source_level)
    target = getattr(KnowledgeSpaceLevelEnum, target_level)

    assert ShougangApprovalService._is_file_publish_pair_allowed(source, target) is False
    assert handler_mod._file_publish_pair_allowed(source, target) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_level", "expected_ids"),
    [
        ("PERSONAL", [101, 201, 301]),
        ("TEAM", [101, 201]),
        ("DEPARTMENT", [101]),
    ],
)
async def test_file_publish_target_spaces_follow_source_matrix(monkeypatch, source_level, expected_ids):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    def space(space_id, level):
        return SimpleNamespace(id=space_id, name=f"space-{space_id}", space_level=level, owner_name=None)

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value, name="源空间")),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=getattr(KnowledgeSpaceLevelEnum, source_level))),
    )
    space_service = SimpleNamespace(
        get_grouped_spaces=AsyncMock(return_value=SimpleNamespace(
            public_spaces=[space(101, KnowledgeSpaceLevelEnum.PUBLIC)],
            department_spaces=[space(201, KnowledgeSpaceLevelEnum.DEPARTMENT)],
            team_spaces=[space(301, KnowledgeSpaceLevelEnum.TEAM)],
        ))
    )

    result = await ShougangApprovalService().list_file_publish_target_spaces(
        source_space_id=10,
        space_service=space_service,
    )

    assert [item.id for item in result.data] == expected_ids


@pytest.mark.asyncio
async def test_file_publish_target_spaces_reject_public_source(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=SimpleNamespace(id=10, type=KnowledgeTypeEnum.SPACE.value, name="公共空间")),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(return_value=SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC)),
    )
    space_service = SimpleNamespace(get_grouped_spaces=AsyncMock())

    with pytest.raises(HTTPException, match="当前知识空间类型不支持发布文件"):
        await ShougangApprovalService().list_file_publish_target_spaces(
            source_space_id=10,
            space_service=space_service,
        )

    space_service.get_grouped_spaces.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_publish_submit_persists_target_folder_snapshot(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService(approval_gate=_pending_approval_gate(118))
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="个人空间"),
                SimpleNamespace(
                    id=100,
                    knowledge_id=10,
                    file_name="制度.pdf",
                    file_type=FileType.FILE.value,
                    status=KnowledgeFileStatus.SUCCESS.value,
                ),
                KnowledgeSpaceLevelEnum.PERSONAL,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_can_publish_file", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_space",
        AsyncMock(return_value=SimpleNamespace(id=20, name="团队空间", space_level=KnowledgeSpaceLevelEnum.TEAM)),
    )
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_folder",
        AsyncMock(return_value=SimpleNamespace(id=301, file_name="制度目录", level=2, file_level_path="/300")),
    )
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_task_approver_user_ids", AsyncMock(return_value=[]))

    await service.submit_file_publish(
        req=ShougangFilePublishSubmitReq(
            source_space_id=10,
            source_file_id=100,
            target_space_id=20,
            target_folder_id=301,
        ),
        login_user=_login_user(),
    )

    service._ensure_publish_target_space.assert_awaited_once_with(
        20,
        source_level=KnowledgeSpaceLevelEnum.PERSONAL,
        space_service=None,
    )
    service._ensure_publish_target_folder.assert_awaited_once_with(20, 301, space_service=None)
    gate_req = service.approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.payload_snapshot["target_folder_id"] == 301
    assert gate_req.payload_snapshot["target_folder_name"] == "制度目录"
    assert gate_req.payload_snapshot["target_folder_level"] == 3
    assert gate_req.payload_snapshot["target_folder_level_path"] == "/300/301"


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

    await ShougangApprovalService()._ensure_publish_target_space(
        20,
        source_level=KnowledgeSpaceLevelEnum.TEAM,
        space_service=space_service,
    )

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
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="公共空间",
                space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
        ),
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
async def test_file_publish_submit_allows_retry_after_route_missing_exception(monkeypatch):
    from bisheng.approval.domain.models.approval_instance import ApprovalInstanceStatus
    from bisheng.approval.domain.schemas.shougang_approval_schema import ShougangFilePublishSubmitReq
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    service = ShougangApprovalService(
        approval_gate=SimpleNamespace(
            request_or_pass=AsyncMock(
                return_value=SimpleNamespace(
                    decision=ApprovalGateDecision.PASS,
                    instance_id=103,
                    task_ids=[],
                    model_dump=lambda: {
                        "decision": "pass",
                        "instance_id": 103,
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
                SimpleNamespace(id=82, name="有数据"),
                SimpleNamespace(id=222, file_name="wod照片.docx", status=KnowledgeFileStatus.SUCCESS.value),
                KnowledgeSpaceLevelEnum.PERSONAL,
            )
        ),
    )
    monkeypatch.setattr(service, "_ensure_can_publish_file", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service,
        "_ensure_publish_target_space",
        AsyncMock(return_value=SimpleNamespace(id=24, name="系统", space_level=KnowledgeSpaceLevelEnum.PUBLIC.value)),
    )
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=3))
    monkeypatch.setattr(service, "_send_approval_message", AsyncMock(return_value=None))

    result = await service.submit_file_publish(
        req=ShougangFilePublishSubmitReq(
            source_space_id=82,
            source_file_id=222,
            target_space_id=24,
            target_document_id=None,
        ),
        login_user=SimpleNamespace(user_id=5, user_name="00011", tenant_id=1, is_admin=lambda: False),
    )

    gate_req = service.approval_gate.request_or_pass.await_args.args[0]
    assert gate_req.duplicate_active_statuses == [
        ApprovalInstanceStatus.PENDING,
        ApprovalInstanceStatus.EXECUTE_FAILED,
    ]
    assert result["decision"] == "pass"


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
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="公共空间",
                space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
        ),
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
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="公共空间",
                space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
        ),
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

    space_service._require_permission_id.assert_any_await("knowledge_space", 10, "publish_file")
    service._ensure_publish_target_space.assert_awaited_once_with(
        20,
        source_level=KnowledgeSpaceLevelEnum.TEAM,
        space_service=space_service,
    )


@pytest.mark.asyncio
async def test_file_publish_similar_candidates_filters_by_file_view_permission(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.schemas.knowledge_version_schema import SimilarCandidateEntry
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

    async def require_permission(object_type, object_id, permission_id, *, space_id=None):
        if object_type == "knowledge_file" and object_id == 201:
            raise SpacePermissionDeniedError()

    space_service = SimpleNamespace(_require_permission_id=AsyncMock(side_effect=require_permission))

    async def similar_candidates(source_file_id, target_space_id, *, can_view_file, **kwargs):
        assert source_file_id == 100
        assert target_space_id == 20
        out = []
        for target_document_id, knowledge_file_id in [(1, 200), (2, 201)]:
            if await can_view_file(knowledge_file_id):
                out.append(
                    SimilarCandidateEntry(
                        target_document_id=target_document_id,
                        title=f"文件{knowledge_file_id}",
                        current_primary_version_no=1,
                        similarity=1.0,
                    )
                )
        return out

    version_service = SimpleNamespace(
        get_shougang_publish_similar_candidates_for_file_in_space=AsyncMock(side_effect=similar_candidates)
    )

    result = await service.list_file_publish_similar_candidates(
        source_file_id=100,
        target_space_id=20,
        version_service=version_service,
        space_service=space_service,
    )

    assert [one.target_document_id for one in result.data] == [1]
    space_service._require_permission_id.assert_any_await(
        "knowledge_file",
        200,
        "view_file",
        space_id=20,
    )
    space_service._require_permission_id.assert_any_await(
        "knowledge_file",
        201,
        "view_file",
        space_id=20,
    )


@pytest.mark.asyncio
async def test_file_publish_document_search_filters_by_file_view_permission(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
    from bisheng.knowledge.domain.schemas.knowledge_version_schema import AssociableDocumentEntry

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

    async def require_permission(object_type, object_id, permission_id, *, space_id=None):
        if object_type == "knowledge_file" and object_id == 201:
            raise SpacePermissionDeniedError()

    space_service = SimpleNamespace(_require_permission_id=AsyncMock(side_effect=require_permission))

    async def search_sources(target_space_id, keyword, source_file_id, *, can_view_file, **kwargs):
        assert target_space_id == 20
        assert keyword == "制度"
        assert source_file_id == 100
        out = []
        for document_id, knowledge_file_id in [(1, 200), (2, 201)]:
            if await can_view_file(knowledge_file_id):
                out.append(
                    AssociableDocumentEntry(
                        document_id=document_id,
                        title=f"文件{knowledge_file_id}",
                        current_primary_version_no=1,
                    )
                )
        return out

    version_service = SimpleNamespace(search_shougang_publish_version_sources=AsyncMock(side_effect=search_sources))

    result = await service.search_file_publish_documents(
        source_file_id=100,
        target_space_id=20,
        keyword="制度",
        version_service=version_service,
        space_service=space_service,
    )

    assert [one.document_id for one in result.data] == [1]


@pytest.mark.asyncio
async def test_file_publish_submit_rejects_version_link_when_version_management_disabled(monkeypatch):
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
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="公共空间",
                space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
        ),
    )
    version_service = SimpleNamespace(
        _require_version_management_enabled=AsyncMock(side_effect=HTTPException(400, "disabled"))
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.submit_file_publish(
            req=ShougangFilePublishSubmitReq(
                source_space_id=10,
                source_file_id=100,
                target_space_id=20,
                target_document_id=1,
                reason="发布到公共空间",
            ),
            login_user=_login_user(),
            version_service=version_service,
        )

    assert exc_info.value.status_code == 400
    service.approval_gate.request_or_pass.assert_not_called()


@pytest.mark.asyncio
async def test_file_publish_submit_accepts_target_file_without_document(monkeypatch):
    from bisheng.approval.domain.schemas.shougang_approval_schema import (
        ShougangFilePublishDocumentEntry,
        ShougangFilePublishSubmitReq,
    )
    from bisheng.approval.domain.services.shougang_approval_service import ShougangApprovalService
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum

    approval_gate = _pending_approval_gate(701)
    service = ShougangApprovalService(approval_gate=approval_gate)
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
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="公共空间",
                space_level=KnowledgeSpaceLevelEnum.PUBLIC.value,
            )
        ),
    )
    monkeypatch.setattr(service, "_get_primary_department_id", AsyncMock(return_value=9))
    monkeypatch.setattr(service, "_send_approval_message", AsyncMock(return_value=None))
    version_service = SimpleNamespace(
        _require_version_management_enabled=AsyncMock(return_value=None),
        search_shougang_publish_version_sources=AsyncMock(
            return_value=[
                ShougangFilePublishDocumentEntry(
                    document_id=None,
                    target_file_id=300,
                    title="桃新品种经济效益分析.pdf",
                    current_primary_version_no=1,
                )
            ]
        ),
    )

    await service.submit_file_publish(
        req=ShougangFilePublishSubmitReq(
            source_space_id=10,
            source_file_id=100,
            target_space_id=20,
            target_file_id=300,
            reason="发布到公共空间",
        ),
        login_user=_login_user(),
        version_service=version_service,
    )

    approval_req = approval_gate.request_or_pass.await_args.args[0]
    assert approval_req.payload_snapshot["target_document_id"] is None
    assert approval_req.payload_snapshot["target_file_id"] == 300
    assert approval_req.payload_snapshot["target_document_title"] == "桃新品种经济效益分析.pdf"


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
async def test_create_approval_handler_rejects_public_level_for_non_admin_applicant(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceCreateApprovalHandler
    from bisheng.common.errcode.knowledge_space import SpaceCreatePublicDeniedError
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
    from bisheng.knowledge.domain.services import knowledge_space_service as space_service_mod
    from bisheng.user.domain.models import user_role as user_role_mod

    class FakeKnowledgeSpaceService:
        def __init__(self, *args, **kwargs):
            pass

        async def validate_knowledge_space_create(self, **kwargs):
            return None

        async def create_knowledge_space(self, **kwargs):
            return SimpleNamespace(id=89, name=kwargs["name"], metadata_fields=[])

    handler = KnowledgeSpaceCreateApprovalHandler()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_get_spaces_by_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        user_role_mod.UserRoleDao,
        "aget_user_roles",
        AsyncMock(return_value=[SimpleNamespace(role_id=2)]),
    )
    monkeypatch.setattr(space_service_mod, "KnowledgeSpaceService", FakeKnowledgeSpaceService)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_update_space",
        AsyncMock(side_effect=lambda space: space),
    )

    with pytest.raises(SpaceCreatePublicDeniedError):
        await handler.on_approved(
            102,
            {
                "tenant_id": 1,
                "applicant_user_id": 11,
                "applicant_user_name": "申请人",
                "create_params": {
                    "name": "公共资料库",
                    "space_level": KnowledgeSpaceLevelEnum.PUBLIC.value,
                },
            },
        )


@pytest.mark.asyncio
async def test_create_approval_handler_rejects_department_level_for_non_admin_applicant(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceCreateApprovalHandler
    from bisheng.common.errcode.knowledge_space import SpaceCreateDepartmentDeniedError
    from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
    from bisheng.knowledge.domain.services import knowledge_space_service as space_service_mod
    from bisheng.user.domain.models import user_role as user_role_mod

    class FakeKnowledgeSpaceService:
        def __init__(self, *args, **kwargs):
            pass

        async def validate_knowledge_space_create(self, **kwargs):
            return None

        async def create_knowledge_space(self, **kwargs):
            return SimpleNamespace(id=90, name=kwargs["name"], metadata_fields=[])

    handler = KnowledgeSpaceCreateApprovalHandler()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_get_spaces_by_user",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        user_role_mod.UserRoleDao,
        "aget_user_roles",
        AsyncMock(return_value=[SimpleNamespace(role_id=2)]),
    )
    monkeypatch.setattr(space_service_mod, "KnowledgeSpaceService", FakeKnowledgeSpaceService)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_update_space",
        AsyncMock(side_effect=lambda space: space),
    )

    with pytest.raises(SpaceCreateDepartmentDeniedError):
        await handler.on_approved(
            103,
            {
                "tenant_id": 1,
                "applicant_user_id": 11,
                "applicant_user_name": "申请人",
                "create_params": {
                    "name": "部门资料库",
                    "space_level": KnowledgeSpaceLevelEnum.DEPARTMENT.value,
                    "department_id": 9,
                },
            },
        )


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
async def test_file_publish_handler_builds_document_for_target_file_before_link(monkeypatch):
    from bisheng.approval.domain.services import shougang_approval_handler as handler_mod
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
    ensure_document = AsyncMock(return_value=300)
    monkeypatch.setattr(handler_mod, "_ensure_file_publish_target_document", ensure_document, raising=False)
    link_file = AsyncMock(return_value={"document_id": 300})
    monkeypatch.setattr(handler_mod, "_link_file_as_version", link_file)
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
            "target_file_id": 300,
        },
    )

    ensure_document.assert_awaited_once_with(
        login_user=ANY,
        target_file_id=300,
    )
    link_file.assert_awaited_once_with(
        login_user=ANY,
        knowledge_file_id=188,
        target_document_id=300,
        file_level_path="",
        level=0,
    )
    assert result == {"file_id": 188, "target_space_id": 20, "version": {"document_id": 300}, "idempotent": True}
    handler._copy_file.assert_not_called()


def test_file_publish_handler_copies_approved_file_to_target_root(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    source_file = KnowledgeFile(
        id=100,
        user_id=11,
        knowledge_id=10,
        file_name="制度.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        level=2,
        file_level_path="/301/302",
    )
    source_space = SimpleNamespace(id=10)
    target_space = SimpleNamespace(id=20)
    fake_file_worker = SimpleNamespace(copy_normal=Mock(return_value=SimpleNamespace(id=188)))
    fake_worker_package = ModuleType("bisheng.worker.knowledge")
    fake_worker_package.file_worker = fake_file_worker
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge", fake_worker_package)
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge.file_worker", fake_file_worker)

    copied_file = handler._copy_file(
        source_file,
        source_space,
        target_space,
        user_id=11,
        instance_id=102,
    )

    assert copied_file.id == 188
    fake_file_worker.copy_normal.assert_called_once()
    kwargs = fake_file_worker.copy_normal.call_args.kwargs
    assert kwargs["target_level"] == 0
    assert kwargs["target_file_level_path"] == ""
    assert kwargs["extra_user_metadata"]["shougang_portal_publish"] == {
        "approval_instance_id": 102,
        "source_space_id": 10,
        "source_file_id": 100,
    }


def test_file_publish_handler_copies_approved_file_to_target_folder(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile, KnowledgeFileStatus

    handler = KnowledgeSpaceFilePublishApprovalHandler()
    source_file = KnowledgeFile(
        id=100,
        user_id=11,
        knowledge_id=10,
        file_name="制度.pdf",
        status=KnowledgeFileStatus.SUCCESS.value,
        level=2,
        file_level_path="/301/302",
    )
    source_space = SimpleNamespace(id=10)
    target_space = SimpleNamespace(id=20)
    fake_file_worker = SimpleNamespace(copy_normal=Mock(return_value=SimpleNamespace(id=188)))
    fake_worker_package = ModuleType("bisheng.worker.knowledge")
    fake_worker_package.file_worker = fake_file_worker
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge", fake_worker_package)
    monkeypatch.setitem(sys.modules, "bisheng.worker.knowledge.file_worker", fake_file_worker)

    copied_file = handler._copy_file(
        source_file,
        source_space,
        target_space,
        user_id=11,
        instance_id=102,
        target_level=3,
        target_file_level_path="/300/301",
    )

    assert copied_file.id == 188
    kwargs = fake_file_worker.copy_normal.call_args.kwargs
    assert kwargs["target_level"] == 3
    assert kwargs["target_file_level_path"] == "/300/301"


@pytest.mark.asyncio
async def test_file_publish_handler_links_version_with_selected_folder_path(monkeypatch):
    from bisheng.approval.domain.services import shougang_approval_handler as handler_mod
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler
    from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
    from bisheng.knowledge.domain.models.knowledge_file import FileType, KnowledgeFileStatus
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
                SimpleNamespace(id=20, type=KnowledgeTypeEnum.SPACE.value, name="公共空间"),
            ]
        ),
    )
    source_file = SimpleNamespace(id=100, knowledge_id=10, status=KnowledgeFileStatus.SUCCESS.value)
    target_folder = SimpleNamespace(
        id=301,
        knowledge_id=20,
        file_type=FileType.DIR.value,
        level=2,
        file_level_path="/300",
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.query_by_id",
        AsyncMock(side_effect=[source_file, target_folder]),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(
            side_effect=[
                SimpleNamespace(level=KnowledgeSpaceLevelEnum.TEAM),
                SimpleNamespace(level=KnowledgeSpaceLevelEnum.PUBLIC),
            ]
        ),
    )
    monkeypatch.setattr(handler, "_copy_file", Mock(return_value=SimpleNamespace(id=188)))
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.async_update_knowledge_update_time_by_id",
        AsyncMock(),
    )
    fake_space_service = Mock()
    fake_space_service._initialize_child_resource_permissions = AsyncMock()
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService",
        Mock(return_value=fake_space_service),
    )
    link_file = AsyncMock(return_value={"document_id": 300})
    monkeypatch.setattr(handler_mod, "_link_file_as_version", link_file)

    result = await handler.on_approved(
        102,
        {
            "tenant_id": 1,
            "applicant_user_id": 11,
            "applicant_user_name": "申请人",
            "source_space_id": 10,
            "source_file_id": 100,
            "target_space_id": 20,
            "target_folder_id": 301,
            "target_document_id": 300,
        },
    )

    link_file.assert_awaited_once_with(
        login_user=ANY,
        knowledge_file_id=188,
        target_document_id=300,
        file_level_path="/300/301",
        level=3,
    )
    assert result == {"file_id": 188, "target_space_id": 20, "version": {"document_id": 300}}


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

    with pytest.raises(ValueError, match="source and target space levels are not allowed for publish"):
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
        "applicant_department_id",
    ]
    assert presets["knowledge_space_create_request"].approver_source_types == [
        "direct_user",
        "department_admin",
        "role_user",
    ]
    assert presets["knowledge_space_file_publish_request"].condition_fields == [
        "applicant_role",
        "source_space_level",
        "target_space_level",
    ]
    assert presets["knowledge_space_file_publish_request"].approver_source_types == [
        "direct_user",
        "department_admin",
        "role_user",
        "knowledge_space_owner",
        "knowledge_space_manager",
        "target_knowledge_space_owner",
        "target_knowledge_space_manager",
        "target_knowledge_space_owner_department_admin",
        "target_knowledge_space_manager_department_admin",
    ]
    create_field_options = {
        option.field: option.model_dump()
        for option in presets["knowledge_space_create_request"].condition_field_options
    }
    assert set(create_field_options) == {"applicant_role", "space_level", "applicant_department_id"}
    assert create_field_options["space_level"]["label"] == "知识空间类型"
    assert create_field_options["space_level"]["type"] == "select"
    assert [item["value"] for item in create_field_options["space_level"]["values"]] == [
        "public",
        "department",
        "team",
        "personal",
    ]
    publish_field_options = {
        option.field: option.model_dump()
        for option in presets["knowledge_space_file_publish_request"].condition_field_options
    }
    assert "target_space_id" not in publish_field_options
    assert publish_field_options["source_space_level"]["label"] == "来源知识空间类型"
    assert publish_field_options["target_space_level"]["label"] == "目标知识空间类型"
    assert [item["value"] for item in publish_field_options["source_space_level"]["values"]] == [
        "public",
        "department",
        "team",
        "personal",
    ]
    assert [item["value"] for item in publish_field_options["target_space_level"]["values"]] == [
        "public",
        "department",
        "team",
        "personal",
    ]
    assert [
        option.source_type
        for option in presets["knowledge_space_file_publish_request"].approver_source_options
    ] == [
        "direct_user",
        "department_admin",
        "role_user",
        "knowledge_space_owner",
        "knowledge_space_manager",
        "target_knowledge_space_owner",
        "target_knowledge_space_manager",
        "target_knowledge_space_owner_department_admin",
        "target_knowledge_space_manager_department_admin",
    ]
    publish_source_options = {
        option.source_type: option.label
        for option in presets["knowledge_space_file_publish_request"].approver_source_options
    }
    assert publish_source_options["knowledge_space_owner"] == "知识空间 Owner"
    assert publish_source_options["knowledge_space_manager"] == "知识空间 Manager"
    assert publish_source_options["target_knowledge_space_owner"] == "目标知识空间 Owner"
    assert publish_source_options["target_knowledge_space_manager"] == "目标知识空间 Manager"
    assert publish_source_options["target_knowledge_space_owner_department_admin"] == "目标知识空间 Owner 的部门管理员"
    assert publish_source_options["target_knowledge_space_manager_department_admin"] == "目标知识空间 Manager 的部门管理员"


@pytest.mark.asyncio
async def test_file_publish_handler_resolves_space_role_sources_by_side(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler

    handler = KnowledgeSpaceFilePublishApprovalHandler()

    async def fake_resolve_space_roles(space_id: int):
        return {
            10: ([31], [32, 33]),
            20: ([41], [42, 33]),
        }[space_id]

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler._resolve_space_roles_via_fga",
        fake_resolve_space_roles,
    )

    approvers = await handler.resolve_approvers(
        {
            "sources": [
                {"type": "direct_user", "user_ids": [33, 34]},
                {"type": "knowledge_space_owner"},
                {"type": "knowledge_space_manager"},
                {"type": "target_knowledge_space_owner"},
                {"type": "target_knowledge_space_manager"},
            ]
        },
        SimpleNamespace(
            tenant_id=1,
            applicant_user_id=11,
            applicant_department_id=None,
            payload_snapshot={
                "source_space_id": 10,
                "target_space_id": 20,
            },
        ),
    )

    assert approvers == [33, 34, 31, 32, 41, 42]


@pytest.mark.asyncio
async def test_file_publish_handler_resolves_target_role_department_admins(monkeypatch):
    from bisheng.approval.domain.services.shougang_approval_handler import KnowledgeSpaceFilePublishApprovalHandler
    from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
    from bisheng.database.models.department_admin_grant import DepartmentAdminGrantDao

    handler = KnowledgeSpaceFilePublishApprovalHandler()

    async def fake_resolve_space_roles(space_id: int):
        assert space_id == 20
        return [41], [42, 43]

    async def fake_get_user_departments(user_ids: list[int]):
        return [
            SimpleNamespace(user_id=41, department_id=300, is_primary=1),
            SimpleNamespace(user_id=42, department_id=400, is_primary=1),
            SimpleNamespace(user_id=43, department_id=500, is_primary=1),
        ]

    async def fake_get_departments(department_ids: list[int]):
        departments = {
            300: SimpleNamespace(id=300, path="/100/200/300/"),
            400: SimpleNamespace(id=400, path="/100/400/"),
            500: SimpleNamespace(id=500, path="/900/500/"),
        }
        return [departments[department_id] for department_id in department_ids if department_id in departments]

    async def fake_get_admins_by_departments(department_ids: list[int]):
        return {
            300: [],
            200: [2001, 2002],
            100: [1001],
            400: [4001],
            500: [],
        }

    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler._resolve_space_roles_via_fga",
        fake_resolve_space_roles,
    )
    monkeypatch.setattr(UserDepartmentDao, "aget_by_user_ids", fake_get_user_departments)
    monkeypatch.setattr(DepartmentDao, "aget_by_ids", fake_get_departments)
    monkeypatch.setattr(DepartmentAdminGrantDao, "aget_user_ids_by_departments", fake_get_admins_by_departments)

    approvers = await handler.resolve_approvers(
        {
            "sources": [
                {"type": "target_knowledge_space_owner_department_admin"},
                {"type": "target_knowledge_space_manager_department_admin"},
            ]
        },
        SimpleNamespace(
            tenant_id=1,
            applicant_user_id=11,
            applicant_department_id=None,
            payload_snapshot={
                "source_space_id": 10,
                "target_space_id": 20,
            },
        ),
    )

    assert approvers == [2001, 2002, 4001]
