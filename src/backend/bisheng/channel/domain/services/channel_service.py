import asyncio
import logging
from datetime import timedelta, datetime
from typing import List, Optional, Dict, Any

from bisheng.channel.domain.models.article_read_record import ArticleReadRecord
from bisheng.channel.domain.models.channel import Channel, ChannelVisibilityEnum
from bisheng.channel.domain.models.channel_info_source import ChannelInfoSource
from bisheng.channel.domain.repositories.implementations.channel_repository_impl import ChannelRepositoryImpl
from bisheng.channel.domain.repositories.interfaces.article_read_repository import ArticleReadRepository
from bisheng.channel.domain.repositories.interfaces.channel_info_source_repository import ChannelInfoSourceRepository
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.article_schema import ArticleSearchPageResponse
from bisheng.channel.domain.schemas.channel_manager_schema import (
    AddArticlesToKnowledgeSpaceRequest,
    CreateChannelRequest,
    UpdateChannelRequest,
    MyChannelQueryRequest,
    SetPinRequest,
    ChannelItemResponse,
    ChannelDetailResponse,
    ChannelMemberResponse,
    ChannelMemberPageResponse,
    UpdateMemberRoleRequest,
    RemoveMemberRequest,
    QueryTypeEnum,
    SortByEnum,
    SubscriptionStatusEnum,
    ChannelSquareItemResponse,
    ChannelSquarePageResponse,
    SubscribeChannelRequest,
    KnowledgeSyncConfig,
    KnowledgeSyncMainConfig,
    KnowledgeSyncSubConfig,
    KnowledgeSyncSpaceItem,
)
from bisheng.channel.domain.models.channel_knowledge_sync import (
    ChannelKnowledgeSync,
    ChannelKnowledgeSyncDao,
)
from bisheng.channel.domain.services.article_es_service import ArticleEsService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.channel import (
    ChannelNotFoundError,
    ChannelAccessDeniedError,
    ChannelPermissionDeniedError,
    ChannelCreateLimitExceededError,
    ChannelAdminLimitExceededError,
    ChannelSubscribeLimitExceededError,
)
from bisheng.common.errcode.knowledge_space import SpacePermissionDeniedError, SpaceFileNameDuplicateError
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    UserRoleEnum,
    SpaceChannelMemberDao,
    MembershipStatusEnum,
    REJECTED_STATUS_DISPLAY_WINDOW,
)
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client
from bisheng.permission.domain.services.owner_service import OwnerService
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.knowledge.domain.models.knowledge_file import FileSource
from bisheng.message.domain.services.message_service import MessageService
from bisheng.user.domain.models.user import UserDao
from bisheng.utils import generate_uuid, get_request_ip

logger = logging.getLogger(__name__)

# Maximum number of channels a user can create
MAX_USER_CHANNEL_COUNT = 10
# Maximum number of administrators per channel
MAX_ADMIN_COUNT = 5
# Maximum number of channels a user can subscribe to (excluding self-created channels)
MAX_USER_SUBSCRIBE_COUNT = 20
CHANNEL_ADMIN_ASSIGNMENT_MESSAGE = "assigned_channel_admin"


class ChannelService:
    def __init__(self, channel_repository: 'ChannelRepository',
                 space_channel_member_repository: 'SpaceChannelMemberRepository',
                 channel_info_source_repository: 'ChannelInfoSourceRepository',
                 article_es_service: 'ArticleEsService' = None,
                 article_read_repository: 'ArticleReadRepository' = None,
                 message_service: Optional[MessageService] = None):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository
        self.channel_info_source_repository = channel_info_source_repository
        self.article_es_service = article_es_service or ArticleEsService()
        self.article_read_repository = article_read_repository
        self.message_service = message_service

    @staticmethod
    def _resolve_subscription_status(
            membership_status: Optional[MembershipStatusEnum],
            update_time: Optional[datetime] = None,
    ) -> SubscriptionStatusEnum:
        if membership_status is None:
            return SubscriptionStatusEnum.NOT_SUBSCRIBED
        if membership_status == MembershipStatusEnum.ACTIVE:
            return SubscriptionStatusEnum.SUBSCRIBED
        if membership_status == MembershipStatusEnum.PENDING:
            return SubscriptionStatusEnum.PENDING
        if (
                membership_status == MembershipStatusEnum.REJECTED
                and update_time is not None
                and update_time >= datetime.now() - REJECTED_STATUS_DISPLAY_WINDOW
        ):
            return SubscriptionStatusEnum.REJECTED
        return SubscriptionStatusEnum.NOT_SUBSCRIBED

    @classmethod
    def _resolve_membership_subscription_status(cls, membership) -> SubscriptionStatusEnum:
        if membership is None:
            return SubscriptionStatusEnum.NOT_SUBSCRIBED
        return cls._resolve_subscription_status(membership.status, membership.update_time)

    async def create_channel(self, channel_data: CreateChannelRequest, login_user: UserPayload, request=None):
        """Create a new channel based on the provided data and the logged-in user."""
        # Check if the user has reached the maximum limit for creating channels
        existing_channels = await self.space_channel_member_repository.find_channel_memberships(
            user_id=login_user.user_id,
            roles=[UserRoleEnum.CREATOR],
            statuses=[MembershipStatusEnum.ACTIVE]
        )
        if len(existing_channels) >= MAX_USER_CHANNEL_COUNT:
            raise ChannelCreateLimitExceededError()

        channel_model = Channel(
            name=channel_data.name,
            source_list=channel_data.source_list,
            description=channel_data.description,
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

        # F008: Write owner tuple to OpenFGA (INV-2)
        try:
            await OwnerService.write_owner_tuple(
                login_user.user_id, 'channel', str(channel_model.id),
            )
        except Exception as e:
            logger.warning('Failed to write owner tuple for channel %s: %s', channel_model.id, e)

        # F017: fan out group-sharing for Root-created channels (D6).
        # share_on_create owns the Root-only gate + FGA + is_shared flip +
        # audit_log; mirror the flag on the in-memory object for the response.
        from bisheng.tenant.domain.services.resource_share_service import ResourceShareService
        shared_children = await ResourceShareService.share_on_create(
            'channel', str(channel_model.id),
            creator_tenant_id=login_user.tenant_id,
            operator_id=login_user.user_id,
            operator_tenant_id=login_user.tenant_id,
            explicit=getattr(channel_data, 'share_to_children', None),
        )
        if shared_children:
            channel_model.is_shared = True

        bisheng_information_client = await get_bisheng_information_client()
        # Subscribe to the information sources associated with the channel
        if channel_data.source_list:
            await bisheng_information_client.subscribe_information_source(channel_data.source_list)

            # Sync information sources to local database
            existing_sources = await self.channel_info_source_repository.find_by_ids(channel_data.source_list)
            existing_source_ids = {source.id for source in existing_sources}

            missing_source_ids = [sid for sid in channel_data.source_list if sid not in existing_source_ids]

            if missing_source_ids:
                missing_information_sources = await bisheng_information_client.get_information_source_by_ids(
                    missing_source_ids)

                new_channel_info_sources = []
                for info_source in missing_information_sources:
                    new_source = ChannelInfoSource(
                        id=info_source.id,
                        source_name=info_source.name,
                        source_icon=info_source.icon,
                        source_type=info_source.business_type,
                        description=info_source.description
                    )
                    new_channel_info_sources.append(new_source)

                if new_channel_info_sources:
                    from bisheng.worker.information.article import sync_information_article
                    await self.channel_info_source_repository.batch_add(new_channel_info_sources)

        # Update latest_article_update_time for the new channel
        if channel_model.source_list:
            await self.update_channels_latest_article_time([channel_model])

        # Persist knowledge-sync config, if provided, using the freshly-assigned id.
        if channel_data.knowledge_sync is not None:
            await self._save_knowledge_sync(
                channel_id=channel_model.id,
                cfg=channel_data.knowledge_sync,
                user_id=login_user.user_id,
            )

        # Audit log
        from bisheng.api.services.audit_log import AuditLogService
        if request:
            await AuditLogService.create_channel(
                login_user, get_request_ip(request), str(channel_model.id), channel_model.name
            )

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
            statuses=[MembershipStatusEnum.ACTIVE]
        )

        if not memberships:
            return []

        # Batch query channels by IDs
        channel_ids = [m.business_id for m in memberships]
        channels = await self.channel_repository.find_channels_by_ids(channel_ids)
        channel_map = {ch.id: ch for ch in channels}

        # Get all read article IDs for the current user
        all_read_ids = []
        if self.article_read_repository:
            all_read_ids = await self.article_read_repository.get_all_read_article_ids(login_user.user_id)

        # Build a map of business_id to membership for quick lookup
        membership_map = {m.business_id: m for m in memberships}

        # Construct the result list, filtering out private channels for "followed" query type
        result: List[ChannelItemResponse] = []
        channels_to_process = []
        for channel_id, membership in membership_map.items():
            channel = channel_map.get(channel_id)
            if not channel:
                continue

            # if query type is "followed", filter out private channels
            if query_data.query_type == QueryTypeEnum.FOLLOWED:
                if channel.visibility == ChannelVisibilityEnum.PRIVATE:
                    continue

            channels_to_process.append((channel, membership))

        # Concurrently calculate unread counts for all applicable channels
        unread_counts = []
        if channels_to_process:
            unread_counts = await asyncio.gather(
                *[self._calculate_unread_count(channel, all_read_ids) for channel, _ in channels_to_process]
            )

        for (channel, membership), unread_count in zip(channels_to_process, unread_counts):
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
                unread_count=unread_count,
            )
            result.append(item)

        # Apply mixed sorting: pinned channels first, then sort by the selected criteria within each group
        result = self._sort_channels(result, query_data.sort_by)

        return result

    async def _calculate_unread_count(self, channel: Channel, all_read_ids: List[str]) -> int:
        """Calculate the exact number of unread articles for a given channel."""
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")

        # 2. Get total number of articles for this channel
        total_count = await self.article_es_service.count_articles(
            source_ids=channel.source_list,
            filter_rules=main_rule_groups if main_rule_groups else None,
        )

        if total_count == 0:
            return 0

        # If user hasn't read any articles, everything is unread
        if not all_read_ids:
            return total_count

        # 3. Calculate how many read articles belong to this channel
        # Chunk requests to avoid Elasticsearch TooManyClauses exception (default limit is 1024)
        chunk_size = 1000
        matching_read_count = 0

        tasks = []
        for i in range(0, len(all_read_ids), chunk_size):
            chunked_ids = all_read_ids[i:i + chunk_size]
            tasks.append(
                self.article_es_service.count_articles(
                    source_ids=channel.source_list,
                    filter_rules=main_rule_groups if main_rule_groups else None,
                    include_article_ids=chunked_ids
                )
            )

        if tasks:
            counts = await asyncio.gather(*tasks)
            matching_read_count = sum(counts)

        # Ensure no negative count just in case
        return max(0, total_count - matching_read_count)

    @staticmethod
    def _sort_channels(items: List[ChannelItemResponse], sort_by: SortByEnum) -> List[ChannelItemResponse]:
        """
        Sort channels with pinned channels always on top, then sort by the selected criteria:
        """
        if sort_by == SortByEnum.LATEST_UPDATE:
            def sort_key(item: ChannelItemResponse):
                # Pinned channels get pin_order=0, others get pin_order=1, so pinned channels come first.
                pin_order = 0 if item.is_pinned else 1
                timestamp = item.latest_article_update_time.timestamp() if item.latest_article_update_time else 0.0
                return pin_order, -timestamp

        elif sort_by == SortByEnum.LATEST_ADDED:
            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                timestamp = item.subscribed_at.timestamp() if item.subscribed_at else 0.0
                return pin_order, -timestamp

        else:  # CHANNEL_NAME
            def sort_key(item: ChannelItemResponse):
                pin_order = 0 if item.is_pinned else 1
                return (pin_order, item.name or "")

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

        if not membership or membership.status != MembershipStatusEnum.ACTIVE:
            raise ChannelNotFoundError()

        await self.space_channel_member_repository.update_pin_status(
            member_id=membership.id,
            is_pinned=pin_data.is_pinned
        )

        return True

    async def list_channel_members(self, channel_id: str, page: int, page_size: int,
                                   keyword: Optional[str], login_user: UserPayload) -> ChannelMemberPageResponse:
        from bisheng.user.domain.services.user import UserService

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
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
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
                user_avatar=await UserService.get_avatar_share_link(user.avatar) if user else None,
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
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ChannelNotFoundError()

        if current_membership.user_role not in (UserRoleEnum.CREATOR, UserRoleEnum.ADMIN):
            raise ChannelPermissionDeniedError()

        # 2. Query target member
        target_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=req.user_id
        )
        if not target_membership or target_membership.status != MembershipStatusEnum.ACTIVE:
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
                raise ChannelAdminLimitExceededError()

        should_notify_admin_assignment = (
                target_membership.user_role == UserRoleEnum.MEMBER
                and req.role == UserRoleEnum.ADMIN.value
        )

        # 6. Update role
        target_membership.user_role = UserRoleEnum(req.role)
        await self.space_channel_member_repository.update(target_membership)

        if should_notify_admin_assignment and self.message_service:
            await self._send_admin_assignment_notification(
                operator_user_id=login_user.user_id,
                target_user_id=target_membership.user_id,
                channel_id=req.channel_id,
            )

        return True

    async def _send_admin_assignment_notification(
            self,
            operator_user_id: int,
            target_user_id: int,
            channel_id: str,
    ) -> None:
        """Notify a channel member after being promoted from member to admin."""
        channel = await self.channel_repository.find_by_id(channel_id)
        if not channel:
            logger.warning(
                "Channel not found when sending admin assignment notification: channel_id=%s, target_user_id=%s",
                channel_id,
                target_user_id,
            )
            return

        user = await UserDao.aget_user(target_user_id)
        target_user_name = user.user_name if user else f"User {target_user_id}"

        content = [
            {
                "type": "user",
                "content": f"@{target_user_name}",
                "metadata": {"user_id": target_user_id},
            },
            {
                "type": "system_text",
                "content": CHANNEL_ADMIN_ASSIGNMENT_MESSAGE,
            },
            {
                "type": "business_url",
                "content": f"--{channel.name}",
                "metadata": {
                    "business_type": "channel_id",
                    "data": {"channel_id": channel.id},
                },
            },
        ]

        await self.message_service.send_generic_notify(
            sender=operator_user_id,
            receiver_user_ids=[target_user_id],
            content_item_list=content,
        )

    async def remove_member(self, req: RemoveMemberRequest, login_user: UserPayload) -> bool:
        """
        Remove a member (hard delete).
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
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
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
        if not target_membership or target_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("The target user is not a member of this channel")

        # 4. Removing the creator is not allowed
        if target_membership.user_role == UserRoleEnum.CREATOR:
            raise ValueError("Removing the creator is not allowed")

        # 5. Admins cannot remove other admins
        if current_membership.user_role == UserRoleEnum.ADMIN:
            if target_membership.user_role == UserRoleEnum.ADMIN:
                raise ValueError("Admins do not have permission to remove other admins")

        # 6. Hard delete: remove from database
        await self.space_channel_member_repository.delete(target_membership.id)

        return True

    async def get_channel_square(self, keyword: Optional[str], page: int, page_size: int,
                                 login_user: UserPayload) -> ChannelSquarePageResponse:
        """
        Get the channel square: paginated list of all released channels with subscription status
        and subscriber count for the current user.
        - Supports fuzzy search by channel name and description
        - Unsubscribed/unapplied channels are shown first
        - Subscribed/applied channels are shown last
        - Within each group, sorted by update_time descending
        """
        # 1. Multi-table join query for channels with subscription info
        rows = await self.channel_repository.find_square_channels(
            user_id=login_user.user_id,
            keyword=keyword,
            page=page,
            page_size=page_size
        )

        # 2. Count total matching channels
        total = await self.channel_repository.count_square_channels(keyword=keyword)

        # 3. Map results to response items
        # To avoid N+1 ES queries, build a batch request
        batch_requests = []
        for row in rows:
            channel = row[0]
            main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
            batch_requests.append({
                "source_ids": channel.source_list or [],
                "filter_rules": main_rule_groups if main_rule_groups else None,
                "include_article_ids": None
            })

        article_counts = await self.article_es_service.count_articles_batch(batch_requests)

        # Collect top 5 source IDs from all channels for the square
        all_needed_source_ids = set()
        channel_to_top_sources = {}
        for row in rows:
            channel = row[0]
            top_5_sources = (channel.source_list or [])[:5]
            channel_to_top_sources[channel.id] = top_5_sources
            all_needed_source_ids.update(top_5_sources)

        # Batch fetch all needed sources
        source_map = {}
        if all_needed_source_ids:
            sources = await self.channel_info_source_repository.find_by_ids(list(all_needed_source_ids))
            source_map = {s.id: s for s in sources}

        result_list: List[ChannelSquareItemResponse] = []
        for i, row in enumerate(rows):
            channel = row[0]  # Channel object
            user_subscription_status = row[1]
            user_subscription_update_time = row[2]
            subscriber_count = row[3]
            article_count = article_counts[i] if i < len(article_counts) else 0

            status = self._resolve_subscription_status(
                membership_status=user_subscription_status,
                update_time=user_subscription_update_time,
            )

            # Prepare source infos
            top_source_ids = channel_to_top_sources.get(channel.id, [])
            source_infos = []
            for sid in top_source_ids:
                if sid in source_map:
                    s = source_map[sid]
                    source_infos.append({
                        "id": s.id,
                        "source_name": s.source_name,
                        "source_icon": s.source_icon,
                        "source_type": s.source_type,
                        "description": s.description
                    })

            result_list.append(ChannelSquareItemResponse(
                id=channel.id,
                name=channel.name,
                description=channel.description,
                visibility=channel.visibility,
                latest_article_update_time=channel.latest_article_update_time,
                create_time=channel.create_time,
                update_time=channel.update_time,
                subscription_status=status,
                subscriber_count=subscriber_count,
                article_count=article_count,
                source_infos=source_infos,
            ))

        return ChannelSquarePageResponse(data=result_list, total=total)

    async def subscribe_channel(self, req: SubscribeChannelRequest, login_user: UserPayload) -> SubscriptionStatusEnum:
        """
        Subscribe to a channel (public or review).
        - Private channels cannot be subscribed to.
        - Public channels can be subscribed to directly.
        - Review channels require approval, so status is set to False (pending).
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([req.channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        existing_membership = await self.space_channel_member_repository.find_membership(
            business_id=req.channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if existing_membership and existing_membership.user_role != UserRoleEnum.MEMBER:
            return SubscriptionStatusEnum.SUBSCRIBED

        # 3. Check channel visibility
        if channel.visibility == ChannelVisibilityEnum.PRIVATE:
            raise ChannelAccessDeniedError()

        # 4. Determine subscription status based on channel visibility
        if channel.visibility == ChannelVisibilityEnum.PUBLIC:
            status = MembershipStatusEnum.ACTIVE
            return_status = SubscriptionStatusEnum.SUBSCRIBED
        elif channel.visibility == ChannelVisibilityEnum.REVIEW:
            status = MembershipStatusEnum.PENDING
            return_status = SubscriptionStatusEnum.PENDING
        else:
            raise ValueError(f"Unsupported channel visibility: {channel.visibility}")

        if existing_membership and existing_membership.status == MembershipStatusEnum.ACTIVE:
            return SubscriptionStatusEnum.SUBSCRIBED
        if existing_membership and existing_membership.status == MembershipStatusEnum.PENDING and status == MembershipStatusEnum.PENDING:
            return SubscriptionStatusEnum.PENDING

        if not existing_membership or existing_membership.status == MembershipStatusEnum.REJECTED:
            subscribed_channels = await self.space_channel_member_repository.find_channel_memberships(
                user_id=login_user.user_id,
                roles=[UserRoleEnum.MEMBER, UserRoleEnum.ADMIN],
                statuses=[MembershipStatusEnum.ACTIVE, MembershipStatusEnum.PENDING]
            )
            if len(subscribed_channels) >= MAX_USER_SUBSCRIBE_COUNT:
                raise ChannelSubscribeLimitExceededError()

        previous_status = existing_membership.status if existing_membership else None
        if existing_membership:
            existing_membership.status = status
            await self.space_channel_member_repository.update(existing_membership)
        else:
            await self.space_channel_member_repository.add_member(
                business_id=req.channel_id,
                business_type=BusinessTypeEnum.CHANNEL,
                user_id=login_user.user_id,
                role=UserRoleEnum.MEMBER,
                status=status
            )

        # 6. Send approval notification for review channels
        if (
                channel.visibility == ChannelVisibilityEnum.REVIEW
                and self.message_service
                and previous_status != MembershipStatusEnum.PENDING
        ):
            try:
                await self._send_subscribe_approval_notification(channel, login_user)
            except Exception as e:
                # Do not block subscription flow if notification fails
                logger.error(
                    "Failed to send subscribe approval notification: channel_id=%s, user=%s, error=%s",
                    channel.id, login_user.user_id, e,
                )

        return return_status

    async def _send_subscribe_approval_notification(
            self,
            channel: Channel,
            login_user: UserPayload,
    ) -> None:
        """
        Send approval notification to channel creator and admins when a user
        subscribes to a review-required channel.
        """
        # 1. Get channel creator and admins
        creators = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel.id,
            role=UserRoleEnum.CREATOR,
        )
        admins = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel.id,
            role=UserRoleEnum.ADMIN,
        )

        receiver_user_ids = list({m.user_id for m in creators + admins})
        if not receiver_user_ids:
            logger.warning(
                "No creator or admin found for channel %s, skipping approval notification",
                channel.id,
            )
            return

        # 2. Get applicant user name
        users = await UserDao.aget_user_by_ids([login_user.user_id])
        applicant_name = users[0].user_name if users else f"User {login_user.user_id}"

        # 3. Send the approval message
        await self.message_service.send_generic_approval(
            applicant_user_id=login_user.user_id,
            applicant_user_name=applicant_name,
            action_code="request_channel",
            business_type="channel_id",
            business_id=channel.id,
            business_name=channel.name,
            button_action_code="request_channel",
            receiver_user_ids=receiver_user_ids,
        )

    async def update_channel(self, channel_id: str, req: UpdateChannelRequest, login_user: UserPayload):
        """
        Update channel information (name and description).
        Only the creator can update the channel.
        """
        # 1. Verify channel existence
        channel = await self.channel_repository.find_by_id(channel_id)
        if not channel:
            raise ChannelNotFoundError()

        # 2. Verify current user is the creator
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("You are not a member of this channel")

        if current_membership.user_role != UserRoleEnum.CREATOR:
            raise ChannelPermissionDeniedError(msg="Only the creator can update the channel information")

        bisheng_information_client = await get_bisheng_information_client()

        # 3. Update channel information
        if req.name is not None:
            channel.name = req.name
        if req.description is not None:
            channel.description = req.description
        if req.is_released is not None:
            channel.is_released = req.is_released
        if req.filter_rules is not None:
            channel.filter_rules = [f.model_dump() for f in req.filter_rules]
        if req.visibility is not None:
            new_visibility = ChannelVisibilityEnum(req.visibility)
            old_visibility = channel.visibility
            if old_visibility != new_visibility:
                # When changing to PRIVATE, remove all non-creator members
                if new_visibility == ChannelVisibilityEnum.PRIVATE:
                    await self.space_channel_member_repository.remove_non_creator_members(channel_id)
                    # F008: Clear all FGA tuples and re-write owner only
                    try:
                        await OwnerService.delete_resource_tuples('channel', channel_id)
                        await OwnerService.write_owner_tuple(login_user.user_id, 'channel', channel_id)
                    except Exception as e:
                        logger.warning('Failed to sync FGA tuples after PRIVATE switch for channel %s: %s',
                                       channel_id, e)
                # When changing from REVIEW to PUBLIC, activate pending members and approve their messages
                elif old_visibility == ChannelVisibilityEnum.REVIEW and new_visibility == ChannelVisibilityEnum.PUBLIC:
                    activated_count = await self.space_channel_member_repository.activate_pending_members(channel_id)
                    if activated_count > 0:
                        logger.info(
                            "Activated %d pending members for channel_id=%s after visibility change from REVIEW to PUBLIC",
                            activated_count, channel_id
                        )
                    await self.space_channel_member_repository.remove_rejected_members(channel_id)
                    if self.message_service:
                        await self.message_service.batch_approve_channel_subscription_messages(
                            channel_id=channel_id,
                            operator_user_id=login_user.user_id,
                        )
            channel.visibility = new_visibility

        # Track if source_list changed for updating latest_article_update_time
        source_list_changed = False
        if req.source_list is not None:

            # Calculate the difference between old and new source lists to minimize calls to bisheng_information_client
            old_sources = set(channel.source_list or [])
            new_sources = set(req.source_list)
            to_add_sources = list(new_sources - old_sources)
            to_remove_sources = list(old_sources - new_sources)

            # Mark as changed if there are any additions or removals
            if to_add_sources or to_remove_sources:
                source_list_changed = True

            if to_add_sources:
                await bisheng_information_client.subscribe_information_source(to_add_sources)
            if to_remove_sources:
                await bisheng_information_client.unsubscribe_information_source(to_remove_sources)

            channel.source_list = req.source_list

        channel = await self.channel_repository.update(channel)

        # Update latest_article_update_time if source_list changed
        if source_list_changed:
            await self.update_channels_latest_article_time([channel])

        if channel.source_list:

            # Sync information sources to local database
            existing_sources = await self.channel_info_source_repository.find_by_ids(channel.source_list)
            existing_source_ids = {source.id for source in existing_sources}

            missing_source_ids = [sid for sid in channel.source_list if sid not in existing_source_ids]

            if missing_source_ids:
                missing_information_sources = await bisheng_information_client.get_information_source_by_ids(
                    missing_source_ids)

                new_channel_info_sources = []
                for info_source in missing_information_sources:
                    new_source = ChannelInfoSource(
                        id=info_source.id,
                        source_name=info_source.name,
                        source_icon=info_source.icon,
                        source_type=info_source.business_type,
                        description=info_source.description
                    )
                    new_channel_info_sources.append(new_source)

                if new_channel_info_sources:
                    from bisheng.worker.information.article import sync_information_article
                    await self.channel_info_source_repository.batch_add(new_channel_info_sources)
                    for one in new_channel_info_sources:
                        # Sync articles for the new information source one hour later
                        exec_time = datetime.now() + timedelta(hours=1)
                        sync_information_article.apply_async(args=(one.id,), eta=exec_time)

        # Replace knowledge-sync config atomically if caller provided one.
        if req.knowledge_sync is not None:
            await self._save_knowledge_sync(
                channel_id=channel.id,
                cfg=req.knowledge_sync,
                user_id=login_user.user_id,
            )

        return channel

    async def get_channel_detail(self, channel_id: str, login_user: UserPayload) -> ChannelDetailResponse:
        """
        Get channel detailed information including creator, subscriber count, and article count.
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        # 2. Verify current user permission
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            # If private, only members can view unless special requirement
            if channel.visibility == ChannelVisibilityEnum.PRIVATE:
                raise ChannelAccessDeniedError(msg="You do not have permission to view this channel")

        # 3. Get Creator Name
        creators = await self.space_channel_member_repository.find_members_by_role(
            channel_id=channel_id,
            role=UserRoleEnum.CREATOR
        )
        creator_name = "Unknown"
        if creators:
            creator_user_id = creators[0].user_id
            users = await UserDao.aget_user_by_ids([creator_user_id])
            if users:
                creator_name = users[0].user_name

        # 4. Get Subscriber Count
        subscriber_count = await self.space_channel_member_repository.count_channel_members(channel_id=channel_id)

        # 5. Get Article Count
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")

        article_count = await self.article_es_service.count_articles(
            source_ids=channel.source_list,
            filter_rules=main_rule_groups if main_rule_groups else None,
        )

        # Complete info source list
        source_infos = []
        if channel.source_list:
            sources = await self.channel_info_source_repository.find_by_ids(channel.source_list)
            source_map = {s.id: s for s in sources}
            for sid in channel.source_list:
                if sid in source_map:
                    s = source_map[sid]
                    source_infos.append({
                        "id": s.id,
                        "source_name": s.source_name,
                        "source_icon": s.source_icon,
                        "source_type": s.source_type,
                        "description": s.description
                    })
                else:
                    source_infos.append({
                        "id": sid,
                        "source_name": "Unknown",
                        "source_icon": "",
                        "source_type": "",
                        "description": ""
                    })

        # Determine subscription status
        subscription_status = self._resolve_membership_subscription_status(current_membership)

        # Knowledge-sync config — only returned for the channel creator since
        # the feature is creator-only (Module D). Members don't need to see it.
        knowledge_sync_cfg: Optional[KnowledgeSyncConfig] = None
        is_creator = (
            current_membership is not None
            and current_membership.user_role == UserRoleEnum.CREATOR
        )
        if is_creator:
            knowledge_sync_cfg = await self._load_knowledge_sync(channel.id)

        return ChannelDetailResponse(
            id=channel.id,
            name=channel.name,
            description=channel.description,
            source_infos=source_infos,
            visibility=channel.visibility,
            filter_rules=channel.filter_rules or [],
            is_released=channel.is_released,
            latest_article_update_time=channel.latest_article_update_time,
            create_time=channel.create_time,
            creator_name=creator_name,
            subscriber_count=subscriber_count,
            article_count=article_count,
            subscription_status=subscription_status,
            knowledge_sync=knowledge_sync_cfg,
        )

    # ------------------------------------------------------------------ #
    # Knowledge-space sync helpers (v2.5 Module D).
    # The channel create/update endpoints accept an optional `knowledge_sync`
    # field which we persist atomically alongside the channel itself. On read,
    # `get_channel_detail` re-hydrates the same shape for the creator's UI.
    # ------------------------------------------------------------------ #

    async def _save_knowledge_sync(
        self, channel_id: str, cfg: KnowledgeSyncConfig, user_id: int,
    ) -> None:
        """Replace every sync row for `channel_id` with the rows derived from `cfg`.

        One row per (channel, sub_channel_name?, space_id + folder_id).
        When a scope's `enabled` flag is False we still persist the rows but
        mark them `is_enabled=False` so the worker skips them; dropping them
        entirely would lose the user's selected spaces once they flip the
        switch back on.
        """
        # TC-037 defence-in-depth: the UI restricts the picker to spaces the
        # current user created, but the server must not trust the client —
        # reject any binding whose space is not owned by `user_id`.
        referenced_ids = {s.knowledge_space_id for s in cfg.main.spaces}
        for sub in cfg.subs:
            referenced_ids.update(s.knowledge_space_id for s in sub.spaces)
        if referenced_ids:
            owned_members = await SpaceChannelMemberDao.async_get_user_created_members(
                int(user_id)
            )
            owned_ids = {m.business_id for m in owned_members}
            if not referenced_ids.issubset(owned_ids):
                raise SpacePermissionDeniedError()

        rows: List[ChannelKnowledgeSync] = []

        # main-channel scope
        for space in cfg.main.spaces:
            rows.append(ChannelKnowledgeSync(
                channel_id=channel_id,
                sub_channel_name=None,
                knowledge_space_id=space.knowledge_space_id,
                folder_id=space.folder_id,
                folder_path=space.folder_path,
                is_enabled=cfg.main.enabled,
                user_id=int(user_id),
            ))

        # sub-channel scopes
        for sub in cfg.subs:
            if not sub.sub_channel_name:
                continue
            for space in sub.spaces:
                rows.append(ChannelKnowledgeSync(
                    channel_id=channel_id,
                    sub_channel_name=sub.sub_channel_name,
                    knowledge_space_id=space.knowledge_space_id,
                    folder_id=space.folder_id,
                    folder_path=space.folder_path,
                    is_enabled=sub.enabled,
                    user_id=int(user_id),
                ))

        await ChannelKnowledgeSyncDao.areplace_for_channel(channel_id, rows)

    async def _load_knowledge_sync(
        self, channel_id: str,
    ) -> KnowledgeSyncConfig:
        """Build a KnowledgeSyncConfig from the stored rows, plus display
        names for the bound knowledge spaces."""
        rows = await ChannelKnowledgeSyncDao.alist_by_channel_id(channel_id)
        # Sort by create_time for stable, creation-order display (requirement 3.1.1).
        rows.sort(key=lambda r: r.create_time)

        # Resolve knowledge-space display names for the UI.
        space_name_by_id: Dict[str, str] = {}
        numeric_ids = [
            int(r.knowledge_space_id)
            for r in rows
            if r.knowledge_space_id and str(r.knowledge_space_id).isdigit()
        ]
        if numeric_ids:
            from bisheng.knowledge.domain.models.knowledge import Knowledge
            from bisheng.core.database import get_async_db_session
            from sqlmodel import select as _select
            async with get_async_db_session() as session:
                q = _select(Knowledge).where(Knowledge.id.in_(numeric_ids))
                for kb in (await session.exec(q)).all():
                    space_name_by_id[str(kb.id)] = kb.name

        def _to_item(r: ChannelKnowledgeSync) -> KnowledgeSyncSpaceItem:
            return KnowledgeSyncSpaceItem(
                knowledge_space_id=str(r.knowledge_space_id),
                knowledge_space_name=space_name_by_id.get(str(r.knowledge_space_id), ''),
                folder_id=r.folder_id,
                folder_path=r.folder_path,
            )

        main_rows = [r for r in rows if not r.sub_channel_name]
        sub_rows_by_name: Dict[str, List[ChannelKnowledgeSync]] = {}
        for r in rows:
            if r.sub_channel_name:
                sub_rows_by_name.setdefault(r.sub_channel_name, []).append(r)

        main_cfg = KnowledgeSyncMainConfig(
            enabled=bool(main_rows) and all(r.is_enabled for r in main_rows),
            spaces=[_to_item(r) for r in main_rows],
        )
        subs: List[KnowledgeSyncSubConfig] = []
        for name, rlist in sub_rows_by_name.items():
            subs.append(KnowledgeSyncSubConfig(
                sub_channel_name=name,
                enabled=bool(rlist) and all(r.is_enabled for r in rlist),
                spaces=[_to_item(r) for r in rlist],
            ))
        return KnowledgeSyncConfig(main=main_cfg, subs=subs)

    async def dismiss_channel(self, channel_id: str, login_user: UserPayload, request=None):
        """
        Dismiss a channel:
        - Must be creator
        - Delete all user relationships
        - Delete channel
        - Call bisheng_information_client.unsubscribe_information_source
        """
        # 1. Verify channel existence
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ChannelNotFoundError()
        channel = channels[0]

        # 2. Verify current user is the creator
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if (
                not current_membership
                or current_membership.status != MembershipStatusEnum.ACTIVE
                or current_membership.user_role != UserRoleEnum.CREATOR
        ):
            raise ChannelPermissionDeniedError(msg="Only the creator can dismiss the channel")

        # 3. Delete all user relationships
        members = await self.space_channel_member_repository.find_all(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL
        )
        for member in members:
            await self.space_channel_member_repository.delete(member.id)

        # F008: Delete all FGA tuples for this channel
        try:
            await OwnerService.delete_resource_tuples('channel', channel_id)
        except Exception as e:
            logger.warning('Failed to delete FGA tuples for channel %s: %s', channel_id, e)

        # 4. Delete channel
        await self.channel_repository.delete(channel_id)

        # 5. Unsubscribe information source
        if channel.source_list:
            bisheng_information_client = await get_bisheng_information_client()
            await bisheng_information_client.unsubscribe_information_source(channel.source_list)

        # Audit log
        from bisheng.api.services.audit_log import AuditLogService
        if request:
            await AuditLogService.delete_channel(
                login_user, get_request_ip(request), channel_id, channel.name
            )

        return True

    async def unsubscribe_channel(self, channel_id: str, login_user: UserPayload):
        """
        Unsubscribe from a channel:
        - Remove current user and channel relationship
        """
        # 1. Verify current user is a member
        current_membership = await self.space_channel_member_repository.find_membership(
            business_id=channel_id,
            business_type=BusinessTypeEnum.CHANNEL,
            user_id=login_user.user_id
        )
        if not current_membership or current_membership.status != MembershipStatusEnum.ACTIVE:
            raise ValueError("You are not subscribed to this channel")

        # 2. Remove relationship
        await self.space_channel_member_repository.delete(current_membership.id)

        return True

    async def search_channel_articles(
            self,
            channel_id: str,
            keyword: Optional[str] = None,
            source_ids: Optional[List[str]] = None,
            sub_channel_name: Optional[str] = None,
            page: int = 1,
            page_size: int = 20,
            login_user: UserPayload = None,
            only_unread: bool = False,
    ) -> ArticleSearchPageResponse:
        """
        Paginated search for articles in a channel.

        1. Query channel by channel_id to get source_list and filter_rules
        2. Determine if a sub-channel is specified, apply corresponding filter rules
        3. Build ES query: info source filter + filter rules + keyword search + highlight + sort + pagination

        Args:
            channel_id: Channel ID
            keyword: Search keyword (title, content, source ID)
            source_ids: Info source ID list specified by frontend (must be a subset of channel source_list)
            sub_channel_name: Sub-channel name, if specified use the corresponding sub-channel's filter rules
            page: Page number
            page_size: Page size
            login_user: Current logged-in user

        Returns:
            ArticleSearchPageResponse
        """
        # 1. Query channel info
        channels = await self.channel_repository.find_channels_by_ids([channel_id])
        if not channels:
            raise ValueError("Channel not found")
        channel = channels[0]

        # 2. Determine info source list
        channel_source_ids = channel.source_list or []
        if source_ids:
            # Info sources from frontend must be a subset of channel info sources
            effective_source_ids = [sid for sid in source_ids if sid in channel_source_ids]
            if not effective_source_ids:
                # None of the provided info sources are in the channel, return empty result
                return ArticleSearchPageResponse(data=[], total=0, page=page, page_size=page_size)
        else:
            effective_source_ids = channel_source_ids
        if not effective_source_ids:
            return ArticleSearchPageResponse(data=[], total=0, page=page, page_size=page_size)

        # 3. Parse filter rules
        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        sub_rule_groups = []
        if sub_channel_name:
            sub_rule_groups = self._extract_filter_rule_groups(
                channel,
                channel_type="sub",
                sub_channel_name=sub_channel_name,
            )

        if sub_rule_groups:
            effective_rule_groups = sub_rule_groups
        else:
            effective_rule_groups = main_rule_groups

        # 4. Get read article ID list
        read_article_ids = []
        if login_user and self.article_read_repository:
            read_article_ids = await self.article_read_repository.find_article_ids_by_user_and_sources(
                user_id=login_user.user_id,
                source_ids=effective_source_ids
            )

        # 5. Call ArticleEsService to search
        exclude_article_ids = read_article_ids if only_unread else None
        article_search_response = await self.article_es_service.search_articles(
            source_ids=effective_source_ids,
            keyword=keyword,
            filter_rules=effective_rule_groups if effective_rule_groups else None,
            page=page,
            page_size=page_size,
            exclude_article_ids=exclude_article_ids
        )

        source_ids_in_result = [item.source_id for item in article_search_response.data]

        # Batch query info source info
        source_info_map = {}
        if source_ids_in_result:
            sources = await self.channel_info_source_repository.find_by_ids(source_ids_in_result)
            for s in sources:
                source_info_map[s.id] = {
                    "id": s.id,
                    "source_name": s.source_name,
                    "source_icon": s.source_icon,
                    "source_type": s.source_type,
                    "description": s.description
                }

        read_ids_set = set(read_article_ids)
        for item in article_search_response.data:
            if item.source_id in source_info_map:
                item.source_info = source_info_map[item.source_id]
            # Set read status
            item.is_read = item.doc_id in read_ids_set

        return article_search_response

    async def get_article_detail(self, article_id: str, login_user: UserPayload):
        """
        Get article details by ID and record reading status.
        """
        # 1. Fetch article from ES
        article = await self.article_es_service.get_article(article_id)
        if not article:
            raise ValueError("Article not found")

        # 2. Check read record
        if self.article_read_repository:
            read_record = await self.article_read_repository.find_by_user_and_article(
                user_id=login_user.user_id,
                article_id=article_id
            )

            # 3. Add read record if not exists
            if not read_record:
                new_record = ArticleReadRecord(
                    article_id=article_id,
                    user_id=login_user.user_id,
                    source_id=article.source_id,
                )
                await self.article_read_repository.save(new_record)

        if article.source_id:
            source = await self.channel_info_source_repository.find_by_id(article.source_id)
            if source:
                article.source_info = {
                    "id": source.id,
                    "source_name": source.source_name,
                    "source_icon": source.source_icon,
                    "source_type": source.source_type,
                    "description": source.description
                }

        return article

    # ──────────────────────────────────────────
    #  Channel latest article update time methods
    # ──────────────────────────────────────────

    @staticmethod
    def _extract_filter_rule_groups(
            channel: Channel,
            channel_type: str = "main",
            sub_channel_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract filter rule groups while preserving top-level grouping semantics."""
        filter_rules_raw = channel.filter_rules or []
        matched_groups: List[Dict[str, Any]] = []
        legacy_main_rules: List[Dict[str, Any]] = []

        for filter_rule in filter_rules_raw:
            if filter_rule.get("type") in {"single", "multi"}:
                if channel_type == "main":
                    legacy_main_rules.append(filter_rule)
                continue

            current_channel_type = filter_rule.get("channel_type", "main")
            if current_channel_type != channel_type:
                continue

            if channel_type == "sub":
                if not sub_channel_name or filter_rule.get("name") != sub_channel_name:
                    continue

            matched_groups.append(filter_rule)

        if legacy_main_rules and channel_type == "main":
            matched_groups.append({
                "relation": "or",
                "rules": legacy_main_rules,
                "channel_type": "main",
            })

        return matched_groups

    @staticmethod
    def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
        """Normalize datetime values before comparison and persistence."""
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    async def _get_channel_latest_article_create_time(self, channel: Channel) -> Optional[datetime]:
        """Get the latest article create_time for a channel under main filter rules (async version)."""
        from bisheng.channel.domain.es.article_index import ARTICLE_INDEX_NAME
        from bisheng.core.search.elasticsearch.manager import get_es_connection

        main_rule_groups = self._extract_filter_rule_groups(channel, channel_type="main")
        query = self.article_es_service._build_count_query(
            source_ids=channel.source_list or [],
            filter_rules=main_rule_groups or None,
        )
        if query is None:
            return None

        client = await get_es_connection()
        body = {
            "size": 1,
            "query": query,
            "sort": [{"publish_time": {"order": "desc"}}],
            "_source": ["publish_time"],
        }
        response = await client.search(index=ARTICLE_INDEX_NAME, body=body)
        hits = response["hits"]["hits"]
        if not hits:
            return None

        latest_time = hits[0]["_source"].get("publish_time")
        if not latest_time:
            return None

        return self._normalize_datetime(datetime.fromisoformat(latest_time))

    async def update_channels_latest_article_time(self, channels: List[Channel]) -> int:
        """
        Update latest_article_update_time for the given channels (async version).

        Args:
            channels: List of channels to update

        Returns:
            Number of channels updated
        """
        if not channels:
            return 0

        updated_count = 0
        for channel in channels:
            try:
                latest_article_create_time = await self._get_channel_latest_article_create_time(channel)
            except Exception as exc:
                logger.exception(
                    f"Failed to query latest article create_time for channel {channel.id}: {exc}"
                )
                continue

            channel.latest_article_update_time = latest_article_create_time
            await self.channel_repository.update(channel)
            updated_count += 1

        return updated_count

    @staticmethod
    def update_channels_latest_article_time_sync(channels: List[Channel]) -> int:
        """
        Update latest_article_update_time for the given channels (sync version).

        This method is designed to be called from sync contexts like Celery workers.

        Args:
            channels: List of channels to update

        Returns:
            Number of channels updated
        """
        from bisheng.channel.domain.es.article_index import ARTICLE_INDEX_NAME
        from bisheng.core.database import get_sync_db_session
        from bisheng.core.search.elasticsearch.manager import get_es_connection_sync

        if not channels:
            return 0

        article_service = ArticleEsService()
        updated_count = 0

        update_channels = []
        for channel in channels:
            try:
                # Get latest article create_time
                main_rule_groups = ChannelService._extract_filter_rule_groups(channel, channel_type="main")
                query = article_service._build_count_query(
                    source_ids=channel.source_list or [],
                    filter_rules=main_rule_groups or None,
                )
                if query is None:
                    # No valid query (empty source_list or no filter rules), clear the time
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                client = get_es_connection_sync()
                body = {
                    "size": 1,
                    "query": query,
                    "sort": [{"publish_time": {"order": "desc"}}],
                    "_source": ["publish_time"],
                }
                response = client.search(index=ARTICLE_INDEX_NAME, body=body)
                hits = response["hits"]["hits"]
                if not hits:
                    # No articles found, clear the time
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                latest_publish_time = hits[0]["_source"].get("publish_time")
                if not latest_publish_time:
                    channel.latest_article_update_time = None
                    update_channels.append(channel)
                    updated_count += 1
                    continue

                latest_article_time = ChannelService._normalize_datetime(
                    datetime.fromisoformat(latest_publish_time)
                )
                channel.latest_article_update_time = latest_article_time
                update_channels.append(channel)
                updated_count += 1

            except Exception as exc:
                logger.exception(
                    f"Failed to update latest_article_update_time for channel {channel.id}: {exc}"
                )
                continue

        if update_channels:
            with get_sync_db_session() as session:
                channel_repository = ChannelRepositoryImpl(session=session)
                # Batch update channels in the database using UPDATE statements
                channel_repository.update_channel_latest_article_update_time(update_channels)
        return updated_count

    # ──────────────────────────────────────────
    #  Add articles to knowledge space
    # ──────────────────────────────────────────

    @staticmethod
    def _sanitize_file_name(title: str) -> str:
        """Remove or replace characters that are invalid in file names."""
        invalid_chars = '/\\:*?"<>|\0'
        for ch in invalid_chars:
            title = title.replace(ch, '_')
        return title.strip()[:200]

    async def add_articles_to_knowledge_space(
            self,
            req: AddArticlesToKnowledgeSpaceRequest,
            login_user: UserPayload,
            request: 'Request',
    ) -> List[dict]:
        """Add channel articles to a knowledge space.

        1. Validate articles exist in ES.
        2. Check write permission on the target knowledge space.
        3. Upload article content as .md and content_html as .html to minio.
        4. Call KnowledgeSpaceService.add_file to import into the space.
        5. Update preview_file_object_name for successfully created files.
        """
        # 1. Fetch all articles from ES and validate
        articles = []
        for article_id in req.article_ids:
            article = await self.article_es_service.get_article(article_id)
            if not article:
                if req.skip_missing_and_duplicates:
                    logger.warning(
                        f"add_articles_to_knowledge_space: skipping missing article {article_id}"
                    )
                    continue
                raise ValueError(f"Article not found: {article_id}")
            articles.append(article)
        if not articles:
            # Nothing to do (all were missing and we're in skip-mode).
            return []

        # 2. Check write permission before uploading to minio
        role = await SpaceChannelMemberDao.async_get_active_member_role(
            req.knowledge_id, login_user.user_id
        )
        _WRITE_ROLES = {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}
        if role not in _WRITE_ROLES:
            raise SpacePermissionDeniedError()

        # 3. Upload articles to minio
        minio_client = await get_minio_storage()
        md_file_paths = []
        preview_map: dict[int, str] = {}  # md_object_name -> preview_object_name

        for index, article in enumerate(articles):
            file_name = self._sanitize_file_name(article.title)
            unique_id = generate_uuid()

            # Upload content as .md
            md_object_name = f"channel_articles/{unique_id}/{file_name}.md"
            md_content = article.content or ""
            await minio_client.put_object_tmp(
                object_name=md_object_name,
                file=md_content.encode("utf-8"),
                content_type="text/markdown",
            )
            md_file_paths.append(
                await minio_client.get_share_link(md_object_name, bucket=minio_client.tmp_bucket, clear_host=False))

            preview_map[index] = article.content_html

        # 4. Call KnowledgeSpaceService.add_file
        from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
        space_service = KnowledgeSpaceService(request=request, login_user=login_user)
        knowledge_files = await space_service.add_file(
            knowledge_id=req.knowledge_id,
            file_path=md_file_paths,
            parent_id=req.parent_id,
            file_source=FileSource.CHANNEL
        )

        # 5. Update preview_file_object_name for successful files
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileDao
        from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFileStatus

        result = []
        failed = False
        for index, kf in enumerate(knowledge_files):
            if kf.status != KnowledgeFileStatus.FAILED.value:
                html_content = preview_map[index]
                preview_object_name = f"preview/{kf.id}.html"
                await minio_client.put_object(object_name=preview_object_name,
                                              file=html_content.encode("utf-8"),
                                              content_type="text/html")
                kf.preview_file_object_name = preview_object_name
                result.append(kf)
            else:
                failed = True
        await KnowledgeFileDao.async_update_batch(result)
        if failed and not req.skip_missing_and_duplicates:
            raise SpaceFileNameDuplicateError()

        return result
