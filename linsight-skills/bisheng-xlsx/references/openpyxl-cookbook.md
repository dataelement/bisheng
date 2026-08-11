# openpyxl 速查（BiSheng 适配）

可直接抄的片段。所有代码假定在**构建脚本**里（`scratch/build_sheet.py`），由代码执行器用
`subprocess.run([sys.executable, "scratch/build_sheet.py"])` 跑。

开头统一这样起：

```python
import sys
sys.path.insert(0, "skills/bisheng-xlsx/scripts")   # 本技能包的 helper
from xlsx_helpers import (
    write_table, autofit_columns, style_header, freeze_and_filter,
    mark_input, mark_formula, mark_assumption, add_note, set_pct, sheet_ref,
    add_legend, FMT, FONT_NAME,
)
from openpyxl import Workbook, load_workbook
import os
os.makedirs("output", exist_ok=True)
os.makedirs("scratch", exist_ok=True)
```

---

## 1. 新建 / 打开 / 保存

```python
wb = Workbook()
ws = wb.active
ws.title = "利润预测"            # 表名 ≤31 字符，不能含 : \ / ? * [ ]
ws2 = wb.create_sheet("假设")     # 追加
ws3 = wb.create_sheet("封面", 0)  # 插到最前

wb.save("output/2024年度经营分析.xlsx")
```

打开已有文件 —— **读一个模型要加载两次**，一次拿公式一次拿值，一次加载给不了两者：

```python
wb_f = load_workbook("uploads/原表.xlsx")                  # 公式字符串，无值
wb_v = load_workbook("uploads/原表.xlsx", data_only=True)  # 缓存值，无公式
```

> ⚠️ **`data_only=True` 打开后再 `save()` 会永久毁掉公式** —— 保存下去的是一堆字面量。
> 要改文件就用默认方式打开。
> ⚠️ `.xlsm` 必须 `load_workbook(path, keep_vba=True)`，否则宏全丢。

## 2. 写单元格

```python
ws["A1"] = "项目"
ws.cell(row=2, column=1, value="主营业务收入")     # 行列号从 1 开始
ws["B2"] = 12500000
ws["B3"] = "=SUM(B4:B9)"                          # 以 = 开头即公式
```

批量写一行：

```python
for r, (name, amount) in enumerate(data, start=2):
    ws.cell(row=r, column=1, value=name)
    ws.cell(row=r, column=2, value=amount).number_format = FMT["money"]
```

## 3. 数字格式（最容易出错的地方）

```python
cell.number_format = FMT["money"]   # #,##0;(#,##0);-   负数括号、0 显示为 -
cell.number_format = FMT["pct"]     # 0.0%
cell.number_format = FMT["mult"]    # 0.0x
cell.number_format = FMT["date"]    # yyyy-mm-dd
cell.number_format = "@"            # 文本（年份用它，避免 2,024）
```

**百分比必须存小数**：15% 存 `0.15`，存 `15` 会显示成 `1500.0%`。
用 `set_pct(cell, 0.15)`，它会在你传 15 时直接报错而不是默默出个错 100 倍的表。

```python
set_pct(ws["C2"], 0.152)          # 显示 15.2%
ws["E2"] = "2024"                 # 年份写成字符串，或 number_format="@"
```

## 4. 表格（一次搞定表头 + 数据 + 格式 + 边框）

```python
first, last = write_table(
    ws,
    headers=["项目", "2024年", "2025E", "增长率"],
    rows=[["营业收入", 12500000, 14200000, 0.136],
          ["营业成本",  8200000,  9100000, 0.110]],
    start_row=3,
    number_format={1: "money", 2: "money", 3: "pct"},   # 键是**列偏移**，从 0 数
)
ws.cell(row=last + 1, column=1, value="合计")
ws.cell(row=last + 1, column=2, value=f"=SUM(B{first}:B{last})").number_format = FMT["money"]

autofit_columns(ws)          # 中文按双宽算，避免 ###
freeze_and_filter(ws, header_row=3)
```

## 5. 样式

```python
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

cell.font = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
cell.fill = PatternFill("solid", fgColor="1F4E79")
cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

thin = Side(style="thin", color="BFBFBF")
cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)

ws.column_dimensions["A"].width = 24     # 单位≈半角字符数
ws.row_dimensions[1].height = 22
```

**审计配色**（财务模型必守，见 design-zh.md §2）：

```python
mark_input(ws["B2"], note="来源：2024 年报 P32")   # 蓝字 = 人填的硬编码 + 批注写来源
mark_formula(ws["B3"])                            # 黑字 = 公式
mark_assumption(ws["B6"], note="管理层给定")       # 黄底蓝字 = 关键假设/待用户填
```

## 6. 合并单元格

```python
ws.merge_cells("A1:D1")
ws["A1"] = "2024 年度经营分析"        # 只写左上角！
```

> 合并区内**除左上角外都是 `MergedCell`，`.value` 只读**，写进去会丢。先写值再合并也一样。

## 7. 公式：哪些能用，哪些是坑

| 类别 | 结论 |
|---|---|
| `SUM` `SUMIFS` `INDEX` `MATCH` `IFERROR` `SUMPRODUCT` `VLOOKUP` | ✅ 直接用 |
| `TEXTJOIN` `CONCAT` `IFS` `SWITCH` `MAXIFS` `MINIFS` | ⚠️ **必须写 `_xlfn.` 前缀**，如 `=_xlfn.TEXTJOIN(",",TRUE,A2:A9)`。裸写 → `#NAME?` |
| `XLOOKUP` `XMATCH` `SORT` `FILTER` `UNIQUE` `SEQUENCE` `LET` `LAMBDA` | ❌ **绝对不要用**。见下 |
| 数组公式 / 动态数组 | ❌ openpyxl 写不出溢出元数据 |

**为什么 XLOOKUP 那一组是硬禁**：openpyxl 写出的文件没有溢出（spill）元数据，
LibreOffice 要么算不出（`#NAME?`），要么只给左上角一个值 —— 而**重算脚本会报 `total_errors: 0`**，
体检也就查不出来，用户打开才发现半张表是空的。查表一律用 `INDEX`/`MATCH`；
排序、去重、筛选**在 Python 里做完再写值**。

跨表引用用 helper，它会按需加引号：

```python
ws["B2"] = sheet_ref("假设 输入", "$B$5")   # → ='假设 输入'!$B$5
```

> 表名含空格却不加引号 → `#VALUE!`。纯中文表名不用加引号，但加了也无害。

保护除法：

```python
ws["D2"] = "=IFERROR(B2/C2,0)"
```

## 8. 批注（假设的来源写这里）

```python
add_note(ws["B6"], "假设：2025 年收入增速 13.6%\n来源：管理层 2025 预算，2025-01 版")
```

## 9. 图表（原生图表，用户可以改数据）

```python
from openpyxl.chart import BarChart, LineChart, Reference

chart = BarChart()
chart.title = "分季度收入"
chart.y_axis.title = "金额（元）"
data = Reference(ws, min_col=2, min_row=3, max_row=last)       # 含表头行则 titles_from_data=True
cats = Reference(ws, min_col=1, min_row=4, max_row=last)
chart.add_data(data, titles_from_data=True)
chart.set_categories(cats)
chart.width, chart.height = 18, 9      # 厘米
ws.add_chart(chart, "F3")
```

> 原生图表比贴 matplotlib 图片好：用户改了数字图会跟着变。只有需要复杂可视化时才退回图片。

## 10. 插入图片

```python
from openpyxl.drawing.image import Image
img = Image("scratch/trend.png")
img.width, img.height = 480, 270        # 像素
ws.add_image(img, "H3")
```

> 图片文件在保存前不能删；`Image` 是懒加载的。

## 11. 条件格式与数据验证

```python
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule
from openpyxl.worksheet.datavalidation import DataValidation

ws.conditional_formatting.add(
    "D4:D20", CellIsRule(operator="lessThan", formula=["0"], font=Font(color="FF0000")))
ws.conditional_formatting.add(
    "B4:B20", ColorScaleRule(start_type="min", start_color="FFFFFF",
                             end_type="max", end_color="63BE7B"))

dv = DataValidation(type="list", formula1='"是,否"', allow_blank=True)
ws.add_data_validation(dv)
dv.add("E4:E20")
```

## 12. 页面设置（要打印时才需要）

```python
ws.page_setup.orientation = "landscape"
ws.page_setup.fitToWidth = 1
ws.sheet_properties.pageSetUpPr.fitToPage = True
ws.print_title_rows = "1:3"      # 每页重复表头
```

## 13. 读已有表做分析

```python
wb = load_workbook("uploads/数据.xlsx", data_only=True, read_only=True)
ws = wb["Sheet1"]
rows = list(ws.iter_rows(min_row=2, values_only=True))
wb.close()
```

> `read_only=True` 读大文件省内存，但拿不到样式，也不能写。

pandas 也在，批量数据进出更省事：

```python
import pandas as pd
df = pd.read_excel("uploads/数据.xlsx", sheet_name="明细")
df.to_excel("output/清洗后.xlsx", index=False)      # 但样式要用 openpyxl 再补
```
