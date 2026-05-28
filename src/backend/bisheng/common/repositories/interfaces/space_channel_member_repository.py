from abc import ABC, abstractmethod
from typing import List, Optional

from bisheng.common.models.space_channel_member import (
    SpaceChannelMember,
    BusinessTypeEnum,
    ChannelRelationEnum,
    UserRoleEnum,
    MembershipStatusEnum,
)
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class SpaceChannelMemberRepository(BaseRepository[SpaceChannelMember, int], ABC):
    """SpaceChannelMember repository interface for managing space and channel memberships."""
    pass

    @abstractmethod
    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
                         relation: Optional[ChannelRelationEnum] = None,
                         grant_subject_type: Optional[str] = None,
                         grant_subject_id: Optional[int] = None,
                         grant_relation: Optional[ChannelRelationEnum] = None,
                         grant_include_children: bool = False,
                         grant_model_id: Optional[str] = None,
                         grant_binding_key: Optional[str] = None) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        pass

    @abstractmethod
    async def find_channel_memberships(self, user_id: int, roles: List[UserRoleEnum],
                                       statuses: Optional[List[MembershipStatusEnum]] = None) -> List[SpaceChannelMember]:
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

    @abstractmethod
    async def get_effective_channel_relation(self, channel_id: str, user_id: int) -> Optional[ChannelRelationEnum]:
        """Return the highest active channel relation for one user."""
        pass

    @abstractmethod
    async def find_channel_membership_sources(self, channel_id: str, user_id: int) -> List[SpaceChannelMember]:
        """Return all active source rows for a user's channel visibility."""
        pass

    @abstractmethod
    async def upsert_channel_membership_source(
        self,
        channel_id: str,
        user_id: int,
        relation: ChannelRelationEnum,
        grant_subject_type: str,
        grant_subject_id: Optional[int] = None,
        grant_relation: Optional[ChannelRelationEnum] = None,
        grant_include_children: bool = False,
        grant_model_id: Optional[str] = None,
        grant_binding_key: Optional[str] = None,
        status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
    ) -> SpaceChannelMember:
        """Create or update a channel membership row for a specific grant source."""
        pass

    @abstractmethod
    async def delete_channel_membership_source(self, channel_id: str, grant_binding_key: str) -> int:
        """Delete all source rows tied to one grant binding key."""
        pass

    @abstractmethod
    async def delete_channel_membership_source_users_not_in(
        self,
        channel_id: str,
        grant_binding_key: str,
        user_ids: list[int],
    ) -> int:
        """Delete stale source rows tied to one grant binding key."""
        pass

    @abstractmethod
    async def has_channel_organization_source(self, channel_id: str, user_id: int) -> bool:
        """Whether a user has active department or user-group channel source."""
        pass

    @abstractmethod
    async def remove_channel_subscription_members(self, channel_id: str) -> int:
        """Remove channel square subscription members while preserving authorization grants."""
        pass

    @abstractmethod
    async def remove_non_creator_members(self, channel_id: str) -> None:
        """Remove all members of a channel except the creator (hard delete)."""
        pass

    @abstractmethod
    async def remove_rejected_members(self, channel_id: str) -> None:
        """Remove all rejected members from a channel."""
        pass

    @abstractmethod
    async def activate_pending_members(self, channel_id: str) -> int:
        """Activate all pending members of a channel (set status to True).

        Returns the number of members activated.
        """
        pass
