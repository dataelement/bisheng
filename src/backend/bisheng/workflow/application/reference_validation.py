"""Keep publication target checks and attach locations from the authorized graph."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.application.model_selection import require_new_models
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.workflow.domain.repositories.workflow_version_repository import WorkflowVersionRepository


def _with_locations(error, references, graph):
    # Never look up names of unavailable targets; only disclose the caller's
    # saved selection and node label from the already authorized version.
    nodes = {node["data"]["id"]: node["data"] for node in graph.get("nodes", []) if "id" in node.get("data", {})}
    details = []
    for reference in references:
        for node_id, node in nodes.items():
            prefix = f"node:{node_id}."
            parameter = reference.slot_key.removeprefix(prefix)
            if parameter not in {
                "model_id",
                "knowledge",
                "knowledge_id",
                "qa_knowledge_id",
                "advanced_retrieval_switch.rerank_model",
            }:
                continue
            resource_type = reference.target.target_type.value
            if parameter == "qa_knowledge_id":
                resource_type = "qa_knowledge"
            elif parameter == "advanced_retrieval_switch.rerank_model":
                resource_type = "rerank_model"
            details.append(
                {
                    "node_id": node_id,
                    "node_name": (str(node.get("name") or "").strip() or node_id)[:100],
                    "resource_type": resource_type,
                    "target_id": reference.target.target_id,
                }
            )
            break
        if len(details) == 5:
            break
    return ResourceReferenceInvalidError(**error.kwargs, workflow_reference_errors=details)


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
