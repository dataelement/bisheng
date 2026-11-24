"""Explain rejected saved knowledge selections without weakening binding checks."""

from fastapi import HTTPException

from bisheng.assistant.application.execution_admission import AssistantExecutionAdmission
from bisheng.assistant.domain.services.assistant_boundary_service import AssistantBoundaryService
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.contracts import TargetType
from bisheng.resource_reference.application.error_details import reference_error_details


async def authorize_assistant_knowledge_bindings(identity, assistant_id, knowledge_ids):
    try:
        await AssistantBoundaryService.authorize_knowledge_bindings(identity, knowledge_ids)
    except HTTPException as error:
        if error.status_code != 404:
            raise
        # Only an editor may inspect saved selections to explain this refusal.
        # Unknown/new IDs retain the original non-disclosing boundary response.
        await require_business_action(identity, resource_type="assistant", resource_id=assistant_id, action="edit")
        result = await AssistantExecutionAdmission.prepare(identity, assistant_id, purpose="inspect")
        selected = {str(value) for value in knowledge_ids}
        states = {
            fact.key: fact.state
            for fact in result.target_states
            if fact.key.target_type == TargetType.KNOWLEDGE_SPACE
            and fact.key.target_id in selected
            and not fact.is_valid
        }
        details = reference_error_details(result.snapshot.references, states)
        if details:
            raise ResourceReferenceInvalidError(reason="reference_target_invalid", reference_errors=details) from error
        raise
