"""F087: create_linsight_agent hands the model's usable input to deepagents.

deepagents reads ``model.profile["max_input_tokens"]`` when it builds the
summarization middleware: present → compress at 85% and keep 10%; absent → the
fixed 170000-token / 6-message defaults (spec AC-08, AC-11, AC-24).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from deepagents.middleware.summarization import compute_summarization_defaults
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

from bisheng.linsight.domain.services import agent_factory
from bisheng.llm.domain.services.context_window import ContextWindowResult


@pytest.fixture
def factory_env(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {"resolve_calls": 0}
    model = GenericFakeChatModel(messages=iter([]))

    def fake_create_deep_agent(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(name="agent")

    from bisheng.core.config.settings import LinsightConf

    monkeypatch.setattr("deepagents.create_deep_agent", fake_create_deep_agent)
    monkeypatch.setattr(agent_factory, "_resolve_model", AsyncMock(return_value=(model, False)))
    monkeypatch.setattr(agent_factory, "settings", SimpleNamespace(get_linsight_conf=lambda: LinsightConf()))

    def set_result(result: ContextWindowResult):
        async def fake_resolve(llm):
            captured["resolve_calls"] += 1
            return result

        monkeypatch.setattr("bisheng.llm.domain.services.context_window.ContextWindowService.resolve", fake_resolve)

    captured["set_result"] = set_result
    captured["model"] = model
    return captured


def _session():
    return SimpleNamespace(id="sv-1", session_id="chat-1", tenant_id=1, user_id=1, question="q", api_meta=None)


async def test_known_window_switches_framework_to_fraction_mode(factory_env):
    factory_env["set_result"](ContextWindowResult(window=133120, kind="total", usable_input=124928, source="deployed"))
    sink: dict = {}

    await agent_factory.create_linsight_agent(_session(), [], context_window_sink=sink)

    model = factory_env["model"]
    assert model.profile == {"max_input_tokens": 124928}
    defaults = compute_summarization_defaults(model)
    assert defaults["trigger"] == ("fraction", 0.85)
    assert defaults["keep"] == ("fraction", 0.1)
    assert sink == {"window": 133120, "kind": "total", "usable_input": 124928, "source": "deployed"}


async def test_researcher_shares_the_main_model(factory_env):
    factory_env["set_result"](ContextWindowResult(window=32768, kind="total", usable_input=32768, source="manual"))

    await agent_factory.create_linsight_agent(_session(), [])

    # No own model: deepagents falls back to the parent's instance, profile included.
    assert all("model" not in spec for spec in factory_env["subagents"])


async def test_unknown_window_keeps_the_framework_defaults(factory_env):
    factory_env["set_result"](ContextWindowResult(window=None, kind=None, usable_input=None, source="unknown"))
    sink: dict = {}

    await agent_factory.create_linsight_agent(_session(), [], context_window_sink=sink)

    model = factory_env["model"]
    assert model.profile is None
    defaults = compute_summarization_defaults(model)
    assert defaults["trigger"] == ("tokens", 170000)
    assert defaults["keep"] == ("messages", 6)
    assert sink["source"] == "unknown"


async def test_every_rebuild_resolves_again(factory_env):
    """Continue, retry and resume after ask_user all rebuild the agent."""
    factory_env["set_result"](ContextWindowResult(window=32768, kind="total", usable_input=32768, source="deployed"))

    for _ in range(3):
        await agent_factory.create_linsight_agent(_session(), [])

    assert factory_env["resolve_calls"] == 3


async def test_window_is_logged(factory_env, caplog):
    from loguru import logger

    factory_env["set_result"](ContextWindowResult(window=32768, kind="total", usable_input=32768, source="deployed"))
    records: list[str] = []
    handler_id = logger.add(lambda message: records.append(str(message)), level="INFO")
    try:
        await agent_factory.create_linsight_agent(_session(), [])
    finally:
        logger.remove(handler_id)

    line = next(r for r in records if "[linsight-context-window]" in r)
    assert "window=32768" in line and "source=deployed" in line and "usable_input=32768" in line
