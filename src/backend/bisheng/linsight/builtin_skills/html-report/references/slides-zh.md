# 网页幻灯片

一份好的汇报，七成来自内容组织，三成来自版式。本分支的做法是：**你负责想清楚每页说什么，版式交给内置模板**。
模板的页面尺寸、字号、留白和配色都已调好；你在构建脚本里按插槽名填内容，脚本生成单个网页。

为什么不手写 HTML：几十页幻灯片的标记几乎一样，只有文字不同。手写时模型要把每页的标记逐字写出来，
改一页要重写整页，几十页的文稿会因此多花一个多小时。用脚本生成，你只写文字；改版只改对应页的那几行。

用户要的是 .pptx 文件（要在 PowerPoint 里编辑、按 .pptx 模板套版）时，不用本分支，改用「PPT 制作」技能。

## 0. 开工

**这一轮只读文档。** 读完本文件，下一轮再动手。

本分支以代码执行工具为主路径。第一次执行代码时先探一次环境：

```python
import os
print("skills 可见:", os.path.isdir("skills/html-report/scripts"))
```

- 没有代码执行工具，或 `skills 可见: False`：脚本用不了。如实说明这一点，改用 §7 的手写路线，不要反复重试路径。

## 1. 先写大纲（内容先行）

动手之前，把逐页大纲写到 `scratch/outline.md`（**不要写进 `output/`**），每页一行：

```
页码 | layout_id | 结论标题 | 支撑证据（数字带单位、期间、来源）
1 | cover | 2026 年度经营汇报：稳中有进，目标全面完成 | —
2 | kpi-4 | 四项核心指标全部超额完成 | 营收 128.6 亿元（+12.4%）、利润 10.8 亿元……（来源：财务快报）
3 | chart-insight | 营收连续四年增长，年均 13.8% | 2023–2026 营收序列（来源：历年年报）
```

- **标题写结论，不写话题**：「营收连续四年增长」而不是「营收情况」。听众只看标题也能带走要点。
- **一页一个结论。** 两个结论就拆两页。
- **先排论证顺序，再定页数**：开场（问题与核心判断）→ 展开 → 证据（图表、表格）→ 收尾（行动、责任人、待决事项）。
- **按内容关系选版式**：并列用卡片、先后用流程、时间用时间轴、取舍用对比、数据用指标或图表、清单用表格。
  不要连续三页用同一个版式，也不要通篇都是卡片。
- 数字只用材料里有的；没有就写定性判断，不要编数字。

改版已有文稿（例如「基于 v3 出 v3.1」）：先把旧稿的页面结构读成大纲，再在大纲上改。不要逐页读旧网页、逐页改写。

## 2. 选主题

| 主题 / 场景 | 主题 id |
|---|---|
| 央国企、党政机关的工作汇报、宣传、党建 | `gov-red`（红韵） |
| 项目方案、技术方案、可研、工程建设 | `blueprint`（蓝图） |
| 经营分析、数据汇报、金融投资 | `operating`（经营） |
| 产品发布、数字化/AI 方案、科技公司介绍 | `tech-dark`（深空） |
| 培训课件、制度宣贯、入职培训、工作坊 | `classroom`（课堂） |

用户点名了风格或行业就照办；拿不准时按上表选最贴近的一套，不必停下来问。所有主题的版式与插槽相同，查看插槽和容量：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/html-report/scripts/list_layouts.py", "operating"],
                   capture_output=True, text=True)
print(r.stdout); print(r.stderr[-2000:] if r.stderr else "")
```

输出里 `title≤28` 表示 title 插槽不超过 28 字（汉字算 1，字母数字算 0.5），`·分条≤4条` 表示传 list 逐条写、最多 4 条。

## 3. 写构建脚本

用 write_file 把完整脚本写到 `scratch/build_slides.py`（**不要把整段代码塞进代码执行工具的参数里**，太长会被截断）：

```python
import sys
sys.path.insert(0, "skills/html-report/scripts")
from slides import Deck

deck = Deck.open("operating", footer="某某集团 · 2026 年度经营汇报")   # footer=None 则不要页脚

s = deck.add("cover")
deck.fill(s, "title", "2026 年度经营汇报：稳中有进")
deck.fill(s, "subtitle", "全年目标全面完成，四项指标超额")
deck.fill(s, "org", "某某集团有限公司")
deck.fill(s, "date", "2026 年 12 月")
deck.drop(s, "kicker")

s = deck.add("kpi-4")
deck.fill(s, "kicker", "01 · 经营成果")
deck.fill(s, "title", "四项核心指标全部超额完成")
deck.fill(s, "kpi1.number", "128.6"); deck.fill(s, "kpi1.unit", "亿元")
deck.fill(s, "kpi1.label", "营业收入"); deck.fill(s, "kpi1.note", "同比增长 12.4%")
# …kpi2–kpi3 同理；只有三个指标就 deck.drop(s, "kpi4")
deck.drop(s, "kpi4")

s = deck.add("chart-insight")
deck.fill(s, "title", "营收连续四年增长，年均 13.8%")
deck.chart(s, "chart", "column", ["2023", "2024", "2025", "2026"],
           [("营业收入（亿元）", [88.2, 101.5, 114.4, 128.6])], number_format="0.0")
deck.fill(s, "insight.title", "读图要点")
deck.fill(s, "insight.body", ["2024 年起新业务贡献过半", "2026 年增速略有回落"])
deck.fill(s, "source", "来源：集团历年年报")
deck.drop(s, "kicker")

deck.save("output/2026年度经营汇报.html")
```

执行：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "scratch/build_slides.py"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

| 方法 | 用途 |
|---|---|
| `Deck.open(主题, footer=, title=, css_vars=)` | 打开主题；footer 写进每个内容页页脚；title 是浏览器标签页标题 |
| `deck.add(layout_id)` | 追加一页，返回页面 |
| `deck.fill(页, 插槽, 文本或 list)` | 写文字；分条插槽传 list，逐条成为要点 |
| `deck.drop(页, 插槽或分组)` | 删掉用不到的插槽，`drop(s, "card3")` 删整张卡片 |
| `deck.chart(页, "chart", kind, 类别, [(系列名, 数值)], number_format=)` | 内联 SVG 图表；kind 取 column / bar / line / stacked / pie / doughnut / waterfall（瀑布图：第一个和最后一个是总量，中间是增减）；number_format 取 "0" / "0.0" / "0%" / "0.0%" |
| `deck.table(页, "table", 表头, 行, highlight_rows=(2,))` | 表格；highlight_rows 标出需要关注的行（从 0 数） |
| `deck.image(页, "image", 图片路径)` | 把 `uploads/` 里的图片或你生成的图嵌进图片区 |
| `deck.notes(页, 文本)` | 演讲者备注（不显示在页面上） |
| `deck.html(页, 插槽, 片段)` | 版式实在表达不了时，在文字插槽里放一小段 HTML；不能带样式和脚本，尽量少用 |
| `deck.save("output/名称.html")` | 生成网页，同时写 `scratch/名称.manifest.json` 供自检使用 |

填写规则：

- **超过插槽容量就精简文案或拆页**，不要缩字号。`fill` 超容量时会打印 `[超容量]`。容量按投影可读的字号算好了，硬塞会溢出页面。
- **用不到的插槽一律 `drop`**，不要填空字符串。
- 图表数据必须来自材料；源数据缺失时换成卡片或观点页，不要编。
- 表格不超过 8 行数据，多了拆成两页。

## 4. 改版和返修

返修和改版都只改构建脚本：用 edit_file 定点改对应页的那几行 `fill` / `chart`，再重跑脚本。
**不要用 edit_file 直接改生成的网页**——下一次重跑会把手改的内容冲掉，自检也会报页数和清单对不上。

用户要求「字大一些」：模板正文已是 20px、标题 36px，投影可读。确实要更大时，在 `Deck.open` 里传
`css_vars={"--fs-body": "22px"}`（可改 `--fs-body`、`--fs-title`、`--fs-lead`、`--fs-h3`、`--fs-small`、`--fs-kicker`、`--fs-number`），
同时减少每页内容。字号变大后容量提示会偏宽，是否装得下以 check_html 的逐页测量为准。

## 5. 交付前自检（必做）

先跑内容自检，再跑渲染检查：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/html-report/scripts/check_slides.py", "output/名称.html"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

然后调用 `check_html(path="output/名称.html")`。它在浏览器里逐页测量，报告里列出溢出的页和超出的像素。

- 某页装不装得下以 check_html 的测量为准，不要在思考里估算像素。
- 只修改报告列出的页（精简、拆页或换版式），改构建脚本后重跑，再各检查一次。**最多修 2 轮。**
- 内容自检的 WARN 逐条复核，能改就改；2 轮后仍有 ERROR，在收尾里如实说明。

## 6. 交付纪律

- `output/` 里**只放最终的 `.html`**。大纲、构建脚本、清单一律放 `scratch/`（多放一个 `.md` 会顶掉网页成为用户看到的头条文件）。
- 文件名用有意义的中文名，如 `output/某某集团2026年度经营汇报.html`。
- 收尾时如实说明：多少页、用了哪套主题、自检结论（几条 WARN 未处理及原因）。不要声称做过没做的检查。
- 网页打开后按 ← → 翻页，按 P 进入单页放映，打印时每页一张 16:9。

## 7. 没有代码执行工具时（手写路线）

```
read_file("/skills/html-report/assets/slides/template.html", limit=1000)
```

它是每个版式一页的示例文稿。用 write_file 写 `output/<name>.html`：

- 整段保留 `<style>` 和末尾 `<script>`；配色在第一段 `:root` 里（示例是 operating 主题）。换主题时，从
  `read_file("/skills/html-report/assets/slides/themes.json")` 取对应主题的 palette，只替换那一段的颜色值。
- 每页是一个 `<section class="slide l-版式名">`，复制需要的版式，把示例文字换成真实内容；用不到的整页删掉。
- 页码在每页的 `<span class="pg">` 里，按顺序改写；页面较多时先写前几页，再用 edit_file 逐页追加。
- 写完照常调用 check_html；修溢出时精简文字或拆页，不要改 `<style>` 里的尺寸。

## 8. 设计规则

- 模板已经定好一主一辅一强调的配色，不要另加颜色；状态色只用于表达状态。
- **不要自己加装饰线条、色条、标题下划线**——这些是一眼看出机器生成的特征。需要区分区块时用模板的底色卡片。
- 不要把整页截图或图片当成文字、表格、图表的替代品。
- 不要为了塞下文字缩小字号。
