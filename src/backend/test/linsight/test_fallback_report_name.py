from bisheng.linsight.domain.utils import (
    FALLBACK_REPORT_NAME,
    _assign_answer_sections_to_deliverables,
    _section_relevance_score,
    _stem_tokens,
    extract_claimed_deliverable_filename,
    extract_claimed_deliverable_filenames,
)


def test_extract_claimed_filename_from_markdown_link():
    answer = "详见 [output/视频内容摘要.md](output/视频内容摘要.md)。"
    assert extract_claimed_deliverable_filename(answer) == "视频内容摘要.md"


def test_extract_claimed_filename_from_prose():
    answer = "内容已保存至 视频内容摘要.md。"
    assert extract_claimed_deliverable_filename(answer) == "视频内容摘要.md"


def test_extract_claimed_filenames_collects_all_unique():
    answer = (
        "音频：[output/音频转录结果.md](output/音频转录结果.md)\n视频：[output/视频内容摘要.md](output/视频内容摘要.md)"
    )
    assert extract_claimed_deliverable_filenames(answer) == [
        "音频转录结果.md",
        "视频内容摘要.md",
    ]


def test_assign_sections_to_multiple_deliverables():
    answer = (
        "综合摘要如下：\n\n"
        "### **1. 音频文件**\n"
        "乔布斯说了移动设备。\n"
        "交付物：[output/音频转录结果.md](output/音频转录结果.md)\n\n"
        "---\n\n"
        "### **2. 视频文件**\n"
        "索娜 AI 宣传片。\n"
        "交付物：[output/视频内容摘要.md](output/视频内容摘要.md)"
    )
    mapping = _assign_answer_sections_to_deliverables(
        answer,
        ["音频转录结果.md", "视频内容摘要.md"],
    )
    assert "音频转录结果.md" in mapping
    assert "视频内容摘要.md" in mapping
    assert "乔布斯" in mapping["音频转录结果.md"]
    assert "索娜" in mapping["视频内容摘要.md"]
    assert mapping["音频转录结果.md"] != mapping["视频内容摘要.md"]
    assert "交付物" not in mapping["音频转录结果.md"]
    assert "交付物" not in mapping["视频内容摘要.md"]


def test_assign_sections_by_keyword_stem():
    answer = (
        "已综合分析您上传的所有文件内容。\n\n"
        "### **1. 音频文件：乔布斯_副本.MP3**\n"
        "It turns out we have solved it.\n\n"
        "---\n\n"
        "### **2. 视频文件：somna宣传片.mp4**\n"
        "索娜，你的AI同事。\n\n"
        "---\n\n"
        "### **交付物**\n"
        "1. [详细分析报告](output/详细分析报告.md)\n"
        "2. [音频原文对照表](output/音频原文对照表.md)\n"
        "3. [视频台词解析](output/视频台词解析.md)"
    )
    mapping = _assign_answer_sections_to_deliverables(
        answer,
        ["综合摘要.md", "乔布斯_转录.md", "somna解析.md"],
    )
    assert "乔布斯" in mapping["乔布斯_转录.md"] or "solved" in mapping["乔布斯_转录.md"]
    assert "索娜" in mapping["somna解析.md"]
    assert mapping["乔布斯_转录.md"] != mapping["somna解析.md"]
    assert "详细分析报告" not in mapping["乔布斯_转录.md"]
    assert "详细分析报告" not in mapping["somna解析.md"]


def test_extract_claimed_filename_falls_back_when_absent():
    assert extract_claimed_deliverable_filename("你好！") is None
    assert FALLBACK_REPORT_NAME == "报告.md"


# --- section scoring is domain-free -----------------------------------------
# The 3.0 implementation scored sections against a hand-written keyword table
# seeded from one customer demo, so it produced 0 for every other tenant. These
# pin the replacement: overlap between filename-stem tokens and section text.


def test_stem_tokens_splits_latin_and_emits_cjk_bigrams():
    # Chinese writes no word separator, so the run must also yield bigrams —
    # otherwise "季度财报" could only ever match a section quoting all 4 chars.
    tokens = _stem_tokens("acme季度财报")
    assert "acme" in tokens
    assert "季度财报" in tokens
    assert "季度" in tokens and "财报" in tokens
    # Generic words carry no signal and must not score.
    assert "报告" not in _stem_tokens("市场报告")


def test_section_score_prefers_the_section_that_shares_stem_tokens():
    energy = "### 光伏装机\n2025 年新增装机同比增长 18%。"
    battery = "### 储能电池\n磷酸铁锂出货量占比继续提升。"
    assert _section_relevance_score(energy, "光伏装机分析.md") > _section_relevance_score(battery, "光伏装机分析.md")
    assert _section_relevance_score(battery, "储能电池分析.md") > _section_relevance_score(energy, "储能电池分析.md")


def test_section_score_is_not_tied_to_any_particular_domain():
    """Same shape, English + an unrelated field — the old keyword table gave 0."""
    quarterly = "### Quarterly revenue\nRevenue grew 12% year over year."
    hiring = "### Hiring plan\nWe expect to add 40 engineers."
    assert _section_relevance_score(quarterly, "quarterly-revenue.md") > 0
    assert _section_relevance_score(hiring, "quarterly-revenue.md") == 0


def test_exact_filename_mention_still_outranks_token_overlap():
    named = "### 附录\n完整数据见 output/储能电池分析.md。"
    topical = "### 储能电池\n磷酸铁锂出货量占比继续提升。"
    assert _section_relevance_score(named, "储能电池分析.md") > _section_relevance_score(topical, "储能电池分析.md")
