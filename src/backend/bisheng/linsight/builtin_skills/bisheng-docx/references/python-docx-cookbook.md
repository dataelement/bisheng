# python-docx 速查（BiSheng 适配）

可直接抄的片段。代码假定写在**构建脚本**里（`scratch/build_doc.py`），由代码执行器用
`subprocess.run([sys.executable, "scratch/build_doc.py"])` 跑。

开头统一这样起：

```python
import sys, os
sys.path.insert(0, "skills/bisheng-docx/scripts")
from docx_helpers import (
    setup_page, apply_chinese_defaults, set_run_font, add_heading_cn, add_body,
    add_table, add_toc, add_page_number_footer, add_hr, add_image_fitted,
    set_cell_shading, content_width_cm, first_line_indent,
    add_gongwen_title, add_signature_block,
)
from style_profiles import active_profile      # 需要取当前档的字体/字号时
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

os.makedirs("output", exist_ok=True)
os.makedirs("scratch", exist_ok=True)

doc = Document()
apply_chinese_defaults(doc)        # ★ 必须调，且在 setup_page 之前：定档（默认公文）
section = setup_page(doc)          # A4 纵向，页边距按档取
```

**版式档决定全篇字体字号**，`apply_chinese_defaults()` 定一次，下面所有 helper 自动跟随：

```python
apply_chinese_defaults(doc)                     # 公文档（默认）：三号仿宋_GB2312 / 黑体 / 楷体
apply_chinese_defaults(doc, profile="modern")   # 简历、宣传稿：微软雅黑 11pt
```

要在片段里手工取当前档的取值（而不是写死字体名）：

```python
P = active_profile()
body_font, body_pt = P["body"]["font"], P["body"]["pt"]
```

---

## 1. ★ 中文字体：最重要的一条

**`run.font.name = "微软雅黑"` 对中文完全无效。** 它只写 `w:ascii` 和 `w:hAnsi`（西文），
中文字符由 `w:eastAsia` 决定；不设的话中文会退回主题字体，和你指定的西文字体对不上，
用户打开一看就是"字体乱了"。

```python
set_run_font(run, "仿宋_GB2312", size_pt=16, bold=True)   # ✅ 三个字段一起设
run.font.name = "仿宋_GB2312"                             # ❌ 中文不生效
```

`apply_chinese_defaults(doc)` 会按当前档把 Normal 和 Heading 1–4 的 `w:eastAsia` 一次性设好
（顺带把 Word 内置 Heading 4 的**斜体**关掉 —— 不关的话四级标题会渲成斜体衬线）。
之后用 `add_body` / `add_heading_cn` / `add_table` 写的内容就都是对的，
**不必也不该逐处写死字体名** —— 写死就会在切档时留下几处漏网的。

体检脚本会专门抓这条。

**拿不到 `docx_helpers` 时（E2B 沙箱下 `skills/` 不可见）**，把这五行抄进构建脚本自己写：

```python
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def set_run_font(run, name, size_pt=None, bold=None):
    run.font.name = name                       # 只写 w:ascii / w:hAnsi
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts"); rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rfonts.set(qn(attr), name)             # ★ w:eastAsia 才管中文
    if size_pt is not None:
        from docx.shared import Pt; run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold
    return run
```

样式（Normal / Heading N）用同一段代码，把 `run._element` 换成 `style.element` 即可。

## 2. 标题与正文

```python
add_heading_cn(doc, "2024 年度经营分析报告", 1)
add_heading_cn(doc, "一、总体情况", 2)
add_body(doc, "本年度公司实现营业收入 12,500 万元，同比增长 15.2%。")   # 自动首行缩进 2 字
add_body(doc, "这段不缩进。", indent=False)
```

> **必须用内置 Heading 样式**（`add_heading_cn` 用的就是）。自定义样式的标题不会进目录，
> 导航窗格也是空的。

手写段落时：

```python
P = active_profile()["body"]
p = doc.add_paragraph()
set_run_font(p.add_run("加粗片段"), P["font"], P["pt"], bold=True)
set_run_font(p.add_run("，普通片段。"), P["font"], P["pt"])
p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY        # 中文正文常用两端对齐
first_line_indent(p)                            # 缩进字数与字号都按当前档
```

> **绝不要用 `\n`**。python-docx 不会把它变成换行，要么用多个 `Paragraph`，
> 要么 `run.add_break()`。

## 3. 目录与页码

```python
add_toc(doc, levels="1-3")          # 插入目录域 + 打开 updateFields
add_page_number_footer(section)     # 页脚「第 X 页 / 共 Y 页」，是活的域不是死字
```

目录是**域**，内容由 Word 打开时生成。`add_toc` 已经写了 `updateFields`，
用户打开会自动刷新；不写这个标记的话目录永远显示占位文字，看起来像坏了。

## 4. 表格

```python
add_table(
    doc,
    headers=["项目", "2024年", "2025E", "同比"],
    rows=[["营业收入", "12,500", "14,200", "13.6%"],
          ["营业成本", " 8,200", " 9,100", "11.0%"]],
    widths_cm=[5, 3.6, 3.6, 3.2],      # ★ 合计不要超过版心
    style="Table Grid",
)
print("版心宽度 cm:", content_width_cm(section))
```

> **列宽必须写到每个单元格**。只设 `table.columns[i].width` Word 会忽略 ——
> 这是"表格被压扁/撑出页面"的头号原因。`add_table` 已经处理了，手写时要自己循环设。
> 另外 `table.autofit` 必须为 False，否则宽度还是会被重算。

跨页的长表要重复表头，靠首行的 `w:tblHeader`（`add_table` 已自动设）：

```python
from docx_helpers import repeat_header_row
repeat_header_row(table)          # 手写表格补这一句，否则第二页只剩一堆数字
```

合并单元格：

```python
a = table.cell(0, 0); b = table.cell(0, 1)
a.merge(b)
```

单元格底纹用 `set_cell_shading(cell, "F2F6FA")`（python-docx 没有 API，要写 XML）。

## 5. 分隔线

```python
add_hr(doc)          # 段落下边框
```

> **不要用单行表格当分隔线** —— 会打断文字流，屏幕阅读器也读不对。

## 6. 图片

```python
add_image_fitted(doc, "scratch/trend.png", section=section, caption="图 1 分季度收入趋势")
```

它按版心宽度封顶等比缩放（只缩不放，小图保持原尺寸），避免图片撑出页面（体检会抓超宽图）。
图表先用 matplotlib 画成 PNG 存 `scratch/`，再插进来。

> matplotlib 画中文要先设字体，否则全是方框：
> ```python
> import matplotlib
> matplotlib.rc("font", family=["WenQuanYi Zen Hei", "Noto Sans CJK SC", "sans-serif"])
> matplotlib.rcParams["axes.unicode_minus"] = False
> ```
> 写成列表是因为不同机器装的中文字体不一样（镜像是文泉驿，有的机器只有 Noto）。

## 7. 列表

```python
doc.add_paragraph("第一项", style="List Bullet")
doc.add_paragraph("第一步", style="List Number")
```

> **不要手写 `•` 或 `1.`** —— 那是假列表，缩进和续行都不对。
> 写完记得 `set_run_font` 补中文字体（`add_paragraph(text, style=...)` 生成的 run 也要设）。

## 8. 分页与分节

```python
doc.add_page_break()

from docx.enum.section import WD_SECTION
new_section = doc.add_section(WD_SECTION.NEW_PAGE)   # 想换成横向就在新节里改
new_section.page_width, new_section.page_height = section.page_height, section.page_width
```

## 9. 页眉

```python
header = section.header
p = header.paragraphs[0]
set_run_font(p.add_run("XX 公司 · 内部资料"), active_profile()["caption"]["font"], 9, color="808080")
p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
```

## 10. 读已有文档

```python
doc = Document("uploads/原文.docx")
for p in doc.paragraphs:
    print(p.style.name, "|", p.text)
for t in doc.tables:
    for row in t.rows:
        print([c.text for c in row.cells])
```

改已有文档时：**只改需要改的 run**，不要整段重建 —— 重建会丢掉原有的字体、编号、批注关联。

```python
for p in doc.paragraphs:
    for r in p.runs:
        if "旧词" in r.text:
            r.text = r.text.replace("旧词", "新词")     # 保留该 run 的全部格式
```

> Word 会把一句话拆进很多个 `w:r`（拼写检查、修订标记都会拆），
> 所以你**看得见**的短语在 XML 里往往不是连续字符串。跨 run 的替换要先合并 run，
> 或退一步用整段重写 + 手动补格式。

## 11. 保存

```python
doc.save("output/2024年度经营分析报告.docx")
print("saved")
```
