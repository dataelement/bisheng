"""Request-scoped open API principal (F049 design D2 / §4.2 ``UserPayload.open_api_principal``).

``OpenApiPrincipal`` is a standalone pydantic model on purpose - it imports
nothing from the ``user`` domain, so ``LoginUser`` can reference it as an
optional field without a ``user <-> open_api`` import cycle (T012).

The ContextVar is written by the router-level ``verify_open_api_access``
dependency after a credential (or share token) validates and is what
``get_open_api_login_user`` and business services read to learn the acting
subject / resource owner. It is ``None`` for every JWT-authenticated request.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

from pydantic import BaseModel, Field

# ``subject_kind`` values a principal can carry. ``hosted_app`` appears once
# F055 registers its resolver; ``share_link`` comes from the share-token channel.
PRINCIPAL_KIND_SERVICE_ACCOUNT = "service_account"
PRINCIPAL_KIND_SHARE_LINK = "share_link"
PRINCIPAL_KIND_HOSTED_APP = "hosted_app"


class OpenApiPrincipal(BaseModel):
    """Who is calling ``/api/v2`` and on whose behalf resources are owned."""

    model_config = {"frozen": True}

    # ``api_credential.id`` for credential-backed calls; ``None`` for share links.
    credential_id: int | None = None
    subject_kind: str = Field(description="service_account | share_link | hosted_app")
    # The executing user id: the service-account user row, or the share link's
    # creator (D8). Sessions and audit rows keep using this id (AC-25).
    subject_user_id: int
    # ``service_account.resource_owner_user_id`` - creation relations of
    # resources created through the open API land on this person (AC-24).
    resource_owner_user_id: int | None = None
    share_link_id: str | None = None
    scopes: tuple[str, ...] = ()

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


current_open_api_principal: ContextVar[OpenApiPrincipal | None] = ContextVar("current_open_api_principal", default=None)


def get_current_open_api_principal() -> OpenApiPrincipal | None:
    return current_open_api_principal.get()


def set_current_open_api_principal(principal: OpenApiPrincipal | None) -> Token:
    """Set the principal for the current request context; keep the token to ``reset``."""
    return current_open_api_principal.set(principal)


def reset_current_open_api_principal(token: Token) -> None:
    current_open_api_principal.reset(token)
