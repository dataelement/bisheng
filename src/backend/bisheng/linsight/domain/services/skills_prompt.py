# ruff: noqa: RUF001 - Chinese prompt text, full-width punctuation is intended
"""Chinese skills section for task mode, replacing deepagents' English template.

deepagents' ``SKILLS_SYSTEM_PROMPT`` told the model where each SKILL.md lives but
not where the paths written INSIDE it are rooted. A SKILL.md lists its supporting
files relatively (``references/rules.md``); the model joined them onto the
workspace root (``/references/rules.md``), got "not found" three times in a row
on 2026-10-23 (svid 4c85fb69…), and redid a 30k-character analysis after each
miss. The template also carried text that does not apply here: a doubled
"Skills Skills" label, the "Deepagents / Agents" source legend, and a
web-research example for a skill that does not exist.

Two framework hooks are overridden. The skill rows keep the ``- **<name>**:``
prefix, which ``annotate_available_skills`` matches to append its notes.
"""

from __future__ import annotations

from deepagents.middleware.skills import SkillMetadata, SkillsMiddleware, _format_skill_annotations

LINSIGHT_SKILLS_HEADING = "可用技能"

LINSIGHT_SKILLS_PROMPT_ZH = (
    "## 技能\n\n"
    "本次任务可以使用下面列出的技能。{skills_locations}{skills_load_warnings}\n\n"
    f"**{LINSIGHT_SKILLS_HEADING}：**\n\n"
    "{skills_list}\n\n"
    "**使用方法：**\n\n"
    "1. 对照每个技能的描述，判断它是否与任务匹配。\n"
    "2. 匹配时，用 read_file 读取它的 SKILL.md，传 limit=1000 一次读完，再按其中的步骤执行。\n"
    "3. SKILL.md 里写的相对路径（如 references/rules.md、scripts/run.py）都以该技能自己的目录为根。"
    "读取时写成完整路径 /skills/<技能名>/references/rules.md；"
    "工作区根目录下的 /references/rules.md 并不存在。"
)


class LinsightSkillsMiddleware(SkillsMiddleware):
    """deepagents' ``SkillsMiddleware`` with the Chinese section above."""

    def __init__(self, *, backend, sources) -> None:
        super().__init__(backend=backend, sources=sources, system_prompt=LINSIGHT_SKILLS_PROMPT_ZH)

    @property
    def name(self) -> str:
        # langgraph names graph nodes after the middleware (``SkillsMiddleware.before_agent``).
        # A task parked before this change resumes from a checkpoint holding those names.
        return "SkillsMiddleware"

    def _format_skills_locations(self) -> str:
        roots = "、".join(f"`{source.rstrip('/')}/<技能名>/`" for source in self.sources)
        return (
            f"每个技能是 {roots} 下的一个目录：SKILL.md 写明做法，"
            "同一目录里可能还有 references/、scripts/、assets/ 等配套文件。"
        )

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        if not skills:
            return "（当前没有可用的技能）"
        lines = []
        for skill in skills:
            row = f"- **{skill['name']}**: {skill['description']}"
            if annotations := _format_skill_annotations(skill):
                row += f" ({annotations})"
            lines.append(row)
            if skill["allowed_tools"]:
                lines.append(f"  -> 需要的工具：{', '.join(skill['allowed_tools'])}")
            lines.append(f"  -> 完整说明：`{skill['path']}`")
        return "\n".join(lines)
