"""Unit tests for the deepagents prompt-assembly optimization (F035 follow-up):

1. ``_LanguageTailMiddleware`` appends the static Chinese language directive to
   the ABSOLUTE TAIL of the system message (after every framework middleware
   prompt). deepagents' framework middleware (TodoList / Filesystem / SubAgent)
   append their English prompts AFTER the static base, so a HarnessProfile suffix
   lands mid-prompt; only a middleware placed LAST reaches the true tail — the
   strongest position to keep the model reasoning (thinking) in the user's
   language.
2. The current-time block is injected into the dynamic first user message
   (``_build_agent_input`` / ``_drive_continue``), never the static system
   prompt — so the system prompt stays prefix-cacheable.

Pure-function / lightweight-stub style, mirroring ``test_subagent_reintroduction``.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services.agent_factory import (
    _LINSIGHT_LANGUAGE_DIRECTIVE_ZH,
    _LanguageTailMiddleware,
)


class _FakeReq:
    """Minimal ModelRequest stand-in: only ``system_message`` + immutable
    ``override`` are consulted by the middleware (mirrors langchain's real
    ``ModelRequest.override`` which returns a new request)."""

    def __init__(self, system_message: SystemMessage):
        self.system_message = system_message

    def override(self, *, system_message):
        return _FakeReq(system_message)


def test_language_tail_middleware_appends_directive_as_last_block():
    """The directive must be the LAST content block (tail), with prior content
    (the framework prompts) preserved before it."""
    mw = _LanguageTailMiddleware(_LINSIGHT_LANGUAGE_DIRECTIVE_ZH)
    captured: dict = {}

    def handler(req):
        captured["req"] = req
        return "RESP"

    base = SystemMessage("BASE_AND_FRAMEWORK_PROMPTS_HERE")
    out = mw.wrap_model_call(_FakeReq(base), handler)

    assert out == "RESP"
    blocks = captured["req"].system_message.content_blocks
    # our directive is the FINAL block — the absolute tail of the system message
    assert _LINSIGHT_LANGUAGE_DIRECTIVE_ZH in blocks[-1]["text"]
    # everything that was already there is preserved BEFORE our block
    assert any("BASE_AND_FRAMEWORK_PROMPTS_HERE" in b.get("text", "") for b in blocks[:-1])


async def test_language_tail_middleware_async_appends_directive():
    """The async hook (the one the linsight worker actually uses) behaves the same."""
    mw = _LanguageTailMiddleware(_LINSIGHT_LANGUAGE_DIRECTIVE_ZH)
    captured: dict = {}

    async def handler(req):
        captured["req"] = req
        return "RESP"

    out = await mw.awrap_model_call(_FakeReq(SystemMessage("BASE")), handler)

    assert out == "RESP"
    assert _LINSIGHT_LANGUAGE_DIRECTIVE_ZH in captured["req"].system_message.content_blocks[-1]["text"]


def test_language_tail_middleware_registers_no_tools_and_has_stable_name():
    mw = _LanguageTailMiddleware(_LINSIGHT_LANGUAGE_DIRECTIVE_ZH)
    assert mw.tools == []
    assert mw.name == "LinsightLanguageTail"


def test_language_directive_constrains_thinking_with_top_priority():
    """The directive must explicitly cover thinking/reasoning and assert top
    priority over the preceding (English) framework prompts."""
    assert "thinking" in _LINSIGHT_LANGUAGE_DIRECTIVE_ZH
    assert "推理过程" in _LINSIGHT_LANGUAGE_DIRECTIVE_ZH
    assert "最高优先级" in _LINSIGHT_LANGUAGE_DIRECTIVE_ZH


class _FakeSession:
    question = "帮我写一份新能源行业研究报告"


def test_current_time_block_format():
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    block = LinsightWorkflowTask._current_time_block()
    assert block.startswith("# 当前时间")
    assert "周" in block  # weekday rendered


def test_build_agent_input_includes_time_and_question():
    from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

    out = LinsightWorkflowTask._build_agent_input(_FakeSession(), file_list=None)
    content = out["messages"][0]["content"]
    assert "# 当前时间" in content
    assert _FakeSession.question in content
