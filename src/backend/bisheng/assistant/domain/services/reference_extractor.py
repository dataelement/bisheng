"""Extract persisted assistant selections without resolving display names."""

from collections.abc import Iterable

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    normalize_references,
)

ASSISTANT_REFERENCE_EXTRACTOR_VERSION = "assistant-v1"


def extract_assistant_references(*, model_name: str | None, knowledge_ids: Iterable[int]) -> tuple[ReferenceSpec, ...]:
    """A multiselect uses its semantic slot plus target, never its list offset.

    Empty model selections and the legacy zero knowledge sentinel are legal
    incomplete configurations. A populated model_name is already a model ID;
    interpreting it as a label could bind an entirely different model.
    """
    references = []
    if model_name is not None and model_name != "":
        if not isinstance(model_name, str):
            raise TypeError("assistant model_name must be a model ID string")
        references.append(ReferenceSpec("model_name", TargetKey(TargetType.MODEL, model_name)))
    for knowledge_id in knowledge_ids:
        if type(knowledge_id) is not int or knowledge_id < 0:
            raise ValueError("assistant knowledge IDs must be non-negative integers")
        if knowledge_id:
            references.append(ReferenceSpec("knowledge_list", TargetKey(TargetType.KNOWLEDGE_SPACE, str(knowledge_id))))
    return normalize_references(tuple(references))
