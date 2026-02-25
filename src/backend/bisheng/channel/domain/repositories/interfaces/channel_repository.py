from abc import ABC

from bisheng.channel.domain.models.channel import Channel
from bisheng.common.repositories.interfaces.base_repository import BaseRepository


class ChannelRepository(BaseRepository[Channel, str], ABC):
    """Channel Repository Interface"""
    pass
