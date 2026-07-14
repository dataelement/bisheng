from __future__ import annotations

import logging

from bisheng.core.database import get_async_db_session
from bisheng.database.models.review_tags import ApproveOrRejectEnum
from bisheng.message.domain.services.notification_content import build_notify_content
from bisheng.workstation.domain.schemas.review_tags_schema import ReviewTagSubmitterTarget

logger = logging.getLogger(__name__)

ACTION_APPROVED_REVIEW_TAG = "approved_review_tag"
ACTION_REJECTED_REVIEW_TAG = "rejected_review_tag"


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
                    file_id = target.file_id
                    if file_id is not None and space_id is not None:
                        notify_metadata = {
                            "data": {
                                "knowledge_space_id": str(space_id),
                                "file_id": str(file_id),
                                "file_name": target.file_name or "",
                                "file_type": target.file_type or "",
                            }
                        }
                        business_type = "knowledge_file_id"
                        business_id = file_id
                        navigable = True
                    elif space_id is not None:
                        notify_metadata = None
                        business_type = "knowledge_space_id"
                        business_id = space_id
                        navigable = True
                    else:
                        notify_metadata = None
                        business_type = None
                        business_id = None
                        navigable = False

                    await message_service.send_generic_notify(
                        sender=sender,
                        receiver_user_ids=[target.user_id],
                        content_item_list=build_notify_content(
                            action_code=action_code,
                            target_name=target_name,
                            business_type=business_type,
                            business_id=business_id,
                            actor_user_id=sender,
                            actor_user_name=sender_user_name,
                            reason=reject_reason if status == ApproveOrRejectEnum.REJECT else None,
                            navigable=navigable,
                            metadata=notify_metadata,
                        ),
                        action_code=action_code,
                    )
        except Exception:
            logger.exception(
                "failed to send review tag notification: tag_name=%s status=%s",
                tag_name,
                status,
            )
