"""收藏源文件变更 → 站内信通知的共享逻辑。

被收藏的源文件发生变更（名称 / 位置 / 标签 / 分类·业务域 / 版本管理）时，
向「收藏了该文件」的用户发送站内信。

KnowledgeSpaceService 与 KnowledgeVersionService 共用本模块，避免重复实现：
前者自带注入好的 message_service，后者通过依赖注入补一个 message_service。

设计要点：
  - 逐收藏者发送：跳转目标指向该用户自己的『我的收藏』空间（必有权限，文件就在里面），
    而不是源文件所在空间（收藏者未必有权限）。
  - 排除编辑者本人。
  - Best-effort：任何异常都被吞掉并记日志，绝不影响调用方的主流程（编辑本身）。
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScopeDao,
)
from bisheng.knowledge.domain.schemas.favorite_notification_schema import (
    FavoriteChangeEvent,
    FavoriteRecipientSnapshot,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileAccessStatus,
)
from bisheng.message.domain.services.notification_content import build_notify_content
from bisheng.permission.domain.services.permission_service import PermissionService
from bisheng.user.domain.models.user import UserDao
from bisheng.user.domain.models.user_role import UserRoleDao

logger = logging.getLogger(__name__)

# 站内信 action_code。前端据此映射到 com_notifications_action_<code> 的 i18n 文案，
# 并按 message metadata 的 business_type=knowledge_space_id 跳转到收藏者自己的收藏库。
FAVORITE_SOURCE_RENAMED = "favorite_source_renamed"
FAVORITE_SOURCE_MOVED = "favorite_source_moved"
FAVORITE_SOURCE_TAGS_UPDATED = "favorite_source_tags_updated"
FAVORITE_SOURCE_CLASSIFICATION_UPDATED = "favorite_source_classification_updated"
FAVORITE_SOURCE_VERSION_UPDATED = "favorite_source_version_updated"
FAVORITE_SOURCE_BUSINESS_DOMAIN_UPDATED = "favorite_source_business_domain_updated"
FAVORITE_SOURCE_SUBCATEGORY_UPDATED = "favorite_source_subcategory_updated"
FAVORITE_SOURCE_VERSION_ADDED = "favorite_source_version_added"
FAVORITE_SOURCE_PRIMARY_VERSION_CHANGED = "favorite_source_primary_version_changed"
FAVORITE_SOURCE_VERSION_DELETED = "favorite_source_version_deleted"
FAVORITE_SOURCE_VERSION_LINKED = "favorite_source_version_linked"
FAVORITE_SOURCE_VERSION_UNLINKED = "favorite_source_version_unlinked"
FAVORITE_SOURCE_DELETED = "favorite_source_deleted"

MAX_EVENTS_PER_TASK = 100
MAX_DELETE_RECIPIENTS_PER_EVENT = 100

CanViewFile = Callable[[int, object], Awaitable[bool]]


async def can_user_view_favorite_source(
    *,
    user_id: int,
    source_file: object,
    tenant_id: int,
    department_access_service=None,
    public_space_cache: dict[int, bool] | None = None,
) -> bool:
    """按 Portal 实际可见性判断收藏者是否仍可查看源文件。"""
    normalized_tenant_id = int(tenant_id)
    if int(getattr(source_file, "tenant_id", 0) or 0) != normalized_tenant_id:
        return False

    user = await UserDao.aget_user(int(user_id))
    if user is None or int(getattr(user, "delete", 0) or 0) != 0:
        return False

    space_id = int(getattr(source_file, "knowledge_id", 0) or 0)
    is_public = (
        public_space_cache.get(space_id)
        if public_space_cache is not None and space_id in public_space_cache
        else None
    )
    if is_public is None:
        scope = await KnowledgeSpaceScopeDao.aget_by_space_id(space_id)
        is_public = bool(
            scope
            and int(getattr(scope, "tenant_id", 0) or 0) == normalized_tenant_id
            and getattr(getattr(scope, "level", None), "value", getattr(scope, "level", None))
            == KnowledgeSpaceLevelEnum.PUBLIC.value
        )
        if public_space_cache is not None:
            public_space_cache[space_id] = is_public
    if is_public:
        return True

    roles = await UserRoleDao.aget_user_roles(int(user_id))
    login_user = UserPayload(
        user_id=int(user_id),
        user_name=str(getattr(user, "user_name", "") or ""),
        user_role=[int(role.role_id) for role in roles] or [-1],
        tenant_id=normalized_tenant_id,
    )

    if department_access_service is not None:
        decision = await department_access_service.evaluate_file(
            login_user=login_user,
            file=source_file,
        )
        if decision.status == DepartmentFileAccessStatus.ALLOWED:
            return True
        if decision.status != DepartmentFileAccessStatus.NOT_APPLICABLE:
            return False

    return await PermissionService.check(
        user_id=int(user_id),
        relation="can_read",
        object_type="knowledge_file",
        object_id=str(source_file.id),
        login_user=login_user,
    )


async def collect_favorite_recipient_snapshots(
    *,
    file_repository,
    source_files: Iterable[object],
    actor_user_id: int,
    can_view_file: CanViewFile,
) -> dict[int, list[FavoriteRecipientSnapshot]]:
    """在删除 mutation 前冻结仍可查看源文件的收藏者。"""
    files_by_id = {
        int(file.id): file
        for file in source_files
        if getattr(file, "id", None) is not None
    }
    result: dict[int, list[FavoriteRecipientSnapshot]] = {
        file_id: [] for file_id in files_by_id
    }
    if not files_by_id:
        return result
    references = await file_repository.find_favorite_referrers_by_source_file_ids(
        sorted(files_by_id)
    )
    seen: set[tuple[int, int]] = set()
    for reference in references:
        source_space_id, source_file_id = FavoriteNotificationService._reference_source(
            reference
        )
        source_file = files_by_id.get(source_file_id)
        if source_file is None:
            continue
        if source_space_id != int(getattr(source_file, "knowledge_id", 0) or 0):
            continue
        if int(getattr(reference, "tenant_id", 0) or 0) != int(
            getattr(source_file, "tenant_id", 0) or 0
        ):
            continue
        user_id = int(getattr(reference, "user_id", 0) or 0)
        favorite_space_id = int(getattr(reference, "knowledge_id", 0) or 0)
        if (
            not user_id
            or not favorite_space_id
            or user_id == int(actor_user_id)
            or (source_file_id, user_id) in seen
        ):
            continue
        try:
            allowed = await can_view_file(user_id, source_file)
        except Exception:
            logger.exception(
                "favorite delete snapshot permission check failed: file_id=%s user_id=%s",
                source_file_id,
                user_id,
            )
            continue
        if not allowed:
            continue
        seen.add((source_file_id, user_id))
        result[source_file_id].append(
            FavoriteRecipientSnapshot(
                user_id=user_id,
                favorite_space_id=favorite_space_id,
            )
        )
    return result


def _split_delete_recipient_snapshots(
    event: FavoriteChangeEvent,
) -> list[FavoriteChangeEvent]:
    recipients = list(event.recipient_snapshots or [])
    if not recipients or len(recipients) <= MAX_DELETE_RECIPIENTS_PER_EVENT:
        return [event]
    split_events: list[FavoriteChangeEvent] = []
    for offset in range(0, len(recipients), MAX_DELETE_RECIPIENTS_PER_EVENT):
        split_events.append(
            event.model_copy(
                update={
                    "event_id": f"{event.event_id}:{offset // MAX_DELETE_RECIPIENTS_PER_EVENT}",
                    "recipient_snapshots": recipients[
                        offset : offset + MAX_DELETE_RECIPIENTS_PER_EVENT
                    ],
                }
            )
        )
    return split_events


def _get_favorite_notification_task():
    from bisheng.worker.knowledge.favorite_notification import (
        send_favorite_change_notifications,
    )

    return send_favorite_change_notifications


def enqueue_favorite_change_events(events: Iterable[FavoriteChangeEvent]) -> None:
    """尽力投递字段级变化事件，不让 broker 状态影响文档主流程。"""
    expanded: list[FavoriteChangeEvent] = []
    for event in events:
        if event.recipient_snapshots is not None and not event.recipient_snapshots:
            continue
        expanded.extend(_split_delete_recipient_snapshots(event))
    if not expanded:
        return

    send_favorite_change_notifications = _get_favorite_notification_task()

    by_tenant: dict[int, list[FavoriteChangeEvent]] = defaultdict(list)
    for event in expanded:
        by_tenant[int(event.tenant_id)].append(event)
    for tenant_events in by_tenant.values():
        for offset in range(0, len(tenant_events), MAX_EVENTS_PER_TASK):
            batch = tenant_events[offset : offset + MAX_EVENTS_PER_TASK]
            try:
                send_favorite_change_notifications.apply_async(
                    args=[[event.model_dump(mode="json") for event in batch]],
                    queue="celery",
                )
            except Exception:
                # 通知是明确的尽力流程；入队失败不能回滚已完成的文档操作。
                logger.exception(
                    "favorite notify enqueue failed: tenant_id=%s event_count=%s",
                    batch[0].tenant_id,
                    len(batch),
                )


class FavoriteNotificationService:
    """批量解析收藏者并写入站内信。"""

    def __init__(
        self,
        *,
        file_repository,
        message_service,
        can_view_file: CanViewFile,
    ):
        self.file_repository = file_repository
        self.message_service = message_service
        self.can_view_file = can_view_file

    @staticmethod
    def _reference_source(row) -> tuple[int, int]:
        reference = (getattr(row, "user_metadata", None) or {}).get(
            "favorite_reference"
        ) or {}
        try:
            return (
                int(reference.get("source_space_id") or 0),
                int(reference.get("source_file_id") or 0),
            )
        except (TypeError, ValueError):
            return 0, 0

    async def consume(self, events: list[FavoriteChangeEvent]) -> int:
        if not events:
            return 0
        ordinary_events = [
            event
            for event in events
            if event.recipient_snapshots is None
        ]
        references_by_file: dict[int, list[object]] = defaultdict(list)
        files_by_id: dict[int, object] = {}
        if ordinary_events:
            source_file_ids = sorted(
                {int(event.source_file_id) for event in ordinary_events}
            )
            references = (
                await self.file_repository.find_favorite_referrers_by_source_file_ids(
                    source_file_ids
                )
            )
            for reference in references:
                _, source_file_id = self._reference_source(reference)
                if source_file_id:
                    references_by_file[source_file_id].append(reference)
            files = await self.file_repository.find_by_ids(source_file_ids)
            files_by_id = {
                int(file.id): file
                for file in files
                if getattr(file, "id", None) is not None
            }

        sent = 0
        delivered: set[tuple] = set()
        for event in events:
            if event.recipient_snapshots is not None:
                recipients = [
                    (snapshot.user_id, snapshot.favorite_space_id)
                    for snapshot in event.recipient_snapshots or []
                ]
            else:
                source_file = files_by_id.get(int(event.source_file_id))
                if (
                    source_file is None
                    or int(getattr(source_file, "tenant_id", 0) or 0)
                    != int(event.tenant_id)
                    or int(getattr(source_file, "knowledge_id", 0) or 0)
                    != int(event.source_space_id)
                    or getattr(source_file, "deleted_at", None) is not None
                ):
                    continue
                recipients = []
                for reference in references_by_file.get(int(event.source_file_id), []):
                    source_space_id, _ = self._reference_source(reference)
                    if source_space_id != int(event.source_space_id):
                        continue
                    if int(getattr(reference, "tenant_id", 0) or 0) != int(
                        event.tenant_id
                    ):
                        continue
                    user_id = int(getattr(reference, "user_id", 0) or 0)
                    favorite_space_id = int(
                        getattr(reference, "knowledge_id", 0) or 0
                    )
                    if not user_id or not favorite_space_id:
                        continue
                    try:
                        allowed = await self.can_view_file(user_id, source_file)
                    except Exception:
                        logger.exception(
                            "favorite notify permission check failed: file_id=%s user_id=%s",
                            event.source_file_id,
                            user_id,
                        )
                        continue
                    if allowed:
                        recipients.append((user_id, favorite_space_id))

            for user_id, favorite_space_id in recipients:
                if int(user_id) == int(event.actor_user_id):
                    continue
                dedupe_key = (
                    int(event.source_file_id),
                    event.action_code,
                    int(user_id),
                    repr(event.before_value),
                    repr(event.after_value),
                )
                if dedupe_key in delivered:
                    continue
                delivered.add(dedupe_key)
                try:
                    await self.message_service.send_generic_notify(
                        sender=int(event.actor_user_id),
                        receiver_user_ids=[int(user_id)],
                        content_item_list=build_notify_content(
                            action_code=event.action_code,
                            target_name=event.file_name,
                            business_type="knowledge_space_id",
                            business_id=int(favorite_space_id),
                            actor_user_id=int(event.actor_user_id),
                            actor_user_name=event.actor_user_name,
                            navigable=True,
                            metadata={
                                "data": {
                                    "favorite_change": {
                                        "source_file_id": str(
                                            event.source_file_id
                                        ),
                                        "action_code": event.action_code,
                                        "before_value": event.before_value,
                                        "after_value": event.after_value,
                                    }
                                }
                            },
                        ),
                        action_code=event.action_code,
                    )
                    sent += 1
                except Exception:
                    # 单条消息是尽力发送；失败后继续处理同批次其他接收人。
                    logger.exception(
                        "favorite notify send failed: file_id=%s action_code=%s user_id=%s",
                        event.source_file_id,
                        event.action_code,
                        user_id,
                    )
        return sent


async def notify_favorite_source_changed(
    message_service,
    *,
    source_file_id: int,
    file_name: str,
    action_code: str,
    actor_user_id: int,
    actor_user_name: str | None = None,
) -> None:
    """给收藏了 ``source_file_id`` 的用户逐一发送站内信。

    参数：
        message_service: 已注入好的 MessageService（None 时直接返回，不发送）。
        source_file_id: 被收藏的源文件 id（即收藏引用里的 source_file_id）。
        file_name: 站内信中展示的文件名（用变更后的最新名称）。
        action_code: 见本模块常量，决定前端展示的变更类型文案。
        actor_user_id: 编辑者 user_id（会被排除，不给自己发）。
        actor_user_name: 编辑者展示名（渲染成 @昵称）。
    """
    if message_service is None:
        return
    try:
        fid = int(source_file_id)
    except (TypeError, ValueError):
        return
    if fid <= 0:
        return

    try:
        referrers = await KnowledgeFileDao.aget_favorite_referrers(fid)
    except Exception:
        logger.exception("favorite notify: reverse-lookup failed file_id=%s", fid)
        return

    seen: set[int] = set()
    for ref in referrers or []:
        try:
            uid = int(getattr(ref, "user_id", 0) or 0)
            fav_space_id = int(getattr(ref, "knowledge_id", 0) or 0)
            if not uid or not fav_space_id:
                continue
            if uid == int(actor_user_id):
                continue  # 不给编辑者本人发
            if uid in seen:
                continue  # 同一用户多条引用只发一次
            seen.add(uid)

            display_name = file_name or getattr(ref, "file_name", "") or ""
            await message_service.send_generic_notify(
                sender=int(actor_user_id),
                receiver_user_ids=[uid],
                content_item_list=build_notify_content(
                    action_code=action_code,
                    target_name=display_name,
                    business_type="knowledge_space_id",
                    business_id=fav_space_id,
                    actor_user_id=int(actor_user_id),
                    actor_user_name=actor_user_name,
                    navigable=True,
                ),
                action_code=action_code,
            )
        except Exception:
            logger.exception(
                "favorite notify: send failed file_id=%s action_code=%s recipient=%s",
                fid,
                action_code,
                getattr(ref, "user_id", None),
            )
