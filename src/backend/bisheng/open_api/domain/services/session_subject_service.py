"""Project an authenticated Open API principal into session ownership."""

from bisheng.chat_session.domain.session_subject import SessionSubject
from bisheng.common.errcode.open_api import OpenApiEndpointUnregisteredError
from bisheng.open_api.domain.context import OpenApiPrincipal


def session_subject_from_principal(principal: OpenApiPrincipal) -> SessionSubject:
    if principal.actor_kind == "service_account" and principal.mode == "S":
        if principal.resource_owner_user_id is None:
            raise OpenApiEndpointUnregisteredError()
        return SessionSubject.service_account(
            tenant_id=principal.tenant_id,
            service_account_id=principal.actor_id,
            resource_owner_user_id=principal.resource_owner_user_id,
            external_user_id=principal.end_user_id,
        )
    if principal.effective_user_id is None:
        raise OpenApiEndpointUnregisteredError()
    return SessionSubject.natural_person(
        tenant_id=principal.tenant_id,
        user_id=principal.effective_user_id,
    )


__all__ = ["session_subject_from_principal"]
