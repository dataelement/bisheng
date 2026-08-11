---
name: bisheng-xlsx
description: >-
  制作或修改 Excel 表格（.xlsx）时使用：从零搭建数据表、明细表、汇总表、预算表、财务模型、
  测算表、报价单、台账、看板底表；把整理好的数据导出成带公式和格式的工作簿；读取、清洗、
  改写用户上传的 .xlsx/.xls/.csv。当用户说到「Excel」「表格」「工作簿」「xlsx」「报表」「台账」
  「预算表」「测算」「明细表」「数据透视」「导出成表」，或提出「把这些数据做成 Excel」
  「按这个模板填一张表」「帮我算一下并出个表」时触发。本技能给出 BiSheng 代码执行器里
  唯一可行的 openpyxl 路径（该环境没有 markitdown，公式必须用 LibreOffice 重算才有值），
  以及中文表格规范、审计配色、公式禁用清单、交付前的重算与体检脚本。
  如果用户要的是图表图片、Word 文档或 PPT，不要用本技能。
metadata:
  display-name: Excel 表格制作（BiSheng 适配）
---

# 在 BiSheng 里做 XLSX

## 0. 开工纪律

**这一轮只读文档，不要在同一轮里并行调用别的工具。** 读完本文件（必要时再读 references）之后，
下一轮才开始动手。把「读 SKILL.md」和「产出交付物」放进同一轮并行调用，等于技能没读。

**本技能要求已勾选代码执行器（`bisheng_code_interpreter`）。** 没有它就无法生成 .xlsx ——
直接告诉用户「请在工具里勾选代码执行器后重试」，不要用 Markdown 表格顶替。

## 1. 环境事实（照做，不要试探）

| 项 | 事实 |
|---|---|
| **生成方式** | **只有 `openpyxl`**（后端 `pyproject.toml` 的正式依赖），`import openpyxl` 直接可用 |
| **公式重算** | 靠 LibreOffice（`soffice`）。**openpyxl 写出的公式没有值**，不重算等于交了张空表 |
| 不存在的东西 | `markitdown`、Node/npm、`defusedxml`、`xlsxwriter` 的部分高级特性、`pdftoppm`、`zip`/`unzip` 命令 |
| 其它可用库 | pandas/numpy、Pillow、PyMuPDF(`fitz`)、matplotlib、python-docx、python-pptx、lxml |
| 禁止 | `pip install`、`npm install`、任何联网假设（生产多为离线内网） |
| 工作目录 | 执行器 cwd = 工作区根，**一律用相对路径** |
| `output/` | 唯一交付区 |
| `scratch/` | 中间产物区，**不会交付**，需自己 `os.makedirs` |
| `uploads/` | 用户上传的原件在这里 |
| `skills/bisheng-xlsx/` | 本技能包，脚本和参考资料在这里，只读 |
| 绝对禁止 | 写 `/output/xxx.xlsx` 这种带前导斜杠的路径 —— 文件被静默丢弃，用户拿不到 |
| 单次执行上限 | 600 秒。构建、重算、体检分多次调用 |
| 日志规则 | **成功时只回传 stdout，stderr 被丢弃** → 一切诊断用 `print()` |
| 可见性 | 代码执行器写的文件**不会**出现在 `ls`/`glob` 结果里。`exitcode 0` + 日志确认即视为已产出，**不要反复找文件** |
| 轮次 | 最后两轮代码执行器会被摘除 → 表要尽早产出，不要拖到收尾 |

### 1.1 先探一次环境（第一次执行代码时顺手做，只花一轮）

```python
import shutil
try:
    import openpyxl
    print("openpyxl OK", openpyxl.__version__)
except ImportError:
    print("openpyxl MISSING")
print("soffice:", shutil.which("soffice") or "无 —— 公式无法重算，见 §4 降级方案")
```

- `openpyxl MISSING`：正常部署不会出现。**不要 `pip install`**（共享的离线环境，装了会污染所有租户）。
  如实告诉用户环境缺依赖，需要运维补装。
- `soffice` 没有、或重算时报「没有 Calc 组件」：见 §4 的降级方案，**不要假装重算过了**。

## 2. 选路线

| 情况 | 做法 |
|---|---|
| 用户给了数据（或让你先查再整理），要一张新表 | §3 从零构建 |
| 用户上传了 .xlsx 要改内容 / 填数 | §5 改已有文件（**先读懂它的约定，再动手**） |
| 用户上传了 .csv/.xls 要清洗成规范表 | pandas 读进来清洗 → 按 §3 写出 |
| 用户要的是图表图片、Word、PPT | 不属于本技能 |

## 3. 从零构建

**第 1 步 · 定结构**。先想清楚分几个表、每个表的列。复杂测算把假设单独放一个表。
草稿写 `scratch/`，**不要写进 `output/`** —— 同一轮往 `output/` 放 `.md` 会让它顶掉 `.xlsx`
成为用户看到的头条交付物。

**第 2 步 · 写构建脚本**。用 `write_file` 把完整脚本写到 `scratch/build_sheet.py`，
**不要把整段代码塞进代码执行器的参数里** —— 参数过长会被截断，导致反复重试却总差一截。
写法读 `/skills/bisheng-xlsx/references/openpyxl-cookbook.md`（表格、样式、数字格式、公式、
图表、批注都有可直接抄的片段），规范读 `/skills/bisheng-xlsx/references/design-zh.md`。

**第 3 步 · 执行**：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "scratch/build_sheet.py"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

> 为什么不直接写 `python scratch/build_sheet.py`：PATH 里的 `python` 未必是后端那个解释器，
> 用 `sys.executable` 才能保证跑在装了 openpyxl 的环境里。**下面所有脚本调用都用这个写法。**

**第 4 步 · 重算（有公式就必做）**，见 §4。
**第 5 步 · 体检并返修**，见 §6。返修用 `edit_file` 定点改 `scratch/build_sheet.py` 再重跑，
不要每次重写整份脚本。

## 4. 重算公式（有公式就必做）

openpyxl 写出的公式**只是字符串，没有结果**。不重算的话，pandas、`data_only=True`、
以及多数预览器读到的全是空 —— 用户打开看到的是一张有公式没数字的表。

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-xlsx/scripts/recalc_check.py", "output/xxx.xlsx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

LibreOffice 会算完所有公式、**就地重写文件**，然后脚本回读并列出所有错误单元格。
看结论：

- `结论: 通过` —— 公式都能算出结果。
- `结论: 不通过` + 错误单元格清单 —— 逐个改完再重算。
- `[未重算]` —— 环境问题（没有 soffice、或只装了 writer 没装 calc、或超时）。**这时不要硬撑**：
  改成在 Python 里把数算好直接写数值，并在表里用一列文字说明计算口径，
  同时如实告诉用户「本环境无法重算公式，已改为写入计算结果，修改输入不会自动重算」。

> **能算 ≠ 算对。** 区间差一行、引用错行，照样是一张干净的错数字表。
> 铺开整张表之前，先写 2–3 个关键公式，重算一次，肉眼核对结果符不符合预期。

## 5. 改用户上传的表

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-xlsx/scripts/inspect_workbook.py",
                    "uploads/原表.xlsx", "--content-only"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

它按单元格坐标打印内容和公式（这是 `markitdown` 在本环境的替代品，而且比它多给坐标，
所以可以据此规划改哪一格）。然后：

- **原表的约定压倒本技能的一切规范** —— 它用什么字体、什么数字格式、什么配色，就跟着它。
- **先找到它的输入格**（通常有独特的字色或填充），只在那里写值，**不要动任何已有公式**。
- 用默认方式 `load_workbook(path)` 打开（**不要加 `data_only=True`**，那样保存会把公式全变成字面量）。
- `.xlsm` 要 `keep_vba=True`，否则宏全丢。
- 改完另存到 `output/`，不要覆盖 `uploads/` 里的原件。
- **不要给别人的表加示例行。**

## 6. 交付前体检（必做）

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-xlsx/scripts/inspect_workbook.py", "output/xxx.xlsx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

输出分两段：

- **内容**：逐表逐格打印，公式旁边跟着重算后的值。用它核对数字对不对、有没有缺漏。
- **体检**：ERROR 必须修完再交付；WARN 逐条复核；INFO 是建议。
  覆盖禁用函数、`_xlfn.` 前缀、跨表引用引号、百分比存法、公式无缓存值、列宽不足导致 `###`、
  合并区丢值、年份千分位、残留占位符、硬编码系数。

改完重新生成 → 重算 → 再体检，直到「结论: 通过」。

## 7. 公式红线（体检会拦，但你一开始就别写）

- ❌ **`XLOOKUP` / `XMATCH` / `SORT` / `FILTER` / `UNIQUE` / `SEQUENCE` / `LET` / `LAMBDA`**
  —— openpyxl 写不出溢出元数据，LibreOffice 要么报 `#NAME?`，要么只填左上角一个值
  **而且重算报 0 错误**。查表用 `INDEX`/`MATCH`；排序、去重、筛选在 Python 里做完再写值。
- ⚠️ **`TEXTJOIN` / `CONCAT` / `IFS` / `SWITCH` / `MAXIFS` / `MINIFS` 必须带 `_xlfn.` 前缀**，
  裸写 → `#NAME?`。
- ⚠️ 表名含空格的跨表引用必须加单引号：`='假设 输入'!$B$5`。用 `sheet_ref()` 自动处理。
- ⚠️ 百分比存小数（0.15 = 15%）。用 `set_pct()`，它会在你传 15 时直接报错。

## 8. 交付纪律

- `output/` 里**只放最终的 `.xlsx`**。草稿、构建脚本、中间版本一律放 `scratch/`。
- 文件名用有意义的中文名，如 `output/2024年度经营分析.xlsx`。
- 收尾时如实说明做了什么、几个表、多少行、公式是否已重算。
  **不要声称生成了实际不存在的文件。**
- 如果因为环境限制改成了写死数值，必须在收尾里明确说出来。

## 9. 绝不要做的事

- ❌ 跑 `markitdown` 读表 —— 环境里没有，用 §5 的 `--content-only`。
- ❌ `pip install` 任何东西。
- ❌ 用绝对路径 `/output/...`。
- ❌ 有公式却不重算就交付。
- ❌ 把表降级成 Markdown 表格或 CSV 交付。用户要的是 .xlsx。
- ❌ `load_workbook(..., data_only=True)` 之后 `save()` —— 会永久毁掉所有公式。
- ❌ 因为 `ls` 看不到刚生成的文件就重做一遍。
