"""业务成功后的积分旁路挂钩：独立会话提交，失败只记日志。"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, UserRoleEnum
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_award_facade import (
    AnswerAdoptedEvent,
    DocumentSharedEvent,
    FavoriteChangedEvent,
    PointsAwardFacade,
    SpaceFileReadyEvent,
)
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService

logger = logging.getLogger(__name__)


async def is_platform_super_admin_user(user_id: int) -> bool:
    """按用户 ID 判断平台超管（与中间件同源）。"""
    try:
        from bisheng.utils.http_middleware import _check_is_global_super

        return bool(await _check_is_global_super(int(user_id)))
    except Exception:
        logger.exception("points.award.hooks super_admin_check_failed user_id=%s", user_id)
        return False


async def resolve_space_manager_ids(*space_ids: int) -> frozenset[int]:
    """汇总空间 creator/admin，并兜底纳入知识库 owner。"""
    managers: set[int] = set()
    for raw in space_ids:
        try:
            space_id = int(raw)
        except (TypeError, ValueError):
            continue
        if space_id <= 0:
            continue
        try:
            members = await SpaceChannelMemberDao.async_get_members_by_space(
                space_id,
                user_roles=[UserRoleEnum.CREATOR, UserRoleEnum.ADMIN],
            )
            for member in members or []:
                if getattr(member, "user_id", None) is not None:
                    managers.add(int(member.user_id))
            space = await KnowledgeDao.aquery_by_id(space_id)
            if space is not None and getattr(space, "user_id", None) is not None:
                managers.add(int(space.user_id))
        except Exception:
            logger.exception("points.award.hooks resolve_managers_failed space_id=%s", space_id)
    return frozenset(managers)


async def resolve_space_level(space_id: int) -> str:
    """读取空间等级；缺失时按 personal 处理（Facade 会 skip）。"""
    try:
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(int(space_id))
        if scope is None or scope.level is None:
            return KnowledgeSpaceLevelEnum.PERSONAL.value
        return str(getattr(scope.level, "value", scope.level))
    except Exception:
        logger.exception("points.award.hooks resolve_level_failed space_id=%s", space_id)
        return KnowledgeSpaceLevelEnum.PERSONAL.value


async def _run_with_facade(action) -> None:
    """打开独立积分会话执行门面并提交。"""
    async with get_async_db_session() as session:
        repository = PointsRepository(session)
        ledger = PointsLedgerService(repository)
        facade = PointsAwardFacade(
            repository,
            ledger,
            is_platform_super_admin=is_platform_super_admin_user,
        )
        await action(facade)
        await session.commit()


async def notify_space_files_ready(
    *,
    tenant_id: int,
    space_id: int,
    files: Iterable[Any],
    uploader_id: int,
    publisher_id: int | None = None,
    is_favorite_space: bool | None = None,
    space_level: str | None = None,
) -> None:
    """上传/发布入库成功后发分；不影响主业务事务。"""
    try:
        file_ids = [int(f.id) for f in files if getattr(f, "id", None)]
        if not file_ids:
            return
        favorite = is_favorite_space
        if favorite is None:
            space = await KnowledgeDao.aquery_by_id(int(space_id))
            favorite = bool(space and getattr(space, "is_favorite", False))
        level = space_level or await resolve_space_level(space_id)
        managers = await resolve_space_manager_ids(space_id)

        async def _award(facade: PointsAwardFacade) -> None:
            for file_id in file_ids:
                await facade.on_space_file_ready(
                    SpaceFileReadyEvent(
                        tenant_id=int(tenant_id),
                        space_id=int(space_id),
                        space_level=level,
                        file_id=file_id,
                        uploader_id=int(uploader_id),
                        publisher_id=int(publisher_id) if publisher_id is not None else None,
                        is_favorite_space=bool(favorite),
                        space_manager_ids=managers,
                    )
                )

        await _run_with_facade(_award)
    except Exception:
        logger.exception(
            "points.award.hooks space_file_ready_failed space_id=%s uploader_id=%s",
            space_id,
            uploader_id,
        )


async def notify_favorite_changed(
    *,
    tenant_id: int,
    source_file_id: int,
    source_space_id: int,
    uploader_id: int | None = None,
) -> None:
    """新收藏成功后触发 G3 阶梯；重复收藏入口不应调用。"""
    try:
        file_id = int(source_file_id)
        payee = uploader_id
        if payee is None:
            source_file = await KnowledgeFileDao.query_by_id(file_id)
            if source_file is None or getattr(source_file, "user_id", None) is None:
                return
            payee = int(source_file.user_id)
        referrers = await KnowledgeFileDao.aget_favorite_referrers(file_id)
        unique_count = len({int(row.user_id) for row in referrers if getattr(row, "user_id", None)})
        managers = await resolve_space_manager_ids(int(source_space_id))

        async def _award(facade: PointsAwardFacade) -> None:
            await facade.on_favorite_changed(
                FavoriteChangedEvent(
                    tenant_id=int(tenant_id),
                    file_id=file_id,
                    uploader_id=int(payee),
                    unique_favoriter_count=unique_count,
                    space_manager_ids=managers,
                )
            )

        await _run_with_facade(_award)
    except Exception:
        logger.exception(
            "points.award.hooks favorite_changed_failed file_id=%s",
            source_file_id,
        )


async def notify_answer_adopted(
    *,
    tenant_id: int,
    answer_id: int,
    answerer_id: int,
) -> None:
    """问答采纳成功后触发 G4。"""
    try:
        if not answer_id or not answerer_id:
            return

        async def _award(facade: PointsAwardFacade) -> None:
            await facade.on_answer_adopted(
                AnswerAdoptedEvent(
                    tenant_id=int(tenant_id),
                    answer_id=int(answer_id),
                    answerer_id=int(answerer_id),
                )
            )

        await _run_with_facade(_award)
    except Exception:
        logger.exception(
            "points.award.hooks answer_adopted_failed answer_id=%s",
            answer_id,
        )


async def notify_document_shared(
    *,
    tenant_id: int,
    share_entry_id: int,
    source_space_id: int,
    target_space_id: int,
    uploader_id: int,
    sharer_id: int,
) -> None:
    """库间 SHARE 审批通过后触发 G7；外链分享不得调用。"""
    try:
        managers = await resolve_space_manager_ids(int(source_space_id), int(target_space_id))

        async def _award(facade: PointsAwardFacade) -> None:
            await facade.on_document_shared(
                DocumentSharedEvent(
                    tenant_id=int(tenant_id),
                    share_entry_id=int(share_entry_id),
                    uploader_id=int(uploader_id),
                    sharer_id=int(sharer_id),
                    related_manager_ids=managers,
                )
            )

        await _run_with_facade(_award)
    except Exception:
        logger.exception(
            "points.award.hooks document_shared_failed share_entry_id=%s",
            share_entry_id,
        )
