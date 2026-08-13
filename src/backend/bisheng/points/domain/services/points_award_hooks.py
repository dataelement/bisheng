"""业务成功后的积分旁路挂钩：可异步投递 Celery，失败不影响主业务。"""

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
from bisheng.points.domain.constants.notify_templates import resolve_earn_notify
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_award_facade import (
    AnswerAdoptedEvent,
    AwardOutcome,
    DocumentSharedEvent,
    FavoriteChangedEvent,
    PointsAwardFacade,
    SpaceFileReadyEvent,
)
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.points.domain.services.points_notify_service import build_points_notify_service

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


def _award_async_enabled() -> bool:
    """读取 points.award_async_enabled；默认 True。"""
    try:
        from bisheng.common.services.config_service import settings

        return bool(getattr(getattr(settings, "points", None), "award_async_enabled", True))
    except Exception:
        return True


def _normalize_outcomes(raw) -> list[AwardOutcome]:
    """将 Facade action 返回值规范为 outcome 列表。"""
    if raw is None:
        return []
    if isinstance(raw, AwardOutcome):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, AwardOutcome)]
    return []


async def _flush_award_notifies(outcomes: list[AwardOutcome]) -> None:
    """账本已提交后发送积分站内信；失败只记日志。"""
    pending = [item for item in outcomes if item.should_notify]
    if not pending:
        return
    try:
        async with get_async_db_session() as session:
            notify = await build_points_notify_service(session)
            for item in pending:
                template, values = resolve_earn_notify(
                    item.rule_code or "",
                    rule_name=item.rule_name or item.rule_code or "",
                    delta=int(item.result.applied_delta) if item.result else 0,
                    **(item.notify_extra or {}),
                )
                await notify.notify(
                    user_id=int(item.notify_user_id),
                    template_code=template,
                    **values,
                )
            await session.commit()
    except Exception:
        # 站内信旁路：不得影响已入账积分。
        logger.exception("points.award.notify_failed count=%s", len(pending))


async def _run_with_facade(action) -> list[AwardOutcome]:
    """打开独立积分会话执行门面、提交，再尽力发站内信。

    MessageService 仅在 commit 后的通知会话注入，避免消息依赖故障阻断入账。
    """
    outcomes: list[AwardOutcome] = []
    async with get_async_db_session() as session:
        repository = PointsRepository(session)
        ledger = PointsLedgerService(repository)
        facade = PointsAwardFacade(
            repository,
            ledger,
            is_platform_super_admin=is_platform_super_admin_user,
        )
        outcomes = _normalize_outcomes(await action(facade))
        await session.commit()
    await _flush_award_notifies(outcomes)
    return outcomes


def _resolve_award_queue() -> str:
    """解析发分投递队列名。

    默认 points_award_celery；POINTS_AWARD_CELERY_QUEUE 非空时覆盖（压测隔离）。
    """
    import os

    from bisheng.core.config.celery_queues import POINTS_AWARD_QUEUE

    return (os.environ.get("POINTS_AWARD_CELERY_QUEUE") or "").strip() or POINTS_AWARD_QUEUE


def _enqueue_award_event(body: dict[str, Any]) -> None:
    """投递 Celery 发分任务；抽出以便单测 patch，避开 conftest 对 worker 包的 mock。

    默认投递到 points_award_celery（见 celery_queues.POINTS_AWARD_QUEUE）。
    """
    from bisheng.worker.points.tasks import process_points_award_event

    process_points_award_event.apply_async(args=[body], queue=_resolve_award_queue())


async def _dispatch(event_type: str, payload: dict[str, Any]) -> None:
    """按开关异步投递或同步入账；enqueue 失败则 fallback 同步一次。"""
    body = {"event_type": event_type, **payload}
    if not _award_async_enabled():
        await _run_payload_sync(body)
        return
    try:
        _enqueue_award_event(body)
        logger.info(
            "points.award.enqueued event_type=%s tenant_id=%s",
            event_type,
            payload.get("tenant_id"),
        )
    except Exception:
        # Broker 不可用时降级同步，避免丢事件。
        logger.exception(
            "points.award.enqueue_fallback_sync event_type=%s tenant_id=%s",
            event_type,
            payload.get("tenant_id"),
        )
        await _run_payload_sync(body)


async def _run_payload_sync(payload: dict[str, Any]) -> None:
    """与 Celery worker 相同的事件分发，供同步路径与 enqueue fallback 复用。"""

    async def _award(facade: PointsAwardFacade) -> AwardOutcome:
        event_type = str(payload.get("event_type") or "")
        if event_type == "space_file_ready":
            return await facade.on_space_file_ready(
                SpaceFileReadyEvent(
                    tenant_id=int(payload["tenant_id"]),
                    space_id=int(payload["space_id"]),
                    space_level=str(payload["space_level"]),
                    file_id=int(payload["file_id"]),
                    uploader_id=int(payload["uploader_id"]),
                    publisher_id=(int(payload["publisher_id"]) if payload.get("publisher_id") is not None else None),
                    is_favorite_space=bool(payload.get("is_favorite_space")),
                    space_manager_ids=frozenset(int(x) for x in (payload.get("space_manager_ids") or [])),
                )
            )
        if event_type == "document_shared":
            return await facade.on_document_shared(
                DocumentSharedEvent(
                    tenant_id=int(payload["tenant_id"]),
                    share_entry_id=int(payload["share_entry_id"]),
                    uploader_id=int(payload["uploader_id"]),
                    sharer_id=int(payload["sharer_id"]),
                    related_manager_ids=frozenset(int(x) for x in (payload.get("related_manager_ids") or [])),
                )
            )
        if event_type == "favorite_changed":
            return await facade.on_favorite_changed(
                FavoriteChangedEvent(
                    tenant_id=int(payload["tenant_id"]),
                    file_id=int(payload["file_id"]),
                    uploader_id=int(payload["uploader_id"]),
                    unique_favoriter_count=int(payload["unique_favoriter_count"]),
                    space_manager_ids=frozenset(int(x) for x in (payload.get("space_manager_ids") or [])),
                )
            )
        if event_type == "answer_adopted":
            return await facade.on_answer_adopted(
                AnswerAdoptedEvent(
                    tenant_id=int(payload["tenant_id"]),
                    question_id=int(payload["question_id"]),
                    answer_id=int(payload["answer_id"]),
                    answerer_id=int(payload["answerer_id"]),
                )
            )
        raise ValueError(f"unknown points award event_type={event_type}")

    await _run_with_facade(_award)


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
    """上传/发布入库成功后发分；一文件一任务（或同步路径一批处理）。"""
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
        manager_list = sorted(int(x) for x in managers)

        if not _award_async_enabled():
            # 同步：同一会话批量处理，减少连接开销；仍按文件各发一条站内信。
            async def _award(facade: PointsAwardFacade) -> list[AwardOutcome]:
                outs: list[AwardOutcome] = []
                for file_id in file_ids:
                    outs.append(
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
                    )
                return outs

            await _run_with_facade(_award)
            return

        for file_id in file_ids:
            await _dispatch(
                "space_file_ready",
                {
                    "tenant_id": int(tenant_id),
                    "space_id": int(space_id),
                    "space_level": level,
                    "file_id": int(file_id),
                    "uploader_id": int(uploader_id),
                    "publisher_id": int(publisher_id) if publisher_id is not None else None,
                    "is_favorite_space": bool(favorite),
                    "space_manager_ids": manager_list,
                },
            )
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
        await _dispatch(
            "favorite_changed",
            {
                "tenant_id": int(tenant_id),
                "file_id": file_id,
                "uploader_id": int(payee),
                "unique_favoriter_count": int(unique_count),
                "space_manager_ids": sorted(int(x) for x in managers),
            },
        )
    except Exception:
        logger.exception(
            "points.award.hooks favorite_changed_failed file_id=%s",
            source_file_id,
        )


async def notify_answer_adopted(
    *,
    tenant_id: int,
    question_id: int,
    answer_id: int,
    answerer_id: int,
) -> None:
    """问答采纳成功后触发 G4（同题同回答者幂等一次）。"""
    try:
        if not question_id or not answer_id or not answerer_id:
            return
        await _dispatch(
            "answer_adopted",
            {
                "tenant_id": int(tenant_id),
                "question_id": int(question_id),
                "answer_id": int(answer_id),
                "answerer_id": int(answerer_id),
            },
        )
    except Exception:
        logger.exception(
            "points.award.hooks answer_adopted_failed question_id=%s answer_id=%s",
            question_id,
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
        await _dispatch(
            "document_shared",
            {
                "tenant_id": int(tenant_id),
                "share_entry_id": int(share_entry_id),
                "uploader_id": int(uploader_id),
                "sharer_id": int(sharer_id),
                "related_manager_ids": sorted(int(x) for x in managers),
            },
        )
    except Exception:
        logger.exception(
            "points.award.hooks document_shared_failed share_entry_id=%s",
            share_entry_id,
        )
