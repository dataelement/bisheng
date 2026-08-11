# python-pptx 配方（BiSheng 环境）

可直接抄进 `scratch/build_deck.py`。所有片段只依赖 `python-pptx`，
需要 XML 的几处统一走本技能包的 `pptx_helpers`。

## 0. 骨架

```python
import sys
sys.path.insert(0, "skills/bisheng-pptx/scripts")   # 本技能包的 helper

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx_helpers import set_font, set_font_all, add_bullet, no_bullet, delete_slide, fill_text

W, H = Inches(13.333), Inches(7.5)          # 16:9
prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]

# 配色（从 design-zh.md 选一套）
PRIMARY   = RGBColor(0x8B, 0x1A, 0x2B)
SECONDARY = RGBColor(0xC9, 0xA8, 0x4C)
ACCENT    = RGBColor(0xA8, 0x23, 0x2F)
BG_LIGHT  = RGBColor(0xF7, 0xF4, 0xEF)
INK       = RGBColor(0x2B, 0x2B, 0x2B)
FONT      = "微软雅黑"

# ... 逐页构建 ...

import os
os.makedirs("output", exist_ok=True)
prs.save("output/公司介绍.pptx")
print("saved output/公司介绍.pptx", "slides:", len(prs.slides._sldIdLst))
```

> **⚠️ 16:9 的坑**：python-pptx 内置模板是 4:3（10×7.5in）。改了 `slide_width` 之后，
> 内置版式（`slide_layouts[0]`「Title Slide」等）里的占位符**不会**跟着变宽 —— 用它们排出来的页
> 内容会挤在左侧 3/4。**从零创建时统一用 `slide_layouts[6]`（Blank）自己摆位**。
> 只有在套用用户模板时才用模板自己的版式（那些是按模板画布做好的）。

## 1. 背景与色块

```python
def add_slide(bg=None):
    slide = prs.slides.add_slide(BLANK)
    if bg is not None:
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = bg
    return slide

cover = add_slide(PRIMARY)          # 深色封面
page  = add_slide(BG_LIGHT)         # 浅色内容页
```

半幅色块 / 卡片：

```python
card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                              Inches(0.8), Inches(2.0), Inches(3.9), Inches(2.1))
card.fill.solid(); card.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
card.line.fill.background()          # 无边框（比描边干净）
card.shadow.inherit = False          # 关掉默认阴影，默认阴影很脏
```

## 2. 文本框（推荐统一用这个函数）

```python
def add_text(slide, text, x, y, w, h, size=16, bold=False, color=INK,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, line_spacing=1.25):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE          # 固定框高，溢出才能被自检发现
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0)   # 与其它元素对齐时必须清零
    tf.margin_top = tf.margin_bottom = Inches(0)
    lines = text if isinstance(text, list) else [text]
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.line_spacing = line_spacing
        run = para.add_run()
        run.text = line
        set_font(run, FONT, size_pt=size, bold=bold, color=color)
    return box
```

要点：

- `auto_size = NONE` 很重要。`add_textbox()` 默认是"自动调整高度"，框会在渲染时被文字撑高、
  压到下方元素，而且自检只能给出 WARN。固定框高之后溢出是硬错误，能被准确报出来。
- 文本框自带内边距，和线条/图形对齐时把四个 margin 清零，否则文字会莫名内缩 0.1 英寸。
- 中文字体必须用 `set_font()`（同时写 latin 和 ea），只设 `run.font.name` 对中文无效。

## 2.1 大数字 + 标签（最容易撞在一起的组合）

60–72pt 的数字很高，标签紧跟在下面时极易被数字框压住 —— 渲染出来就是"标签被大字盖掉一半"。
**按字号算出数字框的高度，再把标签放到它下面**，不要凭感觉给 y 坐标：

```python
STATS = [("212.05", "2025 年营收（亿元）"), ("31.63", "归母净利润（亿元）"),
         ("54.35%", "净利润同比"), ("37.18%", "营收同比")]

STAT_PT = 60
stat_h = STAT_PT * 1.35 / 72          # pt → 英寸，1.35 留行高余量
gap = 0.12
col_w = 2.8
for i, (value, label) in enumerate(STATS):
    x = 0.8 + i * (col_w + 0.25)
    add_text(slide, value, x, 1.9, col_w, stat_h, size=STAT_PT, bold=True, color=PRIMARY)
    add_text(slide, label, x, 1.9 + stat_h + gap, col_w, 0.4, size=13, color=INK)
```

- 一行最多 4 组；每组宽度要放得下最长的那个标签，放不下就缩短标签或减少组数。
- 数字里带 `%` 的会更宽，`col_w` 要按最宽的那个数字算，否则 `%` 会自己换行到第二行、把下面的内容全顶乱。
- 自检里出现「文字区域重叠」的 ERROR，十有八九就是这一处没按上面的方式算 y。

## 3. 项目符号

```python
box = add_text(slide, ["开关设备", "变压器类产品", "保护与自动化"], 0.8, 1.9, 5.6, 3.0, size=16)
for para in box.text_frame.paragraphs:
    add_bullet(para, "▪")               # 不要在文字里手打 •，会出现双重符号
    para.space_after = Pt(10)           # 用段后距控制间隔，不要靠加大行距
```

需要去掉继承来的符号（例如整段叙述性文字）时用 `no_bullet(para)`。

## 4. 表格

```python
rows, cols = 4, 3
tbl_shape = slide.shapes.add_table(rows, cols, Inches(1.0), Inches(2.0), Inches(11.3), Inches(2.6))
table = tbl_shape.table
table.columns[0].width = Inches(3.5)
table.columns[1].width = Inches(3.9)
table.columns[2].width = Inches(3.9)

data = [["指标", "2024", "2025"], ["营业收入", "118.5 亿", "140.0 亿"],
        ["净利润", "12.4 亿", "15.8 亿"], ["研发投入", "6.1 亿", "7.5 亿"]]
for r, row in enumerate(data):
    table.rows[r].height = Inches(0.55)
    for c, value in enumerate(row):
        cell = table.cell(r, c)
        cell.text = value                       # 表格用 cell.text 没问题
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        para = cell.text_frame.paragraphs[0]
        para.alignment = PP_ALIGN.CENTER if c else PP_ALIGN.LEFT
        header = r == 0
        for run in para.runs:
            set_font(run, FONT, size_pt=14 if not header else 15, bold=header,
                     color=RGBColor(0xFF, 0xFF, 0xFF) if header else INK)
        cell.fill.solid()
        cell.fill.fore_color.rgb = PRIMARY if header else RGBColor(0xFF, 0xFF, 0xFF)
```

## 5. 原生图表（能用原生就别贴图片）

```python
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION

data = CategoryChartData()
data.categories = ["2023", "2024", "2025"]
data.add_series("营业收入", (98.2, 118.5, 140.0))

frame = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,
                               Inches(1.0), Inches(1.9), Inches(11.3), Inches(4.5), data)
chart = frame.chart
chart.has_title = True
chart.chart_title.text_frame.text = "营业收入（亿元）"
chart.has_legend = False                        # 单系列不需要图例

plot = chart.plots[0]
plot.gap_width = 120
plot.has_data_labels = True
labels = plot.data_labels
labels.number_format = "0.0"
labels.number_format_is_linked = False
labels.position = XL_LABEL_POSITION.OUTSIDE_END
labels.font.size = Pt(12)

series = chart.series[0]
series.format.fill.solid()
series.format.fill.fore_color.rgb = PRIMARY

chart.font.size = Pt(12)                        # 轴标签
chart.font.color.rgb = RGBColor(0x6B, 0x72, 0x80)
```

- **堆积柱状图**的数据标签位置只能用 `CENTER` / `INSIDE_END` / `INSIDE_BASE`，
  用 `OUTSIDE_END` 会生成 PowerPoint 打不开的文件。
- 图表里的中文若在某些环境显示异常，改用第 6 节的 matplotlib 出图贴入。

## 6. 图片 / matplotlib 出图

```python
slide.shapes.add_picture("uploads/厂区.jpg", Inches(6.9), Inches(1.75), width=Inches(5.6))
# 只给 width 或 height 会等比缩放；两个都给会拉伸变形
```

> **⚠️ 等比缩放要自己核算高度**：只给 `width` 时高度按原图比例算出来，很容易顶出画布底部。
> 先算 `高 = 宽 × 原图高/原图宽`，确认 `y + 高 ≤ 7.5 - 0.4`。放不下就减小 `width`。
> （自检脚本会把越界报成 ERROR，但提前算一步能省一轮返工。）

matplotlib 生成图片（放 `scratch/`，不要放 `output/`）：

```python
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# 选一个这台机器上真实存在的中文字体，否则中文全是方块。
# 执行器会自动注入 family="WenQuanYi Zen Hei"，但有的部署装的是 Noto CJK —— 那条注入就落空了。
_installed = {f.name for f in font_manager.fontManager.ttflist}
for _cand in ("WenQuanYi Zen Hei", "Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "SimHei"):
    if _cand in _installed:
        matplotlib.rc("font", family=_cand)
        break
else:
    print("⚠️ 没有可用中文字体，图里改用英文标签")
matplotlib.rcParams["axes.unicode_minus"] = False   # 负号也会变方块

os.makedirs("scratch", exist_ok=True)
fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=200)      # 2:1
ax.bar(["2023", "2024", "2025"], [98.2, 118.5, 140.0], color="#8B1A2B")
ax.set_ylabel("亿元")
fig.tight_layout()
fig.savefig("scratch/revenue.png", transparent=True)
plt.close(fig)

# 2:1 的图放 10 英寸宽 → 高 5.0；1.9 + 5.0 = 6.9 < 7.5，安全
slide.shapes.add_picture("scratch/revenue.png", Inches(1.67), Inches(1.9), width=Inches(10.0))
```

> 执行器会在最后一行 `import matplotlib` 之后自动插入 `matplotlib.rc("font", family="WenQuanYi Zen Hei")`。
> 上面那段挑字体的代码写在它后面，所以会覆盖它 —— 这正是我们要的：某些部署装的是 Noto CJK 而不是文泉驿，
> 硬写 WenQuanYi 会落空，日志里会刷 `Glyph xxxxx missing from font(s) DejaVu Sans`，图上中文全是方块。
> 看到这条警告就说明字体没选对，回到这一段。

## 7. 套用模板：按占位符填充

```python
prs = Presentation("uploads/模板.pptx")          # 打开模板本身，继承母版与主题
slide = prs.slides.add_slide(prs.slide_layouts[3])   # 索引来自 probe_template.py

fill_text(slide.placeholders[0], "核心业务板块")             # 标题
fill_text(slide.placeholders[1], ["开关设备", "变压器", "储能"])  # 正文，多行
```

- `fill_text()` 会保留模板给这个占位符设定的字号、字色、项目符号；
  **绝不要用 `placeholder.text_frame.text = "..."`**，那会把整段塌成一个无格式 run。
- 用不到的占位符要删掉（下一节），留着会在成品里显示"单击此处添加文本"。
- 模板里成组的示例元素（如四个人的头像＋姓名）如果你只有三条内容，
  要把第四组**整组删除**，不是只清空文字。

删除形状 / 删除页：

```python
shape._element.getparent().remove(shape._element)     # 删一个形状
delete_slide(prs, 5)                                  # 删一页（从大索引往小删）
```

## 8. 演讲者备注

```python
slide.notes_slide.notes_text_frame.text = "这一页强调三个数字：140 亿、25%、60 国。"
```

备注写在备注页，不要写成幻灯片上的文本框。

## 9. 保存与自检

```python
import os
os.makedirs("output", exist_ok=True)
prs.save("output/思源电气企业介绍.pptx")
print("OK:", os.path.getsize("output/思源电气企业介绍.pptx"), "bytes")
```

保存后一定要跑（见 SKILL.md §5）：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/inspect_deck.py",
                    "output/思源电气企业介绍.pptx"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

## 10. python-pptx 做不到的事（别浪费轮次）

- **复制一张已有幻灯片**：没有这个 API。要"再来一页同样的"，就用同一个 layout 再 `add_slide` 一次。
- **渐变填充**：`fill.gradient()` 支持有限且容易出错；要渐变就用一张渐变图片当背景。
- **读取 SVG/EMF**：`add_picture` 会抛 `UnidentifiedImageError`。模板里的矢量图标只能靠"复用带该图标的版式"来保留。
- **自动缩放文字以适应形状**：`auto_size` 的自动缩字号在 PowerPoint 里才生效，生成时不会真的改字号 ——
  放不下就自己改文案或改布局。
