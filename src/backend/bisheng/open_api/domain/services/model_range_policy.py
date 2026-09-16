"""Which models a credential may call, and who the call is attributed to (F051 D7).

Two things are decided here and neither of them reads a request header for its
answer:

* **range** comes from the credential's subject — a service-account key gets the
  whole tenant's enabled set, a hosted application gets its effective capability
  declaration intersected with that set;
* **subject** (audit attribution only) comes from a signed short-lived access
  token, never from a header a caller could simply write.

The two ports are defined here and registered by their owners (F055 for the
declaration read, F054 for token verification). Their defaults fail closed, so a
hosted-app credential that appears before its owner has registered anything is
refused rather than let through with the tenant-wide range.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from bisheng.common.errcode.model_face import (
    ModelFaceAccessTokenRefusedError,
    ModelFaceCatalogUnavailableError,
    ModelFaceIdentityHeaderRefusedError,
)
from bisheng.llm.domain.services.model_catalog import ModelRange
from bisheng.open_api.domain.context import OpenApiPrincipal

ACCESS_TOKEN_HEADER = "X-BiSheng-Access-Token"
END_USER_HEADER = "X-End-User"

SUBJECT_KIND_USER = "user"
SUBJECT_KIND_APP_SELF = "app_self"

HOSTED_APP_ACTOR_KIND = "hosted_app"


@dataclass(frozen=True, slots=True)
class AccessSubject:
    user_id: int


@dataclass(frozen=True, slots=True)
class ResolvedSubject:
    subject_kind: str
    subject_id: int | None = None
    app_id: str | None = None


class HostedAppDeclarationPort(Protocol):
    """Reads a hosted application's **effective** capability declaration.

    ``None`` means "cannot tell right now" and must lead to a refusal; an empty
    frozenset means "declared zero models", which refuses every model by name
    with a different code.
    """

    async def declared_model_names(self, app_id: str, tenant_id: int) -> frozenset[str] | None: ...


class AccessSubjectVerifierPort(Protocol):
    """Verifies the short-lived access token app-proxy issues per visitor."""

    def verify(self, token: str, *, app_id: str, tenant_id: int) -> AccessSubject | None: ...


class _UnregisteredDeclarationPort:
    async def declared_model_names(self, app_id: str, tenant_id: int) -> frozenset[str] | None:
        logger.error(
            "model_range_policy.declaration_port_missing | app_id={} tenant_id={}",
            app_id,
            tenant_id,
        )
        return None


class _NullAccessSubjectVerifier:
    def verify(self, token: str, *, app_id: str, tenant_id: int) -> AccessSubject | None:
        return None


_declaration_port: HostedAppDeclarationPort = _UnregisteredDeclarationPort()
_access_subject_verifier: AccessSubjectVerifierPort = _NullAccessSubjectVerifier()


def register_hosted_app_declaration_port(port: HostedAppDeclarationPort) -> None:
    global _declaration_port
    _declaration_port = port


def register_access_subject_verifier(port: AccessSubjectVerifierPort) -> None:
    global _access_subject_verifier
    _access_subject_verifier = port


def get_hosted_app_declaration_port() -> HostedAppDeclarationPort:
    return _declaration_port


def get_access_subject_verifier() -> AccessSubjectVerifierPort:
    return _access_subject_verifier


def _header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        # Starlette headers are case-insensitive; a plain dict in a test is not.
        lowered = name.lower()
        for key, candidate in headers.items():
            if key.lower() == lowered:
                value = candidate
                break
    return value


async def resolve_range_and_subject(
    principal: OpenApiPrincipal,
    headers: Mapping[str, str] | None = None,
) -> tuple[ModelRange, ResolvedSubject]:
    """Decide the callable range and the audit subject, in a fixed order.

    The order is part of the contract, not an implementation detail: a caller
    that sent a header it should not have must always be told about the header,
    even when the model name happens to be wrong too. Otherwise an agent's
    correction loop gets a different answer each round.

    1. delegation-style identity header → refuse (26205)
    2. access token header → refuse or verify (26204)
    3. establish the range (26216 / declaration)
    4. name resolution — done by the caller, against the range returned here
    """

    if _header(headers, END_USER_HEADER) is not None:
        # The shared /api/v2 base validates this header's format and then adopts
        # it without a word. This face carries no delegation at all, so a
        # well-formed value is refused here rather than quietly believed.
        raise ModelFaceIdentityHeaderRefusedError()

    access_token = _header(headers, ACCESS_TOKEN_HEADER)

    if principal.actor_kind != HOSTED_APP_ACTOR_KIND:
        if access_token is not None:
            # No third party is present in local development, so a service
            # account key presenting a visitor token is a forgery attempt, not
            # a mistake worth tolerating.
            raise ModelFaceAccessTokenRefusedError()
        return ModelRange(kind="tenant"), ResolvedSubject(
            subject_kind=principal.actor_kind,
            subject_id=principal.actor_id,
        )

    app_id = principal.actor_name

    # Step 2 before step 3, always: a forged or expired token is refused whether
    # or not the declaration happens to be readable this second. Reading the
    # declaration first would answer 26216 ("cannot tell right now, try again")
    # to a caller whose token is permanently invalid.
    subject = ResolvedSubject(subject_kind=SUBJECT_KIND_APP_SELF, app_id=app_id)
    if access_token is not None:
        verified = _access_subject_verifier.verify(
            access_token,
            app_id=app_id,
            tenant_id=principal.tenant_id,
        )
        if verified is None:
            # An expired or forged token must not degrade to "the app itself" —
            # that would make attribution something the caller can steer.
            raise ModelFaceAccessTokenRefusedError()
        subject = ResolvedSubject(
            subject_kind=SUBJECT_KIND_USER,
            subject_id=verified.user_id,
            app_id=app_id,
        )

    try:
        declared = await _declaration_port.declared_model_names(app_id, principal.tenant_id)
    except Exception as exc:
        raise ModelFaceCatalogUnavailableError(exception=exc) from exc
    if declared is None:
        raise ModelFaceCatalogUnavailableError()

    return ModelRange(kind="declared", declared=frozenset(declared)), subject


__all__ = [
    "ACCESS_TOKEN_HEADER",
    "END_USER_HEADER",
    "HOSTED_APP_ACTOR_KIND",
    "SUBJECT_KIND_APP_SELF",
    "SUBJECT_KIND_USER",
    "AccessSubject",
    "AccessSubjectVerifierPort",
    "HostedAppDeclarationPort",
    "ResolvedSubject",
    "get_access_subject_verifier",
    "get_hosted_app_declaration_port",
    "register_access_subject_verifier",
    "register_hosted_app_declaration_port",
    "resolve_range_and_subject",
]
