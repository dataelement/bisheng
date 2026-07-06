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
from typing import Optional

from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
from bisheng.message.domain.services.notification_content import build_notify_content

logger = logging.getLogger(__name__)

# 站内信 action_code。前端据此映射到 com_notifications_action_<code> 的 i18n 文案，
# 并按 message metadata 的 business_type=knowledge_space_id 跳转到收藏者自己的收藏库。
FAVORITE_SOURCE_RENAMED = "favorite_source_renamed"
FAVORITE_SOURCE_MOVED = "favorite_source_moved"
FAVORITE_SOURCE_TAGS_UPDATED = "favorite_source_tags_updated"
FAVORITE_SOURCE_CLASSIFICATION_UPDATED = "favorite_source_classification_updated"
FAVORITE_SOURCE_VERSION_UPDATED = "favorite_source_version_updated"


async def notify_favorite_source_changed(
    message_service,
    *,
    source_file_id: int,
    file_name: str,
    action_code: str,
    actor_user_id: int,
    actor_user_name: Optional[str] = None,
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
