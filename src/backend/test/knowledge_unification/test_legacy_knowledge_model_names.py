"""AC-137: retain original names without issuing fake model references."""

import pytest

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError
from bisheng.knowledge.domain.services.model_reference_extractor import (
    KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION,
    knowledge_model_source_configuration,
    legacy_knowledge_model_version,
)


@pytest.mark.parametrize("name", ["bge-large-zh", "jina-embeddings-v2-base-zh", "custom-model", "旧模型名称"])
def test_existing_name_retention_has_exact_fingerprint_and_no_model_target(name):
    version, refs = knowledge_model_source_configuration(model=name, retain_legacy=True)
    assert version == legacy_knowledge_model_version(name)
    assert len(version) <= 64 and version != legacy_knowledge_model_version(name + "x")
    assert refs == ()
    with pytest.raises(ReferenceCoverageNotReadyError):
        knowledge_model_source_configuration(model=name)


@pytest.mark.parametrize("model", ["0", "-1", "+1", " 5", "5 ", "", None, {}, [], "bad\x00name"])
def test_legacy_compatibility_does_not_reinterpret_invalid_ids_or_unknown_shapes(model):
    assert legacy_knowledge_model_version(model) is None


def test_valid_model_reference_and_transition_remain_strict():
    version, refs = knowledge_model_source_configuration(model="17", retain_legacy=True)
    assert version == KNOWLEDGE_MODEL_REFERENCE_EXTRACTOR_VERSION
    assert len(refs) == 1 and refs[0].target.target_id == "17"
    with pytest.raises(ReferenceCoverageNotReadyError):
        knowledge_model_source_configuration(model="old-name", model_transition={}, retain_legacy=True)
