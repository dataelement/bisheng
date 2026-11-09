"""Actual channel import reaches the original SPACE upload writer, not a stub."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.channel.domain.schemas.channel_manager_schema import AddArticlesToKnowledgeSpaceRequest
from bisheng.channel.domain.services import channel_service as module
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.services import knowledge_space_service as spaces
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


@pytest.fixture
async def channel_upload(upload, monkeypatch):
    article = SimpleNamespace(title="Article", content="Original article", content_html="<p>Original</p>")
    service = module.ChannelService(
        channel_repository=AsyncMock(),
        space_channel_member_repository=AsyncMock(),
        channel_info_source_repository=AsyncMock(),
        article_es_service=SimpleNamespace(get_article=AsyncMock(return_value=article)),
    )
    service.ensure_article_sensitive_view_allowed = AsyncMock()
    monkeypatch.setattr(
        module.SpaceChannelMemberDao, "async_get_active_member_role", AsyncMock(return_value=UserRoleEnum.CREATOR)
    )
    storage = SimpleNamespace(
        tmp_bucket="temporary",
        put_object_tmp=AsyncMock(),
        get_share_link=AsyncMock(return_value="opaque-document"),
        put_object=AsyncMock(),
    )
    monkeypatch.setattr(module, "get_minio_storage", AsyncMock(return_value=storage))
    # Execute the real native service; only its construction site is redirected
    # to the already composed native writer and isolated storage/queue transports.
    original = upload.service.upload_application_factory
    upload.service.upload_application_factory = None
    construct = Mock(return_value=upload.service)
    monkeypatch.setattr(spaces, "KnowledgeSpaceService", construct)
    return SimpleNamespace(upload=upload, service=service, factory=lambda _: original(), storage=storage)


async def test_channel_uses_injected_writer_and_preserves_article_preview(channel_upload):
    context = channel_upload
    context.service.space_upload_factory = context.factory
    result = await context.service.add_articles_to_knowledge_space(
        AddArticlesToKnowledgeSpaceRequest(knowledge_id=40, article_ids=["one"]), context.upload.context.user, None
    )
    assert len(result) == 1 and result[0].user_id == 7
    assert result[0].preview_file_object_name == f"preview/{result[0].id}.html"
    context.upload.publish.assert_called_once()
    context.storage.put_object.assert_awaited_once()
    context.upload.projection._permission.authorize_created.assert_awaited_once()


async def test_missing_channel_factory_rejects_before_storage_effects(channel_upload):
    context = channel_upload
    with pytest.raises(RuntimeError, match=r"upload.*factory"):
        await context.service.add_articles_to_knowledge_space(
            AddArticlesToKnowledgeSpaceRequest(knowledge_id=40, article_ids=["one"]), context.upload.context.user, None
        )
    context.storage.put_object_tmp.assert_not_awaited()
    context.storage.get_share_link.assert_not_awaited()
    context.upload.publish.assert_not_called()
