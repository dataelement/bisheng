from typing import Callable, List, Awaitable, Tuple, Any

from bisheng.common.models.space_channel_member import SpaceChannelMemberDao, SpaceChannelMember
from bisheng.knowledge.domain.models.knowledge import KnowledgeDao, Knowledge
from bisheng.message.domain.models.inbox_message import InboxMessage
from bisheng.message.domain.schemas.message_schema import MessageContentItem, UserContentItem, BusinessContentItem
from bisheng.message.domain.services.approval_handler import ApprovalHandler
from bisheng.user.domain.models.user import UserDao, User


class KnowledgeSpaceSubscribeHandler(ApprovalHandler):
    def __init__(self, notify_sender: Callable[[int, List[int], Any], Awaitable[InboxMessage]]):
        self.notify_sender = notify_sender

    def get_action_code(self) -> str:
        """Return the channel subscription approval action code."""
        return "request_knowledge_space"

    async def _get_base_info(self, message: InboxMessage, operator_user_id: int) -> Tuple[
        Knowledge | None,
        SpaceChannelMember | None,
        User | None]:
        space_id = self._extract_business_id(message.content, "knowledge_space_id")
        applicant_user_id = self._extract_applicant_user_id(message.content)
        space_info = await KnowledgeDao.aquery_by_id(int(space_id))
        if not space_info:
            return None, None, None

        memory_info = await SpaceChannelMemberDao.async_find_member(space_info.id, applicant_user_id)
        if not memory_info or memory_info.status:
            return None, None, None

        operator_user_info = await UserDao.aget_user(operator_user_id)
        return space_info, memory_info, operator_user_info

    async def on_approved(self, message: InboxMessage, operator_user_id: int) -> None:
        """Execute business logic when approval is granted."""
        space_info, memory_info, operator_user_info = await self._get_base_info(message, operator_user_id)
        if not space_info or not memory_info:
            return

        memory_info.status = True
        await SpaceChannelMemberDao.update(memory_info)

        await self.notify_sender(
            operator_user_id,
            [memory_info.user_id],
            [
                UserContentItem(
                    user_id=operator_user_id,
                    user_name=operator_user_info.user_name if operator_user_info else f"Unknown user {operator_user_id}",
                ),
                MessageContentItem(
                    type="system_text",
                    content="approved_knowledge_space",
                ),
                BusinessContentItem(
                    business_name=space_info.name,
                    business_type="knowledge_space_id",
                    business_id=str(space_info.id),
                )
            ],
        )

    async def on_rejected(self, message: InboxMessage, operator_user_id: int) -> None:
        """Execute business logic when approval is denied."""
        space_info, memory_info, operator_user_info = await self._get_base_info(message, operator_user_id)
        if not space_info or not memory_info:
            return

        await self.notify_sender(
            operator_user_id,
            [memory_info.user_id],
            [
                UserContentItem(
                    user_id=operator_user_id,
                    user_name=operator_user_info.user_name if operator_user_info else f"Unknown user {operator_user_id}",
                ),
                MessageContentItem(
                    type="system_text",
                    content="rejected_knowledge_space",
                ),
                BusinessContentItem(
                    business_name=space_info.name,
                    business_type="knowledge_space_id",
                    business_id=str(space_info.id),
                )
            ],
        )
