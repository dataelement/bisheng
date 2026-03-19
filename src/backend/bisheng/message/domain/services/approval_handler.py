from abc import ABC, abstractmethod

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
