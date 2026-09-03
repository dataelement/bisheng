"""add_file 的 award_points 开关: 接口同步关挂钩, 页面直传仍调用 notify."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum
from test.test_knowledge_space_service import (
    _load_service_class,
    _make_file,
    _make_login_user,
    _make_space,
)


class _FakeSession:
    def add(self, _obj):
        return None

    async def flush(self):
        return None

    async def commit(self):
        return None


@asynccontextmanager
async def _fake_session_ctx():
    yield _FakeSession()


@pytest.fixture
def space_service():
    svc = _load_service_class()(None, _make_login_user())
    svc.normalize_file_category_code = lambda value: str(value).strip().upper() if value else None
    svc.normalize_business_domain_code = lambda value: str(value).strip().upper() if value else None
    return svc


async def _run_add_file(space_service, *, award_points: bool, notify, file_id: int = 4242):
    """走与接口同步相同的 enqueue_processing=False 入库尾路径, 断言挂钩是否发出."""
    space_service.normalize_file_category_code = lambda value: str(value).strip().upper() if value else None
    space_service.normalize_business_domain_code = lambda value: str(value).strip().upper() if value else None
    knowledge_id = 19
    space = _make_space(space_id=knowledge_id, auth_type=AuthTypeEnum.PUBLIC)
    added_file = _make_file(
        file_id=file_id,
        knowledge_id=knowledge_id,
        file_name="report.pdf",
        file_level_path="",
        level=0,
    )
    added_file.file_size = 100
    added_file.tenant_id = 1
    with (
        patch.object(space_service, "_require_permission_id", new_callable=AsyncMock),
        patch.object(space_service, "_check_filename_sensitive_words", return_value=None),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service._require_not_write_frozen",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
            new_callable=AsyncMock,
            return_value=space,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.SpaceFileDao.get_user_total_file_size",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_knowledge_space_upload_limit_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.QuotaService.get_tenant_storage_remaining_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.process_one_file",
            return_value=added_file,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeService.apply_manual_upload_tags",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.PermissionService.batch_write_tuples",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.OwnerService.write_owner_tuple",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
            new_callable=AsyncMock,
        ),
        patch.object(space_service, "update_folder_update_time", new_callable=AsyncMock),
        patch.object(space_service, "_initialize_child_resource_permissions", new_callable=AsyncMock),
        patch(
            "bisheng.knowledge.domain.services.knowledge_space_service.get_async_db_session",
            new=_fake_session_ctx,
        ),
        patch(
            "bisheng.knowledge.domain.services.knowledge_pdf_artifact_service.enqueue_current_pdf_artifact",
            new_callable=AsyncMock,
        ),
        patch(
            "bisheng.points.domain.services.points_award_hooks.notify_space_files_ready",
            new=notify,
        ),
    ):
        return await space_service.add_file(
            knowledge_id,
            ["/tmp/report.pdf"],
            enqueue_processing=False,
            skip_space_business_domain_check=True,
            award_points=award_points,
        )


@pytest.mark.asyncio
async def test_add_file_default_notifies_points(space_service):
    notify = AsyncMock()
    result = await _run_add_file(space_service, award_points=True, notify=notify)
    assert result[0].id == 4242
    notify.assert_awaited_once()
    assert notify.await_args.kwargs["space_id"] == 19
    assert notify.await_args.kwargs["uploader_id"] == 7


@pytest.mark.asyncio
async def test_add_file_skips_points_when_award_points_false(space_service):
    notify = AsyncMock()
    result = await _run_add_file(space_service, award_points=False, notify=notify, file_id=4242)
    assert result[0].id == 4242
    notify.assert_not_awaited()
    # 再打一枪: 仍不挂钩, 避免默认值回退把同步路径重新打开.
    result_again = await _run_add_file(space_service, award_points=False, notify=notify, file_id=4243)
    assert result_again[0].id == 4243
    notify.assert_not_awaited()
