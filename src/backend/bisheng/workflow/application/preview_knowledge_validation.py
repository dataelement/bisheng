"""Preserve preview binding authorization while returning every failing slot."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.permission.application.business_authorization import batch_check_business_actions
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.resource_reference.application.error_details import reference_error_details


async def require_preview_knowledge(session, identity, references, graph, repository, *, for_update=False):
    targets = {ref.target for ref in references if ref.target.target_type == TargetType.KNOWLEDGE_SPACE}
    kinds = await repository.aget_knowledge_resource_types(
        session, [target.target_id for target in targets], for_update=for_update
    )
    failed = {
        target: "unavailable"
        for target in targets
        if target.target_id in kinds and kinds[target.target_id] not in {0, 1, 3}
    }
    for kind, allowed_types in (("knowledge_space", {3}), ("knowledge_library", {0, 1})):
        ids = tuple(sorted(target.target_id for target in targets if kinds.get(target.target_id) in allowed_types))
        if not ids:
            continue
        actions = await batch_check_business_actions(
            identity, resource_type=kind, resource_ids=ids, actions=("visible",)
        )
        failed.update(
            {
                target: "unavailable"
                for target in targets
                if target.target_id in ids and "visible" not in actions.get(target.target_id, ())
            }
        )
    if failed:
        # A C3-filtered absence cannot distinguish a missing resource from a foreign one.
        failed.update({target: "unavailable" for target in targets if target.target_id not in kinds})
        raise ResourceReferenceInvalidError(
            reason="reference_target_invalid",
            reference_errors=reference_error_details(references, failed, graph, limit=None, include_parameter=True),
        )
    # Absent rows proceed only to the issued target-fact reader. It distinguishes
    # actual missing/foreign targets and rejects both before any execution.
