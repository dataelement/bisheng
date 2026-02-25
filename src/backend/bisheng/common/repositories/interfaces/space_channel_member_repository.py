from abc import ABC, abstractmethod

from bisheng.common.models.space_channel_member import SpaceChannelMember, BusinessTypeEnum, UserRoleEnum
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class SpaceChannelMemberRepository(BaseRepository[SpaceChannelMember, str], ABC):
    """SpaceChannelMember repository interface for managing space and channel memberships."""
    pass

    @abstractmethod
    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: bool = True) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        pass
