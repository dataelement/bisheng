"""Re-enter the existing knowledge-write credential face for delayed work.

Only a credential identifier and its original identity/scope ceiling persist.
The current credential and delegation policy are checked again on every entry.
"""

from contextlib import asynccontextmanager
from datetime import datetime

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.domain.context import OpenApiPrincipal
from bisheng.open_api.domain.repositories.credential_repository import CredentialRepository
from bisheng.open_api.domain.scopes import OPEN_API_SCOPE_CODES, OpenApiScopeMarker, is_scope_granted
from bisheng.open_api.domain.services.access_context import open_api_access_context
from bisheng.open_api.domain.services.credential_validator import SUBJECT_RESOLVERS
from bisheng.open_api.domain.services.service_account_tenancy import revalidate_service_account

_IDENTITY_FIELDS = (
    "actor_kind",
    "actor_id",
    "mode",
    "authorization_subject_type",
    "authorization_subject_id",
    "resource_owner_user_id",
    "effective_user_id",
    "on_behalf_of_user_id",
    "end_user_id",
)


def capture_knowledge_processing_reference(principal: OpenApiPrincipal) -> dict:
    if (
        not isinstance(principal, OpenApiPrincipal)
        or get_current_open_api_principal() is not principal
        or principal.actor_kind not in {"service_account", "natural_person"}
        or not principal.has_scope("knowledge:write")
    ):
        raise PermissionDeniedError(reason="processing_api_origin_invalid")
    return {
        "kind": "api_credential",
        "credential_id": principal.credential_id,
        "tenant_id": principal.tenant_id,
        "scopes": sorted(principal.scopes),
        "identity": {field: getattr(principal, field) for field in _IDENTITY_FIELDS},
    }


@asynccontextmanager
async def restore_knowledge_processing_reference(reference, *, tenant_id: int):
    try:
        if (
            not isinstance(reference, dict)
            or set(reference) != {"kind", "credential_id", "tenant_id", "scopes", "identity"}
            or reference["kind"] != "api_credential"
            or type(reference["credential_id"]) is not int
            or reference["credential_id"] <= 0
            or type(reference["tenant_id"]) is not int
            or reference["tenant_id"] != tenant_id
            or not isinstance(reference["scopes"], list)
            or not all(isinstance(value, str) for value in reference["scopes"])
            or not isinstance(reference["identity"], dict)
            or set(reference["identity"]) != set(_IDENTITY_FIELDS)
        ):
            raise ValueError("invalid API origin")
        expected = reference["identity"]
        if (
            expected["actor_kind"] not in {"service_account", "natural_person"}
            or expected["mode"] not in {"S", "D"}
            or expected["authorization_subject_type"] not in {"user", "service_account"}
            or any(
                type(expected[key]) is not int or expected[key] <= 0 for key in ("actor_id", "authorization_subject_id")
            )
            or any(
                expected[key] is not None and (type(expected[key]) is not int or expected[key] <= 0)
                for key in ("resource_owner_user_id", "effective_user_id", "on_behalf_of_user_id")
            )
            or (expected["end_user_id"] is not None and not isinstance(expected["end_user_id"], str))
        ):
            raise ValueError("invalid API subject")
        row = await CredentialRepository.get(reference["credential_id"])
        if (
            row is None
            or row.id != reference["credential_id"]
            or row.tenant_id != tenant_id
            or row.subject_kind != expected["actor_kind"]
            or row.subject_id != expected["actor_id"]
            or not row.is_valid_at(datetime.now())
        ):
            raise ValueError("credential unavailable")
        resolver = SUBJECT_RESOLVERS.get(row.subject_kind)
        if resolver is None:
            raise ValueError("credential subject unavailable")
        current = await revalidate_service_account(await resolver(row))
        if (
            current.credential_id != reference["credential_id"]
            or current.tenant_id != tenant_id
            or (current.actor_kind, current.actor_id) != (expected["actor_kind"], expected["actor_id"])
        ):
            raise ValueError("credential identity changed")
        original_scopes = frozenset(reference["scopes"])
        scopes = frozenset(
            code for code in OPEN_API_SCOPE_CODES if current.has_scope(code) and is_scope_granted(code, original_scopes)
        )
        current = current.model_copy(update={"scopes": scopes})
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise PermissionDeniedError(reason="processing_api_credential_invalid") from error

    async def validator(_):
        return current

    async with open_api_access_context(
        authorization=None,
        headers=(),
        marker=OpenApiScopeMarker("knowledge:write", frozenset({"S", "D"}), False),
        on_behalf_of=str(expected["on_behalf_of_user_id"]) if expected["on_behalf_of_user_id"] is not None else None,
        end_user=expected["end_user_id"],
        credential_validator=validator,
    ) as restored:
        if any(getattr(restored, field) != expected[field] for field in _IDENTITY_FIELDS):
            raise PermissionDeniedError(reason="processing_api_identity_changed")
        yield restored
