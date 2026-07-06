import pytest
from unittest.mock import AsyncMock, patch
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


def _make_service(user_id=7):
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = type("U", (), {"user_id": user_id, "user_name": "u", "tenant_id": 1})()
    svc.request = None
    return svc


@pytest.mark.asyncio
async def test_ensure_favorite_space_returns_existing():
    svc = _make_service()
    existing = Knowledge(id=100, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(return_value=existing)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock()) as creator:
        space = await svc._ensure_favorite_space()
        assert space.id == 100
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_favorite_space_creates_when_missing():
    svc = _make_service()
    created = Knowledge(id=101, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_adopt_existing_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock(return_value=created)) as creator:
        space = await svc._ensure_favorite_space()
        assert space.id == 101
        creator.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_favorite_space_adopts_existing_named():
    # 无 is_favorite 库, 但已有同名个人库(上线前手动建) -> 收编, 不创建(避免撞名)
    svc = _make_service()
    legacy = Knowledge(id=117, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_adopt_existing_favorite_space",
                      new=AsyncMock(return_value=legacy)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock()) as creator:
        space = await svc._ensure_favorite_space()
        assert space.id == 117
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_adopt_existing_favorite_space_sets_flag():
    # 收编时把同名库标记为 is_favorite 并持久化
    svc = _make_service()
    legacy = Knowledge(id=117, name="我的收藏", user_id=7, type=3, is_favorite=False)
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_get_personal_space_by_owner_name",
               new=AsyncMock(return_value=legacy)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
               new=AsyncMock(side_effect=lambda s: s)) as updater:
        space = await svc._adopt_existing_favorite_space()
        assert space.id == 117
        assert space.is_favorite is True
        updater.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_favorite_space_concurrent_fallback():
    # 创建抛异常（并发下别人已建），回查能拿到
    svc = _make_service()
    created = Knowledge(id=102, name="我的收藏", user_id=7, type=3, is_favorite=True)
    find = AsyncMock(side_effect=[None, created])  # 第一次没有，回查命中
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=find), \
         patch.object(KnowledgeSpaceService, "_adopt_existing_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock(side_effect=Exception("dup"))):
        space = await svc._ensure_favorite_space()
        assert space.id == 102


@pytest.mark.asyncio
async def test_create_favorite_idempotent_returns_existing():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteCreateReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    source_space = Knowledge(id=1, name="src", user_id=3, type=3)
    source_file = KnowledgeFile(id=2, knowledge_id=1, user_id=3, file_name="doc.pdf")
    existing_ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                                 user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=source_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=source_file)), \
         patch.object(KnowledgeSpaceService, "_ensure_space_file", new=lambda self, f, sid: f), \
         patch.object(KnowledgeSpaceService, "_require_permission_id", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch.object(KnowledgeSpaceService, "_find_favorite_reference", new=AsyncMock(return_value=existing_ref)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_reference", new=AsyncMock()) as creator:
        resp = await svc.create_shougang_portal_favorite(
            ShougangPortalFavoriteCreateReq(source_space_id=1, source_file_id=2))
        assert resp.favorite_file_id == 999
        assert resp.space_id == 200
        assert resp.source_space_id == 1 and resp.source_file_id == 2
        creator.assert_not_called()


@pytest.mark.asyncio
async def test_create_favorite_creates_reference_when_absent():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteCreateReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    source_space = Knowledge(id=1, name="src", user_id=3, type=3)
    source_file = KnowledgeFile(id=2, knowledge_id=1, user_id=3, file_name="doc.pdf")
    new_ref = KnowledgeFile(id=1000, knowledge_id=200, user_id=7, file_name="doc.pdf",
                            user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.aquery_by_id",
               new=AsyncMock(return_value=source_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=source_file)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
               new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_space_file", new=lambda self, f, sid: f), \
         patch.object(KnowledgeSpaceService, "_require_permission_id", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch.object(KnowledgeSpaceService, "_find_favorite_reference", new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_reference", new=AsyncMock(return_value=new_ref)) as creator:
        resp = await svc.create_shougang_portal_favorite(
            ShougangPortalFavoriteCreateReq(source_space_id=1, source_file_id=2))
        assert resp.favorite_file_id == 1000
        creator.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_favorite_returns_true_when_found():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteRemoveReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                        user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch.object(KnowledgeSpaceService, "_find_favorite_reference", new=AsyncMock(return_value=ref)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.adelete_batch",
               new=AsyncMock(return_value=True)) as deleter, \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_knowledge_update_time_by_id",
               new=AsyncMock()):
        resp = await svc.remove_shougang_portal_favorite(
            ShougangPortalFavoriteRemoveReq(source_space_id=1, source_file_id=2))
        assert resp.removed is True
        deleter.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_favorite_false_when_absent():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteRemoveReq
    svc = _make_service()
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=None)):
        resp = await svc.remove_shougang_portal_favorite(
            ShougangPortalFavoriteRemoveReq(source_space_id=1, source_file_id=2))
        assert resp.removed is False


@pytest.mark.asyncio
async def test_status_marks_favorited():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteStatusReq
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                        user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_references_by_knowledge_id",
               new=AsyncMock(return_value=([ref], 1))):
        resp = await svc.get_shougang_portal_favorite_status(
            ShougangPortalFavoriteStatusReq(items=[{"space_id": 1, "file_id": 2}, {"space_id": 1, "file_id": 3}]))
        by_file = {(d.space_id, d.file_id): d.favorited for d in resp.data}
        assert by_file[(1, 2)] is True
        assert by_file[(1, 3)] is False


@pytest.mark.asyncio
async def test_status_no_space_all_false():
    from bisheng.knowledge.domain.schemas.knowledge_space_schema import ShougangPortalFavoriteStatusReq
    svc = _make_service()
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=None)):
        resp = await svc.get_shougang_portal_favorite_status(
            ShougangPortalFavoriteStatusReq(items=[{"space_id": 1, "file_id": 2}]))
        assert resp.data[0].favorited is False


@pytest.mark.asyncio
async def test_list_marks_invalid_when_source_deleted():
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                        user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_references_by_knowledge_id",
               new=AsyncMock(return_value=([ref], 1))), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=None)):  # 源文件已删
        resp = await svc.list_shougang_portal_favorites(page=1, page_size=20)
        assert resp.total == 1
        assert resp.data[0].status == "invalid"
        assert resp.data[0].source_space_id == 1 and resp.data[0].source_file_id == 2


@pytest.mark.asyncio
async def test_create_favorite_space_cleans_orphan_on_unique_conflict():
    # #2 并发防重：更新 is_favorite 撞唯一索引(uq_knowledge_favorite_user)时，
    # 清理本次刚建的孤儿空间并上抛，交由 _ensure_favorite_space 回查复用赢家。
    svc = _make_service()
    orphan = Knowledge(id=201, name="我的收藏", user_id=7, type=3, is_favorite=False)
    with patch.object(KnowledgeSpaceService, "create_knowledge_space",
                      new=AsyncMock(return_value=orphan)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_update_space",
               new=AsyncMock(side_effect=Exception("duplicate favorite"))), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeDao.async_delete_knowledge",
               new=AsyncMock()) as deleter:
        with pytest.raises(Exception):
            await svc._create_favorite_space()
        deleter.assert_awaited_once_with(201, only_clear=False)


@pytest.mark.asyncio
async def test_ensure_favorite_space_recovers_winner_after_conflict():
    # 并发下本次创建失败(撞唯一索引) → _ensure_favorite_space 回查到赢家并返回
    svc = _make_service()
    winner = Knowledge(id=117, name="我的收藏", user_id=7, type=3, is_favorite=True)
    with patch.object(KnowledgeSpaceService, "_find_favorite_space",
                      new=AsyncMock(side_effect=[None, winner])), \
         patch.object(KnowledgeSpaceService, "_adopt_existing_favorite_space",
                      new=AsyncMock(return_value=None)), \
         patch.object(KnowledgeSpaceService, "_create_favorite_space",
                      new=AsyncMock(side_effect=Exception("unique conflict"))):
        space = await svc._ensure_favorite_space()
        assert space.id == 117


@pytest.mark.asyncio
async def test_list_marks_valid_when_source_exists():
    from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
    svc = _make_service()
    fav_space = Knowledge(id=200, name="我的收藏", user_id=7, type=3, is_favorite=True)
    ref = KnowledgeFile(id=999, knowledge_id=200, user_id=7, file_name="doc.pdf",
                        user_metadata={"favorite_reference": {"source_space_id": 1, "source_file_id": 2}})
    src = KnowledgeFile(id=2, knowledge_id=1, user_id=3, file_name="doc.pdf")
    with patch.object(KnowledgeSpaceService, "_find_favorite_space", new=AsyncMock(return_value=fav_space)), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.aget_references_by_knowledge_id",
               new=AsyncMock(return_value=([ref], 1))), \
         patch("bisheng.knowledge.domain.services.knowledge_space_service.KnowledgeFileDao.query_by_id",
               new=AsyncMock(return_value=src)):
        resp = await svc.list_shougang_portal_favorites(page=1, page_size=20)
        assert resp.data[0].status == "valid"


# ── rename_file → 收藏变更站内信接线 ─────────────────────────────────────────

def _svc_for_rename(user_id=7):
    from types import SimpleNamespace
    svc = KnowledgeSpaceService.__new__(KnowledgeSpaceService)
    svc.login_user = SimpleNamespace(user_id=user_id, user_name="u", tenant_id=1)
    svc.request = None
    svc.message_service = object()
    return svc


async def _drive_rename(svc, old_name, new_name):
    """驱动 rename_file，屏蔽其重型依赖，只关心是否触发收藏站内信。"""
    import sys
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch
    from bisheng.knowledge.domain.services import knowledge_space_service as kss

    file_record = SimpleNamespace(
        file_name=old_name, file_source="space_upload", knowledge_id=55,
        file_level_path="", user_metadata=None, updater_id=None, updater_name=None,
        status=None,
    )
    # rename_file 内部 `from bisheng.worker... import rebuild_knowledge_file_chunk`——用桩替掉避免副作用
    fake_worker = MagicMock()
    with patch.dict(sys.modules, {"bisheng.worker.knowledge.rebuild_knowledge_worker": fake_worker}), \
         patch.object(KnowledgeSpaceService, "_get_file_for_action", new=AsyncMock(return_value=file_record)), \
         patch.object(KnowledgeSpaceService, "_require_permission_id", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_ensure_space_async_task_tenant_consistency", new=MagicMock()), \
         patch.object(KnowledgeSpaceService, "_check_filename_sensitive_words", new=MagicMock()), \
         patch.object(KnowledgeSpaceService, "update_folder_update_time", new=AsyncMock()), \
         patch.object(KnowledgeSpaceService, "_notify_favorite_source_changed", new=AsyncMock()) as notify, \
         patch.object(kss.KnowledgeDao, "aquery_by_id", new=AsyncMock(return_value=SimpleNamespace(id=55))), \
         patch.object(kss.KnowledgeDao, "async_update_knowledge_update_time_by_id", new=AsyncMock()), \
         patch.object(kss.SpaceFileDao, "count_file_by_name", new=AsyncMock(return_value=0)), \
         patch.object(kss.KnowledgeFileDao, "async_update", new=AsyncMock(side_effect=lambda r: r)), \
         patch.object(kss.KnowledgeSpaceContentStat, "enqueue_file_stat_async", new=AsyncMock()):
        await svc.rename_file(file_id=321, new_name=new_name)
        return notify


@pytest.mark.asyncio
async def test_rename_file_notifies_when_name_changed():
    from bisheng.knowledge.domain.services.favorite_notify import FAVORITE_SOURCE_RENAMED
    svc = _svc_for_rename()
    notify = await _drive_rename(svc, "old.pdf", "new.pdf")
    notify.assert_awaited_once()
    assert notify.await_args.kwargs["action_code"] == FAVORITE_SOURCE_RENAMED
    assert notify.await_args.kwargs["source_file_id"] == 321
    assert notify.await_args.kwargs["file_name"] == "new.pdf"


@pytest.mark.asyncio
async def test_rename_file_no_notify_when_name_unchanged():
    svc = _svc_for_rename()
    notify = await _drive_rename(svc, "same.pdf", "same.pdf")
    notify.assert_not_awaited()
