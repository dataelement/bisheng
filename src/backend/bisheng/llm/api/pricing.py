"""F016 read-only access to the built-in model price catalog (admin add-model form)."""

from fastapi import APIRouter, Depends, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import resp_200
from bisheng.llm.domain.pricing.service import catalog_view, match_view

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
