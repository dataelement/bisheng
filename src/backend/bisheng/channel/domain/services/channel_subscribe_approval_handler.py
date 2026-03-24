import logging
from typing import Awaitable, Callable, List, Any

from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.common.models.space_channel_member import BusinessTypeEnum
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.message.domain.models.inbox_message import InboxMessage
from bisheng.message.domain.schemas.message_schema import UserContentItem, MessageContentItem, BusinessContentItem
from bisheng.message.domain.services.approval_handler import ApprovalHandler
from bisheng.user.domain.models.user import UserDao

logger = logging.getLogger(__name__)


class ChannelSubscribeApprovalHandler(ApprovalHandler):
    """Handle channel subscription approval actions."""

    def __init__(
            self,
            space_channel_member_repository: SpaceChannelMemberRepository,
            channel_repository: ChannelRepository,
            notify_sender: Callable[[int, List[int], Any], Awaitable[InboxMessage]],
    ):
        self.space_channel_member_repository = space_channel_member_repository
        self.channel_repository = channel_repository
        self.notify_sender = notify_sender

    def get_action_code(self) -> str:
        """Return the channel subscription approval action code."""
        return "request_channel"

    async def on_approved(self, message: InboxMessage, operator_user_id: int) -> None:
        """Activate the pending channel membership after approval."""
        channel_id = self._extract_business_id(message.content, "channel_id")
        applicant_user_id = self._extract_applicant_user_id(message.content)
        membership = await self._get_membership(channel_id, applicant_user_id)
        if not membership:
            logger.warning(
                "Pending channel membership not found when approving subscription: channel_id=%s, applicant_user_id=%s, message_id=%s",
                channel_id, applicant_user_id, message.id,
            )
            return
        channel_info = await self.channel_repository.find_by_id(channel_id)
        if not channel_info:
            return

        membership.status = True
        await self.space_channel_member_repository.update(membership)
        operator_user_info = await UserDao.aget_user(operator_user_id)
        await self.notify_sender(
            operator_user_id,
            [applicant_user_id],
            [
                UserContentItem(
                    user_id=operator_user_id,
                    user_name=operator_user_info.user_name if operator_user_info else f"Unknown user {operator_user_id}",
                ),
                MessageContentItem(
                    type="system_text",
                    content="approved_channel",
                ),
                BusinessContentItem(
                    content=f"--{channel_info.name}",
                    business_type="channel_id",
                    business_id=channel_info.id,
                )
            ]
        )

    async def on_rejected(self, message: InboxMessage, operator_user_id: int) -> None:
        """Remove the pending channel membership after rejection."""
        channel_id = self._extract_business_id(message.content, "channel_id")
        applicant_user_id = self._extract_applicant_user_id(message.content)
        membership = await self._get_membership(channel_id, applicant_user_id)
        if not membership or membership.id is None:
            logger.warning(
                "Pending channel membership not found when rejecting subscription: channel_id=%s, applicant_user_id=%s, message_id=%s",
                channel_id, applicant_user_id, message.id,
            )
            return
        channel_info = await self.channel_repository.find_by_id(channel_id)
        if not channel_info:
            return

        await self.space_channel_member_repository.delete(membership.id)

        operator_user_info = await UserDao.aget_user(operator_user_id)

        await self.notify_sender(
            operator_user_id,
            [applicant_user_id],
            [
                UserContentItem(
                    user_id=operator_user_id,
                    user_name=operator_user_info.user_name if operator_user_info else f"Unknown user {operator_user_id}",
                ),
                MessageContentItem(
                    type="system_text",
                    content="rejected_channel",
                ),
                BusinessContentItem(
                    content=f"--{channel_info.name}",
                    business_type="channel_id",
                    business_id=channel_info.id,
                )
            ]
        )

    async def _get_membership(self, channel_id: str, applicant_user_id: int):
        """Load the applicant membership for the target channel."""
        return await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=applicant_user_id,
        )
