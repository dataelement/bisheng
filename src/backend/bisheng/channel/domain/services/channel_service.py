from typing import List, Optional

from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.channel_manager_schema import (
    CreateChannelRequest,
    MyChannelQueryRequest,
    SetPinRequest,
    ChannelItemResponse,
    ChannelMemberResponse,
    ChannelMemberPageResponse,
    UpdateMemberRoleRequest,
    RemoveMemberRequest,
    QueryTypeEnum,
    SortByEnum,
)
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.models.space_channel_member import BusinessTypeEnum, UserRoleEnum
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.user.domain.models.user import UserDao

MAX_ADMIN_COUNT = 5

from typing import List, Optional


# Assuming necessary imports like CreateChannelRequest, UserPayload, Channel, etc. are defined elsewhere

class ChannelService:
    def __init__(self, channel_repository: 'ChannelRepository',
                 space_channel_member_repository: 'SpaceChannelMemberRepository'):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository

    async def create_channel(self, channel_data: CreateChannelRequest, login_user: UserPayload):
        """Create a new channel based on the provided data and the logged-in user."""
        channel_model = Channel(
            name=channel_data.name,
            source_list=channel_data.source_list,
            visibility=channel_data.visibility,
            filter_rules=[] if not channel_data.filter_rules else [f.model_dump() for f in channel_data.filter_rules],
            user_id=login_user.user_id,
            is_released=channel_data.is_released
        )

        channel_model = await self.channel_repository.save(channel_model)

        # Add the creator as a member of the channel
        await self.space_channel_member_repository.add_member(
            business_id=channel_model.id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id,
            role=UserRoleEnum.CREATOR
        )

        bisheng_information_client = await get_bisheng_information_client()
        # Subscribe to the information sources associated with the channel
        await bisheng_information_client.subscribe_information_source(channel_data.source_list)

        return channel_model

    async def get_my_channels(self, query_data: MyChannelQueryRequest,
                              login_user: UserPayload) -> List[ChannelItemResponse]:
        """
        Get the list of channels associated with the logged-in user based on the query type (created or followed) and sorting preference.
        """

        if query_data.query_type == QueryTypeEnum.CREATED:
            roles = [UserRoleEnum.CREATOR]
        else:
            # My Followed Channels include both ADMIN and MEMBER roles
            roles = [UserRoleEnum.ADMIN, UserRoleEnum.MEMBER]

        # Get the user's channel memberships based on the query type and active status
        memberships = await self.space_channel_member_repository.find_channel_memberships(
            user_id=login_user.user_id,
            roles=roles,
            status=True
        )

        if not memberships:
            return []

        # Batch query channels by IDs
        channel_ids = [m.business_id for m in memberships]
        channels = await self.channel_repository.find_channels_by_ids(channel_ids)
        channel_map = {ch.id: ch for ch in channels}

        # Build a map of business_id to membership for quick lookup
        membership_map = {m.business_id: m for m in memberships}

        # Construct the result list, filtering out private channels for "followed" query type
        result: List[ChannelItemResponse] = []
        for channel_id, membership in membership_map.items():
            channel = channel_map.get(channel_id)
            if not channel:
                continue

            # if query type is "followed", filter out private channels
            if query_data.query_type == QueryTypeEnum.FOLLOWED:
                if channel.visibility == ChannelVisibilityEnum.PRIVATE:
                    continue

            item = ChannelItemResponse(
                id=channel.id,
                name=channel.name,
                source_list=channel.source_list,
                visibility=channel.visibility,
                is_released=channel.is_released,
                latest_article_update_time=channel.latest_article_update_time,
                create_time=channel.create_time,
                user_role=membership.user_role.value,
                is_pinned=membership.is_pinned,
                subscribed_at=membership.create_time,
            )
            result.append(item)

        # Apply mixed sorting: pinned channels first, then sort by the selected criteria within each group
        result = self._sort_channels(result, query_data.sort_by)

        return result

    @staticmethod
    def _sort_channels(items: List[ChannelItemResponse], sort_by: SortByEnum) -> List[ChannelItemResponse]:
        """
        Sort channels with pinned channels always on top, then sort by the selected criteria:
        """
        from datetime import datetime

        # Define a minimum datetime for comparison when the timestamp is None
        min_dt = datetime.min

        if sort_by == SortByEnum.LATEST_UPDATE:
            def sort_key(item: ChannelItemResponse):
                # Pinned channels get pin_order=0, others get pin_order=1, so pinned channels come first.
                pin_order = 0 if item.is_pinned else 1
                update_time = item.latest_article_update_time or min_dt
                return pin_order, -update_time.timestamp()

        elif sort_by == SortByEnum.LATEST_ADDED:
            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                added_time = item.subscribed_at or min_dt
                return pin_order, -added_time.timestamp()

        else:  # CHANNEL_NAME
            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                return (pin_order, item.name)

        return sorted(items, key=sort_key)

    async def set_channel_pin(self, pin_data: SetPinRequest, login_user: UserPayload) -> bool:
        """
        Set the pin status of a channel for the logged-in user.
        - Validate that the user is a member of the channel
        - Update the is_pinned status in the membership record
        """

        membership = await self.space_channel_member_repository.find_membership(
            business_id=pin_data.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )

        if not membership:
            raise ValueError("User is not a member of the channel")

        await self.space_channel_member_repository.update_pin_status(
            member_id=membership.id,
            is_pinned=pin_data.is_pinned
        )

        return True

    async def list_channel_members(self, channel_id: str, page: int, page_size: int,
                                   keyword: Optional[str], login_user: UserPayload) -> ChannelMemberPageResponse:
        """
        Paginate through the list of channel members.
        - Verify if the current user is a member of the channel
        - Support fuzzy search by username
        - Return user information and associated user groups
        - Sorting: Creators and administrators at the top, regular members sorted by username
        """
        # 1. Verify if the current user is a member of the channel
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or not current_membership.status:
            raise ValueError("You are not a member of this channel and cannot view the member list")

        # 2. If a keyword is provided, perform a fuzzy search on usernames to get matched user_ids
        search_user_ids = None
        if keyword:
            matched_users = await UserDao.afilter_users(user_ids=[], keyword=keyword)
            search_user_ids = [u.user_id for u in matched_users]
            if not search_user_ids:
                return ChannelMemberPageResponse(data=[], total=0)

        # 3. Paginate member records
        members = await self.space_channel_member_repository.find_channel_members_paginated(
            channel_id=channel_id,
            user_ids=search_user_ids,
            page=page,
            page_size=page_size
        )

        # 4. Query total count
        total = await self.space_channel_member_repository.count_channel_members(
            channel_id=channel_id,
            user_ids=search_user_ids
        )

        if not members:
            return ChannelMemberPageResponse(data=[], total=total)

        # 5. Batch query user information
        member_user_ids = [m.user_id for m in members]
        users = await UserDao.aget_user_by_ids(member_user_ids)
        user_map = {u.user_id: u for u in users}

        # 6. Batch query user group information
        result_list: List[ChannelMemberResponse] = []
        for member in members:
            user = user_map.get(member.user_id)
            user_name = user.user_name if user else f"User {member.user_id}"

            # Query user groups the user belongs to
            user_groups = await login_user.get_user_groups(member.user_id)

            result_list.append(ChannelMemberResponse(
                user_id=member.user_id,
                user_name=user_name,
                user_role=member.user_role.value,
                user_groups=user_groups,
            ))

        return ChannelMemberPageResponse(data=result_list, total=total)

    async def update_member_role(self, req: UpdateMemberRoleRequest, login_user: UserPayload) -> bool:
        """
        Set member role (admin/regular member).
        Permissions:
        - Creators can set anyone as an admin or member
        - Admins cannot promote others to admin, nor can they modify the roles of other admins or creators
        - Modifying the creator's role is not allowed
        """
        # 1. Verify current user permissions
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or not current_membership.status:
            raise ValueError("You are not a member of this channel")

        if current_membership.user_role not in (UserRoleEnum.CREATOR, UserRoleEnum.ADMIN):
            raise ValueError("You do not have permission to modify member roles")

        # 2. Query target member
        target_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=req.user_id
        )
        if not target_membership or not target_membership.status:
            raise ValueError("The target user is not a member of this channel")

        # 3. Modifying the creator's role is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Modifying the creator's role is not allowed")

        # 4. Admin permission limits
        if current_membership.user_role == UserRoleEnum.ADMIN:
            # Admins cannot set others as admins
            if req.role == UserRoleEnum.ADMIN.value:
                raise ValueError("Admins do not have permission to set others as admins")
            # Admins cannot modify the roles of other admins
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to modify the roles of other admins")

        # 5. Check maximum limit when setting as an admin
        if req.role == UserRoleEnum.ADMIN.value:
            current_admins = await self.space_channel_member_repository.find_members_by_role(
                channel_id=req.channel_id,
                role=UserRoleEnum.ADMIN
            )
            if len(current_admins) >= MAX_ADMIN_COUNT:
                raise ValueError(
                    f"The number of administrators has reached the maximum limit (up to {MAX_ADMIN_COUNT})")

        # 6. Update role
        target_membership.user_role = UserRoleEnum(req.role)
        await self.space_channel_member_repository.update(target_membership)

        return True

    async def remove_member(self, req: RemoveMemberRequest, login_user: UserPayload) -> bool:
        """
        Remove a member (soft delete).
        Permissions:
        - Creators can remove anyone (except themselves)
        - Admins can remove regular members
        - Admins cannot remove other admins or creators
        """
        # 1. Verify current user permissions
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or not current_membership.status:
            raise ValueError("You are not a member of this channel")

        if current_membership.user_role not in (UserRoleEnum.CREATOR, UserRoleEnum.ADMIN):
            raise ValueError("You do not have permission to remove members")

        # 2. Cannot remove yourself
        if req.user_id == login_user.user_id:
            raise ValueError("Cannot remove yourself")

        # 3. Query target member
        target_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=req.user_id
        )
        if not target_membership or not target_membership.status:
            raise ValueError("The target user is not a member of this channel")

        # 4. Removing the creator is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Removing the creator is not allowed")

        # 5. Admins cannot remove other admins
        if current_membership.user_role == UserRoleEnum.ADMIN:
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to remove other admins")

        # 6. Soft delete: set status to False
        target_membership.status = False
        await self.space_channel_member_repository.update(target_membership)

        return True
