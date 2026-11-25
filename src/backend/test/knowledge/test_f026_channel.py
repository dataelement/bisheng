"""Manual and automatic channel imports must decide the real target before staging Native content."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bisheng.channel.api.endpoints import channel_manager
from bisheng.channel.domain.schemas.channel_manager_schema import AddArticlesToKnowledgeSpaceRequest
from bisheng.channel.domain.services import channel_service as channel
from bisheng.channel.domain.services.information_knowledge_delivery_service import InformationKnowledgeDeliveryService
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.common.errcode.knowledge_space import SpaceFileNameDuplicateError, SpacePermissionDeniedError
from bisheng.common.models.space_channel_member import UserRoleEnum
from bisheng.knowledge.domain.models import knowledge_file as knowledge_file_module
from bisheng.knowledge.domain.models.knowledge_file import FileSource, KnowledgeFileStatus
from bisheng.knowledge.domain.services import knowledge_space_service as spaces


@pytest.fixture
def delivery(monkeypatch):
    article = SimpleNamespace(title="Headline", content="search text", content_html="<p>preview</p>")
    articles = SimpleNamespace(get_article=AsyncMock(return_value=article), match_article_ids_sync=lambda ids, *_: ids)
    user = SimpleNamespace(tenant_id=2, user_id=7)
    importer = channel.ChannelService(AsyncMock(), AsyncMock(), AsyncMock(), article_es_service=articles)
    importer.space_upload_factory = Mock()
    importer.ensure_article_sensitive_view_allowed = AsyncMock()
    monkeypatch.setattr(
        channel.SpaceChannelMemberDao, "async_get_active_member_role", AsyncMock(return_value=UserRoleEnum.ADMIN)
    )
    space = AsyncMock()
    space.require_upload_container.return_value = SimpleNamespace(id=12, tenant_id=2)
    monkeypatch.setattr(spaces, "KnowledgeSpaceService", Mock(return_value=space))
    storage = AsyncMock(side_effect=AssertionError("native storage was opened"))
    monkeypatch.setattr(channel, "get_minio_storage", storage)
    return SimpleNamespace(importer=importer, user=user, space=space, storage=storage, articles=articles)


async def manual(d):
    req = AddArticlesToKnowledgeSpaceRequest(knowledge_id=12, parent_id=34, article_ids=["one"])
    response = await channel_manager.add_articles_to_knowledge_space(req, None, d.user, d.importer)
    return response.data


async def automatic(d):
    config = SimpleNamespace(channel_id="c", is_enabled=True, create_time=1, update_time=1)
    admission = SimpleNamespace(
        identity=d.user,
        config={"knowledge_space_id": 12, "folder_id": 34, "sub_channel_name": None},
        channel={"source_list": ["s"], "filter_rules": []},
    )
    worker = InformationKnowledgeDeliveryService(
        SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace(id="c"))),
        SimpleNamespace(find_by_id=AsyncMock(return_value=config)),
        d.articles,
        channel_service=d.importer,
        prepare_delivery=AsyncMock(return_value=admission),
    )
    return await worker.deliver_to_config(2, "cfg", ["one"], 3)


def target_facts(provider_key="weknora", state="ready", active_generation=1, pending=None):
    return SimpleNamespace(
        provider_key=provider_key,
        state=state,
        active_generation=active_generation,
        pending_write_operation_id=pending,
    )


def target_session(monkeypatch):
    from bisheng.knowledge.domain.repositories import provider_transfer_repository

    binding = AsyncMock(return_value=None)
    monkeypatch.setattr(provider_transfer_repository, "binding", binding)
    session = AsyncMock()
    monkeypatch.setattr(channel, "get_async_db_session", Mock(return_value=session))
    return binding, session


@pytest.mark.parametrize(
    "facts",
    [
        target_facts(),
        target_facts(state="provisioning", active_generation=None),
        target_facts(provider_key="native", active_generation=4),
        target_facts(pending="pending-operation"),
    ],
    ids=["remote-ready", "remote-provisioning", "native-with-generation", "remote-pending-write"],
)
@pytest.mark.parametrize("entry", [manual, automatic], ids=["manual", "automatic"])
async def test_non_native_target_is_rejected_before_staging(delivery, monkeypatch, entry, facts):
    binding, session = target_session(monkeypatch)
    binding.return_value = facts

    if entry is manual:
        with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
            await entry(delivery)
        assert caught.value.kwargs["reason"] == "provider_transfer_unsupported_channel_snapshot_upload"
        # The business error must say why this import cannot proceed instead of
        # surfacing the generic "frozen reference plan" conflict text.
        assert "remote" in caught.value.message
        assert "native" in caught.value.message
        assert "snapshot" in caught.value.message
    else:
        result = await entry(delivery)
        assert result["accepted"] == 0
        assert result["failed"] == {"snapshot_upload_unsupported": 1}

    delivery.space.require_upload_container.assert_awaited_once_with(12, 34)
    binding.assert_awaited_once_with(session.__aenter__.return_value, 2, 12)
    delivery.storage.assert_not_awaited()
    delivery.space.add_file.assert_not_awaited()


@pytest.mark.parametrize("entry", [manual, automatic], ids=["manual", "automatic"])
async def test_unreadable_target_facts_fail_closed(delivery, monkeypatch, entry):
    from bisheng.knowledge.domain.repositories import provider_transfer_repository

    binding = AsyncMock(side_effect=RuntimeError("target facts unavailable"))
    monkeypatch.setattr(provider_transfer_repository, "binding", binding)
    session = AsyncMock()
    monkeypatch.setattr(channel, "get_async_db_session", Mock(return_value=session))

    if entry is manual:
        with pytest.raises(RuntimeError, match="target facts unavailable"):
            await entry(delivery)
    else:
        result = await entry(delivery)
        assert result["accepted"] == 0
        assert result["failed"] == {"system_failed": 1}

    delivery.storage.assert_not_awaited()
    delivery.space.add_file.assert_not_awaited()


async def test_denied_folder_never_reads_binding_or_stages_articles(delivery, monkeypatch):
    delivery.space.require_upload_container.side_effect = SpacePermissionDeniedError()
    lookup = Mock(side_effect=AssertionError("binding lookup before permission"))
    monkeypatch.setattr(channel, "get_async_db_session", lookup)
    with pytest.raises(SpacePermissionDeniedError):
        await manual(delivery)
    lookup.assert_not_called()
    delivery.storage.assert_not_awaited()


@pytest.fixture
def native_storage():
    return SimpleNamespace(
        tmp_bucket="temporary",
        put_object_tmp=AsyncMock(),
        get_share_link=AsyncMock(return_value="opaque-document"),
        put_object=AsyncMock(),
    )


async def test_native_import_keeps_markdown_object_metadata_and_preview(delivery, native_storage, monkeypatch):
    binding, _session = target_session(monkeypatch)
    binding.return_value = None
    monkeypatch.setattr(channel, "get_minio_storage", AsyncMock(return_value=native_storage))
    created = SimpleNamespace(id=900, status=KnowledgeFileStatus.SUCCESS.value, tenant_id=2)
    delivery.space.add_file = AsyncMock(return_value=[created])
    stored = SimpleNamespace(id=900, knowledge_id=12, tenant_id=2, preview_file_object_name=None)
    monkeypatch.setattr(knowledge_file_module.KnowledgeFileDao, "aget_file_by_ids", AsyncMock(return_value=[stored]))
    update = AsyncMock()
    monkeypatch.setattr(knowledge_file_module.KnowledgeFileDao, "async_update_batch", update)

    result = await manual(delivery)

    assert result == [stored]
    assert stored.preview_file_object_name == "preview/900.html"
    native_storage.put_object_tmp.assert_awaited_once()
    assert native_storage.put_object_tmp.await_args.kwargs["file"] == b"search text"
    assert native_storage.put_object_tmp.await_args.kwargs["content_type"] == "text/markdown"
    delivery.space.add_file.assert_awaited_once()
    assert delivery.space.add_file.await_args.kwargs == {
        "knowledge_id": 12,
        "file_path": ["opaque-document"],
        "parent_id": 34,
        "file_source": FileSource.CHANNEL,
    }
    native_storage.put_object.assert_awaited_once_with(
        object_name="preview/900.html",
        file=b"<p>preview</p>",
        content_type="text/html",
    )
    update.assert_awaited_once_with([stored])


async def test_native_duplicate_failure_keeps_existing_terminal_semantics(delivery, native_storage, monkeypatch):
    binding, _session = target_session(monkeypatch)
    binding.return_value = None
    monkeypatch.setattr(channel, "get_minio_storage", AsyncMock(return_value=native_storage))
    delivery.space.add_file.return_value = [SimpleNamespace(id=901, status=KnowledgeFileStatus.FAILED.value)]
    monkeypatch.setattr(knowledge_file_module.KnowledgeFileDao, "async_update_batch", AsyncMock(return_value=True))

    with pytest.raises(SpaceFileNameDuplicateError):
        await manual(delivery)

    assert delivery.space.add_file.await_count == 1
    knowledge_file_module.KnowledgeFileDao.async_update_batch.assert_awaited_once_with([])
