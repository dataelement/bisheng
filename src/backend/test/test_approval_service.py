from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.approval.domain.models.approval_request import (
    ApprovalRequest,
    ApprovalRequestStatusEnum,
    ApprovalRequestTypeEnum,
    ApprovalReviewModeEnum,
    ApprovalSafetyStatusEnum,
)
from bisheng.approval.domain.schemas.approval_schema import (
    ApprovalDecisionActionEnum,
    DepartmentKnowledgeSpaceApprovalSettings,
)
from bisheng.approval.domain.services.approval_service import ApprovalService
from bisheng.common.errcode.approval import (
    ApprovalRequestNotFoundError,
    ApprovalRequestPermissionDeniedError,
)
from bisheng.knowledge.domain.models.knowledge import KnowledgeTypeEnum


def _make_login_user(user_id: int, *, is_admin: bool = False):
    return SimpleNamespace(
        user_id=user_id,
        user_name=f'user-{user_id}',
        tenant_id=1,
        is_admin=lambda: is_admin,
    )


def _make_request_row(
    *,
    request_id: int = 1,
    applicant_user_id: int = 10,
    reviewer_user_ids=None,
):
    return ApprovalRequest(
        id=request_id,
        tenant_id=1,
        request_type=ApprovalRequestTypeEnum.DEPARTMENT_KNOWLEDGE_SPACE_FILE_UPLOAD.value,
        status=ApprovalRequestStatusEnum.PENDING_REVIEW.value,
        review_mode=ApprovalReviewModeEnum.FIRST_RESPONSE_WINS.value,
        space_id=101,
        department_id=10,
        parent_folder_id=None,
        applicant_user_id=applicant_user_id,
        applicant_user_name=f'user-{applicant_user_id}',
        reviewer_user_ids=list(reviewer_user_ids or []),
        file_count=1,
        payload_json={'files': [{'file_path': '/tmp/doc.txt', 'file_name': 'doc.txt'}]},
        safety_status=ApprovalSafetyStatusEnum.SKIPPED.value,
    )


@pytest.mark.asyncio
async def test_get_request_for_user_denies_removed_reviewer():
    request_row = _make_request_row(applicant_user_id=10, reviewer_user_ids=[20])

    with patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=request_row,
    ), patch.object(
        ApprovalService,
        '_get_live_reviewer_user_ids_for_row',
        new_callable=AsyncMock,
        return_value=[],
    ):
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await ApprovalService.get_request_for_user(
                request_id=1,
                login_user=_make_login_user(20),
            )


@pytest.mark.asyncio
async def test_list_requests_for_user_filters_out_stale_reviewer_snapshot():
    request_row = _make_request_row(applicant_user_id=10, reviewer_user_ids=[20])

    with patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.alist_all',
        new_callable=AsyncMock,
        return_value=[request_row],
    ), patch.object(
        ApprovalService,
        '_can_user_access_request',
        new_callable=AsyncMock,
        return_value=False,
    ):
        data, total = await ApprovalService.list_requests_for_user(
            login_user=_make_login_user(20),
            page=1,
            page_size=20,
        )

    assert data == []
    assert total == 0


@pytest.mark.asyncio
async def test_decide_request_blocks_self_approval():
    request_row = _make_request_row(applicant_user_id=20, reviewer_user_ids=[20])

    with patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.aget_by_id',
        new_callable=AsyncMock,
        return_value=request_row,
    ):
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await ApprovalService.decide_request(
                request_id=1,
                operator_user_id=20,
                action=ApprovalDecisionActionEnum.APPROVE,
                reason=None,
            )


@pytest.mark.asyncio
async def test_create_department_space_upload_request_excludes_applicant_from_reviewer_list():
    login_user = _make_login_user(10)

    async def _acreate(request_row: ApprovalRequest) -> ApprovalRequest:
        request_row.id = 11
        return request_row

    async def _aupdate(request_row: ApprovalRequest) -> ApprovalRequest:
        return request_row

    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=10),
    ), patch(
        'bisheng.approval.domain.services.approval_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=101, name='Dept Space', type=KnowledgeTypeEnum.SPACE.value),
    ), patch.object(
        ApprovalService,
        'get_department_knowledge_space_settings',
        new_callable=AsyncMock,
        return_value=DepartmentKnowledgeSpaceApprovalSettings(),
    ), patch.object(
        ApprovalService,
        '_build_file_payload',
        new_callable=AsyncMock,
        return_value=[{'file_path': '/tmp/doc.txt', 'file_name': 'doc.txt', 'space_id': 101}],
    ), patch.object(
        ApprovalService,
        '_run_safety_check',
        new_callable=AsyncMock,
        return_value=(ApprovalSafetyStatusEnum.SKIPPED.value, None),
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.acreate',
        new_callable=AsyncMock,
        side_effect=_acreate,
    ), patch.object(
        ApprovalService,
        'get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[20],
    ) as mock_get_reviewers, patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.aupdate',
        new_callable=AsyncMock,
        side_effect=_aupdate,
    ), patch.object(
        ApprovalService,
        '_send_approval_messages',
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await ApprovalService.create_department_space_upload_request(
            request=SimpleNamespace(),
            login_user=login_user,
            space_id=101,
            parent_folder_id=None,
            file_paths=['/tmp/doc.txt'],
        )

    assert result.reviewer_user_ids == [20]
    assert mock_get_reviewers.await_args.kwargs['exclude_user_ids'] == [10]


@pytest.mark.asyncio
async def test_create_department_space_upload_request_does_not_persist_without_reviewers():
    login_user = _make_login_user(10)

    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(department_id=10),
    ), patch(
        'bisheng.approval.domain.services.approval_service.KnowledgeDao.aquery_by_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(id=101, name='Dept Space', type=KnowledgeTypeEnum.SPACE.value),
    ), patch.object(
        ApprovalService,
        'get_department_knowledge_space_settings',
        new_callable=AsyncMock,
        return_value=DepartmentKnowledgeSpaceApprovalSettings(),
    ), patch.object(
        ApprovalService,
        '_build_file_payload',
        new_callable=AsyncMock,
        return_value=[{'file_path': '/tmp/doc.txt', 'file_name': 'doc.txt', 'space_id': 101}],
    ), patch.object(
        ApprovalService,
        '_run_safety_check',
        new_callable=AsyncMock,
        return_value=(ApprovalSafetyStatusEnum.SKIPPED.value, None),
    ), patch.object(
        ApprovalService,
        'get_department_space_reviewer_user_ids',
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        'bisheng.approval.domain.services.approval_service.ApprovalRequestDao.acreate',
        new_callable=AsyncMock,
    ) as mock_create:
        with pytest.raises(ApprovalRequestPermissionDeniedError):
            await ApprovalService.create_department_space_upload_request(
                request=SimpleNamespace(),
                login_user=login_user,
                space_id=101,
                parent_folder_id=None,
                file_paths=['/tmp/doc.txt'],
            )

    mock_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_department_knowledge_space_settings_reads_per_space_binding():
    binding = SimpleNamespace(
        approval_enabled=False,
        sensitive_check_enabled=True,
    )

    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=binding,
    ):
        result = await ApprovalService.get_department_knowledge_space_settings(space_id=101)

    assert result.approval_enabled is False
    assert result.sensitive_check_enabled is True


@pytest.mark.asyncio
async def test_get_department_knowledge_space_settings_raises_when_missing():
    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=None,
    ):
        with pytest.raises(ApprovalRequestNotFoundError):
            await ApprovalService.get_department_knowledge_space_settings(space_id=101)


@pytest.mark.asyncio
async def test_update_department_knowledge_space_settings_updates_binding():
    binding = SimpleNamespace(
        approval_enabled=True,
        sensitive_check_enabled=False,
    )
    settings = DepartmentKnowledgeSpaceApprovalSettings(
        approval_enabled=False,
        sensitive_check_enabled=True,
    )

    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=binding,
    ), patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aupdate',
        new_callable=AsyncMock,
        return_value=binding,
    ) as mock_update:
        result = await ApprovalService.update_department_knowledge_space_settings(
            login_user=_make_login_user(1, is_admin=True),
            space_id=101,
            settings=settings,
        )

    assert binding.approval_enabled is False
    assert binding.sensitive_check_enabled is True
    mock_update.assert_awaited_once_with(binding)
    assert result == settings


@pytest.mark.asyncio
async def test_should_require_department_space_approval_uses_binding_setting():
    with patch(
        'bisheng.approval.domain.services.approval_service.DepartmentKnowledgeSpaceDao.aget_by_space_id',
        new_callable=AsyncMock,
        return_value=SimpleNamespace(approval_enabled=False),
    ):
        assert await ApprovalService.should_require_department_space_approval(101) is False
