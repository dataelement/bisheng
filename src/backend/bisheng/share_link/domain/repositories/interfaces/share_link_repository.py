from abc import ABC

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.share_link.domain.models.share_link import ShareLink


class ShareLinkRepository(BaseRepository[ShareLink, str], ABC):
    """共享链接仓库接口"""
    pass
