from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.models.space_channel_member import BusinessTypeEnum, UserRoleEnum
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository
from bisheng.core.external.bisheng_information_client.bisheng_information_manager import get_bisheng_information_client


class ChannelService:
    def __init__(self, channel_repository: 'ChannelRepository',
                 space_channel_member_repository: 'SpaceChannelMemberRepository'):
        self.channel_repository = channel_repository
        self.space_channel_member_repository = space_channel_member_repository

    async def create_channel(self, channel_data: CreateChannelRequest, login_user: UserPayload):
        """Create a new channel based on the provided data and the logged-in user."""
        # Implement the logic to create a channel using the channel_repository
        # For example, you might want to save the channel data to the database
        # and associate it with the login_user.
        # This is a placeholder implementation and should be replaced with actual logic.

        channel_model = Channel(
            name=channel_data.name,
            source_list=channel_data.source_list,
            visibility=channel_data.visibility,
            filter_rules=[] if not channel_data.filter_rules else [f.model_dump() for f in channel_data.filter_rules],
            user_id=login_user.user_id,
            is_released=channel_data.is_released
        )

        channel_model = await self.channel_repository.save(channel_model)

        # If the channel is created successfully, you can also add the creator as a member of the channel
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
