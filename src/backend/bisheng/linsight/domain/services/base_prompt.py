# ruff: noqa: RUF001 - Chinese prompt text, full-width punctuation is intended
"""Task mode's Chinese base prompt, appended to the main graph's system prompt.

Through deepagents 0.6 ``create_deep_agent`` appended its own English
``BASE_AGENT_PROMPT`` after BiSheng's system prompt, and a middleware here
swapped that text for the Chinese one below. Parts of the English text
contradicted task mode: its "Clarifying Requests" rules competed with step 0 of
the main prompt (and invited questions in unattended runs, where step 0 forbids
them), "your first attempt is rarely correct — iterate" added self-check rounds
to runs already dominated by long thinking, and the monitoring/alerting guidance
did not apply. The one useful rule — stop and analyze a repeated failure instead
of retrying it — was in English and ignored when the model read a wrong path
three times on 2026-10-23 (svid 4c85fb69…).

deepagents 0.7 no longer appends a base prompt at all (``BASE`` is empty unless a
``HarnessProfile`` defines one), so there is nothing left to swap: the factory
appends the Chinese text itself, at the position the English one used to hold.

``HarnessProfile.base_system_prompt`` is NOT used: deepagents applies it to every
graph it builds, replacing declarative subagents' ``system_prompt`` outright,
which would erase the researcher's prompt. ``with_base_prompt`` is applied to the
main graph's prompt only, so the researcher keeps its own.
"""

from __future__ import annotations

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


def with_base_prompt(system_prompt: str) -> str:
    """``system_prompt`` followed by the Chinese base prompt."""
    return f"{system_prompt}\n\n{LINSIGHT_BASE_PROMPT_ZH}"
