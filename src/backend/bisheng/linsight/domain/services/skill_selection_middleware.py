"""Mark the skills the user picked on the 可用技能 rows (cofco).

Every governance-enabled skill is mounted on every run (skill_provisioning), so
the picker no longer decides which skills exist in the workspace. What the user
picked still matters to the model: this middleware appends a short note to each
picked skill's row in the system prompt. It is a slim port of the release line's
``agent_factory.SkillSelectionMiddleware`` (selection note only; cofco has no
personal skills, tool declarations or skill snapshot to guard).

Sits after deepagents' ``SkillsMiddleware``, which writes the rows from
``skills_metadata``; this one only edits them and never reads ``SKILL.md``.
"""

from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import SystemMessage

# Appended to a 可用技能 row. Not written into SKILL.md. Same wording as the release line.
SKILL_SELECTED_NOTE = "用户选中了这个技能"


def annotate_available_skills(text: str, skills: list[dict], selected: set[str]) -> str:
    """Append the selection note onto the rows of picked skills (``- **name**:``)."""
    names = [s.get("name") for s in skills if s.get("name") in selected]
    if not names:
        return text
    lines = []
    for line in text.split("\n"):
        for name in names:
            if f"- **{name}**:" in line and SKILL_SELECTED_NOTE not in line:
                line = f"{line} {SKILL_SELECTED_NOTE}"
                break
        lines.append(line)
    return "\n".join(lines)


class SkillSelectionMiddleware(AgentMiddleware):
    def __init__(self, selected_names: list[str] | None) -> None:
        super().__init__()
        self.tools = []
        self._selected = set(selected_names or [])

    @property
    def name(self) -> str:
        return "LinsightSkillSelection"

    def _rewrite(self, request):
        state = getattr(request, "state", None)
        skills = (state.get("skills_metadata") if isinstance(state, dict) else None) or []
        system_message = getattr(request, "system_message", None)
        if not self._selected or not skills or system_message is None:
            return request
        blocks, changed = [], False
        for block in system_message.content_blocks:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if not isinstance(text, str):
                blocks.append(block)
                continue
            rewritten = annotate_available_skills(text, skills, self._selected)
            if rewritten == text:
                blocks.append(block)
                continue
            changed = True
            blocks.append(
                {**block, "text": rewritten} if isinstance(block, dict) else {"type": "text", "text": rewritten}
            )
        if not changed:
            return request
        return request.override(system_message=SystemMessage(content_blocks=blocks))

    def wrap_model_call(self, request, handler):
        return handler(self._rewrite(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._rewrite(request))
