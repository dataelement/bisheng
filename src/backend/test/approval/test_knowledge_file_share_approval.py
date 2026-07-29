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
)
from bisheng.approval.domain.services.shougang_approval_service import (
    ShougangApprovalService,
)
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
        _require_permission_id=AsyncMock(return_value=None),
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
    result = await service.list_file_share_target_spaces(
        source_space_id=10,
        source_file_id=100,
        space_service=_space_service(),
    )

    assert [item.id for item in result.data] == [20]


def test_share_scenario_is_registered_with_fixed_role_sources():
    preset = ApprovalRegistry.with_default_presets().get_preset(FILE_SHARE_SCENARIO)

    assert preset is not None
    assert preset.condition_fields == ["applicant_role"]
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
