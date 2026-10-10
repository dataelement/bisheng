"""F073 task-mode request contract (spec AC-10, AC-15, AC-17, AC-27)."""

import pytest
from pydantic import ValidationError

from bisheng.open_api.domain.schemas.task_mode import (
    TASK_TEXT_MAX_LENGTH,
    OpenTaskStatus,
    OpenTaskSubmitReq,
)


def _body(**overrides):
    body = {
        "run_mode": "task",
        "execution": "async",
        "clientTimestamp": "2026-09-30T10:00:00",
        "text": "Summarize the attached contracts",
        "model": "7",
    }
    body.update(overrides)
    return body


def test_minimal_submission_is_accepted():
    req = OpenTaskSubmitReq.model_validate(_body())
    internal = req.to_internal()
    assert internal.task_mode is True
    assert internal.conversationId is None
    assert internal.use_knowledge_base.personal_knowledge_enabled is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("conversationId", "abc"),
        ("use_knowledge_base", {"personal_knowledge_enabled": True}),
        ("personal_knowledge_enabled", True),
        ("task_mode", True),
        ("unknown", 1),
    ],
)
def test_fields_outside_the_contract_are_rejected(field, value):
    with pytest.raises(ValidationError):
        OpenTaskSubmitReq.model_validate(_body(**{field: value}))


@pytest.mark.parametrize("text", ["", "   ", "x" * (TASK_TEXT_MAX_LENGTH + 1)])
def test_text_must_be_present_and_bounded(text):
    with pytest.raises(ValidationError):
        OpenTaskSubmitReq.model_validate(_body(text=text))


def test_execution_must_be_async():
    with pytest.raises(ValidationError):
        OpenTaskSubmitReq.model_validate(_body(execution="sync"))


def test_knowledge_lists_are_capped():
    with pytest.raises(ValidationError):
        OpenTaskSubmitReq.model_validate(_body(knowledge_ids=list(range(51))))


def test_every_attachment_gets_a_file_id_for_the_linsight_mapping():
    req = OpenTaskSubmitReq.model_validate(
        _body(files=[{"file_path": "http://x/tmp/open-api/p/a.pdf", "file_name": "a.pdf", "relative_path": "a.pdf"}])
    )
    (item,) = req.to_internal().files
    assert item["file_id"] and item["filepath"] == "http://x/tmp/open-api/p/a.pdf"
    assert req.file_refs() == [{"file_path": "http://x/tmp/open-api/p/a.pdf", "file_name": "a.pdf"}]


def test_skills_are_deduplicated_in_order():
    req = OpenTaskSubmitReq.model_validate(_body(skills=["b", "a", "b"]))
    assert req.skills == ["b", "a"]


def test_waiting_input_is_reserved_in_the_status_enum():
    assert OpenTaskStatus("waiting_input") is OpenTaskStatus.WAITING_INPUT
