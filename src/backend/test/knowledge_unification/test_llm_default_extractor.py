"""T464: extract real five-key defaults without task or consumer copies.

覆盖 AC: AC-71, AC-74, AC-87, AC-88, AC-89
"""

import pytest

from bisheng.llm.domain.services.default_reference_extractor import (
    MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION,
    extract_model_default_references,
)


def pairs(key, payload):
    return {(ref.slot_key, ref.target.target_id) for ref in extract_model_default_references(key, payload)}


@pytest.mark.parametrize("key", ["knowledge_llm", "assistant_llm", "evaluation_llm", "workflow_llm", "linsight_llm"])
def test_empty_saved_original_is_an_explicit_zero_set(key):
    assert extract_model_default_references(key, {}) == ()
    assert MODEL_DEFAULT_REFERENCE_EXTRACTOR_VERSION


def test_knowledge_all_real_slots_and_no_unrelated_json_or_task_binding():
    fields = ["embedding_model_id", "source_model_id", "extract_title_model_id", "qa_similar_model_id", "asr_model_id"]
    raw = {name: number for number, name in enumerate(fields, 1)}
    raw.update({"abstract_enabled": False, "auto_tag_enabled": False, "nested": {"model_id": 999}, "task_model": 999})
    assert pairs("knowledge_llm", raw) == {(name, str(number)) for number, name in enumerate(fields, 1)}


def test_assistant_member_slots_stable_on_reorder_duplicate_and_metadata_change():
    raw = {
        "llm_list": [{"model_id": "001", "streaming": True}, {"model_id": 2}, {"model_id": 1}],
        "auto_llm": {"model_id": 3},
    }
    expected = {("llm_list.1.model_id", "1"), ("llm_list.2.model_id", "2"), ("auto_llm.model_id", "3")}
    assert pairs("assistant_llm", raw) == expected
    raw["llm_list"].reverse()
    assert pairs("assistant_llm", raw) == expected


@pytest.mark.parametrize("key", ["evaluation_llm", "workflow_llm"])
def test_evaluation_and_workflow_only_original_default_slot(key):
    assert pairs(key, {"model_id": 7, "task_id": 12, "result": {"model_id": 99}}) == {("model_id", "7")}


def test_workbench_real_linsight_key_all_saved_model_slots():
    raw = {
        "models": [{"id": "1", "name": "a"}, {"id": "2", "name": "b"}],
        "linsight_default_model_id": "3",
        "chat_default_model_id": "4",
        **{
            name: {"id": str(number), "name": "not an identity"}
            for number, name in enumerate(
                ["embedding_model", "asr_model", "tts_model", "chat_title_llm", "image_read_model"], 5
            )
        },
    }
    expected = {
        ("models.1.id", "1"),
        ("models.2.id", "2"),
        ("linsight_default_model_id", "3"),
        ("chat_default_model_id", "4"),
    }
    expected |= {
        (f"{name}.id", str(number))
        for number, name in enumerate(
            ["embedding_model", "asr_model", "tts_model", "chat_title_llm", "image_read_model"], 5
        )
    }
    assert pairs("linsight_llm", raw) == expected
    assert raw["models"][0]["id"] == "1"


@pytest.mark.parametrize("value", [True, False, -1, 0, "not-an-id", "-1", "1.2"])
def test_configured_nonempty_invalid_id_is_never_silently_dropped(value):
    with pytest.raises(ValueError):
        extract_model_default_references("knowledge_llm", {"source_model_id": value})


@pytest.mark.parametrize("key", ["workbench", "workstation", "task", "arbitrary"])
def test_only_business_keys_are_sources(key):
    with pytest.raises(ValueError):
        extract_model_default_references(key, {"model_id": 1})
