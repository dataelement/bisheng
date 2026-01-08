from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.share_link.domain.models.share_link import ShareLink
from bisheng.share_link.domain.repositories.interfaces.share_link_repository import ShareLinkRepository


class ShareLinkRepositoryImpl(BaseRepositoryImpl[ShareLink, str], ShareLinkRepository):
    """Shared link repository implementation"""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ShareLink)
