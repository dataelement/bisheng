from bisheng.linsight.domain.utils import (
    FALLBACK_REPORT_NAME,
    _assign_answer_sections_to_deliverables,
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
