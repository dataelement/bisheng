"""Template-specific prototype layouts (one or two per template)."""

from __future__ import annotations

from builder import SlideBuilder
from layouts import CW, RIGHT, TOP, M, light_page

# ---------------------------------------------------------------------------
# 蓝图 blueprint
# ---------------------------------------------------------------------------


def architecture(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：总体架构分四层，自下而上支撑业务")
    names = ["示例：应用层", "示例：服务层", "示例：数据层", "示例：基础设施"]
    label_w, gap, row_h, row_gap = 150.0, 12.0, 78.0, 10.0
    comp_x = M + label_w + 16
    comp_w = (RIGHT - comp_x - 2 * gap) / 3
    for i, name in enumerate(names, start=1):
        y = TOP + (i - 1) * (row_h + row_gap)
        b.rect(f"layer{i}.box", M, y, label_w, row_h, fill=t.primary)
        b.text(
            f"layer{i}.name",
            M + 12,
            y,
            label_w - 24,
            row_h,
            name,
            size=15,
            color="FFFFFF",
            bold=True,
            align="center",
            anchor="middle",
            role="label",
        )
        for k in range(1, 4):
            x = comp_x + (k - 1) * (comp_w + gap)
            b.rect(f"layer{i}.c{k}bg", x, y, comp_w, row_h, fill=t.surface, line=t.line)
            b.text(
                f"layer{i}.c{k}",
                x + 12,
                y,
                comp_w - 24,
                row_h,
                f"示例：组件{'一二三'[k - 1]}",
                size=13,
                color=t.text,
                align="center",
                anchor="middle",
                role="label",
            )


def risk_register(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：主要风险可控，两项需要重点盯防")
    cols = [("等级", M, 60), ("风险", M + 84, 280), ("应对措施", M + 388, 320), ("责任人", M + 732, CW - 732)]
    for label, x, w in cols:
        b.text(f"deco.h{x:.0f}", x, TOP, w, 18, label, size=11, color=t.muted, bold=True, role="label", slot=False)
    b.hline("deco.head", M, TOP + 26, CW, t.secondary, 1.25)
    row_h = 78.0
    for i in range(1, 5):
        y = TOP + 34 + (i - 1) * row_h
        b.rect(f"risk{i}.pill", M, y + 14, 48, 24, fill=t.accent, radius=0.5)
        b.text(
            f"risk{i}.level",
            M,
            y + 14,
            48,
            24,
            "高" if i < 3 else "中",
            size=12,
            color="FFFFFF",
            bold=True,
            align="center",
            anchor="middle",
            role="label",
        )
        b.text(
            f"risk{i}.title",
            M + 84,
            y + 10,
            280,
            24,
            f"示例：风险事项{'一二三四'[i - 1]}",
            size=15,
            color=t.text,
            bold=True,
            role="subtitle",
        )
        b.text(
            f"risk{i}.desc", M + 84, y + 38, 280, 32, "示例：触发条件与可能影响", size=12, color=t.muted, role="caption"
        )
        b.text(
            f"risk{i}.measure",
            M + 388,
            y + 10,
            320,
            56,
            "示例：具体应对措施与验证标准",
            size=13,
            color=t.text,
            role="body",
            line_spacing=1.3,
        )
        b.text(f"risk{i}.owner", M + 732, y + 10, CW - 732, 24, "示例部门", size=13, color=t.text, role="label")
        b.hline(f"risk{i}.rule", M, y + row_h - 2, CW, t.line)


# ---------------------------------------------------------------------------
# 经营 operating
# ---------------------------------------------------------------------------


def scorecard(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：五项指标四项达标，回款率需要关注")
    header = ["示例：指标", "目标", "实际", "完成率", "说明"]
    rows = [
        ["营业收入（亿元）", "120.0", "128.6", "107%", "示例：超额完成"],
        ["净利润（亿元）", "10.0", "10.8", "108%", "示例：结构优化"],
        ["回款率", "95%", "86%", "91%", "示例：两个大项目延期付款"],
        ["新签合同（亿元）", "150.0", "162.3", "108%", "示例：新签大单两项"],
        ["安全生产事故", "0", "0", "达标", "示例：全年无事故"],
    ]
    b.table("table", M, TOP, CW, header, rows, col_widths=[2.6, 1.2, 1.2, 1.2, 3.0], row_h=40, highlight_rows=(2,))
    b.rect("alert.bg", M, TOP + 40 * 6 + 16, CW, 52, fill=t.surface)
    b.rect("alert.flag", M, TOP + 40 * 6 + 16, 6, 52, fill=t.accent)
    b.text(
        "alert.text",
        M + 22,
        TOP + 40 * 6 + 16,
        CW - 40,
        52,
        "示例：异常说明——哪一项没达标、原因、补救动作和时间。",
        size=14,
        color=t.text,
        bold=True,
        anchor="middle",
        role="body",
    )


def bridge(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：收入增长主要来自销量，汇率拖累 1.6 亿元")
    b.chart(
        "chart",
        M,
        TOP,
        580,
        330,
        ["2025 收入", "价格", "销量", "结构", "汇率", "2026 收入"],
        [("示例：收入变动（亿元）", (100.0, 8.5, 12.3, -4.2, -1.6, 115.0))],
        kind="waterfall",
        number_format="0.0",
    )
    px = M + 604
    pw = RIGHT - px
    b.rect("insight.bg", px, TOP, pw, 330, fill=t.surface)
    b.text(
        "insight.title",
        px + 20,
        TOP + 22,
        pw - 40,
        50,
        "示例：对账结论",
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
        ["示例：起点加各项贡献等于终点", "示例：最大正向贡献及原因", "示例：最大拖累及应对"],
        size=14,
        color=t.text,
        bullets=True,
        role="body",
        line_spacing=1.35,
    )
    b.text("source", M, 458, 580, 14, "示例来源：填写数据口径与出处", size=10, color=t.muted, role="caption")


# ---------------------------------------------------------------------------
# 课堂 classroom
# ---------------------------------------------------------------------------


def objectives(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：本节课的学习目标与内容安排")
    b.rect("obj.bg", M, TOP, 320, 340, fill=t.primary, radius=t.card_radius)
    b.text("obj.title", M + 24, TOP + 24, 272, 28, "学习目标", size=18, color="FFFFFF", bold=True, role="subtitle")
    b.text(
        "obj.items",
        M + 24,
        TOP + 68,
        272,
        250,
        ["示例：能说出制度的三条核心要求", "示例：能判断常见场景是否合规", "示例：知道遇到问题找谁"],
        size=14,
        color=t.on_dark_muted,
        bullets=True,
        role="body",
        line_spacing=1.4,
    )
    x = M + 352
    w = RIGHT - x
    b.text("outline.title", x, TOP + 4, w, 28, "本节内容", size=18, color=t.primary, bold=True, role="subtitle")
    b.text(
        "outline.items",
        x,
        TOP + 46,
        w,
        190,
        ["示例：为什么要有这项制度", "示例：三条核心要求逐条讲解", "示例：典型案例分析", "示例：随堂自测"],
        size=15,
        color=t.text,
        bullets=True,
        role="body",
        line_spacing=1.45,
    )
    b.rect("tip.bg", x, TOP + 258, w, 82, fill=t.surface, radius=t.card_radius)
    b.text(
        "tip.text",
        x + 20,
        TOP + 258,
        w - 40,
        82,
        "示例：学完本节，你可以独立完成一次合规自查。",
        size=14,
        color=t.text,
        bold=True,
        anchor="middle",
        role="body",
    )


def quiz(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：随堂自测，检验一下是否掌握")
    row_h = 104.0
    for i in range(1, 4):
        y = TOP + (i - 1) * (row_h + 12)
        b.rect(f"q{i}.bg", M, y, CW, row_h, fill=t.surface, radius=t.card_radius)
        b.text(f"q{i}.no", M + 20, y + 16, 50, 30, f"Q{i}", size=20, color=t.accent, bold=True, role="number")
        b.text(
            f"q{i}.stem",
            M + 80,
            y + 16,
            CW - 110,
            30,
            f"示例：第{'一二三'[i - 1]}道题的题干写在这里？",
            size=15,
            color=t.text,
            bold=True,
            role="subtitle",
        )
        b.text(
            f"q{i}.options",
            M + 80,
            y + 54,
            CW - 110,
            36,
            "A. 示例选项　B. 示例选项　C. 示例选项　D. 示例选项",
            size=13,
            color=t.muted,
            role="body",
        )
    b.text(
        "hint",
        M,
        TOP + 3 * (row_h + 12) + 4,
        CW,
        16,
        "示例：参考答案见演讲者备注",
        size=11,
        color=t.muted,
        role="caption",
    )


# ---------------------------------------------------------------------------
# 红韵 gov-red
# ---------------------------------------------------------------------------


def honor_wall(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：近三年获得的主要荣誉与成果")
    gap = 20.0
    w = (CW - 2 * gap) / 3
    h = 160.0
    for i in range(6):
        r, c = divmod(i, 3)
        x = M + c * (w + gap)
        y = TOP + r * (h + gap)
        k = i + 1
        b.rect(f"honor{k}.bg", x, y, w, h, fill=t.surface)
        b.oval(f"honor{k}.badge", x + 20, y + 22, 56, 56, fill=t.secondary)
        b.text(
            f"honor{k}.year",
            x + 20,
            y + 22,
            56,
            56,
            "2025",
            size=12,
            color=t.primary,
            bold=True,
            align="center",
            anchor="middle",
            role="number",
        )
        b.text(
            f"honor{k}.title",
            x + 92,
            y + 24,
            w - 112,
            52,
            "示例：荣誉或成果名称",
            size=16,
            color=t.text,
            bold=True,
            role="subtitle",
        )
        b.text(
            f"honor{k}.org",
            x + 20,
            y + 96,
            w - 40,
            44,
            "示例：颁发单位或成果说明",
            size=12,
            color=t.muted,
            role="caption",
            line_spacing=1.3,
        )


# ---------------------------------------------------------------------------
# 深空 tech-dark
# ---------------------------------------------------------------------------


def feature_hero(b: SlideBuilder) -> None:
    t = b.theme
    light_page(b, "示例：产品亮点的总标题")
    b.image_area("image", M, TOP, 500, 340, label="示例：产品界面截图或主视觉")
    x = M + 532
    w = RIGHT - x
    b.text(
        "headline",
        x,
        TOP,
        w,
        70,
        "示例：一句话讲清产品最打动人的价值",
        size=22,
        color=t.text,
        bold=True,
        role="subtitle",
        line_spacing=1.25,
    )
    for i in range(1, 4):
        y = TOP + 92 + (i - 1) * 84
        b.oval(f"feat{i}.dot", x, y + 6, 10, 10, fill=t.accent)
        b.text(
            f"feat{i}.title",
            x + 22,
            y,
            w - 22,
            24,
            f"示例：亮点{'一二三'[i - 1]}",
            size=15,
            color=t.text,
            bold=True,
            role="label",
        )
        b.text(
            f"feat{i}.body",
            x + 22,
            y + 28,
            w - 22,
            44,
            "示例：一句话说明它解决了什么问题。",
            size=12,
            color=t.muted,
            role="caption",
            line_spacing=1.3,
        )


SPECIAL_LAYOUTS = {
    "blueprint": [
        ("architecture", "architecture", "分层架构", "系统或组织的分层结构，自下而上", architecture),
        ("risk-register", "risk", "风险登记", "主要风险、等级、应对措施与责任人", risk_register),
    ],
    "operating": [
        ("scorecard", "table", "指标计分表", "多项指标的目标与完成情况，突出异常行", scorecard),
        ("bridge", "chart", "贡献对账", "起点到终点的变化拆解（瀑布图）", bridge),
    ],
    "classroom": [
        ("objectives", "objectives", "学习目标", "课程开头的学习目标与内容安排", objectives),
        ("quiz", "quiz", "随堂自测", "2–3 道自测题", quiz),
    ],
    "gov-red": [
        ("honor-wall", "cards", "荣誉成果", "荣誉、奖项或标志性成果的陈列", honor_wall),
    ],
    "tech-dark": [
        ("feature-hero", "two-column", "产品亮点", "左侧产品主视觉、右侧三个亮点", feature_hero),
    ],
}
