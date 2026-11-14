"""Extract persisted assistant selections without resolving display names."""

import re
from collections.abc import Iterable
from hashlib import sha256

from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    normalize_references,
)

ASSISTANT_REFERENCE_EXTRACTOR_VERSION = "assistant-v1"
LEGACY_NAME_PREFIX = "assistant-v1.legacy-name."


def legacy_assistant_name_version(model_name):
    """An exact original name fingerprint, never a model ID or name lookup."""
    if type(model_name) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:/+\-]{0,254}", model_name):
        return LEGACY_NAME_PREFIX + sha256(model_name.encode()).hexdigest()[:32]
    return None


def extract_legacy_assistant_knowledge_references(*, model_name, knowledge_ids):
    if legacy_assistant_name_version(model_name) is None:
        raise ValueError("an original unresolved assistant model name is required")
    return extract_assistant_references(model_name="", knowledge_ids=knowledge_ids)


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
