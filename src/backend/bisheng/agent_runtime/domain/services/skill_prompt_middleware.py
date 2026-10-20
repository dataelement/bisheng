# The prompt text is Chinese for the model; its full-width punctuation is intended.
# ruff: noqa: RUF001
"""Skill rules appended to the agent's system prompt (F078 design decision 11).

The author's own prompt is never changed; these rules are appended after it on
every model call. The text is distilled from task mode's skill lines without the
task-mode placeholders (ask_user, export_*, numbered steps).

Two variants match what the run can do:

- ``WITH_EXECUTOR``: a code executor is bound, so a skill's scripts can run;
- ``NO_EXECUTOR``: no executor, so the model follows the skill as far as text allows.
"""

from __future__ import annotations

from enum import StrEnum

from langchain.agents.middleware import AgentMiddleware

_COMMON_RULES = """# 技能使用规则

- 系统提示中的「Available Skills」列出了本次可用的技能。动手前先对照每个技能的描述判断是否与任务匹配；一旦匹配，必须先用 read_file 读完它的 SKILL.md（传 limit=1000 一次读完），再按它的指引执行。不要把“读 SKILL.md”和“产出结果”放进同一轮并行工具调用，否则技能内容返回时结果已经生成，等于没读。
- 技能文件位于 /skills/<技能名>/，只读，不要修改。
- 用户提供的文件在 /uploads/。"""

_WITH_EXECUTOR_RULES = """- 交付给用户的文件一律写到 /output/。需要修改用户的文件时，把修改后的结果另存到 /output/，不要覆盖 /uploads/ 里的原件。
- 技能规定了生成文件的脚本或库时，用 bisheng_code_interpreter 按技能的做法生成成品，直接写进 output/。
- bisheng_code_interpreter 的当前工作目录就是工作区根，代码里用不带前导斜杠的相对路径，例如 open("skills/<技能名>/assets/t.docx")、保存到 "output/报告.docx"。
- 代码执行结果 exitcode 为 0 且 file_list 中出现目标文件，就视为已经产出，不要反复 ls 查找。
- 完成后在回复中简要说明生成了哪些文件。"""

_NO_EXECUTOR_RULES = """- 本次没有可用的代码执行工具，技能中需要执行脚本的做法无法落地。请按技能说明尽量完成，用 write_file 把结果写到 /output/，并在回复中说明技能脚本未能执行。
- 需要修改用户的文件时，把结果另存到 /output/，不要覆盖 /uploads/ 里的原件。"""


class SkillPromptVariant(StrEnum):
    WITH_EXECUTOR = "with_executor"
    NO_EXECUTOR = "no_executor"


_VARIANT_RULES = {
    SkillPromptVariant.WITH_EXECUTOR: _WITH_EXECUTOR_RULES,
    SkillPromptVariant.NO_EXECUTOR: _NO_EXECUTOR_RULES,
}


def skill_rules_text(variant: SkillPromptVariant) -> str:
    return f"{_COMMON_RULES}\n{_VARIANT_RULES[variant]}"


class SkillPromptMiddleware(AgentMiddleware):
    """Append the skill rules to the system message on every model call.

    Static text keeps the assembled system message identical across calls, so it
    stays prefix-cacheable. Registers no tools.
    """

    def __init__(self, variant: SkillPromptVariant) -> None:
        super().__init__()
        self.tools = []
        self._text = skill_rules_text(variant)

    @property
    def name(self) -> str:
        return "AgentSkillPrompt"

    def _append(self, request):
        from deepagents.middleware._utils import append_to_system_message

        return request.override(system_message=append_to_system_message(request.system_message, self._text))

    def wrap_model_call(self, request, handler):
        return handler(self._append(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._append(request))
