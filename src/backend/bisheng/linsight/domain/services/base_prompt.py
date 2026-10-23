# ruff: noqa: RUF001 - Chinese prompt text, full-width punctuation is intended
"""Swap deepagents' English base prompt for task mode's Chinese one, main graph only.

``create_deep_agent`` appends ``BASE_AGENT_PROMPT`` right after BiSheng's own
system prompt. Parts of it contradict task mode: its "Clarifying Requests" rules
compete with step 0 of the main prompt (and invite questions in unattended runs,
where step 0 forbids them), "your first attempt is rarely correct — iterate"
adds self-check rounds to runs already dominated by long thinking, and the
monitoring/alerting guidance does not apply. The one useful rule — stop and
analyze a repeated failure instead of retrying it — was in English and ignored
when the model read a wrong path three times on 2026-10-23 (svid 4c85fb69…).

``HarnessProfile.base_system_prompt`` is NOT used: deepagents applies it to every
graph it builds, replacing declarative subagents' ``system_prompt`` outright,
which would erase the researcher's prompt. This middleware edits only the main
graph's request, so the researcher keeps its own.
"""

from __future__ import annotations

from deepagents.graph import BASE_AGENT_PROMPT
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import SystemMessage
from loguru import logger

LINSIGHT_BASE_PROMPT_ZH = (
    "# 基本要求\n\n"
    "- 简洁直接，不写客套开场，不预告“我现在要做 X”，直接做。\n"
    "- 以准确为先：用户的判断有误时如实指出，不附和、不堆砌赞美。\n"
    "- 一直做到任务完成再结束，不要做到一半停下来描述打算怎么做。\n\n"
    "# 出错时\n\n"
    "- 同一个操作连续失败时，先停下来分析失败原因，再换做法；不要用同样的参数重试。\n"
    "- 读文件报 not found 时，先确认路径的根目录是否正确，必要时用 ls 查看。\n\n"
    "# 向用户提问\n\n"
    "- 是否向用户提问、何时提问，以上文第 0 步为准。"
)


class LinsightBasePromptMiddleware(AgentMiddleware):
    """Replace ``BASE_AGENT_PROMPT`` in the system message with ``LINSIGHT_BASE_PROMPT_ZH``."""

    def __init__(self) -> None:
        super().__init__()
        self.tools = []
        self._warned = False

    @property
    def name(self) -> str:
        return "LinsightBasePrompt"

    def _replace(self, request):
        system_message = request.system_message
        if system_message is None:
            return request
        blocks = []
        replaced = False
        for block in system_message.content_blocks:
            text = block.get("text") if isinstance(block, dict) else None
            if isinstance(text, str) and BASE_AGENT_PROMPT in text:
                blocks.append({**block, "text": text.replace(BASE_AGENT_PROMPT, LINSIGHT_BASE_PROMPT_ZH)})
                replaced = True
            else:
                blocks.append(block)
        if not replaced:
            # Only a deepagents upgrade that reworded the base prompt gets here; the
            # run continues on the English text, so say so once instead of per turn.
            if not self._warned:
                logger.warning("[linsight-base-prompt] BASE_AGENT_PROMPT not found in the system message; left as is")
                self._warned = True
            return request
        return request.override(system_message=SystemMessage(content_blocks=blocks))

    def wrap_model_call(self, request, handler):
        return handler(self._replace(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._replace(request))
