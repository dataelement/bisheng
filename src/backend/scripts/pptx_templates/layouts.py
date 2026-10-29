"""Common prototype layouts shared by every built-in template.

Each function draws one prototype slide on a ``SlideBuilder``. Geometry is in
points on a 960×540 canvas. Theme differences live in the page chrome
(``light_page`` / ``dark_page``) and in the theme tokens, so the layouts stay
identical in structure across templates.
"""

from __future__ import annotations

from builder import SlideBuilder

M = 48.0  # outer margin
RIGHT = 912.0  # SLIDE_W - M
CW = RIGHT - M  # content width
TOP = 118.0  # content area top on light pages
FOOT_Y = 492.0

SAMPLE_ORG = "示例单位 · 文稿名称"


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------


def light_page(b: SlideBuilder, title: str | None, kicker: str = "01 · 示例章节") -> None:
    """Content-page frame: background, theme marker, kicker, title, footer."""
    t = b.theme
    b.background(t.bg)
    kicker_x = title_x = M
    if t.marker == "sidebar":
        b.rect("deco.sidebar", 0, 0, 14, 540, fill=t.primary)
    elif t.marker == "block" and title is not None:
        b.rect("deco.marker", M, 56, 6, 30, fill=t.primary)
        kicker_x = title_x = M + 16
    elif t.marker == "dot":
        b.oval("deco.marker", M, 34, 8, 8, fill=t.accent)
        kicker_x = M + 14
    elif t.marker == "tab":
        b.rect("deco.marker", M, 24, 28, 3, fill=t.accent)
    b.text(
        "kicker",
        kicker_x,
        30,
        520,
        16,
        kicker,
        size=11,
        color=t.accent if t.marker != "rule" else t.secondary,
        bold=True,
        role="label",
    )
    if title is not None:
        b.text(
            "title",
            title_x,
            50,
            RIGHT - title_x,
            40,
            title,
            size=26,
            color=t.text if t.all_dark else t.primary,
            bold=True,
            font="title",
            role="title",
            anchor="middle",
        )
    if t.marker == "rule":
        b.hline("deco.rule", M, 100, CW, t.line)
    footer(b)


def footer(b: SlideBuilder, on_dark: bool = False) -> None:
    t = b.theme
    color = t.on_dark_muted if on_dark else t.muted
    b.text("footer", M, FOOT_Y + 2, 560, 16, SAMPLE_ORG, size=10, color=color, role="footer")
    b.page_number("deco.page", RIGHT - 60, FOOT_Y, 60, 16, 10, color)


def dark_page(b: SlideBuilder, variant: str = "cover") -> None:
    """Cover / section / closing canvas with the theme's signature decoration."""
    t = b.theme
    bg = t.primary if t.marker == "sidebar" and variant != "cover" else t.dark_bg
    b.background(bg)
    if t.marker == "block":  # 红韵: concentric gold rings on the right
        b.oval("deco.ring1", 580, 50, 360, 360, line=t.secondary, line_w=1.5)
        b.oval("deco.ring2", 650, 120, 220, 220, line=t.secondary, line_w=0.75)
    elif t.marker == "rule":  # 蓝图: faint drafting grid
        grid = "2A5182"
        for i, x in enumerate(range(96, 960, 96)):
            b.vline(f"deco.gv{i}", x, 0, 540, grid, 0.5)
        for i, y in enumerate((135, 270, 405)):
            b.hline(f"deco.gh{i}", 0, y, 960, grid, 0.5)
    elif t.marker == "tab":  # 经营: navy panel with a light side
        b.rect("deco.side", 600, 0, 360, 540, fill=t.surface)
    elif t.marker == "dot":  # 深空: two soft glows
        b.oval("deco.glow1", 520, 24, 420, 420, fill=t.secondary, alpha=0.22)
        b.oval("deco.glow2", 700, 236, 240, 240, fill=t.accent, alpha=0.16)
    elif t.marker == "sidebar":  # 课堂: green panel on a light page / outline ring on green
        if variant == "cover":
            b.rect("deco.panel", 0, 0, 320, 540, fill=t.primary)
        else:
            b.oval("deco.ring1", 600, 80, 340, 340, line=t.secondary, line_w=1.5)


# ---------------------------------------------------------------------------
# Opening and closing
# ---------------------------------------------------------------------------


def cover(b: SlideBuilder) -> None:
    t = b.theme
    dark_page(b, "cover")
    if t.marker == "sidebar":  # 课堂: text on the light right side
        b.background(t.bg)
        b.text("badge", M, 64, 224, 22, "培训课程", size=14, color=t.on_dark_muted, bold=True, role="label")
        b.text("speaker", M, 426, 240, 20, "讲师：示例姓名", size=14, color=t.on_dark, role="label")
        b.text("duration", M, 452, 240, 18, "时长：示例 90 分钟", size=12, color=t.on_dark_muted, role="label")
        x, w = 372.0, 540.0
        b.text("kicker", x, 150, w, 20, "示例 · 新员工入职培训", size=14, color=t.accent, bold=True, role="label")
        b.text(
            "title",
            x,
            180,
            w,
            130,
            "示例：用一句话说清这门课要解决的问题",
            size=38,
            color=t.primary,
            bold=True,
            font="title",
            role="title",
        )
        b.text(
            "subtitle", x, 326, w, 50, "示例：副标题写清对象、范围或学习收获", size=18, color=t.muted, role="subtitle"
        )
        b.text("org", x, 466, w, 20, "示例单位名称", size=14, color=t.text, role="label")
        b.text("date", x, 490, w, 18, "2026 年 10 月", size=12, color=t.muted, role="label")
        return

    x = 72.0
    width = {"block": 480.0, "tab": 480.0}.get(t.marker, 620.0)
    kicker_color = (
        t.secondary if t.marker == "block" else (t.accent if t.marker in ("dot", "rule") else t.on_dark_muted)
    )
    b.text(
        "kicker", x, 118, width, 20, "示例 · 2026 年度工作汇报", size=13, color=kicker_color, bold=True, role="label"
    )
    if t.marker in ("rule", "tab"):
        b.rect("deco.tab", x, 146, 44, 5, fill=t.accent)
    b.text(
        "title",
        x,
        162,
        width,
        130,
        "示例：主标题写一句核心判断或文稿名称",
        size=44,
        color=t.on_dark,
        bold=True,
        font="title",
        role="title",
    )
    b.text(
        "subtitle",
        x,
        306,
        width,
        52,
        "示例：副标题补充范围、时间或汇报对象",
        size=18,
        color=t.on_dark_muted,
        role="subtitle",
    )
    if t.marker == "block":  # 红韵: gold band carrying the organisation line
        b.rect("deco.band", 0, 456, 960, 84, fill=t.secondary)
        b.text("org", x, 484, 520, 22, "示例单位名称", size=14, color=t.dark_bg, bold=True, role="label")
        b.text("date", 700, 484, 188, 22, "2026 年 10 月", size=13, color=t.dark_bg, align="right", role="label")
    else:
        b.text("org", x, 462, 520, 20, "示例单位名称", size=14, color=t.on_dark, role="label")
        b.text("date", x, 488, 520, 18, "2026 年 10 月", size=12, color=t.on_dark_muted, role="label")
    if t.marker == "tab":  # 经营: one headline figure on the light side
        b.text("highlight.number", 640, 196, 280, 80, "36.8%", size=60, color=t.primary, bold=True, role="number")
        b.text(
            "highlight.label",
            640,
            282,
            280,
            44,
            "示例：一项最能代表本期结论的指标",
            size=14,
            color=t.muted,
            role="caption",
        )


def agenda(b: SlideBuilder) -> None:
    t = b.theme
    b.background(t.bg)
    if t.marker == "sidebar":
        b.rect("deco.sidebar", 0, 0, 14, 540, fill=t.primary)
    b.text("kicker", M, 128, 300, 18, "CONTENTS", size=12, color=t.accent, bold=True, role="label")
    b.text(
        "title",
        M,
        150,
        320,
        60,
        "目录",
        size=40,
        color=t.text if t.all_dark else t.primary,
        bold=True,
        font="title",
        role="title",
    )
    items = ["示例：经营概况", "示例：重点工作进展", "示例：问题与原因分析", "示例：下一步计划", "示例：需协调事项"]
    x, y0, row = 420.0, 112.0, 70.0
    for i, label in enumerate(items, start=1):
        y = y0 + (i - 1) * row
        b.text(f"item{i}.no", x, y + 8, 60, 36, f"{i:02d}", size=26, color=t.accent, bold=True, role="number")
        b.text(f"item{i}.text", x + 72, y + 14, RIGHT - x - 72, 28, label, size=18, color=t.text, role="body")
        b.hline(f"item{i}.rule", x, y + row - 6, RIGHT - x, t.line)
    footer(b)


def section(b: SlideBuilder) -> None:
    t = b.theme
    dark_page(b, "section")
    number_color = t.secondary if t.marker in ("block", "sidebar") else t.accent
    if t.marker == "sidebar":
        number_color = t.accent
    b.text("no", 72, 150, 300, 110, "01", size=88, color=number_color, bold=True, role="number")
    b.text("title", 72, 270, 640, 60, "示例：章节标题", size=34, color=t.on_dark, bold=True, font="title", role="title")
    b.text(
        "subtitle",
        72,
        340,
        640,
        50,
        "示例：一句话说明本章要回答的问题",
        size=17,
        color=t.on_dark_muted,
        role="subtitle",
    )
    footer(b, on_dark=True)


def statement(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, None, kicker="01 · 核心观点")
    b.rect("deco.quote", M, 134, 40, 5, fill=t.accent)
    b.text(
        "statement",
        M,
        156,
        800,
        160,
        "示例：用一句完整的话写出本页结论，让听众不看其他内容也能带走它",
        size=34,
        color=t.text,
        bold=True,
        font="title",
        role="title",
        line_spacing=1.25,
    )
    b.text(
        "support",
        M,
        336,
        660,
        84,
        "示例：用一两句话交代支撑这个判断的事实、数据或依据。",
        size=16,
        color=t.muted,
        role="body",
        line_spacing=1.3,
    )
    b.text("source", M, 470, 640, 14, "示例来源：填写数据或材料出处", size=10, color=t.muted, role="caption")


def closing(b: SlideBuilder) -> None:
    t = b.theme
    dark_page(b, "closing")
    b.text("title", 72, 190, 640, 70, "感谢聆听", size=44, color=t.on_dark, bold=True, font="title", role="title")
    b.text("subtitle", 72, 272, 640, 40, "示例：恳请各位领导批评指正", size=18, color=t.on_dark_muted, role="subtitle")
    b.text("contact", 72, 440, 640, 40, "示例单位 · 联系人 · 联系方式", size=13, color=t.on_dark_muted, role="caption")


# ---------------------------------------------------------------------------
# Content layouts
# ---------------------------------------------------------------------------


def two_column(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：图文页的标题写本页结论")
    b.text(
        "lead",
        M,
        TOP + 4,
        400,
        56,
        "示例：先用一句加粗的话点题，再展开要点。",
        size=18,
        color=t.text,
        bold=True,
        role="subtitle",
    )
    b.text(
        "body",
        M,
        TOP + 74,
        400,
        260,
        [
            "示例要点一：写事实或做法，一行一个要点",
            "示例要点二：数字要带单位和期间",
            "示例要点三：最多五条，放不下就拆页",
        ],
        size=15,
        color=t.text,
        bullets=True,
        role="body",
        line_spacing=1.3,
    )
    b.image_area("image", 480, TOP, 432, 344)


def _card(b: SlideBuilder, prefix: str, x, y, w, h, number, title, body, title_size=18, body_size=14):
    t = b.theme
    fill = t.surface
    line = t.line if t.card_border else None
    b.rect(f"{prefix}.bg", x, y, w, h, fill=fill, line=line, radius=t.card_radius)
    b.text(f"{prefix}.no", x + 24, y + 22, 80, 34, number, size=26, color=t.accent, bold=True, role="number")
    b.text(
        f"{prefix}.title",
        x + 24,
        y + 66,
        w - 48,
        52 if h > 200 else 26,
        title,
        size=title_size,
        color=t.text,
        bold=True,
        role="subtitle",
    )
    body_y = y + (126 if h > 200 else 98)
    b.text(
        f"{prefix}.body",
        x + 24,
        body_y,
        w - 48,
        y + h - body_y - 18,
        body,
        size=body_size,
        color=t.muted,
        role="body",
        line_spacing=1.3,
    )


def cards_3(b: SlideBuilder) -> None:
    light_page(b, "示例：三个并列要点的总标题")
    b.text(
        "lead",
        M,
        TOP,
        CW,
        24,
        "示例：一句话说明这三点之间的关系或共同指向。",
        size=15,
        color=b.theme.muted,
        role="subtitle",
    )
    gap = 24.0
    w = (CW - 2 * gap) / 3
    for i in range(3):
        _card(
            b,
            f"card{i + 1}",
            M + i * (w + gap),
            TOP + 52,
            w,
            250,
            f"{i + 1:02d}",
            f"示例：要点{'一二三'[i]}的小标题",
            "示例：两三句话说明做了什么、带来什么变化，最好有一个数字。",
        )


def cards_4(b: SlideBuilder) -> None:
    light_page(b, "示例：四项工作或四个维度的总标题")
    gap = 20.0
    w = (CW - gap) / 2
    h = 168.0
    for i in range(4):
        r, c = divmod(i, 2)
        _card(
            b,
            f"card{i + 1}",
            M + c * (w + gap),
            TOP + r * (h + gap),
            w,
            h,
            f"{i + 1:02d}",
            f"示例：维度{'一二三四'[i]}",
            "示例：一两句话写清现状与成效。",
            body_size=14,
        )


def kpi_4(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：用四个关键指标概括本期成绩")
    gap = 24.0
    w = (CW - 3 * gap) / 4
    samples = [
        ("128.6", "亿元", "营业收入"),
        ("12.4%", "同比", "增长率"),
        ("36", "个", "新签项目"),
        ("98.7%", "全年", "交付准时率"),
    ]
    for i, (num, unit, label) in enumerate(samples):
        x = M + i * (w + gap)
        if i:
            b.vline(f"kpi{i + 1}.rule", x - gap / 2, TOP + 40, 200, t.line)
        b.text(
            f"kpi{i + 1}.number",
            x,
            TOP + 36,
            w,
            64,
            num,
            size=44,
            color=t.accent if t.all_dark else t.primary,
            bold=True,
            role="number",
        )
        b.text(f"kpi{i + 1}.unit", x, TOP + 104, w, 20, f"示例单位：{unit}", size=12, color=t.muted, role="caption")
        b.text(
            f"kpi{i + 1}.label", x, TOP + 136, w, 26, f"示例：{label}", size=16, color=t.text, bold=True, role="label"
        )
        b.text(
            f"kpi{i + 1}.note",
            x,
            TOP + 168,
            w,
            64,
            "示例：一句话说明口径或变化原因",
            size=12,
            color=t.muted,
            role="caption",
            line_spacing=1.3,
        )
    b.rect("takeaway.bg", M, 384, CW, 60, fill=t.surface, radius=t.card_radius)
    b.text(
        "takeaway.text",
        M + 20,
        384,
        CW - 40,
        60,
        "示例：一句话解读这组数字说明了什么。",
        size=15,
        color=t.text,
        bold=True,
        role="body",
        anchor="middle",
    )
    b.text("source", M, 456, CW, 14, "示例来源：填写数据口径与出处", size=10, color=t.muted, role="caption")


def chart_insight(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：图表页的标题直接写出数据结论")
    b.chart(
        "chart",
        M,
        TOP,
        560,
        330,
        ["2022", "2023", "2024", "2025", "2026E"],
        [("示例：营业收入（亿元）", (82.1, 95.4, 108.7, 121.3, 136.0))],
    )
    px = M + 584
    pw = RIGHT - px
    b.rect("insight.bg", px, TOP, pw, 330, fill=t.surface, radius=t.card_radius)
    b.text(
        "insight.title",
        px + 20,
        TOP + 22,
        pw - 40,
        50,
        "示例：读图要点",
        size=18,
        color=t.text,
        bold=True,
        role="subtitle",
    )
    b.text(
        "insight.body",
        px + 20,
        TOP + 76,
        pw - 40,
        230,
        ["示例：拐点或异常出现在哪里", "示例：原因是什么", "示例：意味着什么、要做什么"],
        size=14,
        color=t.text,
        bullets=True,
        role="body",
        line_spacing=1.35,
    )
    b.text("source", M, 458, 560, 14, "示例来源：填写数据口径与出处", size=10, color=t.muted, role="caption")


def compare(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：对比页的标题写出取舍结论")
    gap = 24.0
    w = (CW - gap) / 2
    for i, (side, head, color) in enumerate(
        (("left", "示例：方案 A / 改革前", t.secondary), ("right", "示例：方案 B / 改革后", t.primary))
    ):
        x = M + i * (w + gap)
        b.rect(f"{side}.bg", x, TOP, w, 280, fill=t.surface, radius=t.card_radius)
        b.rect(f"{side}.head", x, TOP, w, 46, fill=color)
        b.text(
            f"{side}.title",
            x + 20,
            TOP,
            w - 40,
            46,
            head,
            size=17,
            color="FFFFFF" if not t.all_dark else t.dark_bg,
            bold=True,
            role="subtitle",
            anchor="middle",
        )
        b.text(
            f"{side}.body",
            x + 20,
            TOP + 64,
            w - 40,
            196,
            ["示例：对比维度一的表现", "示例：对比维度二的表现", "示例：对比维度三的表现"],
            size=14,
            color=t.text,
            bullets=True,
            role="body",
            line_spacing=1.35,
        )
    b.rect(
        "conclusion.bg",
        M,
        414,
        CW,
        52,
        fill=t.surface if t.all_dark else t.bg,
        line=t.accent,
        line_w=1.25,
        radius=t.card_radius,
    )
    b.text(
        "conclusion.text",
        M + 20,
        414,
        CW - 40,
        52,
        "示例结论：在什么条件下选哪一个，理由是什么。",
        size=15,
        color=t.text,
        bold=True,
        role="body",
        anchor="middle",
    )


def process(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：流程页的标题说明整体做法")
    gap = 32.0
    w = (CW - 3 * gap) / 4
    for i in range(4):
        x = M + i * (w + gap)
        n = i + 1
        b.oval(f"step{n}.dot", x, TOP + 16, 52, 52, fill=t.primary if not t.all_dark else t.secondary)
        b.text(
            f"step{n}.no",
            x,
            TOP + 16,
            52,
            52,
            f"{n}",
            size=20,
            color="FFFFFF" if not t.all_dark else t.text,
            bold=True,
            align="center",
            anchor="middle",
            role="number",
        )
        if i:
            b.hline(f"step{n}.link", x - gap - w + 64, TOP + 42, w + gap - 76, t.line, 1.5)
        b.rect(f"step{n}.bg", x, TOP + 88, w, 210, fill=t.surface, radius=t.card_radius)
        b.text(
            f"step{n}.title",
            x + 18,
            TOP + 106,
            w - 36,
            50,
            f"示例：第{'一二三四'[i]}步",
            size=17,
            color=t.text,
            bold=True,
            role="subtitle",
        )
        b.text(
            f"step{n}.body",
            x + 18,
            TOP + 162,
            w - 36,
            120,
            "示例：这一步做什么、谁负责、产出什么。",
            size=13,
            color=t.muted,
            role="body",
            line_spacing=1.35,
        )


def timeline(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：时间轴页的标题写出发展主线")
    axis_y = 236.0
    b.hline("deco.axis", M, axis_y, CW, t.line, 2.0)
    n = 5
    slot_w = CW / n
    for i in range(n):
        k = i + 1
        cx = M + i * slot_w
        b.oval(f"node{k}.dot", cx + 4, axis_y - 7, 14, 14, fill=t.accent)
        b.text(
            f"node{k}.time",
            cx,
            axis_y - 60,
            slot_w - 16,
            30,
            f"{2022 + i}",
            size=22,
            color=t.primary if not t.all_dark else t.accent,
            bold=True,
            role="number",
        )
        b.text(
            f"node{k}.title",
            cx,
            axis_y + 24,
            slot_w - 16,
            48,
            "示例：关键事件",
            size=15,
            color=t.text,
            bold=True,
            role="subtitle",
        )
        b.text(
            f"node{k}.body",
            cx,
            axis_y + 76,
            slot_w - 16,
            150,
            "示例：一两句话说明意义或成果。",
            size=12,
            color=t.muted,
            role="body",
            line_spacing=1.35,
        )


def table(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：表格页的标题写出需要关注的结论")
    header = ["示例：事项", "责任单位", "完成时限", "进展"]
    rows = [
        ["示例：重点任务一", "示例部门", "2026-12", "已完成"],
        ["示例：重点任务二", "示例部门", "2026-12", "推进中"],
        ["示例：重点任务三", "示例部门", "2027-03", "推进中"],
        ["示例：重点任务四", "示例部门", "2027-06", "未启动"],
    ]
    b.table("table", M, TOP, CW, header, rows, col_widths=[3.2, 2.2, 1.6, 1.4], row_h=40)
    b.text(
        "note",
        M,
        TOP + 40 * 5 + 18,
        CW,
        40,
        "示例：表下说明一句需要领导关注或协调的事项。",
        size=13,
        color=t.muted,
        role="caption",
    )


# layout_id, family, display name, use_for, draw function
COMMON_LAYOUTS = [
    ("cover", "cover", "封面", "文稿开头；主标题写核心判断或文稿名称", cover),
    ("agenda", "agenda", "目录", "4–5 个章节的目录", agenda),
    ("section", "section", "章节页", "章节过渡，一句话交代本章问题", section),
    ("statement", "statement", "观点页", "一句结论加一段依据，用于关键判断", statement),
    ("two-column", "two-column", "图文两栏", "左侧要点、右侧照片或截图", two_column),
    ("cards-3", "cards", "三卡片", "三个并列的举措、成果或特点", cards_3),
    ("cards-4", "cards", "四卡片", "四个维度或四项工作", cards_4),
    ("kpi-4", "kpi", "关键指标", "3–4 个关键数字加一句解读", kpi_4),
    ("chart-insight", "chart", "图表加解读", "一张趋势或对比图，右侧写读图结论", chart_insight),
    ("compare", "compare", "对比", "两个方案、改革前后、我们与对标的对比", compare),
    ("process", "process", "流程", "3–4 个有先后顺序的步骤", process),
    ("timeline", "timeline", "时间轴", "3–5 个时间节点的历程或计划", timeline),
    ("table", "table", "表格", "任务清单、责任分工、多维对照", table),
    ("closing", "closing", "结尾页", "致谢与联系方式", closing),
]
