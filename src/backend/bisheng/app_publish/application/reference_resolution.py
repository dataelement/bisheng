"""Freeze one complete APP declaration in the caller's original name plan."""

from dataclasses import dataclass
from weakref import WeakKeyDictionary, ref

from bisheng.app_publish.domain.repositories.reference_source_repository import HostedAppReferenceSourceRepository
from bisheng.app_publish.domain.services.reference_extractor import (
    extract_app_reference_requests,
    extract_app_references,
)
from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, ResourceReferenceInvalidError
from bisheng.llm.application.model_name_resolution import get_model_name_resolution_port
from bisheng.resource_reference.application.contracts import TargetKey, TargetType, normalize_references


@dataclass(frozen=True, slots=True)
class _KnowledgePlan:
    original: object
    requests: tuple
    rows: tuple


_knowledge_plans = WeakKeyDictionary()


def _invalid(reason="app_reference_resolution"):
    return ResourceReferenceInvalidError(reason=reason)


async def resolve_app_references(
    session,
    declaration,
    *,
    identity,
    source_tenant_id,
    model_name_plan,
    frozen_references=None,
    model_range=None,
):
    """Resolve without opening a Session, rewriting JSON, or preparing new models.

    The first call locks the complete knowledge namespace after the caller's
    complete server/model plan. Later consumption locks only these already
    known IDs, and any manifest change requires a new outer transaction.
    """
    names = get_model_name_resolution_port()
    await names.assert_plan_current(
        session, source_tenant_id, identity=identity, plan=model_name_plan, range=model_range
    )
    try:
        requests = extract_app_reference_requests(declaration)
    except (TypeError, ValueError) as error:
        raise _invalid() from error
    requested_names = tuple(sorted({item.requested_name for item in requests if item.target_type == TargetType.MODEL}))
    if model_name_plan.requested_names != requested_names or model_name_plan.tenant_id != source_tenant_id:
        raise _invalid("app_model_plan_incomplete")
    resolved_targets = {}
    for request in requests:
        if request.target_type == TargetType.MODEL:
            model = await names.resolve_model_name_current(
                session,
                source_tenant_id,
                request.requested_name,
                identity=identity,
                plan=model_name_plan,
                range=model_range,
            )
            resolved_targets[request.slot_key] = TargetKey(TargetType.MODEL, str(model.model_id))

    knowledge_requests = tuple(item for item in requests if item.target_type == TargetType.KNOWLEDGE_SPACE)
    ids = {int(item.target_id) for item in knowledge_requests if item.target_id is not None}
    if frozen_references is not None:
        ids.update(
            int(item.target.target_id)
            for item in frozen_references
            if item.target.target_type == TargetType.KNOWLEDGE_SPACE
        )
    requested_knowledge_names = {item.requested_name for item in knowledge_requests if item.requested_name is not None}
    repo = HostedAppReferenceSourceRepository()
    rows = await repo.aget_knowledge_candidates(
        session, ids=tuple(sorted(ids)), names=tuple(sorted(requested_knowledge_names))
    )
    registered = _knowledge_plans.get(model_name_plan)
    if registered is None:
        locked = await repo.aget_knowledge_candidates(
            session, ids=tuple(sorted(ids)), names=tuple(sorted(requested_knowledge_names)), for_update=True
        )
        if locked != rows:
            raise KnowledgeOperationPlanConflictError(reason="app_knowledge_plan_changed")
        registered = _KnowledgePlan(ref(model_name_plan), knowledge_requests, rows)
        _knowledge_plans[model_name_plan] = registered
    else:
        if registered.original() is not model_name_plan or registered.requests != knowledge_requests:
            raise _invalid("app_knowledge_plan_invalid")
        if registered.rows != rows:
            raise KnowledgeOperationPlanConflictError(reason="app_knowledge_plan_changed")
        locked = await repo.aget_knowledge_candidates(
            session, ids=tuple(row["id"] for row in registered.rows), for_update=True
        )
        if locked != registered.rows:
            raise KnowledgeOperationPlanConflictError(reason="app_knowledge_plan_changed")
    supported = [row for row in registered.rows if row["type"] in {0, 1, 3}]
    for request in knowledge_requests:
        matches = (
            [row for row in supported if str(row["id"]) == request.target_id]
            if request.target_id
            else [row for row in supported if row["name"] == request.requested_name]
        )
        if len(matches) != 1 or matches[0]["tenant_id"] != source_tenant_id:
            raise _invalid("app_knowledge_name_ambiguous" if len(matches) > 1 else "app_knowledge_unavailable")
        resolved_targets[request.slot_key] = TargetKey(TargetType.KNOWLEDGE_SPACE, str(matches[0]["id"]))
    try:
        references = extract_app_references(declaration, resolved_targets=resolved_targets)
    except (TypeError, ValueError) as error:
        raise _invalid() from error
    if frozen_references is not None and normalize_references(tuple(frozen_references)) != references:
        raise _invalid("app_name_binding_changed")
    return references
