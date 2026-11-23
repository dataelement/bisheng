"""Closed, credential-free acknowledgements for the model deletion Owner."""

from copy import deepcopy

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanChangedError
from bisheng.llm.application.model_provider_projection import execution_metadata


def checked_model_ack(row, command):
    metadata = execution_metadata(row)
    ack = metadata["ack"]
    if (
        metadata["force"] != command.force
        or not isinstance(ack, dict)
        or set(ack)
        != {"operation_id", "server_id", "removed_model_ids", "deleted_server", "new_model_ids", "result_digest"}
        or ack["operation_id"] != row.operation_id
        or type(ack["server_id"]) is not int
        or ack["server_id"] != command.server_id
        or type(ack["deleted_server"]) is not bool
        or ack["deleted_server"] != (command.operation == "model_delete_server")
    ):
        raise KnowledgeOperationPlanChangedError()
    for key in ("removed_model_ids", "new_model_ids"):
        values = ack[key]
        if (
            type(values) is not list
            or any(type(value) is not int or value <= 0 for value in values)
            or len(set(values)) != len(values)
        ):
            raise KnowledgeOperationPlanChangedError()
    if ack["removed_model_ids"] != [int(item["target_id"]) for item in row.target_manifest]:
        raise KnowledgeOperationPlanChangedError()
    if set(ack["removed_model_ids"]) & set(ack["new_model_ids"]):
        raise KnowledgeOperationPlanChangedError()
    if command.operation == "model_delete_server":
        if ack["new_model_ids"] or ack["result_digest"] is not None:
            raise KnowledgeOperationPlanChangedError()
    elif (
        not isinstance(ack["result_digest"], str)
        or len(ack["result_digest"]) != 64
        or any(ch not in "0123456789abcdef" for ch in ack["result_digest"])
    ):
        raise KnowledgeOperationPlanChangedError()
    return deepcopy(ack)


async def completed_model_result(application, request, command, row):
    ack = checked_model_ack(row, command)
    from bisheng.llm.application.model_deletion_context import model_write_phase

    sharing, prepared = None, None
    metadata = execution_metadata(row)
    if metadata["sharing"] is not None:
        sharing = await application._sharing(request)
        prepared = await request.call(
            sharing.arestore,
            metadata["sharing"],
            confirmation_id=row.id,
            tenant_id=row.tenant_id,
            operation=row.operation,
            operator_id=row.actor_user_id,
        )
    async with model_write_phase(application.session_factory, request) as phase:
        await phase.call(application.writer.arequire_completed, phase.session, plan=row, ack=ack)
        if sharing is not None:
            await phase.call(sharing.arequire_finalized, phase.session, prepared)
    if command.operation == "model_delete_server":
        return ack
    from bisheng.llm.domain.services.llm import LLMService

    return await request.call(LLMService.get_one_llm, command.server_id, operator=request.identity)
