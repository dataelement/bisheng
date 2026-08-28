"""F079: which knowledge space an approval is attributed to.

Regression for a 171 defect where every approval failed with "缺少来源知识".
The original code read the space id off ``review_tag.business_id``, assuming the
row would say ``business_type='knowledge_space'``. Real rows say
``business_type='tag_library'`` and the id is the *tag library*, so the lookup
never matched. Worse than the failure: had it matched, the tag would have been
approved into whatever space happened to share that number.

Provenance lives on the file link instead — ``review_tag_link.resource_id`` ->
``knowledgefile.knowledge_id`` — which is the route the workbench page takes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagScope
from bisheng.workstation.domain.schemas.tag_console_schema import TagConsoleReviewRef
from bisheng.workstation.domain.services.tag_console_service import TagConsoleService

TENANT_ID = 1
LIBRARY_ID = 7
REVIEW_TAG_ID = 254
FILE_ID = 1461
SPACE_ID = 109

TAG = TagConsoleReviewRef(name="9999", resource_type="ai_auto_tag")


def _review_row():
    """Shape seen in production: the business fields point at a tag library."""
    return SimpleNamespace(
        id=REVIEW_TAG_ID,
        name=TAG.name,
        resource_type=TAG.resource_type,
        business_type="tag_library",
        business_id="1",
        review_status=0,
        user_id=101,
    )


def _build_service(*, scope=None, files_by_tag=None, briefs=None):
    repository = AsyncMock()
    repository.library_exists.return_value = True
    repository.load_review_group.return_value = {(TAG.name, TAG.resource_type): [_review_row()]}
    repository.list_review_source_files.return_value = (
        {REVIEW_TAG_ID: [FILE_ID]} if files_by_tag is None else files_by_tag
    )
    repository.list_file_briefs.return_value = (
        {FILE_ID: {"file_id": FILE_ID, "file_name": "a.docx", "knowledge_id": SPACE_ID, "parent_id": None}}
        if briefs is None
        else briefs
    )

    tags_service = AsyncMock()
    tags_service.resolve_review_tag_scope.return_value = ReviewTagScope(full_tenant=True) if scope is None else scope
    return (
        TagConsoleService(
            login_user=SimpleNamespace(user_id=1, tenant_id=TENANT_ID),
            repository=repository,
            tags_service=tags_service,
        ),
        tags_service,
    )


@pytest.mark.asyncio
async def test_approve_uses_the_space_from_the_source_file():
    service, tags_service = _build_service()

    result = await service.batch_approve([TAG], LIBRARY_ID, TENANT_ID)

    assert result.succeeded == 1
    assert not result.failed
    request = tags_service.approve_or_reject_review_tag.await_args.args[0]
    assert request.status == ApproveOrRejectEnum.APPROVE
    assert request.knowledge_id == SPACE_ID, "must not fall back to business_id (the tag library)"
    assert request.tag_library_id == LIBRARY_ID


@pytest.mark.asyncio
async def test_approve_fails_when_the_space_is_out_of_the_admins_scope():
    """A department admin must not approve a tag sourced from someone else's space."""
    service, tags_service = _build_service(scope=ReviewTagScope(role_managed_space_ids=frozenset({999})))

    result = await service.batch_approve([TAG], LIBRARY_ID, TENANT_ID)

    assert result.succeeded == 0
    assert [failure.reason for failure in result.failed] == ["缺少来源知识"]
    tags_service.approve_or_reject_review_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_fails_when_no_source_file_survives():
    service, tags_service = _build_service(files_by_tag={}, briefs={})

    result = await service.batch_approve([TAG], LIBRARY_ID, TENANT_ID)

    assert result.succeeded == 0
    assert [failure.reason for failure in result.failed] == ["缺少来源知识"]
    tags_service.approve_or_reject_review_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_does_not_need_a_source_space():
    """Rejecting never writes into a library, so it must work without one."""
    service, tags_service = _build_service(files_by_tag={}, briefs={})

    with patch(
        "bisheng.workstation.domain.services.tag_console_service.TagBlacklistService.ensure_can_insert_async",
        new=AsyncMock(),
    ):
        result = await service.batch_reject([TAG], "不建议新增", TENANT_ID)

    assert result.succeeded == 1
    request = tags_service.approve_or_reject_review_tag.await_args.args[0]
    assert request.status == ApproveOrRejectEnum.REJECT
    assert request.reject_reason == "不建议新增"
    assert request.skip_blacklist is False


@pytest.mark.asyncio
async def test_reject_ignores_older_rejected_row_for_same_name():
    """A previous reject leaves a soft-deleted row; a new pending proposal of the
    same name must still be rejectable."""
    pending = _review_row()
    rejected = SimpleNamespace(**{**pending.__dict__, "id": 255, "review_status": 2})
    service, tags_service = _build_service()
    service.repository.load_review_group.return_value = {(TAG.name, TAG.resource_type): [pending, rejected]}

    with patch(
        "bisheng.workstation.domain.services.tag_console_service.TagBlacklistService.ensure_can_insert_async",
        new=AsyncMock(),
    ):
        result = await service.batch_reject([TAG], "不建议新增", TENANT_ID)

    assert result.succeeded == 1
    assert not result.failed
    tags_service.approve_or_reject_review_tag.assert_awaited_once()


@pytest.mark.asyncio
async def test_reject_already_rejected_item_does_not_abort_batch():
    rejected = SimpleNamespace(**{**_review_row().__dict__, "review_status": 2})
    service, tags_service = _build_service()
    service.repository.load_review_group.return_value = {(TAG.name, TAG.resource_type): [rejected]}

    with patch(
        "bisheng.workstation.domain.services.tag_console_service.TagBlacklistService.ensure_can_insert_async",
        new=AsyncMock(),
    ):
        result = await service.batch_reject([TAG], "不建议新增", TENANT_ID)

    assert result.succeeded == 0
    assert [failure.reason for failure in result.failed] == ["该标签的当前状态不支持此操作"]
    tags_service.approve_or_reject_review_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_clinic_admin_uses_source_team_or_personal_space():
    """科室路径下来源空间不在 role 集合里，仍应写回来源团队/个人库。"""
    service, tags_service = _build_service(scope=ReviewTagScope(clinic_admin_department_ids=frozenset({10})))

    result = await service.batch_approve([TAG], LIBRARY_ID, TENANT_ID)

    assert result.succeeded == 1
    request = tags_service.approve_or_reject_review_tag.await_args.args[0]
    assert request.knowledge_id == SPACE_ID
    assert request.tag_library_id == LIBRARY_ID
