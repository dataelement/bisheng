"""Routers exported by the OAuth 2.0 / OIDC Provider module."""

from fastapi import APIRouter

from bisheng.oauth2_provider.api.endpoints.clients import admin_router as oauth2_admin_router
from bisheng.oauth2_provider.api.endpoints.oidc import (
    consent_router as oauth2_consent_router,
)
from bisheng.oauth2_provider.api.endpoints.oidc import (
    openid_metadata,
)
from bisheng.oauth2_provider.api.endpoints.oidc import (
    public_router as oauth2_public_router,
)

well_known_router = APIRouter(tags=["OAuth2 Provider"])
well_known_router.add_api_route("/.well-known/openid-configuration", openid_metadata, methods=["GET"])
well_known_router.add_api_route("/.well-known/oauth-authorization-server", openid_metadata, methods=["GET"])

__all__ = [
    "oauth2_admin_router",
    "oauth2_consent_router",
    "oauth2_public_router",
    "well_known_router",
]
