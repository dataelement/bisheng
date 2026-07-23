from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.dependencies.core_deps import get_db_session
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.knowledge.domain.repositories.implementations.department_file_view_grant_repository_impl import (
    DepartmentFileViewGrantRepositoryImpl,
)
from bisheng.knowledge.domain.services.department_file_view_access_service import (
    DepartmentFileViewAccessService,
)
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

if TYPE_CHECKING:
    from bisheng.workstation.domain.repositories.review_tags_repository import (
        ReviewTagsRepositoryImpl,
    )
    from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl
    from bisheng.workstation.domain.services.workstation_tags_service import (
        WorkStationTagsService,
    )

LoginUserDep = Depends(UserPayload.get_login_user)
AdminUserDep = Depends(UserPayload.get_admin_user)
ShareLinkDep = Depends(header_share_token_parser)

__all__ = [
    "AdminUserDep",
    "LoginUserDep",
    "ShareLink",
    "ShareLinkDep",
    "UserPayload",
    "get_department_file_view_access_service",
    "get_workstation_citation_registry_service",
    "get_workstation_tags_service",
]


async def get_department_file_view_access_service(
    session: AsyncSession = Depends(get_db_session),
) -> DepartmentFileViewAccessService:
    """为首钢门户工作台入口装配部门文件访问服务。"""
    return DepartmentFileViewAccessService(
        session=session,
        grant_repository=DepartmentFileViewGrantRepositoryImpl(session),
        persist_stale_grant_revalidation=True,
    )


async def get_workstation_citation_registry_service(
    session: AsyncSession = Depends(get_db_session),
):
    """Provide citation history access without coupling workstation to citation API."""
    from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
        MessageCitationRepositoryImpl,
    )
    from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService

    return CitationRegistryService(MessageCitationRepositoryImpl(session))


async def get_tags_repository(
    session: AsyncSession = Depends(get_db_session),
) -> "TagRepositoryImpl":
    from bisheng.workstation.domain.repositories.tags_repository import TagRepositoryImpl

    return TagRepositoryImpl(session)


async def get_review_tags_repository(
    session: AsyncSession = Depends(get_db_session),
    tags_repository: "TagRepositoryImpl" = Depends(get_tags_repository),
) -> "ReviewTagsRepositoryImpl":
    from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl

    return ReviewTagsRepositoryImpl(session, tags_repository)


async def get_workstation_tags_service(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    login_user: UserPayload = Depends(UserPayload.get_login_user),
    review_tags_repository: "ReviewTagsRepositoryImpl" = Depends(get_review_tags_repository),
) -> "WorkStationTagsService":
    from bisheng.workstation.domain.services.workstation_tags_service import WorkStationTagsService as _SvcClass

    service = _SvcClass(
        request=request, session=session, login_user=login_user, review_tags_repository=review_tags_repository
    )
    return service
