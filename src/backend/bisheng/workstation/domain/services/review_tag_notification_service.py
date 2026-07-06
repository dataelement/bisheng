from __future__ import annotations

import logging
from dataclasses import dataclass

from bisheng.core.database import get_async_db_session
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.message.domain.services.notification_content import build_notify_content

logger = logging.getLogger(__name__)

ACTION_APPROVED_REVIEW_TAG = "approved_review_tag"
ACTION_REJECTED_REVIEW_TAG = "rejected_review_tag"


@dataclass(frozen=True)
class ReviewTagSubmitterTarget:
    user_id: int
    knowledge_space_id: int | None = None


class ReviewTagNotificationService:
    """Inbox notifications for review-tag approve/reject decisions."""

    @staticmethod
    def _resolve_action_code(status: ApproveOrRejectEnum) -> str:
        if status == ApproveOrRejectEnum.APPROVE:
            return ACTION_APPROVED_REVIEW_TAG
        return ACTION_REJECTED_REVIEW_TAG

    @staticmethod
    def _display_target_name(tag_name: str) -> str:
        normalized = (tag_name or "").strip()
        return f"「{normalized}」" if normalized else ""

    @classmethod
    async def notify_after_decision(
        cls,
        *,
        sender: int,
        sender_user_name: str | None,
        tag_name: str,
        status: ApproveOrRejectEnum,
        submitter_targets: list[ReviewTagSubmitterTarget],
        reject_reason: str | None = None,
        fallback_knowledge_id: int | None = None,
    ) -> None:
        if not submitter_targets:
            return

        action_code = cls._resolve_action_code(status)
        target_name = cls._display_target_name(tag_name)
        try:
            from bisheng.message.api.dependencies import get_message_service

            async with get_async_db_session() as session:
                message_service = await get_message_service(session)
                for target in submitter_targets:
                    space_id = target.knowledge_space_id or fallback_knowledge_id
                    await message_service.send_generic_notify(
                        sender=sender,
                        receiver_user_ids=[target.user_id],
                        content_item_list=build_notify_content(
                            action_code=action_code,
                            target_name=target_name,
                            business_type="knowledge_space_id" if space_id is not None else None,
                            business_id=space_id,
                            actor_user_id=sender,
                            actor_user_name=sender_user_name,
                            reason=reject_reason if status == ApproveOrRejectEnum.REJECT else None,
                            navigable=space_id is not None,
                        ),
                        action_code=action_code,
                    )
        except Exception:
            logger.exception(
                "failed to send review tag notification: tag_name=%s status=%s",
                tag_name,
                status,
            )
