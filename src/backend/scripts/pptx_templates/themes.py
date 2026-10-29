"""Theme tokens for the built-in task-mode PPT templates.

One ``Theme`` per template. Colors are hex strings without ``#``. ``light`` pages
(agenda / content) and ``dark`` pages (cover / section / closing) read different
token pairs so every layout function can stay theme-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    scenes: str
    mood: str
    primary: str
    secondary: str
    accent: str
    # light (content) pages
    bg: str
    surface: str
    text: str
    muted: str
    line: str
    # dark (cover / section / closing) pages
    dark_bg: str
    on_dark: str
    on_dark_muted: str
    # typography
    title_font: str = "微软雅黑"
    body_font: str = "微软雅黑"
    latin_font: str = "Arial"
    # shape language
    card_radius: float = 0.0  # 0 = square corners; otherwise the rounded-rect adjust value
    card_border: bool = False
    marker: str = "block"  # header marker: block | rule | tab | dot | sidebar
    all_dark: bool = False  # content pages on a dark canvas too
    extra_layouts: tuple = field(default_factory=tuple)


GOV_RED = Theme(
    id="gov-red",
    name="红韵",
    scenes="央国企与党政机关的年度工作汇报、集团宣传、党建与主题活动材料",
    mood="庄重、稳健；封面与章节页红底金饰，内容页白底",
    primary="8B1A2B",
    secondary="C9A84C",
    accent="A8232F",
    bg="FFFFFF",
    surface="F8F3EC",
    text="2B2B2B",
    muted="6B6B6B",
    line="E6DDD0",
    dark_bg="8B1A2B",
    on_dark="FFFFFF",
    on_dark_muted="F0D9B5",
    title_font="黑体",
    marker="block",
)

BLUEPRINT = Theme(
    id="blueprint",
    name="蓝图",
    scenes="项目方案、技术方案、可行性研究、电力与基建工程汇报",
    mood="理性、工程感；深蓝封面配细网格，内容页白底细分隔线，琥珀色点出重点",
    primary="123A6B",
    secondary="2E6DA4",
    accent="E39A2D",
    bg="FFFFFF",
    surface="EEF3F9",
    text="24303F",
    muted="5F6B7A",
    line="D5DEE8",
    dark_bg="123A6B",
    on_dark="FFFFFF",
    on_dark_muted="B8C9DE",
    card_border=True,
    marker="rule",
)

OPERATING = Theme(
    id="operating",
    name="经营",
    scenes="管理层经营分析、月度/季度数据汇报、金融与投资分析",
    mood="克制、数据优先；藏青为主，香槟金只用于关键数字",
    primary="1B2A4A",
    secondary="44618C",
    accent="B8955A",
    bg="FFFFFF",
    surface="F3F5F8",
    text="20293A",
    muted="66707F",
    line="DADFE6",
    dark_bg="1B2A4A",
    on_dark="FFFFFF",
    on_dark_muted="C3CCDA",
    marker="tab",
)

TECH_DARK = Theme(
    id="tech-dark",
    name="深空",
    scenes="产品发布、数字化与 AI 方案、科技公司介绍",
    mood="现代、科技感；全篇深色画布，青绿色高亮，圆角卡片",
    primary="35D0BA",
    secondary="4C7BD9",
    accent="35D0BA",
    bg="121C2E",
    surface="1B2943",
    text="EAF0F8",
    muted="93A5C0",
    line="2C3D5C",
    dark_bg="0D1524",
    on_dark="EAF0F8",
    on_dark_muted="93A5C0",
    card_radius=0.08,
    marker="dot",
    all_dark=True,
)

CLASSROOM = Theme(
    id="classroom",
    name="课堂",
    scenes="培训课件、制度宣贯、新员工入职培训、工作坊",
    mood="清新、易读；墨绿与麦金，圆角卡片，左侧色条串起全篇",
    primary="1E4D3B",
    secondary="6FA287",
    accent="C98F2E",
    bg="F7F9F6",
    surface="E6EFE8",
    text="223129",
    muted="5E6E64",
    line="D3DFD6",
    dark_bg="1E4D3B",
    on_dark="FFFFFF",
    on_dark_muted="CFE3D6",
    card_radius=0.06,
    marker="sidebar",
)

THEMES = [GOV_RED, BLUEPRINT, OPERATING, TECH_DARK, CLASSROOM]
