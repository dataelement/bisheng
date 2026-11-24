"""Keep publication target checks and attach locations from the authorized graph."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.application.model_selection import require_new_models
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.resource_reference.application.error_details import reference_error_details
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository


def _with_locations(error, references, graph):
    details = reference_error_details(references, {ref.target: "unavailable" for ref in references}, graph)
    kwargs = {**error.kwargs, "reference_errors": details}
    # Keep the existing publication response field for older clients.
    kwargs["workflow_reference_errors"] = [{k: v for k, v in detail.items() if k != "state"} for detail in details]
    return ResourceReferenceInvalidError(**kwargs)


async def require_workflow_targets(session, references, graph):
    """Preserve real validation and give editors an actionable failing location."""
    try:
        await require_new_models(session, references)
    except ResourceReferenceInvalidError as error:
        if error.kwargs.get("reason") != "model_selection_unavailable":
            raise
        unavailable = set(error.kwargs["unavailable_target_ids"])
        failed = tuple(
            reference
            for reference in references
            if reference.target.target_type == TargetType.MODEL and reference.target.target_id in unavailable
        )
        raise _with_locations(error, failed, graph) from error
    for reference in references:
        if reference.target.target_type != TargetType.KNOWLEDGE_SPACE:
            continue
        try:
            await WorkflowVersionRepository.aget_knowledge_resource_type(session, int(reference.target.target_id))
        except ResourceReferenceInvalidError as error:
            if error.kwargs.get("reason") != "knowledge_reference_target_unavailable":
                raise
            raise _with_locations(error, (reference,), graph) from error
