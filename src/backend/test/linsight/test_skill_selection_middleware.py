"""cofco: every enabled skill is mounted; the picked ones are marked on their 可用技能 rows."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import SystemMessage

from bisheng.linsight.domain.services.skill_selection_middleware import (
    SKILL_SELECTED_NOTE,
    SkillSelectionMiddleware,
    annotate_available_skills,
)

ROWS = (
    "**Skills Skills**: `/skills/`\n- **html-report**: 做网页\n- **bisheng-pptx**: 做 PPT\n- **bisheng-docx**: 做 Word"
)
SKILLS = [{"name": "html-report"}, {"name": "bisheng-pptx"}, {"name": "bisheng-docx"}]


def test_only_picked_rows_get_the_note():
    out = annotate_available_skills(ROWS, SKILLS, {"html-report"})
    lines = out.split("\n")
    assert lines[1].endswith(SKILL_SELECTED_NOTE)
    assert SKILL_SELECTED_NOTE not in lines[2] and SKILL_SELECTED_NOTE not in lines[3]
    assert annotate_available_skills(out, SKILLS, {"html-report"}) == out  # idempotent


def test_a_prefix_name_does_not_mark_its_longer_sibling():
    rows = "- **pptx**: a\n- **pptx-pro**: b"
    out = annotate_available_skills(rows, [{"name": "pptx"}, {"name": "pptx-pro"}], {"pptx"})
    assert out.split("\n")[1] == "- **pptx-pro**: b"


class _Request(SimpleNamespace):
    def override(self, **kw):
        return _Request(**{**self.__dict__, **kw})


def _request(text):
    return _Request(
        state={"skills_metadata": SKILLS}, system_message=SystemMessage(content_blocks=[{"type": "text", "text": text}])
    )


def test_middleware_rewrites_the_system_message():
    seen = {}
    SkillSelectionMiddleware(["bisheng-pptx"]).wrap_model_call(_request(ROWS), lambda r: seen.setdefault("r", r))
    text = seen["r"].system_message.content_blocks[0]["text"]
    assert f"- **bisheng-pptx**: 做 PPT {SKILL_SELECTED_NOTE}" in text


async def test_nothing_picked_leaves_the_request_alone():
    req = _request(ROWS)

    async def handler(r):
        return r

    assert await SkillSelectionMiddleware(None).awrap_model_call(req, handler) is req
