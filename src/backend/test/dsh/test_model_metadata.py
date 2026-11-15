"""Discovery aliases use configured facts only, never arbitrary model secrets."""

from types import SimpleNamespace

import pytest

from bisheng.dsh.domain.schemas.chat import ChatCapabilities
from bisheng.dsh.domain.schemas.reasoning import reasoning_declaration
from bisheng.dsh.domain.services.model_metadata import model_metadata


@pytest.mark.parametrize("custom", [{"context_window": 131072}, '{"context_window": 131072}'])
def test_context_window_from_advanced_config(custom):
    model = SimpleNamespace(model_name=" org/model-v1 ", config={"user_kwargs": custom})
    assert model_metadata(model, ChatCapabilities(vision=True)) == {
        "slug": "org/model-v1",
        "context_window": 131072,
        "input_modalities": ["text", "image"],
    }


@pytest.mark.parametrize("window", [None, True, False, 0, -1, 1.5, "131072", {}, []])
def test_invalid_context_window_is_omitted(window):
    model = SimpleNamespace(config={"user_kwargs": {"context_window": window}})
    assert model_metadata(model, ChatCapabilities()) == {"input_modalities": ["text"]}


@pytest.mark.parametrize("custom", [None, "broken JSON", "[]", "null", [], 7])
def test_invalid_advanced_config_is_optional(custom):
    model = SimpleNamespace(model_name=" ", config={"user_kwargs": custom})
    assert model_metadata(model, ChatCapabilities()) == {"input_modalities": ["text"]}


def test_unknown_window_and_sensitive_fields_are_not_fabricated_or_forwarded():
    model = SimpleNamespace(
        model_name="gpt-4.1",
        config={
            "context_window": 999999,
            "api_key": "SECRET",
            "user_kwargs": {"max_tokens": 8192, "base_instructions": "PRIVATE", "secret": "SECRET"},
        },
    )
    assert model_metadata(model, ChatCapabilities(reasoning_content=True)) == {
        "slug": "gpt-4.1",
        "input_modalities": ["text"],
    }


@pytest.mark.parametrize("default", [None, "high"])
def test_reasoning_aliases_follow_validated_declaration_without_inventing_default(default):
    config = {"user_kwargs": {"reasoning_efforts": [{"id": "high", "name": "Deeper reasoning"}]}}
    if default is not None:
        config["reasoning_effort"] = default
    declaration = reasoning_declaration(config)
    metadata = model_metadata(SimpleNamespace(config=config), ChatCapabilities(reasoning=declaration))
    assert metadata["supported_reasoning_levels"] == [{"effort": "high", "description": "Deeper reasoning"}]
    if default is None:
        assert "default_reasoning_level" not in metadata
    else:
        assert metadata["default_reasoning_level"] == default
