"""F005 AC-07: the main-graph prompt tells the model to trust check_html's per-page
measurement and to edit locally, in every prompt variant that offers the file tools."""

from __future__ import annotations

import pytest

from bisheng.linsight.domain.services.agent_factory import _build_linsight_system_prompt
from bisheng.tool.domain.langchain.linsight_html_check import CheckHtmlTool


@pytest.mark.parametrize("has_kb", [False, True])
@pytest.mark.parametrize("skills_present", [False, True])
def test_prompt_requires_measured_pages_and_local_edits(has_kb, skills_present):
    prompt = _build_linsight_system_prompt(has_kb, skills_present=skills_present)
    assert "以 check_html 的逐页测量为准，不要在思考里估算像素高度" in prompt
    assert "只修改报告列出的溢出页，没列出的页不要再改" in prompt
    assert "old_string 取能唯一定位的最短片段" in prompt
    assert "改 <style> 里的 CSS 规则，不要逐页改 HTML 正文" in prompt


def test_tool_description_advertises_per_page_measurement():
    assert "逐页测量" in CheckHtmlTool().description
