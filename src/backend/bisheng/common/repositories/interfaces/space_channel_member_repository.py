from abc import ABC, abstractmethod

from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    ChannelRelationEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class SpaceChannelMemberRepository(BaseRepository[SpaceChannelMember, int], ABC):
    """SpaceChannelMember repository interface for managing space and channel memberships."""

    pass

    @abstractmethod
    async def add_member(
        self,
        business_id: str,
        business_type: BusinessTypeEnum,
        user_id: int,
        role: UserRoleEnum,
        status: MembershipStatusEnum = MembershipStatusEnum.ACTIVE,
        relation: ChannelRelationEnum | None = None,
        grant_subject_type: str | None = None,
        grant_subject_id: int | None = None,
        grant_relation: ChannelRelationEnum | None = None,
        grant_include_children: bool = False,
        grant_model_id: str | None = None,
        grant_binding_key: str | None = None,
    ) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        pass

    @abstractmethod
    async def find_channel_memberships(
        self, user_id: int, roles: list[UserRoleEnum], statuses: list[MembershipStatusEnum] | None = None
    ) -> list[SpaceChannelMember]:
        """Get all channel memberships for a user filtered by roles and status."""
        pass

    @abstractmethod
    async def find_membership(
        self, business_id: str, business_type: BusinessTypeEnum, user_id: int, include_inactive: bool = False
    ) -> SpaceChannelMember | None:
        """Find a specific membership by business ID, type, and user ID.

        For channels the default only returns ACTIVE members. Set
        ``include_inactive=True`` to also match PENDING/REJECTED rows — required by
        the approval activation flow, which must locate the PENDING membership to
        flip it to ACTIVE.
        """
        pass

    @abstractmethod
    async def find_membership_split(
        self, business_id: str, business_type: BusinessTypeEnum, user_id: int
    ) -> tuple[SpaceChannelMember | None, SpaceChannelMember | None]:
        """Single-query variant for the channel-detail path: returns
        ``(highest_active, highest_any)``.

        The old detail code issued two queries — an ACTIVE-only lookup for
        permission gating and an include-inactive lookup for the displayed
        subscription status. Because a user may hold several membership rows
        (multi-grant model) and the highest-RANK row is not necessarily ACTIVE,
        collapsing both into a single ``include_inactive`` lookup was NOT
        equivalent: a higher-ranked PENDING/REJECTED row could mask an ACTIVE one.
        This returns both derivations from a single DB lookup, preserving exact
        equivalence (AC-06: one membership query).
        """
        pass

    @abstractmethod
    async def update_pin_status(self, member_id: int, is_pinned: bool) -> SpaceChannelMember | None:
        """Update the pin status of a channel membership."""
        pass

    @abstractmethod
    async def find_channel_members_paginated(
        self, channel_id: str, user_ids: list[int] | None = None, page: int = 1, page_size: int = 20
    ) -> list[SpaceChannelMember]:
        """Get a paginated list of channel members, optionally filtered by user IDs."""
        pass

    @abstractmethod
    async def count_channel_members(self, channel_id: str, user_ids: list[int] | None = None) -> int:
        """Count the total number of channel members, optionally filtered by user IDs."""
        pass

    @abstractmethod
    async def find_members_by_role(self, channel_id: str, role: UserRoleEnum) -> list[SpaceChannelMember]:
        """Find all members of a channel with a specific role (e.g., all admins or all regular members)."""
        pass

    @abstractmethod
    async def get_effective_channel_relation(self, channel_id: str, user_id: int) -> ChannelRelationEnum | None:
        """Return the highest active channel relation for one user."""
        pass

    @abstractmethod
    async def find_channel_membership_sources(self, channel_id: str, user_id: int) -> list[SpaceChannelMember]:
        """Return all active source rows for a user's channel visibility."""
        pass

    @abstractmethod
    async def upsert_channel_membership_source(
        self,
        channel_id: str,
        user_id: int,
        relation: ChannelRelationEnum,
        grant_subject_type: str,
        grant_subject_id: int | None = None,
        grant_relation: ChannelRelationEnum | None = None,
        grant_include_children: bool = False,
        grant_model_id: str | None = None,
        grant_binding_key: str | None = None,
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
    async def activate_pending_members(self, channel_id: str) -> list[SpaceChannelMember]:
        """Activate all pending members of a channel (set status to ACTIVE).

        Returns the members that were activated.
        """
        pass
