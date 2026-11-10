"""Exact model slots owned by a Knowledge business resource, not its jobs."""

from collections.abc import Mapping

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.resource_reference.application.contracts import (
    ReferenceSpec,
    TargetKey,
    TargetType,
    canonical_target_id,
    normalize_references,
)

KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION = "knowledge-model-v1"
_TRANSITION_FIELDS = frozenset({"schema_version", "operation_id", "current_model_id", "pending_model_id"})


def extract_knowledge_model_references(*, model, model_transition=None) -> tuple[ReferenceSpec, ...]:
    """The serving model stays current while the business pending slot builds.

    processing_defaults contains processing rules. It is intentionally not an
    input to this extractor, and no arbitrary JSON is scanned for model IDs.
    """
    try:
        current = None if model is None or model == "" else canonical_target_id(model)
        references = [ReferenceSpec("model", TargetKey(TargetType.MODEL, current))] if current else []
        if model_transition is not None:
            stage = model_transition
            if (
                not isinstance(stage, Mapping)
                or set(stage) != _TRANSITION_FIELDS
                or type(stage["schema_version"]) is not int
                or stage["schema_version"] != 1
                or not isinstance(stage["operation_id"], str)
                or not stage["operation_id"].strip()
                or len(stage["operation_id"]) > 64
                or "\x00" in stage["operation_id"]
            ):
                raise ValueError("unknown knowledge model transition")
            if current is None or canonical_target_id(stage["current_model_id"]) != current:
                raise ValueError("transition current model differs from the serving resource")
            references.append(
                ReferenceSpec(
                    "model_transition.pending_model_id", TargetKey(TargetType.MODEL, stage["pending_model_id"])
                )
            )
        return normalize_references(tuple(references))
    except (KeyError, TypeError, ValueError) as error:
        raise ReferenceCoverageNotReadyError(reason="knowledge_model_configuration_invalid") from error
