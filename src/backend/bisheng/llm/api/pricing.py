"""F016 built-in price catalog (admin add-model form) and per-model price edits (T04)."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.llm.domain.pricing.service import catalog_view, match_view, save_model_pricing

router = APIRouter(prefix="/llm", tags=["LLM"])


@router.get("/price-catalog")
async def price_catalog(login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user)):
    return resp_200(data=catalog_view())


@router.get("/price-catalog/match")
async def price_catalog_match(
    server_type: str = Query(..., min_length=1, max_length=64),
    model_name: str = Query(..., min_length=1, max_length=255),
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    return resp_200(data=match_view(server_type, model_name))


@router.put("/models/{model_id}/pricing")
async def update_model_pricing(
    model_id: Annotated[int, Path(gt=0, le=9223372036854775807)],
    pricing: Annotated[dict, Body()],
    login_user: UserPayload = Depends(UserPayload.get_tenant_admin_user),
):
    """Body: currency, input, cache_read, cache_write (optional), output and the revision last read."""
    return resp_200(data=await save_model_pricing(login_user, model_id, pricing))
