---
name: bisheng-pptx
description: >-
  制作 PowerPoint 演示文稿（.pptx）时使用：企业介绍、工作汇报、项目方案、经营分析、产品发布、培训课件等幻灯片；
  按用户提供的模板（.pptx/.potx）套版生成；读取或改写已有 PPT。当用户说到「PPT」「幻灯片」「演示文稿」「汇报材料」
  「宣讲材料」「课件」「deck」「slides」「pptx」，或提出「做一个介绍 X 的 PPT」「按这个模板做一版」
  「把这份材料做成 PPT」时触发。本技能内置五套场景模板（央国企汇报、项目方案、经营分析、科技发布、培训课件），
  按模板版式填写内容生成可编辑的 .pptx，并附交付前自检脚本。
  如果用户明确要的是网页翻页式 HTML 演示而不是 .pptx 文件，不要用本技能。
metadata:
  display-name: PPT 制作
---

# 制作 PPTX

一份好 PPT 的质量，七成来自内容组织，三成来自版式。本技能的做法是：
**你负责想清楚每页说什么，版式交给内置模板**。模板的配色、字号、留白和对齐都已调好，
你只按插槽名把内容填进去，不要自己画坐标、加装饰。

## 0. 开工纪律

**这一轮只读文档，不要在同一轮里并行调用别的工具。** 读完本文件（必要时再读 references）之后，
下一轮才开始动手。

**本技能要求已勾选代码执行器（`bisheng_code_interpreter`）。** 没有它就无法生成 .pptx ——
直接告诉用户「请在工具里勾选代码执行器后重试」，不要用 Word 或 PDF 顶替。

**第一次执行代码时先探一次环境**（只花一轮）：

```python
import os, shutil
try:
    import pptx; print("python-pptx OK", getattr(pptx, "__version__", ""))
except ImportError:
    print("python-pptx MISSING")
print("skills 可见:", os.path.isdir("skills/bisheng-pptx/templates"))
print("soffice:", shutil.which("soffice") or shutil.which("libreoffice") or "无")
```

- `python-pptx MISSING`：告诉用户「当前环境缺少 python-pptx，需要运维补装」，不要 `pip install`，不要假装做出来了。
- `skills 可见: False`：当前执行环境看不到技能目录，**内置模板和自检脚本都用不了**。
  如实告诉用户这一点，然后按 `references/freeform.md` 用纯 python-pptx 从零生成，不要反复重试路径。

环境的其余细节（路径、目录、单次时长上限、日志规则）见 `references/environment.md`，遇到问题再查。

## 1. 选路线

| 情况 | 做法 |
|---|---|
| 用户上传了 .pptx/.potx 模板，或说「按这个模板/样式做」 | §5 套用户模板（**优先级最高**，不要换成内置模板） |
| 用户上传了已有 PPT 要改内容 | 先用 §6 的 `inspect_deck.py` 读出内容，再按 §5 的方式打开原文件改写 |
| 其余情况（最常见） | **§2–§4：内置模板**（默认路线） |
| 用户明确要求自由设计，或五套模板都明显不贴合主题 | `references/freeform.md` 从零创建，§6 自检照做 |

## 2. 先写大纲（内容先行）

动手做页面之前，先把逐页大纲写到 `scratch/outline.md`（**不要写进 `output/`**），每页一行：

```
页码 | layout_id | 首读结论（就是这页的标题） | 支撑证据（数字带单位、期间、来源）
1 | cover | 2026 年度工作汇报：稳中求进，目标全面完成 | —
2 | kpi-4 | 四项核心指标全部超额完成 | 营收 128.6 亿元（+12.4%）、利润 10.8 亿元……（来源：财务快报）
3 | chart-insight | 营收连续四年增长，年均 13.8% | 2022–2026 营收序列（来源：历年年报）
```

写大纲时守住这几条（细则见 `references/design-zh.md`「零、内容组织」）：

- **标题写结论，不写话题**：「营收连续四年增长」而不是「营收情况」。听众只看标题也能带走要点。
- **一页一个结论**。两个结论就拆两页。
- **先排论证顺序，再定页数**：开场（问题与核心判断）→ 展开（按比较、流程、时间、层级选结构）→ 证据（图表、表格）→ 收尾（行动、责任人、待决事项）。
- **按内容关系选版式**：并列用卡片、先后用流程、时间用时间轴、取舍用对比、数据用 KPI 或图表、清单用表格。
  **不要连续三页用同一个版式**，也不要通篇都是卡片。
- 数字只用材料里有的；没有就写定性判断，**不要编数字**。示例数据要明确标注。

## 3. 选模板

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/list_templates.py"], capture_output=True, text=True)
print(r.stdout); print(r.stderr[-2000:] if r.stderr else "")
```

| 主题 / 场景 | 模板 id |
|---|---|
| 央国企、党政机关的工作汇报、宣传、党建 | `gov-red`（红韵） |
| 项目方案、技术方案、可研、工程建设 | `blueprint`（蓝图） |
| 经营分析、数据汇报、金融投资 | `operating`（经营） |
| 产品发布、数字化/AI 方案、科技公司介绍 | `tech-dark`（深空） |
| 培训课件、制度宣贯、入职培训、工作坊 | `classroom`（课堂） |

用户点名了风格或行业就照办；拿不准时按上表选最贴近的一套。选定后看它的版式和插槽：

```python
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/list_templates.py", "gov-red"],
                   capture_output=True, text=True)
print(r.stdout); print(r.stderr[-2000:] if r.stderr else "")
```

输出里 `title≤27` 表示 title 插槽建议不超过 27 字（汉字算 1，字母数字算 0.5），`·分条` 表示传 list 逐条写。
把大纲里的 layout_id 对照这张表核一遍，再开始构建。

## 4. 用 Deck 构建

用 `write_file` 把完整脚本写到 `scratch/build_deck.py`（**不要把整段代码塞进代码执行器的参数里**，会被截断）：

```python
import sys
sys.path.insert(0, "skills/bisheng-pptx/scripts")
from deck_template import Deck

deck = Deck.open("gov-red", footer="某某集团 · 2026 年度工作汇报")   # footer=None 则不要页脚

s = deck.add("cover")
deck.fill(s, "title", "2026 年度工作汇报")
deck.fill(s, "subtitle", "稳中求进，全年目标全面完成")
deck.fill(s, "kicker", "集团年度工作会")
deck.fill(s, "org", "某某集团有限公司")
deck.fill(s, "date", "2026 年 12 月")

s = deck.add("kpi-4")
deck.fill(s, "kicker", "01 · 经营成果")
deck.fill(s, "title", "四项核心指标全部超额完成")
deck.fill(s, "kpi1.number", "128.6"); deck.fill(s, "kpi1.unit", "单位：亿元")
deck.fill(s, "kpi1.label", "营业收入"); deck.fill(s, "kpi1.note", "同比增长 12.4%")
# …kpi2–kpi4 同理；只有三个指标就 deck.drop(s, "kpi4")

s = deck.add("chart-insight")
deck.fill(s, "kicker", "01 · 经营成果")
deck.fill(s, "title", "营收连续四年增长，年均增速 13.8%")
deck.chart(s, "chart", "column", ["2022", "2023", "2024", "2025", "2026"],
           [("营业收入（亿元）", [76.6, 88.2, 101.5, 114.4, 128.6])], number_format="0.0")
deck.fill(s, "insight.title", "读图要点")
deck.fill(s, "insight.body", ["2024 年起新能源贡献过半", "2026 年增速略有回落"])
deck.fill(s, "source", "来源：集团历年年报")

deck.save("output/2026年度工作汇报.pptx")
```

执行：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "scratch/build_deck.py"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

| 方法 | 用途 |
|---|---|
| `Deck.open(id, footer=...)` | 打开模板；footer 写进每页页脚 |
| `deck.add(layout_id)` | 追加一页（复制该版式的原型页），返回 slide |
| `deck.fill(slide, 插槽, 文本或 list)` | 写文字，保留模板的字体字号颜色；list 逐条成段 |
| `deck.drop(slide, 插槽或分组)` | 删掉用不到的插槽，`drop(s, "card3")` 删整张卡片 |
| `deck.chart(slide, "chart", kind, 类别, [(系列名, 数值)], number_format=)` | 原生图表；kind 取 column / bar / line / stacked / pie / doughnut / waterfall（瀑布图：第一个和最后一个是总量，中间是增减） |
| `deck.table(slide, "table", 表头, 行, highlight_rows=(2,))` | 原生表格；highlight_rows 标出需要关注的行（从 0 数） |
| `deck.image(slide, "image", 图片路径)` | 把 `uploads/` 里的图片或你生成的图放进图片区，自动裁切填满 |
| `deck.notes(slide, 文本)` | 演讲者备注 |
| `deck.save("output/名称.pptx")` | 删除原型页并保存，同时写 `scratch/名称.manifest.json` 供自检使用 |

填写规则：

- **超过插槽容量就精简文案或拆页**，不要缩字号、不要改框尺寸。`fill` 超容量时会打印 `[超容量]`。
- **用不到的插槽一律 `drop`**，不要留空字符串，更不要留模板示例文字（带「示例」字样的都是示例）。
- **不要改坐标、不要自己加线条和色块**。确实需要额外元素（比如在图片区旁加一个标注），保持在内容区内，并在自检里复核。
- 图表数据必须来自材料；源数据缺失时换成定性的卡片或观点页，不要编。
- 返修时用 `edit_file` 定点改 `scratch/build_deck.py` 再重跑，不要每次重写整份脚本。

## 5. 套用用户模板

**第 1 步 · 探版式**：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/probe_template.py", "uploads/模板.pptx"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

它会打印画布尺寸、主题配色与字体、每个版式的索引与占位符 idx、以及模板自带的页。

**第 2 步 · 以模板为基底生成**：

- `prs = Presentation("uploads/模板.pptx")` —— **打开模板本身**，不要 `Presentation()` 空开再仿色。
- `slide = prs.slides.add_slide(prs.slide_layouts[i])`，`i` 用第 1 步打印的索引。
- 填占位符用 `pptx_helpers.fill_text(shape, "文字")`（见 `references/pptx-cookbook.md` §7），
  **不要用 `text_frame.text = "..."`**，那会丢掉模板样式。
- 模板自带的示例页要删掉（cookbook 有删页片段），删页放在写内容之前。
- 用不到的占位图形整组删除，不要只清空文字。
- 保存到 `output/`，扩展名保持 `.pptx`。§2 的大纲要求同样适用。

**注意**：模板文件是二进制，**不要用 `read_file` 去读它**，只能由代码执行器打开。

## 6. 交付前自检（必做）

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/inspect_deck.py", "output/xxx.pptx"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

输出分「内容」和「体检」两段：

- **内容**：逐页文本加备注，用来核对错字、顺序、缺漏。
- **体检**：每条问题带页码和元素名。**ERROR 必须修完再交付；WARN 逐条复核**，能改就改。
  用 Deck 生成的文稿会自动读取 `scratch/` 下的清单，额外检查：文字超出该位置的容量、残留模板示例、
  连续三页用同一版式、封面缺少首读焦点、图表区没放图表。模板自带的结构元素不会被报出来。

改完重新生成、再跑一次，直到「结论: 通过」。**没报 ERROR ≠ 完全合规**，版式仍以 `references/design-zh.md` 为准。

渲染成图片逐页查看是可选步骤，只在确知当前模型支持读图时才做，做法见 `references/environment.md`。

## 7. 交付纪律

- `output/` 里**只放最终的 `.pptx`**。大纲、构建脚本、清单、预览图一律放 `scratch/`
  （同时放一个 `.md` 会顶掉 PPT 成为用户看到的头条文件）。
- 文件名用有意义的中文名，如 `output/某某集团2026年度工作汇报.pptx`。
- 收尾时如实说明：多少页、用了哪套模板、自检结论（几条 WARN 未处理及原因）。
  **不要声称做过没做的检查**，也不要声称生成了实际不存在的文件。

## 8. 绝不要做的事

- ❌ 写 Node / `pptxgenjs` 脚本、`pip install` / `npm install` 任何东西。
- ❌ 用绝对路径 `/output/...`（文件会被静默丢弃）。
- ❌ 把 PPT 降级成 Word/PDF/Markdown 交付。用户要的是 .pptx。
- ❌ 把整页截图或图片当成文字、表格、图表的替代品。
- ❌ 为了塞下文字把字号缩到模板之下。
- ❌ 因为 `ls` 看不到刚生成的文件就重做一遍 —— 以执行结果为准。
