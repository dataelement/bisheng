from fastapi import APIRouter, Depends

from bisheng.api.v1.schemas import resp_200
from bisheng.citation.api.dependencies import get_citation_resolve_service
from bisheng.citation.domain.schemas.citation_schema import ResolveCitationRequest, ResolveCitationResponse
from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.exceptions.auth import JWTDecodeError
from bisheng.user.domain.services.auth import AuthJwt

router = APIRouter()


async def get_optional_login_user(auth_jwt: AuthJwt = Depends()) -> UserPayload | None:
    try:
        return await UserPayload.get_login_user(auth_jwt)
    except JWTDecodeError:
        return None


@router.post('/resolve')
async def resolve_citations(
    req: ResolveCitationRequest,
    login_user: UserPayload | None = Depends(get_optional_login_user),
    service: CitationResolveService = Depends(get_citation_resolve_service),
):
    items = await service.resolve_citations(req.citationIds, login_user)
    return resp_200(ResolveCitationResponse(items=items))


@router.get('/{citation_id}')
async def get_citation_detail(
    citation_id: str,
    login_user: UserPayload | None = Depends(get_optional_login_user),
    service: CitationResolveService = Depends(get_citation_resolve_service),
):
    item = await service.resolve_citation(citation_id, login_user)
    return resp_200(item)
