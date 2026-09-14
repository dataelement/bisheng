import pytest
from pydantic import ValidationError

from bisheng.open_api.domain.schemas.workstation import OpenDailyChatCompletionReq
from bisheng.workstation.domain.schemas.chat import APIChatCompletion


def test_daily_schema_is_internal_schema_minus_exactly_two_fields():
    assert set(APIChatCompletion.model_fields) - set(OpenDailyChatCompletionReq.model_fields) == {
        "task_mode",
        "use_knowledge_base",
    }
    assert "files" in OpenDailyChatCompletionReq.model_fields
    assert OpenDailyChatCompletionReq.model_fields["clientTimestamp"].is_required()


@pytest.mark.parametrize("field", ["task_mode", "use_knowledge_base", "execution", "run_mode", "turn_id"])
def test_daily_schema_forbids_removed_and_unknown_fields(field):
    payload = {"clientTimestamp": "1", "model": "m", field: False}
    with pytest.raises(ValidationError):
        OpenDailyChatCompletionReq.model_validate(payload)


def test_conversion_forces_daily_mode_and_preserves_files():
    files = [{"file_path": "https://example.test/tmp-dir/a"}]
    request = OpenDailyChatCompletionReq(clientTimestamp="1", model="m", files=files)
    internal = request.to_internal()
    assert internal.task_mode is False
    assert internal.use_knowledge_base is None
    assert internal.files == files
