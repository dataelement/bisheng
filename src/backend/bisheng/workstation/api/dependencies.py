from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

LoginUserDep = Depends(UserPayload.get_login_user)
AdminUserDep = Depends(UserPayload.get_admin_user)
ShareLinkDep = Depends(header_share_token_parser)

__all__ = ['LoginUserDep', 'AdminUserDep', 'ShareLink', 'ShareLinkDep', 'UserPayload', 'get_workstation_tags_service']

async def get_tags_repository(
        session: AsyncSession = Depends(get_db_session),
) -> 'TagRepositoryImpl':
    from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl
    return TagRepositoryImpl(session)

async def get_review_tags_repository(
        session: AsyncSession = Depends(get_db_session),
        tags_repository: 'TagRepositoryImpl' = Depends(get_tags_repository),
) -> 'ReviewTagsRepositoryImpl':
    from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl
    return ReviewTagsRepositoryImpl(session, tags_repository)  

async def get_workstation_tags_service(
        request: Request,
        session: AsyncSession = Depends(get_db_session),
        login_user: UserPayload = Depends(UserPayload.get_login_user),
        review_tags_repository: 'ReviewTagsRepositoryImpl' = Depends(get_review_tags_repository),
) -> 'WorkStationTagsService':
    from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService as _SvcClass
    service = _SvcClass(request=request, session=session, login_user=login_user, review_tags_repository=review_tags_repository)
    return service