from abc import ABC, abstractmethod
from typing import List, Dict, Any

from bisheng.message.domain.models.inbox_message import InboxMessage


class ApprovalHandler(ABC):
    """Abstract base class for business-specific approval handlers."""

    @abstractmethod
    def get_action_code(self) -> str:
        """Return the action code this handler handles."""

    @abstractmethod
    async def on_approved(self, message: InboxMessage, operator_user_id: int) -> None:
        """Execute business logic when approval is granted."""

    @abstractmethod
    async def on_rejected(self, message: InboxMessage, operator_user_id: int) -> None:
        """Execute business logic when approval is denied."""

    @staticmethod
    def _extract_business_id(content: List[Dict[str, Any]], business_type: str) -> str:
        """Extract channel ID from approval message content."""
        for item in content:
            metadata = item.get('metadata', {})
            if metadata.get('business_type') != business_type:
                continue

            data = metadata.get('data', {})
            channel_id = data.get(business_type)
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
