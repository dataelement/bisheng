"""Generate the gov-red PPTD reference project of the PPT skill (deck.pptd + 12 pages).

    python scripts/pptd_templates/gen_gov_red.py bisheng/linsight/builtin_skills/bisheng-pptx/templates/gov-red/source-zh

Rerun after editing, then check with the PPTD engine (see pptd_runtime/README.md) and look at a
render of every page. Colours must stay in step with html-report's gov-red theme
(test_html_slides.py::test_gov_red_palette_matches_the_pptx_gov_red_template).
"""

import os
import sys

import yaml

OUT = sys.argv[1]
FONT = {"latin": "Arial", "ea": "Microsoft YaHei"}
W, H = 960, 540
M = 48  # outer margin

COLORS = {
    "red": "#8B1A2B",
    "deepred": "#6E1422",
    "accent": "#A8232F",
    "gold": "#C9A84C",
    "lightgold": "#E8D6A0",
    "surface": "#F8F3EC",
    "white": "#FFFFFF",
    "ink": "#2B2B2B",
    "muted": "#6B6B6B",
    "rule": "#E3D6C3",
}


def ts(size, color="$ink", bold=False, lh=1.3, align=("left", "top")):
    d = {"fontFamily": FONT, "fontSize": size, "color": color, "lineHeight": lh, "align": list(align)}
    if bold:
        d["bold"] = True
    return d


TEXT_STYLES = {
    "title": ts(26, "$red", True, 1.15),
    "lead": ts(15, "$ink", True, 1.3),
    "body": ts(13, "$ink", False, 1.4),
    "label": ts(12, "$muted", False, 1.3),
    "meta": ts(10, "$muted", False, 1.2),
    "kicker": ts(11, "$gold", True, 1.2),
}
TABLE_STYLES = {
    "gov-table": {
        "cellStyle": {
            "fontFamily": FONT,
            "fontSize": 12,
            "color": "$ink",
            "fill": {"type": "solid", "color": "$white"},
            "border": {"color": "$rule", "width": 0.8},
        },
        "firstRowStyle": {"bold": True, "color": "$white", "fill": {"type": "solid", "color": "$red"}},
    }
}


def rect(eid, x, y, w, h, color, line=None, lw=0, shape="rect"):
    return {
        "elementId": eid,
        "elementType": "shape",
        "bounds": [x, y, w, h],
        "shapeName": shape,
        "fill": {"type": "solid", "color": color} if color else {"type": "solid", "color": "#FFFFFF00"},
        "border": {"color": line or color or "#FFFFFF00", "width": lw},
    }


def hline(eid, x, y, w, color="$rule", width=0.8):
    return {
        "elementId": eid,
        "elementType": "line",
        "bounds": [x, y, w, 1],
        "viewBox": [w, 1],
        "points": f"0,0 {w},0",
        "border": {"color": color, "width": width},
    }


def vline(eid, x, y, h, color="$rule", width=0.8):
    return {
        "elementId": eid,
        "elementType": "line",
        "bounds": [x, y, 1, h],
        "viewBox": [1, h],
        "points": f"0,0 0,{h}",
        "border": {"color": color, "width": width},
    }


def text(eid, x, y, w, h, t, style=None, **kw):
    c = {"text": t}
    if style:
        c["style"] = "$" + style
    c.update(kw)
    if "fontSize" in kw or "color" in kw or "bold" in kw:
        c.setdefault("fontFamily", FONT)
    return {"elementId": eid, "elementType": "text", "bounds": [x, y, w, h], "content": c}


def chrome(no, title, kicker):
    """Content-page frame: red top rule, title, gold underline, footer."""
    return [
        rect("top-band", 0, 0, W, 8, "$red"),
        rect("top-gold", 0, 8, W, 2, "$gold"),
        text("kicker", M, 28, 600, 16, kicker, "kicker"),
        text("title", M, 46, W - 2 * M, 36, title, "title"),
        rect("title-mark", M, 88, 56, 3, "$gold"),
        hline("footer-rule", M, 502, W - 2 * M, "$rule", 0.8),
        text("footer-org", M, 508, 500, 16, "示例单位 · 2026 年度工作汇报", "meta"),
        text("footer-no", W - M - 60, 508, 60, 16, f"{no:02d}", "meta", align=["right", "top"]),
    ]


pages = []

# 01 cover
pages.append(
    {
        "pageType": "cover",
        "background": {"type": "solid", "color": "$red"},
        "elements": [
            rect("cover-deep", 0, 380, W, 160, "$deepred"),
            rect("cover-gold-top", M, 64, W - 2 * M, 2, "$gold"),
            rect("cover-gold-top2", M, 70, W - 2 * M, 0.8, "$gold"),
            text("cover-kicker", M, 104, 700, 20, "示例 · 2026 年度工作汇报", "kicker", fontSize=13),
            text(
                "cover-title",
                M,
                136,
                W - 2 * M,
                122,
                "坚持稳中求进\n推动高质量发展取得新成效",
                "title",
                fontSize=48,
                color="$white",
            ),
            text(
                "cover-sub",
                M,
                270,
                W - 2 * M,
                48,
                "2026 年度工作总结与 2027 年重点工作安排",
                "lead",
                fontSize=20,
                color="$lightgold",
                bold=False,
            ),
            rect("cover-gold-bottom", M, 404, 120, 3, "$gold"),
            text(
                "cover-org", M, 420, 600, 24, "示例集团有限公司 党委", "lead", fontSize=16, color="$white", bold=False
            ),
            text("cover-date", M, 450, 400, 20, "2026 年 12 月", "label", fontSize=14, color="$lightgold"),
        ],
    }
)

# 02 agenda
items = [("01", "年度工作总体情况"), ("02", "重点任务完成情况"), ("03", "存在的问题与不足"), ("04", "2027 年工作安排")]
els = [
    rect("agenda-panel", 0, 0, 320, H, "$red"),
    rect("agenda-gold", 320, 0, 4, H, "$gold"),
    text("agenda-title", M, 190, 240, 56, "目  录", "title", fontSize=40, color="$white"),
    text("agenda-en", M, 254, 240, 20, "CONTENTS", "kicker", fontSize=14),
]
for i, (no, t) in enumerate(items):
    y = 120 + i * 84
    els += [
        text(f"agenda-no-{i + 1}", 380, y, 70, 44, no, "title", fontSize=32, color="$gold"),
        text(f"agenda-item-{i + 1}", 460, y + 6, 420, 32, t, "lead", fontSize=20),
        hline(f"agenda-rule-{i + 1}", 380, y + 56, 520),
    ]
pages.append({"pageType": "agenda", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 03 section
pages.append(
    {
        "pageType": "section",
        "background": {"type": "solid", "color": "$red"},
        "elements": [
            rect("section-deep", 0, 0, 300, H, "$deepred"),
            text("section-no", 60, 196, 200, 120, "01", "title", fontSize=96, color="$gold"),
            rect("section-gold", 340, 230, 80, 3, "$gold"),
            text("section-title", 340, 248, 560, 50, "年度工作总体情况", "title", fontSize=36, color="$white"),
            text(
                "section-desc",
                340,
                310,
                560,
                48,
                "经营指标全面完成，改革发展质量稳步提升",
                "body",
                fontSize=16,
                color="$lightgold",
            ),
        ],
    }
)

# 04 KPI
kpis = [
    ("营业收入", "386.2", "亿元", "同比增长 8.6%，完成年度目标的 103%"),
    ("利润总额", "42.7", "亿元", "同比增长 11.2%，增速高于收入 2.6 个百分点"),
    ("研发投入强度", "3.4", "%", "较上年提高 0.5 个百分点"),
    ("安全生产事故", "0", "起", "连续 5 年未发生较大及以上事故"),
]
els = chrome(4, "主要经营指标全面完成，利润增速高于收入增速", "一、年度工作总体情况")
cw, gap = 204, 16
for i, (lab, num, unit, note) in enumerate(kpis):
    x = M + i * (cw + gap)
    els += [
        rect(f"kpi-card-{i + 1}", x, 118, cw, 210, "$surface"),
        rect(f"kpi-bar-{i + 1}", x, 118, cw, 4, "$red"),
        text(f"kpi-label-{i + 1}", x + 16, 136, cw - 32, 20, lab, "label", fontSize=13),
        text(f"kpi-num-{i + 1}", x + 16, 166, cw - 70, 56, num, "title", fontSize=40),
        text(f"kpi-unit-{i + 1}", x + cw - 60, 188, 44, 24, unit, "label", fontSize=14),
        hline(f"kpi-rule-{i + 1}", x + 16, 236, cw - 32),
        text(f"kpi-note-{i + 1}", x + 16, 248, cw - 32, 64, note, "body", fontSize=12),
    ]
els += [
    rect("kpi-insight-band", M, 350, W - 2 * M, 120, "$white", "$rule", 0.8),
    rect("kpi-insight-mark", M, 350, 4, 120, "$gold"),
    text("kpi-insight-head", M + 20, 364, 300, 22, "总体判断", "lead"),
    text(
        "kpi-insight-body",
        M + 20,
        392,
        W - 2 * M - 40,
        64,
        "规模与效益同步提升，利润增速连续两年高于收入增速，说明结构调整开始见效；研发投入强度首次超过 3%，为下一阶段转型打下基础。（示例数据，不代表事实）",
        "body",
    ),
]
pages.append({"pageType": "evidence", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 05 chart + insight
els = chrome(5, "营业收入五年增长 46%，新兴业务贡献过半增量", "一、年度工作总体情况")
els += [
    {
        "elementId": "rev-chart",
        "elementType": "chart",
        "bounds": [M, 112, 540, 330],
        "data": {
            "cols": ["year", "base", "new"],
            "rows": [
                ["2022", 238, 26],
                ["2023", 249, 41],
                ["2024", 258, 62],
                ["2025", 268, 87.6],
                ["2026", 276, 110.2],
            ],
        },
        "series": [
            {
                "type": "bar",
                "name": "传统业务",
                "encode": {"x": "year", "y": "base"},
                "fill": "$red",
                "dataLabels": {"show": False},
            },
            {
                "type": "bar",
                "name": "新兴业务",
                "encode": {"x": "year", "y": "new"},
                "fill": "$gold",
                "dataLabels": {"show": False},
            },
        ],
        "xAxis": {"label": {"fontSize": 11, "color": "$muted"}, "gridLine": False},
        "yAxis": {
            "min": 0,
            "label": {"fontSize": 10, "color": "$muted"},
            "gridLine": {"color": "$rule", "style": "dot"},
        },
        "legend": {"show": True, "position": "top", "fontSize": 11},
        "fontFamily": FONT,
        "fill": {"type": "solid", "color": "#FFFFFF00"},
        "border": {"color": "#FFFFFF00", "width": 0},
    },
    text("rev-unit", M, 446, 400, 16, "单位：亿元；数据为示例", "meta"),
    vline("rev-divider", 616, 120, 320),
    text("rev-h1", 640, 122, 272, 22, "增量主要来自新兴业务", "lead"),
    text("rev-b1", 640, 148, 272, 72, "新兴业务收入由 26 亿元增至 110.2 亿元，五年累计贡献收入增量的 69%。", "body"),
    text("rev-h2", 640, 232, 272, 22, "传统业务保持稳定", "lead"),
    text("rev-b2", 640, 258, 272, 72, "传统业务年均增长 3.8%，继续承担现金流与就业稳定的基础作用。", "body"),
    text("rev-h3", 640, 342, 272, 22, "下一步关注", "lead"),
    text(
        "rev-b3",
        640,
        368,
        272,
        72,
        "新兴业务毛利率仍低于传统业务 4 个百分点，需要在规模扩张中同步提升盈利质量。",
        "body",
    ),
]
pages.append({"pageType": "evidence", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 06 table
rows = [
    ["重点任务", "年度目标", "完成情况", "状态"],
    ["国企改革深化提升行动", "完成 3 项改革任务", "3 项全部完成，经验在系统内推广", "已完成"],
    ["科技创新平台建设", "新增 2 个省级平台", "新增省级研发中心 2 个、实验室 1 个", "超额完成"],
    ["数字化转型", "核心业务系统上线", "主体上线，供应链模块延期至一季度", "基本完成"],
    ["安全生产专项整治", "隐患整改率 100%", "排查隐患 1,286 项，整改 1,286 项", "已完成"],
    ["人才队伍建设", "引进高层次人才 30 名", "引进 34 名，培养青年骨干 120 名", "超额完成"],
]
els = chrome(6, "五项重点任务四项完成，数字化转型一个模块延期", "二、重点任务完成情况")
els += [
    {
        "elementId": "task-table",
        "elementType": "table",
        "bounds": [M, 112, W - 2 * M, 316],
        "style": "$gov-table",
        "columnWidths": [0.24, 0.2, 0.42, 0.14],
        "rowHeights": [0.14] + [0.172] * 5,
        "rows": [[{"text": c} for c in r] for r in rows],
    },
    rect("task-note-mark", M, 444, 4, 40, "$gold"),
    text(
        "task-note",
        M + 16,
        444,
        W - 2 * M - 16,
        40,
        "延期原因：供应链模块需与上游供应商系统对接，接口标准年内未统一；已明确 2027 年一季度上线。",
        "body",
        fontSize=12,
    ),
]
pages.append({"pageType": "evidence", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 07 timeline
steps = [
    ("一季度", "改革方案获批", "完成三项制度改革方案报批，明确责任分工"),
    ("二季度", "平台挂牌运行", "省级研发中心挂牌，首批 12 个项目立项"),
    ("三季度", "系统主体上线", "核心业务系统切换，覆盖 9 家二级单位"),
    ("四季度", "专项整治收官", "隐患整改全部闭环，通过上级验收"),
]
els = chrome(7, "全年工作按季度推进，关键节点全部按期达成", "二、重点任务完成情况")
els += [hline("tl-axis", M + 20, 206, W - 2 * M - 40, "$red", 2)]
sw = (W - 2 * M) / 4
for i, (q, h, d) in enumerate(steps):
    x = M + i * sw
    els += [
        rect(f"tl-dot-{i + 1}", x + 20, 198, 16, 16, "$gold", "$red", 2, "ellipse"),
        text(f"tl-q-{i + 1}", x + 20, 140, sw - 30, 28, q, "title", fontSize=20),
        text(f"tl-h-{i + 1}", x + 20, 236, sw - 36, 24, h, "lead"),
        text(f"tl-d-{i + 1}", x + 20, 266, sw - 36, 80, d, "body"),
    ]
els += [
    rect("tl-band", M, 380, W - 2 * M, 72, "$surface"),
    text(
        "tl-band-text",
        M + 20,
        394,
        W - 2 * M - 40,
        48,
        "全年 16 个关键节点中 15 个按期完成，1 个延期并已制定补救计划。（示例）",
        "lead",
        bold=False,
    ),
]
pages.append({"pageType": "process", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 09 matrix 2x3
cards = [
    ("党的建设", "开展主题教育 48 场，基层党支部全部达标"),
    ("深化改革", "完成三项制度改革，任期制和契约化管理全覆盖"),
    ("科技创新", "新增发明专利 86 件，研发投入 13.1 亿元"),
    ("安全环保", "单位产值能耗下降 4.2%，零较大事故"),
    ("人才建设", "引进高层次人才 34 名，培养青年骨干 120 名"),
    ("民生保障", "职工收入增长 6.5%，办实事项目 26 项"),
]
els = chrome(8, "六个方面协同发力，形成全年工作合力", "二、重点任务完成情况")
cw, ch = (W - 2 * M - 32) / 3, 160
for i, (h, d) in enumerate(cards):
    x = M + (i % 3) * (cw + 16)
    y = 116 + (i // 3) * (ch + 16)
    els += [
        rect(f"mx-card-{i + 1}", x, y, cw, ch, "$surface"),
        rect(f"mx-mark-{i + 1}", x, y, 4, ch, "$red"),
        text(f"mx-no-{i + 1}", x + 20, y + 16, 60, 30, f"{i + 1:02d}", "title", fontSize=22, color="$gold"),
        text(f"mx-h-{i + 1}", x + 20, y + 52, cw - 40, 26, h, "lead", fontSize=17, color="$red"),
        text(f"mx-d-{i + 1}", x + 20, y + 84, cw - 40, 64, d, "body"),
    ]
pages.append({"pageType": "matrix", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 08 two columns
good = [
    "党建引领作用进一步发挥，基层党组织标准化建设达标率 100%",
    "经营效益稳步提升，利润增速连续两年高于收入增速",
    "科技创新取得突破，获省部级科技奖励 6 项",
]
bad = [
    "新兴业务盈利能力偏弱，毛利率低于传统业务",
    "数字化转型进度不均衡，部分二级单位推进偏慢",
    "高端人才结构性短缺，关键岗位后备不足",
]
els = chrome(9, "成绩来之不易，短板同样需要正视", "三、存在的问题与不足")
cw = (W - 2 * M - 24) / 2
for side, (head, color, lst) in enumerate([("主要成绩", "$red", good), ("存在不足", "$muted", bad)]):
    x = M + side * (cw + 24)
    els += [
        rect(f"col-head-{side + 1}", x, 114, cw, 40, color),
        text(f"col-head-text-{side + 1}", x + 20, 122, cw - 40, 26, head, "lead", fontSize=17, color="$white"),
    ]
    for j, t in enumerate(lst):
        y = 172 + j * 100
        els += [
            text(f"col-{side + 1}-no-{j + 1}", x + 4, y, 36, 32, f"{j + 1}", "title", fontSize=22, color=color),
            text(f"col-{side + 1}-text-{j + 1}", x + 44, y + 2, cw - 52, 72, t, "body", fontSize=14),
            hline(f"col-{side + 1}-rule-{j + 1}", x, y + 86, cw),
        ]
pages.append({"pageType": "comparison", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 10 problem -> cause -> measure
rowsd = [
    ("新兴业务盈利偏弱", "市场开拓期投入集中，规模效应尚未形成", "设定分业务毛利率目标，季度复盘"),
    ("数字化推进不均衡", "二级单位基础差异大，缺少统一标准", "制定数据标准，实行挂图作战"),
    ("高端人才短缺", "薪酬竞争力不足，培养周期长", "实施专项引才计划，建立后备库"),
]
els = chrome(10, "问题聚焦三个方面，逐项明确原因和措施", "三、存在的问题与不足")
cols = [("问题", 260), ("原因", 300), ("整改措施", W - 2 * M - 560 - 32)]
x = M
for k, (h, w) in enumerate(cols):
    els += [
        rect(f"pcm-head-{k + 1}", x, 114, w, 36, "$red" if k == 0 else ("$deepred" if k == 1 else "$gold")),
        text(f"pcm-head-text-{k + 1}", x + 16, 120, w - 32, 24, h, "lead", fontSize=15, color="$white"),
    ]
    for r, row in enumerate(rowsd):
        y = 162 + r * 104
        els += [
            rect(f"pcm-cell-{r + 1}-{k + 1}", x, y, w, 92, "$surface" if k != 2 else "$white", "$rule", 0.8),
            text(f"pcm-text-{r + 1}-{k + 1}", x + 16, y + 14, w - 32, 66, row[k], "body", fontSize=14, bold=(k == 0)),
        ]
    x += w + 16
pages.append({"pageType": "evidence", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 11 next-year plan
goals = [
    ("营业收入", "≥ 415", "亿元", "增长 7.5% 以上"),
    ("利润总额", "≥ 46", "亿元", "增长 8% 以上"),
    ("研发投入强度", "≥ 3.8", "%", "提高 0.4 个百分点"),
]
tasks = [
    "深入推进改革深化提升行动，完成剩余 2 项改革任务",
    "一季度完成供应链模块上线，年内实现数据贯通",
    "新兴业务毛利率提升 2 个百分点，培育 2 个十亿级业务",
]
els = chrome(11, "2027 年：稳增长、提质量、补短板", "四、2027 年工作安排")
gw = (W - 2 * M - 32) / 3
for i, (lab, num, unit, note) in enumerate(goals):
    x = M + i * (gw + 16)
    els += [
        rect(f"goal-card-{i + 1}", x, 114, gw, 128, "$red"),
        text(f"goal-label-{i + 1}", x + 20, 126, gw - 40, 20, lab, "label", fontSize=13, color="$lightgold"),
        text(f"goal-num-{i + 1}", x + 20, 150, gw - 90, 50, num, "title", fontSize=34, color="$white"),
        text(f"goal-unit-{i + 1}", x + gw - 70, 168, 50, 24, unit, "label", fontSize=14, color="$lightgold"),
        text(f"goal-note-{i + 1}", x + 20, 208, gw - 40, 22, note, "label", fontSize=12, color="$white"),
    ]
els += [text("plan-head", M, 262, 400, 24, "重点任务", "lead", fontSize=17, color="$red")]
for j, t in enumerate(tasks):
    y = 298 + j * 62
    els += [
        rect(f"plan-dot-{j + 1}", M, y + 6, 10, 10, "$gold"),
        text(f"plan-task-{j + 1}", M + 24, y, W - 2 * M - 24, 44, t, "body", fontSize=14),
        hline(f"plan-rule-{j + 1}", M, y + 50, W - 2 * M),
    ]
pages.append({"pageType": "action", "background": {"type": "solid", "color": "$white"}, "elements": els})

# 12 closing
pages.append(
    {
        "pageType": "closing",
        "background": {"type": "solid", "color": "$red"},
        "elements": [
            rect("close-deep", 0, 380, W, 160, "$deepred"),
            rect("close-gold-top", 330, 170, 300, 2, "$gold"),
            text(
                "close-title",
                120,
                190,
                720,
                64,
                "汇报完毕  敬请指正",
                "title",
                fontSize=40,
                color="$white",
                align=["center", "top"],
            ),
            rect("close-gold-bottom", 330, 270, 300, 2, "$gold"),
            text(
                "close-org",
                120,
                420,
                720,
                24,
                "示例集团有限公司 党委",
                "lead",
                fontSize=16,
                color="$white",
                bold=False,
                align=["center", "top"],
            ),
            text(
                "close-date",
                120,
                450,
                720,
                20,
                "2026 年 12 月",
                "label",
                fontSize=14,
                color="$lightgold",
                align=["center", "top"],
            ),
        ],
    }
)

os.makedirs(os.path.join(OUT, "pages"), exist_ok=True)
manifest = {
    "version": "v2",
    "title": "示例集团 2026 年度工作汇报（政企红色参考稿）",
    "size": [W, H],
    "theme": {"colors": COLORS, "textStyles": TEXT_STYLES, "tableStyles": TABLE_STYLES},
    "pages": [f"pages/{i + 1:02d}.page" for i in range(len(pages))],
    "template": {"id": "gov-red", "name": "Gov Red"},
}


class D(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _str(dumper, data):
    style = "'" if data.isdigit() else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


D.add_representer(str, _str)


def dump(obj, fh):
    yaml.dump(obj, fh, Dumper=D, allow_unicode=True, sort_keys=False, width=1000)


with open(os.path.join(OUT, "deck.pptd"), "w", encoding="utf-8") as f:
    dump(manifest, f)
for i, p in enumerate(pages):
    with open(os.path.join(OUT, "pages", f"{i + 1:02d}.page"), "w", encoding="utf-8") as f:
        dump(p, f)
print("pages", len(pages))
