import logging
from typing import Any, Awaitable, Callable, Dict, List

from bisheng.common.models.space_channel_member import BusinessTypeEnum
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.message.domain.models.inbox_message import InboxMessage
from bisheng.message.domain.services.approval_handler import ApprovalHandler

logger = logging.getLogger(__name__)


class ChannelSubscribeApprovalHandler(ApprovalHandler):
    """Handle channel subscription approval actions."""

    def __init__(
        self,
        space_channel_member_repository: SpaceChannelMemberRepository,
        notify_sender: Callable[[int, str, List[int], str], Awaitable[InboxMessage]],
    ):
        self.space_channel_member_repository = space_channel_member_repository
        self.notify_sender = notify_sender

    def get_action_code(self) -> str:
        """Return the channel subscription approval action code."""
        return "request_channel"

    async def on_approved(self, message: InboxMessage, operator_user_id: int) -> None:
        """Activate the pending channel membership after approval."""
        channel_id = self._extract_channel_id(message.content)
        applicant_user_id = self._extract_applicant_user_id(message.content)
        membership = await self._get_membership(channel_id, applicant_user_id)
        if not membership:
            logger.warning(
                "Pending channel membership not found when approving subscription: channel_id=%s, applicant_user_id=%s, message_id=%s",
                channel_id, applicant_user_id, message.id,
            )
            return

        membership.status = True
        await self.space_channel_member_repository.update(membership)
        await self.notify_sender(
            operator_user_id,
            "approved_channel",
            [applicant_user_id],
            "system_text",
        )

    async def on_rejected(self, message: InboxMessage, operator_user_id: int) -> None:
        """Remove the pending channel membership after rejection."""
        channel_id = self._extract_channel_id(message.content)
        applicant_user_id = self._extract_applicant_user_id(message.content)
        membership = await self._get_membership(channel_id, applicant_user_id)
        if not membership or membership.id is None:
            logger.warning(
                "Pending channel membership not found when rejecting subscription: channel_id=%s, applicant_user_id=%s, message_id=%s",
                channel_id, applicant_user_id, message.id,
            )
            return

        await self.space_channel_member_repository.delete(membership.id)
        await self.notify_sender(
            operator_user_id,
            "rejected_channel",
            [applicant_user_id],
            "system_text",
        )

    async def _get_membership(self, channel_id: str, applicant_user_id: int):
        """Load the applicant membership for the target channel."""
        return await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=applicant_user_id,
        )

    @staticmethod
    def _extract_channel_id(content: List[Dict[str, Any]]) -> str:
        """Extract channel ID from approval message content."""
        for item in content:
            metadata = item.get('metadata', {})
            if metadata.get('business_type') != 'channel_id':
                continue

            data = metadata.get('data', {})
            channel_id = data.get('channel_id')
            if channel_id is not None:
                return str(channel_id)

        raise ValueError("Missing channel_id in approval message content")

    @staticmethod
    def _extract_applicant_user_id(content: List[Dict[str, Any]]) -> int:
        """Extract applicant user ID from approval message content."""
        for item in content:
            metadata = item.get('metadata', {})
            user_id = metadata.get('user_id')
            if user_id is not None:
                return int(user_id)

        raise ValueError("Missing applicant user_id in approval message content")
