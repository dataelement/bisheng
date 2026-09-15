"""F065: LLMModelCreateReq strips leading/trailing whitespace from model_name."""

import pytest
from pydantic import ValidationError

from bisheng.llm.domain.schemas import LLMModelCreateReq, LLMServerCreateReq


def _model(**overrides) -> LLMModelCreateReq:
    payload = {
        "name": "model 1",
        "model_name": "gpt-4",
        "model_type": "llm",
    }
    payload.update(overrides)
    return LLMModelCreateReq(**payload)


def test_model_name_strips_leading_and_trailing_whitespace():
    model = _model(model_name="  gpt-4  ")
    assert model.model_name == "gpt-4"


def test_model_name_strips_tabs_and_newlines():
    model = _model(model_name="\tgpt-4\n")
    assert model.model_name == "gpt-4"


def test_model_name_keeps_internal_spaces():
    model = _model(model_name=" gpt 4 ")
    assert model.model_name == "gpt 4"


def test_whitespace_only_model_name_is_rejected():
    with pytest.raises(ValidationError):
        _model(model_name="   \t\n  ")


def test_nested_server_request_strips_model_names():
    server = LLMServerCreateReq(
        name="openai",
        type="openai",
        models=[
            LLMModelCreateReq(
                name="model 1",
                model_name="  gpt-4  ",
                model_type="llm",
            )
        ],
    )
    assert server.models[0].model_name == "gpt-4"
