from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.share_link.domain.repositories.interfaces.share_link_repository import ShareLinkRepository


class ShareLinkRepositoryImpl(BaseRepositoryImpl[ShareLink, str], ShareLinkRepository):
    """共享链接仓库实现"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ShareLink)
