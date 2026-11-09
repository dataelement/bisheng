"""Identity and detached move-stage material used only by the actual MoveOwner."""

from contextlib import asynccontextmanager

from bisheng.common.errcode.permission import PermissionDeniedError, PermissionPublishNotReadyError
from bisheng.core.context.tenant import get_current_tenant_id, is_tenant_filter_bypassed
from bisheng.knowledge.application.processing_identity import (
    _actor_facts,
    _narrow_actor,
    capture_processing_actor,
    restore_processing_actor,
)
from bisheng.knowledge.domain.schemas.processing_actor_subject import processing_actor_subject
from bisheng.open_api.application.knowledge_processing_identity import OPEN_API_SCOPE_CODES, is_scope_granted
from bisheng.permission.application.business_authorization import VerifiedPermissionTarget, require_business_action
from bisheng.permission.application.data_scope import DATA_SCOPE_PERSONAL, get_data_scope_resolver
from bisheng.permission.application.identity import (
    get_current_permission_actor,
    reset_current_permission_actor,
    set_current_permission_actor,
)
from bisheng.permission.application.knowledge_move_projection import (
    KnowledgeMoveProjectionApplication,
    MoveProjectionExpectation,
    operation_key,
)


def tenant():
    value = get_current_tenant_id()
    if type(value) is not int or value <= 0 or is_tenant_filter_bypassed():
        raise PermissionDeniedError(reason="move_concrete_tenant_required")
    return value


def subject(reference):
    return processing_actor_subject(
        reference, tenant_id=tenant(), actor_user_id=reference["actor_user_id"], source_space_id=reference["space_id"]
    )


@asynccontextmanager
async def identity(reference, *, current=None, entry_kind=None, allow_other=False):
    original = subject(reference)
    active = reference
    if current is not None:
        active = (
            await capture_processing_actor(
                current, space_id=reference["space_id"], required_action="move", entry_kind=entry_kind
            )
        ).reference
        if subject(active) != original and not allow_other:
            raise PermissionDeniedError(reason="move_retry_required_for_other_subject")
    if current is not None and subject(active) == original:
        old, fresh = reference["credential_reference"], active["credential_reference"]
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
    async with restore_processing_actor(active, tenant_id=tenant()) as restored:
        actor = get_current_permission_actor()
        if subject(active) == original:
            actor = _narrow_actor(actor, reference["actor"])
        token = set_current_permission_actor(actor)
        try:
            yield restored, {**active, "actor": _actor_facts(actor)}
        finally:
            reset_current_permission_actor(token)


def resource(root):
    return "folder" if root.type == "folder" else "knowledge_file", root.id


async def authorize(identity, *, roots, destination_space_id, destination_folder_id, move=()):
    actor = get_current_permission_actor()
    current_tenant = tenant()

    def current():
        if tenant() != current_tenant or get_current_permission_actor() is not actor:
            raise PermissionDeniedError(reason="move_admission_context_changed")

    groups = {}
    for root in roots:
        kind, ident = resource(root)
        groups.setdefault(kind, set()).add(str(ident))
    if actor.data_scope == DATA_SCOPE_PERSONAL:
        resolver = get_data_scope_resolver()
        if resolver is None or actor.subject_type != "user":
            raise PermissionDeniedError(reason="move_ownership_resolver_required")
        for kind, ids in groups.items():
            ordered = sorted(ids)
            for offset in range(0, len(ordered), 200):
                page = tuple(ordered[offset : offset + 200])
                actual = await resolver.filter_owned(
                    holder_user_id=actor.subject_id, tenant_id=current_tenant, resource_type=kind, resource_ids=page
                )
                current()
                if actual != frozenset(page):
                    raise PermissionDeniedError(reason="move_personal_scope_denied")
    for root in move:
        kind, ident = resource(root)
        await require_business_action(identity, resource_type=kind, resource_id=ident, action="move")
        current()
    await require_business_action(
        identity,
        resource_type="folder" if destination_folder_id is not None else "knowledge_space",
        resource_id=destination_folder_id or destination_space_id,
        action="upload_file",
    )
    current()


def expectations(job, changes, *, actor_id, candidates, members):
    by_target = {(row.resource_type, row.resource_id): row.operator_id for row in candidates}
    if actor_id not in members or any(ident not in members for ident in by_target.values()):
        raise PermissionDeniedError(reason="move_operator_not_accepted")
    result = []
    for change in changes:
        allowed = {actor_id}
        candidate = by_target.get((change.resource_type, str(change.resource_id)))
        if candidate is not None:
            allowed.add(candidate)
        common = {
            "tenant_id": job.tenant_id,
            "resource_type": change.resource_type,
            "resource_id": str(change.resource_id),
            "resource_version": change.expected_permission_version,
            "context_version": job.parameters["scope_digest"],
        }
        before = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.old_parent_type, parent_id=str(change.old_parent_id)
        )
        after = VerifiedPermissionTarget.from_business_service(
            **common, parent_type=change.new_parent_type, parent_id=str(change.new_parent_id)
        )
        result.append(
            MoveProjectionExpectation(
                job.id,
                job.tenant_id,
                change.resource_type,
                str(change.resource_id),
                before,
                after,
                change.mode,
                change.expected_permission_version,
                job.parameters["changes_digest"],
                tuple(sorted(allowed)),
            )
        )
    return tuple(result)


def needs_move(changes, facts):
    by_key = {fact.idempotency_key: fact for fact in facts}
    result = set()
    for item in changes:
        fact = by_key.get(operation_key(item.job_id, item.resource_type, item.resource_id))
        if fact is None:
            result.add((item.resource_type, int(item.resource_id)))
            continue
        if fact.status not in {"PREPARED", "STAGING", "COMMIT_UNKNOWN", "COMMITTED", "FINALIZED", "FAILED_CLOSED"}:
            raise PermissionPublishNotReadyError(msg="Move operation has an unknown stage")
        state = fact.parent_state
        if (
            fact.status == "PREPARED"
            and state is not None
            and state.projection_state == "CURRENT"
            and (state.mode, state.version, state.parent_type, state.parent_id)
            == (item.mode, item.expected_permission_version, item.before.parent_type, item.before.parent_id)
        ):
            result.add((item.resource_type, int(item.resource_id)))
        elif fact.status == "FINALIZED":
            if state is None or (
                state.projection_state,
                state.operation_id,
                state.version,
                state.mode,
                state.parent_type,
                state.parent_id,
            ) != ("CURRENT", fact.id, fact.target_version, item.mode, item.after.parent_type, item.after.parent_id):
                raise PermissionPublishNotReadyError(msg="Move finalized mode is not its exact current after")
        else:
            KnowledgeMoveProjectionApplication._owned_mode(item, fact)
    return result
