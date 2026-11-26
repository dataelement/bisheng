"""Report failed default-model selections consistently on reads and writes."""

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.llm.domain.services.default_reference_extractor import model_default_models_are_callable


def require_callable_default_models(key, references, states):
    details = []
    for reference in references:
        if model_default_models_are_callable(key, (reference,), states):
            continue
        model = states.get(int(reference.target.target_id))
        state = "unavailable" if model is None else "offline" if not model.online else "type_mismatch"
        details.append({"resource_type": "model", "target_id": reference.target.target_id, "state": state})
        if len(details) == 5:
            break
    if details:
        raise ResourceReferenceInvalidError(reason="model_default_models_unavailable", reference_errors=details)
