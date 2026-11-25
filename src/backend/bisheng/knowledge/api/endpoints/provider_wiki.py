"""Space-authorized Wiki reads; never expose provider keys, original URLs or upstream error bodies."""

from fastapi import APIRouter, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.knowledge.application.provider_v1_runtime import ProviderFeatureUnavailable
from bisheng.knowledge.application.provider_wiki import WikiApplication, WikiUnavailable, scoped_wiki_get

router = APIRouter(prefix="/{space_id}/wiki", tags=["knowledge_wiki"])

# The space identity is a bounded database key: a non-positive or out-of-range
# value is a malformed request, not a permission answer about some other space.
SpaceId = Path(gt=0, le=9223372036854775807)


def get_wiki_application():
    return WikiApplication(get=scoped_wiki_get)


async def _response(result):
    try:
        return resp_200(await result)
    except WikiUnavailable:
        raise ProviderFeatureUnavailable() from None


@router.get("/status")
async def wiki_status(
    space_id: int = SpaceId,
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_wiki_application),
):
    return await _response(application.status_detail(identity, space_id))


@router.get("/graph")
async def wiki_graph(
    space_id: int = SpaceId,
    generation: int | None = Query(None, gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_wiki_application),
):
    return await _response(application.graph(identity, space_id, generation=generation))


@router.get("/search")
async def wiki_search(
    space_id: int = SpaceId,
    q: str = Query(min_length=1, max_length=512, pattern=r"\S"),
    generation: int | None = Query(None, gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_wiki_application),
):
    return await _response(application.search(identity, space_id, q, generation=generation))


@router.get("/page")
async def wiki_page(
    space_id: int = SpaceId,
    generation: int = Query(gt=0),
    slug: str = Query(min_length=1, max_length=255),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_wiki_application),
):
    return await _response(application.page(identity, space_id, generation=generation, slug=slug))


@router.get("/pages/{slug:path}")
async def wiki_page_by_slug(
    space_id: int = SpaceId,
    slug: str = Path(min_length=1, max_length=255),
    generation: int = Query(gt=0),
    identity: UserPayload = Depends(UserPayload.get_login_user),
    application=Depends(get_wiki_application),
):
    """Wiki slugs are hierarchical (`entity/a`). The catch-all keeps `/` inside one
    opaque slug; the application still rejects traversal, encoded separators and
    any generation that is not the frozen active binding."""
    return await _response(application.page(identity, space_id, generation=generation, slug=slug))