"""Platform super-admin endpoints for managing OAuth 2.0 / OIDC client registrations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import PageData, UnifiedResponseModel, resp_200
from bisheng.oauth2_provider.domain.schemas.client import (
    OAuth2ClientCreate,
    OAuth2ClientResponse,
    OAuth2ClientSecretResponse,
    OAuth2ClientUpdate,
)
from bisheng.oauth2_provider.runtime import OAuth2ProviderRuntime, get_oauth2_runtime

admin_router = APIRouter(prefix="/oauth2/clients", tags=["OAuth2 Clients Admin"])


async def require_super_admin(user: UserPayload = Depends(UserPayload.get_login_user)) -> UserPayload:
    if not (getattr(user, "is_global_super", False) or user.is_admin()):
        raise HTTPException(status_code=403, detail="Super admin permission required")
    return user


@admin_router.get("", response_model=UnifiedResponseModel[PageData[OAuth2ClientResponse]])
async def list_oauth2_clients(
    keyword: str | None = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    rows, total = await runtime.clients.list_clients(keyword=keyword, page=page, page_size=page_size)
    return resp_200(data=PageData(data=rows, total=total))


@admin_router.post("", response_model=UnifiedResponseModel[OAuth2ClientSecretResponse])
async def create_oauth2_client(
    body: OAuth2ClientCreate,
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    created = await runtime.clients.create_client(body)
    return resp_200(data=created)


@admin_router.get("/{client_id}", response_model=UnifiedResponseModel[OAuth2ClientResponse])
async def get_oauth2_client(
    client_id: str,
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    client = await runtime.clients.get_client(client_id)
    return resp_200(data=client)


@admin_router.put("/{client_id}", response_model=UnifiedResponseModel[OAuth2ClientResponse])
async def update_oauth2_client(
    client_id: str,
    body: OAuth2ClientUpdate,
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    updated = await runtime.clients.update_client(client_id, body)
    return resp_200(data=updated)


@admin_router.post("/{client_id}/rotate-secret", response_model=UnifiedResponseModel[OAuth2ClientSecretResponse])
async def rotate_oauth2_client_secret(
    client_id: str,
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    rotated = await runtime.clients.rotate_secret(client_id)
    return resp_200(data=rotated)


@admin_router.delete("/{client_id}", response_model=UnifiedResponseModel[dict])
async def delete_oauth2_client(
    client_id: str,
    _: UserPayload = Depends(require_super_admin),
    runtime: OAuth2ProviderRuntime = Depends(get_oauth2_runtime),
):
    await runtime.clients.delete_client(client_id)
    return resp_200(data={"deleted": True})
