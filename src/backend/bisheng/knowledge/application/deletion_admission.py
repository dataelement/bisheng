"""Original typed credential continuation for one confirmed knowledge deletion."""

from contextlib import asynccontextmanager

from bisheng.common.errcode.permission import PermissionDeniedError
from bisheng.core.context.tenant import get_admin_scope_tenant_id, get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.application.processing_identity import (
    _actor_facts,
    _narrow_actor,
    capture_processing_actor,
    restore_processing_actor,
)
from bisheng.knowledge.domain.schemas.processing_actor_subject import processing_actor_subject
from bisheng.open_api.application.access_context import get_current_open_api_principal
from bisheng.open_api.application.knowledge_processing_identity import OPEN_API_SCOPE_CODES, is_scope_granted
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL, get_data_scope_resolver
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)


def tenant():
    value = get_current_tenant_id()
    if type(value) is not int or value <= 0 or is_tenant_filter_bypassed():
        raise PermissionDeniedError(reason="delete_concrete_tenant_required")
    return value


def subject(reference):
    return processing_actor_subject(
        reference,
        tenant_id=tenant(),
        actor_user_id=reference["actor_user_id"],
        source_space_id=reference["space_id"],
        required_action="delete",
    )


async def capture(identity, *, space_id):
    entry = "open_api" if get_current_open_api_principal() is not None else "web"
    return (
        await capture_processing_actor(identity, space_id=space_id, required_action="delete", entry_kind=entry)
    ).reference


@asynccontextmanager
async def identity(original, *, current=None, continuation=None):
    expected, active = subject(original), continuation or original
    if current is not None:
        active = await capture(current, space_id=original["space_id"])
    if subject(active) != expected or active["entry_kind"] != original["entry_kind"]:
        raise PermissionDeniedError(reason="delete_original_subject_required")
    old, fresh = original["credential_reference"], active["credential_reference"]
    if old.get("kind") == fresh.get("kind") == "api_credential":
        active = {
            **active,
            "credential_reference": {
                **fresh,
                "scopes": [
                    code
                    for code in OPEN_API_SCOPE_CODES
                    if is_scope_granted(code, frozenset(old["scopes"]))
                    and is_scope_granted(code, frozenset(fresh["scopes"]))
                ],
            },
        }
    async with restore_processing_actor(active, tenant_id=tenant()) as actual:
        actor = _narrow_actor(get_current_permission_actor(), original["actor"])
        token = set_current_permission_actor(actor)
        try:
            yield actual, {**active, "actor": _actor_facts(actor)}
        finally:
            reset_current_permission_actor(token)


def current(actor, actual_tenant, management_pin):
    if (
        tenant() != actual_tenant
        or get_current_permission_actor() is not actor
        or get_admin_scope_tenant_id() != management_pin
    ):
        raise PermissionDeniedError(reason="delete_execution_context_changed")


async def narrow(resources):
    actor, actual_tenant, pin = get_current_permission_actor(), tenant(), get_admin_scope_tenant_id()
    if actor is None:
        raise PermissionDeniedError(reason="delete_original_actor_required")
    if actor.data_scope != DATA_SCOPE_PERSONAL:
        return
    resolver = get_data_scope_resolver()
    if resolver is None or actor.subject_type != "user":
        raise PermissionDeniedError(reason="delete_ownership_resolver_required")
    groups = {}
    for kind, ident in resources:
        groups.setdefault("knowledge_folder" if kind == "folder" else kind, set()).add(str(ident))
    for kind, ids in groups.items():
        ordered = sorted(ids)
        for offset in range(0, len(ordered), 200):
            page = tuple(ordered[offset : offset + 200])
            owned = await resolver.filter_owned(
                holder_user_id=actor.subject_id, tenant_id=actual_tenant, resource_type=kind, resource_ids=page
            )
            current(actor, actual_tenant, pin)
            if owned != frozenset(page):
                raise PermissionDeniedError(reason="delete_personal_scope_denied")
