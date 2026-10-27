
"""deepagents' English base prompt is swapped for the Chinese one on the main graph."""

from __future__ import annotations

import inspect

import pytest
from deepagents.graph import BASE_AGENT_PROMPT
from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services import base_prompt
from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt, create_linsight_agent
from bisheng.linsight.domain.services.base_prompt import LINSIGHT_BASE_PROMPT_ZH, LinsightBasePromptMiddleware


class _Request:
    def __init__(self, system_message):
        self.system_message = system_message

    def override(self, **kwargs):
        return _Request(kwargs.get("system_message", self.system_message))


def _texts(message) -> list[str]:
    return [block["text"] for block in message.content_blocks if block.get("text")]


def _assembled(main_prompt: str) -> SystemMessage:
    # create_deep_agent: USER + "\n\n" + BASE, then framework middleware append blocks.
    return SystemMessage(
        content_blocks=[
            {"type": "text", "text": f"{main_prompt}\n\n{BASE_AGENT_PROMPT}"},
            {"type": "text", "text": "\n\n## `write_todos`"},
        ]
    )


def test_base_prompt_is_replaced_and_the_rest_is_kept():
    request = _Request(_assembled("主提示词"))
    shown = LinsightBasePromptMiddleware().wrap_model_call(request, lambda item: item)
    texts = _texts(shown.system_message)

    assert texts[0] == f"主提示词\n\n{LINSIGHT_BASE_PROMPT_ZH}"
    assert texts[1] == "\n\n## `write_todos`"
    assert "You are a deep agent" not in "".join(texts)


async def test_async_hook_replaces_too():
    async def handler(item):
        return item

    shown = await LinsightBasePromptMiddleware().awrap_model_call(_Request(_assembled("主提示词")), handler)
    assert LINSIGHT_BASE_PROMPT_ZH in "".join(_texts(shown.system_message))


def test_missing_base_prompt_leaves_the_request_and_warns_once(monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(base_prompt.logger, "warning", warnings.append)
    middleware = LinsightBasePromptMiddleware()
    request = _Request(SystemMessage(content="只有主提示词"))

    assert middleware.wrap_model_call(request, lambda item: item) is request
    middleware.wrap_model_call(request, lambda item: item)
    assert len(warnings) == 1


@pytest.mark.parametrize("unattended", [False, True])
def test_step_zero_the_question_rule_points_at_exists(unattended):
    prompt = _build_linsight_system_prompt(True, unattended=unattended)
    assert "\n0. 【" in prompt


def test_only_the_main_graph_gets_the_middleware():
    source = inspect.getsource(create_linsight_agent)
    assert source.count("LinsightBasePromptMiddleware()") == 1
    assert source.index("LinsightBasePromptMiddleware()") < source.index('researcher["middleware"]')
