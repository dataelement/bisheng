"""Approval contract tests for F059 department file sharing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from bisheng.approval.domain.schemas.approval_center_schema import (
    ApprovalGateDecision,
)
from bisheng.approval.domain.schemas.shougang_approval_schema import (
    ShougangFileShareSubmitReq,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry
from bisheng.approval.domain.services.shougang_approval_handler import (
    FILE_SHARE_SCENARIO,
    KnowledgeSpaceFileShareApprovalHandler,
)
from bisheng.approval.domain.services.shougang_approval_service import (
    ShougangApprovalService,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFileEntryStatus,
    KnowledgeFileEntryType,
    KnowledgeFileStatus,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
)


def _login_user():
    return SimpleNamespace(
        user_id=11,
        user_name="申请人",
        tenant_id=7,
    )


def _approval_gate():
    return SimpleNamespace(
        request_or_pass=AsyncMock(
            return_value=SimpleNamespace(
                decision=ApprovalGateDecision.PENDING,
                instance_id=801,
                task_ids=[901],
                model_dump=lambda: {
                    "decision": "pending",
                    "instance_id": 801,
                    "task_ids": [901],
                },
            )
        )
    )


def _space_service():
    return SimpleNamespace(
        login_user=_login_user(),
        _require_permission_id=AsyncMock(return_value=None),
        _get_valid_department_space_ids=AsyncMock(
            return_value={10, 20, 30, 40},
        ),
        get_grouped_spaces=AsyncMock(
            return_value=SimpleNamespace(
                department_spaces=[
                    SimpleNamespace(
                        id=10,
                        name="来源部门",
                        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                        owner_name="来源管理员",
                    ),
                    SimpleNamespace(
                        id=20,
                        name="目标部门",
                        space_level=KnowledgeSpaceLevelEnum.DEPARTMENT,
                        owner_name="目标管理员",
                    ),
                ]
            )
        ),
    )


def _source_file(*, entry_type=KnowledgeFileEntryType.MANAGER.value):
    return SimpleNamespace(
        id=100,
        tenant_id=7,
        knowledge_id=10,
        file_name="制度.pdf",
        file_type=FileType.FILE.value,
        status=KnowledgeFileStatus.SUCCESS.value,
        entry_type=entry_type,
        entry_status=KnowledgeFileEntryStatus.ACTIVE.value,
        reference_document_id=900,
    )


@pytest.fixture(autouse=True)
def _no_pending_approval(monkeypatch):
    from bisheng.approval.domain.services import shougang_approval_service

    # 新发布/分享不得依赖任何运行时开关。
    monkeypatch.setattr(shougang_approval_service, "settings", object(), raising=False)
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service."
        "ApprovalInstanceRepository.find_pending_instance_by_business_resource_id",
        AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_share_submit_uses_canonical_business_key_and_download_snapshot(
    monkeypatch,
):
    service = ShougangApprovalService(approval_gate=_approval_gate())
    source_file = _source_file()
    target_space = SimpleNamespace(
        id=20,
        name="目标部门",
        type="space",
    )
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="来源部门"),
                source_file,
                KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_ensure_file_share_target_space",
        AsyncMock(return_value=target_space),
    )
    monkeypatch.setattr(
        service,
        "_normalize_share_source",
        AsyncMock(
            return_value=SimpleNamespace(
                document_id=900,
                manager_file_id=100,
                manager_space_id=10,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_get_primary_department_id",
        AsyncMock(return_value=9),
    )
    monkeypatch.setattr(
        service,
        "_send_approval_message",
        AsyncMock(return_value=None),
    )
    space_service = _space_service()

    result = await service.submit_file_share(
        req=ShougangFileShareSubmitReq(
            source_space_id=10,
            source_file_id=100,
            target_space_id=20,
            reason="跨部门复用",
            allow_download=True,
        ),
        login_user=_login_user(),
        space_service=space_service,
    )

    request = service.approval_gate.request_or_pass.await_args.args[0]
    assert request.scenario_code == FILE_SHARE_SCENARIO
    assert request.business_key == ("knowledge-file-share:document:900:target:20")
    assert request.business_resource_id == "900:20"
    assert request.payload_snapshot["canonical_document_id"] == 900
    assert request.payload_snapshot["source_entry_id"] == 100
    assert request.payload_snapshot["allow_download"] is True
    assert result["decision"] == "pending"
    space_service._require_permission_id.assert_awaited_once_with(
        "knowledge_file",
        100,
        "share_file",
        space_id=10,
    )


@pytest.mark.asyncio
async def test_share_submit_rejects_share_entry_before_approval(monkeypatch):
    service = ShougangApprovalService(approval_gate=_approval_gate())
    source_file = _source_file(entry_type=KnowledgeFileEntryType.SHARE.value)
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="来源部门"),
                source_file,
                KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )

    with pytest.raises(HTTPException, match="分享入口不能再次分享"):
        await service.submit_file_share(
            req=ShougangFileShareSubmitReq(
                source_space_id=10,
                source_file_id=100,
                target_space_id=20,
                reason="非法扩散",
            ),
            login_user=_login_user(),
            space_service=_space_service(),
        )

    service.approval_gate.request_or_pass.assert_not_awaited()


@pytest.mark.asyncio
async def test_share_target_candidates_only_include_other_department_spaces(
    monkeypatch,
):
    service = ShougangApprovalService()
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="来源部门"),
                _source_file(),
                KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_space_ids_by_level",
        AsyncMock(return_value=[10, 20, 30, 40]),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.async_get_spaces_by_ids",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=10,
                    name="来源部门",
                    user_name="来源管理员",
                    tenant_id=7,
                ),
                SimpleNamespace(
                    id=20,
                    name="目标部门",
                    user_name="目标管理员",
                    tenant_id=7,
                ),
                SimpleNamespace(
                    id=30,
                    name="无读取权限部门",
                    user_name="接收管理员",
                    tenant_id=7,
                ),
                SimpleNamespace(
                    id=40,
                    name="其他租户部门",
                    user_name="其他租户管理员",
                    tenant_id=8,
                ),
            ],
        ),
    )
    space_service = _space_service()
    result = await service.list_file_share_target_spaces(
        source_space_id=10,
        source_file_id=100,
        space_service=space_service,
    )

    assert [item.id for item in result.data] == [20, 30]
    space_service._get_valid_department_space_ids.assert_awaited_once_with(
        {10, 20, 30, 40},
    )
    space_service._require_permission_id.assert_awaited_once_with(
        "knowledge_file",
        100,
        "share_file",
        space_id=10,
    )


@pytest.mark.asyncio
async def test_share_target_validation_does_not_require_target_space_view(
    monkeypatch,
):
    service = ShougangApprovalService()
    target_space = SimpleNamespace(
        id=20,
        name="目标部门",
        type=KnowledgeTypeEnum.SPACE.value,
        tenant_id=7,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(return_value=target_space),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeSpaceScopeDao.aget_by_space_id",
        AsyncMock(
            return_value=SimpleNamespace(
                level=KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )
    space_service = _space_service()

    result = await service._ensure_file_share_target_space(
        source_space_id=10,
        target_space_id=20,
        space_service=space_service,
    )

    assert result is target_space
    space_service._get_valid_department_space_ids.assert_awaited_once_with(
        {20},
    )
    space_service._require_permission_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_share_target_validation_rejects_other_tenant(monkeypatch):
    service = ShougangApprovalService()
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.KnowledgeDao.aquery_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                name="其他租户部门",
                type=KnowledgeTypeEnum.SPACE.value,
                tenant_id=8,
            )
        ),
    )

    with pytest.raises(HTTPException, match="目标知识空间不存在"):
        await service._ensure_file_share_target_space(
            source_space_id=10,
            target_space_id=20,
            space_service=_space_service(),
        )


@pytest.mark.asyncio
async def test_share_target_folder_listing_only_returns_directories(
    monkeypatch,
):
    from bisheng.approval.domain.services import shougang_approval_service

    service = ShougangApprovalService()
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="来源部门"),
                _source_file(),
                KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_ensure_file_share_target_space",
        AsyncMock(
            return_value=SimpleNamespace(id=20, name="目标部门"),
        ),
    )
    monkeypatch.setattr(
        service,
        "_ensure_file_share_target_folder",
        AsyncMock(
            return_value=SimpleNamespace(
                id=301,
                knowledge_id=20,
                file_name="制度目录",
                file_type=FileType.DIR.value,
                level=1,
                file_level_path="/300",
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_service.SpaceFileDao.async_list_children",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    id=302,
                    file_name="子目录",
                    file_type=FileType.DIR.value,
                    level=2,
                )
            ]
        ),
    )

    space_service = _space_service()
    result = await service.list_file_share_target_folders(
        source_space_id=10,
        source_file_id=100,
        target_space_id=20,
        parent_id=301,
        space_service=space_service,
    )

    assert [item.model_dump() for item in result.data] == [
        {
            "id": 302,
            "name": "子目录",
            "level": 2,
        }
    ]
    shougang_approval_service.SpaceFileDao.async_list_children.assert_awaited_once_with(
        20,
        301,
        order_field="file_name",
        order_sort="asc",
        page=1,
        page_size=200,
        file_type=FileType.DIR.value,
    )
    space_service._require_permission_id.assert_awaited_once_with(
        "knowledge_file",
        100,
        "share_file",
        space_id=10,
    )


@pytest.mark.asyncio
async def test_share_submit_persists_selected_target_folder(monkeypatch):
    service = ShougangApprovalService(approval_gate=_approval_gate())
    source_file = _source_file()
    monkeypatch.setattr(
        service,
        "_load_publish_source",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=10, name="来源部门"),
                source_file,
                KnowledgeSpaceLevelEnum.DEPARTMENT,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_ensure_file_share_target_space",
        AsyncMock(
            return_value=SimpleNamespace(id=20, name="目标部门"),
        ),
    )
    monkeypatch.setattr(
        service,
        "_ensure_file_share_target_folder",
        AsyncMock(
            return_value=SimpleNamespace(
                id=301,
                file_name="制度目录",
                level=1,
                file_level_path="/300",
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        service,
        "_normalize_share_source",
        AsyncMock(
            return_value=SimpleNamespace(
                document_id=900,
                manager_file_id=100,
                manager_space_id=10,
            )
        ),
    )
    monkeypatch.setattr(
        service,
        "_get_primary_department_id",
        AsyncMock(return_value=9),
    )
    monkeypatch.setattr(
        service,
        "_send_approval_message",
        AsyncMock(return_value=None),
    )

    await service.submit_file_share(
        req=ShougangFileShareSubmitReq(
            source_space_id=10,
            source_file_id=100,
            target_space_id=20,
            target_folder_id=301,
            reason="跨部门复用",
        ),
        login_user=_login_user(),
        space_service=_space_service(),
    )

    request = service.approval_gate.request_or_pass.await_args.args[0]
    assert request.payload_snapshot["target_folder_id"] == 301
    assert request.payload_snapshot["target_folder_name"] == "制度目录"


@pytest.mark.asyncio
async def test_share_approved_resolves_current_target_folder_location(
    monkeypatch,
):
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.is_valid_department_space_id",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.aquery_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                tenant_id=7,
                type=KnowledgeTypeEnum.SPACE.value,
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.query_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=301,
                knowledge_id=20,
                file_type=FileType.DIR.value,
                level=1,
                file_level_path="/300",
            )
        ),
    )

    path, level = await KnowledgeSpaceFileShareApprovalHandler._resolve_target_location(
        {
            "tenant_id": 7,
            "target_space_id": 20,
            "target_folder_id": 301,
        }
    )

    assert path == "/300/301"
    assert level == 2
    root_path, root_level = (
        await KnowledgeSpaceFileShareApprovalHandler._resolve_target_location(
            {
                "tenant_id": 7,
                "target_space_id": 20,
            }
        )
    )
    assert root_path == ""
    assert root_level == 0


@pytest.mark.asyncio
async def test_share_approved_rejects_target_folder_from_other_space(
    monkeypatch,
):
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.is_valid_department_space_id",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.aquery_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                tenant_id=7,
                type=KnowledgeTypeEnum.SPACE.value,
            )
        ),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeFileDao.query_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=301,
                knowledge_id=99,
                file_type=FileType.DIR.value,
                level=1,
                file_level_path="/300",
            )
        ),
    )

    with pytest.raises(ValueError, match="target folder"):
        await KnowledgeSpaceFileShareApprovalHandler._resolve_target_location(
            {
                "tenant_id": 7,
                "target_space_id": 20,
                "target_folder_id": 301,
            }
        )


@pytest.mark.asyncio
async def test_share_approved_rejects_target_space_from_other_tenant(
    monkeypatch,
):
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeSpaceService.is_valid_department_space_id",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "bisheng.approval.domain.services.shougang_approval_handler.KnowledgeDao.aquery_by_id",
        AsyncMock(
            return_value=SimpleNamespace(
                id=20,
                tenant_id=8,
                type=KnowledgeTypeEnum.SPACE.value,
            )
        ),
    )

    with pytest.raises(ValueError, match="target department"):
        await KnowledgeSpaceFileShareApprovalHandler._resolve_target_location(
            {
                "tenant_id": 7,
                "target_space_id": 20,
            }
        )


def test_share_scenario_is_registered_with_fixed_role_sources():
    preset = ApprovalRegistry.with_default_presets().get_preset(FILE_SHARE_SCENARIO)

    assert preset is not None
    assert preset.condition_fields == []
    assert preset.approver_source_types == [
        "knowledge_space_owner",
        "knowledge_space_manager",
        "target_knowledge_space_owner",
        "target_knowledge_space_manager",
    ]


@pytest.mark.asyncio
async def test_legacy_share_creation_is_permanently_disabled():
    from bisheng.common.errcode.knowledge import (
        KnowledgeShareCreationDisabledError,
    )
    from bisheng.knowledge.domain.services.knowledge_space_service import (
        KnowledgeSpaceService,
    )

    service = object.__new__(KnowledgeSpaceService)

    with pytest.raises(KnowledgeShareCreationDisabledError):
        await service.create_shougang_portal_share_link(SimpleNamespace(space_id=10, file_id=100))
