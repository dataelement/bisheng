"""Saved space-file links follow the caller's current resource authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileNotFoundError, SpacePermissionDeniedError
from bisheng.common.errcode.permission import PermissionFGAUnavailableError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.api.endpoints.knowledge_space import get_file_preview
from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from test.knowledge.test_knowledge_space_service import _make_file, _make_login_user, _make_space

MODULE = "bisheng.knowledge.domain.services.knowledge_space_service"


@pytest.fixture
def preview_context():
    service = KnowledgeSpaceService(MagicMock(), _make_login_user())
    file = _make_file()
    file.user_metadata = {"html_snapshot_object_name": "preview/11.html", "source_url": "https://example.test/source"}
    with (
        patch(f"{MODULE}.KnowledgeFileDao.query_by_id", AsyncMock(return_value=file)),
        patch.object(
            service, "_permission_actor", AsyncMock(return_value=SimpleNamespace(user_id=7, super_admin=False))
        ),
        patch(f"{MODULE}.check_business_action", AsyncMock(return_value=True)) as check,
        patch(f"{MODULE}.KnowledgeService.get_file_share_url", return_value=("original", "preview")) as urls,
        patch(f"{MODULE}.KnowledgeService.get_file_share_url_with_empty", return_value="html") as html,
    ):
        yield service, file, check, urls, html


async def test_preview_requires_current_file_visibility(preview_context):
    service, _, check, urls, html = preview_context
    check.return_value = False

    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_preview(11)

    urls.assert_not_called()
    html.assert_not_called()


async def test_visible_file_returns_all_preview_formats(preview_context):
    service, file, check, urls, html = preview_context
    result = await service.get_file_preview(11)

    assert result["original_url"] == "original"
    assert result["preview_url"] == "preview"
    assert result["html_preview_url"] == "html"
    assert check.await_args.kwargs["resource_type"] == "knowledge_file"
    assert check.await_args.kwargs["resource_id"] == file.id
    assert check.await_args.kwargs["action"] == "visible"
    urls.assert_called_once()
    html.assert_called_once()


@pytest.mark.parametrize("file_type", [FileType.FILE.value, FileType.DIR.value])
async def test_preview_route_validates_space_file_binding(preview_context, file_type):
    service, file, check, urls, html = preview_context
    file.file_type = file_type

    with pytest.raises(SpaceFileNotFoundError):
        await get_file_preview(space_id=999, file_id=11, svc=service)

    check.assert_not_awaited()
    urls.assert_not_called()
    html.assert_not_called()


async def test_preview_fails_closed_when_authorization_is_unavailable(preview_context):
    service, _, check, urls, html = preview_context
    check.side_effect = PermissionFGAUnavailableError()

    with pytest.raises(PermissionFGAUnavailableError):
        await service.get_file_preview(11)

    urls.assert_not_called()
    html.assert_not_called()


@pytest.mark.parametrize("independent_file_grant", [False, True])
async def test_saved_preview_link_after_unsubscribe(preview_context, independent_file_grant):
    service, _, check, urls, html = preview_context
    membership = {"active": True}

    async def check_current_grants(*args, **kwargs):
        assert kwargs["resource_type"] == "knowledge_file"
        assert kwargs["action"] == "visible"
        return membership["active"] or independent_file_grant

    async def sync_membership(**kwargs):
        assert kwargs["resource_id"] == "1"
        assert kwargs["subject_user_id"] == 7
        assert kwargs["model_key"] is None
        membership["active"] = False

    async def delete_membership(*args):
        assert membership["active"] is False
        return True

    check.side_effect = check_current_grants
    adapter = SimpleNamespace(sync_membership=AsyncMock(side_effect=sync_membership))
    with (
        patch(f"{MODULE}.KnowledgeDao.aquery_by_id", AsyncMock(return_value=_make_space())),
        patch(
            f"{MODULE}.SpaceChannelMemberDao.async_find_member",
            AsyncMock(return_value=SimpleNamespace(user_role=UserRoleEnum.MEMBER)),
        ),
        patch(f"{MODULE}.SpaceChannelMemberDao.delete_space_member", AsyncMock(side_effect=delete_membership)),
        patch(f"{MODULE}.get_f048_resource_adapter", AsyncMock(return_value=adapter)),
    ):
        await get_file_preview(space_id=1, file_id=11, svc=service)
        assert await service.unsubscribe_space(1) is True
        urls.reset_mock()
        html.reset_mock()
        if independent_file_grant:
            await get_file_preview(space_id=1, file_id=11, svc=service)
            urls.assert_called_once()
        else:
            with pytest.raises(SpacePermissionDeniedError):
                await get_file_preview(space_id=1, file_id=11, svc=service)
            urls.assert_not_called()
            html.assert_not_called()

    assert check.await_count == 2
    adapter.sync_membership.assert_awaited_once()


async def test_preview_and_download_use_separate_actions(preview_context):
    service, _, check, urls, _ = preview_context
    check.side_effect = lambda *args, **kwargs: kwargs["action"] == "visible"
    await service.get_file_preview(11)
    urls.reset_mock()

    with pytest.raises(SpacePermissionDeniedError):
        await service.get_file_download(11, space_id=1)

    urls.assert_not_called()
    assert [call.kwargs["action"] for call in check.await_args_list] == ["visible", "download"]
