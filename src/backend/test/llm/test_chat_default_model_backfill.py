"""Pre-3.0 workbench configs get the daily-mode default the 2.x client used (last model)."""

import pytest

from bisheng.llm.domain.services.chat_default_model_backfill import transform_chat_default


@pytest.mark.parametrize(
    "payload",
    [
        {"models": [{"id": "3"}, {"id": "7"}, {"id": "5"}]},
        # A 3.0 save wrote the key as null without any admin choice (seen on 114).
        {"models": [{"id": "3"}, {"id": "7"}, {"id": "5"}], "chat_default_model_id": None},
    ],
)
def test_missing_default_becomes_last_listed_model(payload):
    before = dict(payload)
    out, action = transform_chat_default(payload)
    assert action == "last"
    assert out["chat_default_model_id"] == "5"
    assert payload == before  # input not mutated


@pytest.mark.parametrize(
    "payload",
    [
        {"models": [{"id": "3"}, {"id": "5"}], "chat_default_model_id": "3"},
        {"models": []},
        {"models": [], "chat_default_model_id": None},
    ],
)
def test_configured_default_or_empty_list_is_left_alone(payload):
    out, action = transform_chat_default(payload)
    assert action == "skip"
    assert out is payload
