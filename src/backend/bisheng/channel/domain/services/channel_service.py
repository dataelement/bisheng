from bisheng.channel.domain.models.channel import Channel
from bisheng.channel.domain.repositories.interfaces.channel_repository import ChannelRepository
from bisheng.channel.domain.schemas.channel_manager_schema import CreateChannelRequest
from bisheng.common.dependencies.user_deps import UserPayload


class ChannelService:
    def __init__(self, channel_repository: 'ChannelRepository'):
        self.channel_repository = channel_repository

    async def create_channel(self, channel_data: CreateChannelRequest, login_user: UserPayload):
        """Create a new channel based on the provided data and the logged-in user."""
        # Implement the logic to create a channel using the channel_repository
        # For example, you might want to save the channel data to the database
        # and associate it with the login_user.
        # This is a placeholder implementation and should be replaced with actual logic.

        channel_model = Channel(
            name=channel_data.name,
            source_list =channel_data.source_list,
            visibility = channel_data.visibility,
            filter_rules= [] if not channel_data.filter_rules else [f.model_dump() for f in channel_data.filter_rules],
            user_id= login_user.user_id,
            is_released= channel_data.is_released
        )

        return await self.channel_repository.save(channel_model)
