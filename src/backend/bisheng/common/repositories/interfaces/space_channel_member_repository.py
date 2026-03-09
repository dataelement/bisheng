from abc import ABC, abstractmethod
from typing import List, Optional

from bisheng.common.models.space_channel_member import SpaceChannelMember, BusinessTypeEnum, UserRoleEnum
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class SpaceChannelMemberRepository(BaseRepository[SpaceChannelMember, int], ABC):
    """SpaceChannelMember repository interface for managing space and channel memberships."""
    pass

    @abstractmethod
    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: bool = True) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        pass

    @abstractmethod
    async def find_channel_memberships(self, user_id: int, roles: List[UserRoleEnum],
                                       status: bool = True) -> List[SpaceChannelMember]:
        """Get all channel memberships for a user filtered by roles and status."""
        pass

    @abstractmethod
    async def find_membership(self, business_id: str, business_type: BusinessTypeEnum,
                              user_id: int) -> Optional[SpaceChannelMember]:
        """Find a specific membership by business ID, type, and user ID."""
        pass

    @abstractmethod
    async def update_pin_status(self, member_id: int, is_pinned: bool) -> Optional[SpaceChannelMember]:
        """Update the pin status of a channel membership."""
        pass

    @abstractmethod
    async def find_channel_members_paginated(self, channel_id: str, user_ids: Optional[List[int]] = None,
                                             page: int = 1, page_size: int = 20) -> List[SpaceChannelMember]:
        """Get a paginated list of channel members, optionally filtered by user IDs."""
        pass

    @abstractmethod
    async def count_channel_members(self, channel_id: str,
                                    user_ids: Optional[List[int]] = None) -> int:
        """Count the total number of channel members, optionally filtered by user IDs."""
        pass

    @abstractmethod
    async def find_members_by_role(self, channel_id: str, role: UserRoleEnum) -> List[SpaceChannelMember]:
        """Find all members of a channel with a specific role (e.g., all admins or all regular members)."""
        pass

