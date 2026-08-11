---
name: bisheng-docx
description: >-
  制作或修改 Word 文档（.docx）时使用：撰写工作报告、分析报告、方案、纪要、通知、公文、
  合同初稿、说明书、简历、周报月报等正式文档；把已有内容整理成带标题层级、目录、页码、
  表格和图表的 Word 文件；读取、改写用户上传的 .docx。当用户说到「Word」「文档」「报告」
  「方案」「纪要」「公文」「通知」「说明书」「docx」「写一份 X」「整理成 Word」
  「导出成 Word」时触发。本技能给出 BiSheng 代码执行器里唯一可行的 python-docx 路径
  （该环境没有 Node/docx-js，中文字体必须显式写 w:eastAsia 才生效），
  以及中文排版规范、目录页码写法、交付前自检与渲染脚本。
  如果用户要的是 Excel 表格、PPT 或纯 Markdown，不要用本技能。
metadata:
  display-name: Word 文档制作（BiSheng 适配）
---

# 在 BiSheng 里做 DOCX

## 0. 开工纪律

**这一轮只读文档，不要在同一轮里并行调用别的工具。** 读完本文件（必要时再读 references）之后，
下一轮才开始动手。把「读 SKILL.md」和「产出交付物」放进同一轮并行调用，等于技能没读。

**本技能要求已勾选代码执行器（`bisheng_code_interpreter`）。** 没有它就无法生成 .docx ——
直接告诉用户「请在工具里勾选代码执行器后重试」。

> 灵思自带 `export_docx` 能把回答导出成 Word。**两者不冲突**：用户只要一份"把刚才的内容存成
> Word"，用 `export_docx` 更省事；用户要的是有标题层级、目录、页码、表格样式的**正式文档**，
> 才用本技能。判断不了就问一句。

## 1. 环境事实（照做，不要试探）

| 项 | 事实 |
|---|---|
| **生成方式** | **只有 `python-docx`**（后端 `pyproject.toml` 的正式依赖），`import docx` 直接可用 |
| **中文字体** | `run.font.name` 只管西文；中文必须写 `w:eastAsia`。用本技能包的 `set_run_font()` |
| 不存在的东西 | Node/npm/`docx-js`、`markitdown`、`defusedxml`、`pdftoppm`、`zip`/`unzip` 命令 |
| 可能没有 | `pandoc`（发布镜像有，手工部署的机器未必）、`soffice`（只影响可选的渲染预览） |
| 其它可用库 | pandas/numpy、Pillow、PyMuPDF(`fitz`)、matplotlib、openpyxl、python-pptx、lxml |
| 禁止 | `pip install`、`npm install`、任何联网假设（生产多为离线内网） |
| 工作目录 | 执行器 cwd = 工作区根，**一律用相对路径** |
| `output/` | 唯一交付区 |
| `scratch/` | 中间产物区，**不会交付**，需自己 `os.makedirs` |
| `uploads/` | 用户上传的原件在这里 |
| `skills/bisheng-docx/` | 本技能包，脚本和参考资料在这里，只读 |
| 绝对禁止 | 写 `/output/xxx.docx` 这种带前导斜杠的路径 —— 文件被静默丢弃，用户拿不到 |
| 单次执行上限 | 600 秒。构建、体检、渲染分多次调用 |
| 日志规则 | **成功时只回传 stdout，stderr 被丢弃** → 一切诊断用 `print()` |
| 可见性 | 代码执行器写的文件**不会**出现在 `ls`/`glob` 结果里。`exitcode 0` + 日志确认即视为已产出，**不要反复找文件** |
| 轮次 | 最后两轮代码执行器会被摘除 → 文档要尽早产出，不要拖到收尾 |

### 1.1 先探一次环境（第一次执行代码时顺手做，只花一轮）

```python
import shutil
try:
    import docx
    print("python-docx OK")
except ImportError:
    print("python-docx MISSING")
print("soffice:", shutil.which("soffice") or "无（只影响可选的渲染预览，不影响生成）")
print("pandoc :", shutil.which("pandoc") or "无（读 .docx 用 inspect_docx.py 即可）")
```

`python-docx MISSING` 正常部署不会出现。**不要 `pip install`**（共享的离线环境，装了会污染所有租户），
如实告诉用户环境缺依赖、需要运维补装。

## 2. 选路线

| 情况 | 做法 |
|---|---|
| 用户要一份新文档 | §3 从零构建 |
| 用户上传了 .docx 要改 | §5 改已有文件 |
| 用户上传了模板要按样式填 | 用 `Document("uploads/模板.docx")` 打开**模板本身**，样式自动继承 |
| 用户只想把刚才的回答存成 Word | 用 `export_docx`，不用本技能 |

## 3. 从零构建

**第 1 步 · 定结构**。先把提纲写到 `scratch/outline.md`（**不要写进 `output/`**）。
定清楚几级标题、哪里要表、哪里要图。

**第 2 步 · 写构建脚本**。用 `write_file` 把完整脚本写到 `scratch/build_doc.py`，
**不要把整段代码塞进代码执行器的参数里** —— 参数过长会被截断，导致反复重试却总差一截。
写法读 `/skills/bisheng-docx/references/python-docx-cookbook.md`
（中文字体、标题、目录、页码、表格、图片、列表都有可直接抄的片段），
排版规范读 `/skills/bisheng-docx/references/design-zh.md`。

骨架长这样：

```python
import sys, os
sys.path.insert(0, "skills/bisheng-docx/scripts")
from docx_helpers import setup_page, apply_chinese_defaults, add_heading_cn, add_body, \
                         add_table, add_toc, add_page_number_footer
from docx import Document

os.makedirs("output", exist_ok=True)
doc = Document()
section = setup_page(doc)          # A4 纵向
apply_chinese_defaults(doc)        # ★ 必须调：设好中文字体和标题样式
add_heading_cn(doc, "标题", 1)
add_toc(doc)                       # 3 页以上才需要
add_heading_cn(doc, "一、xxx", 2)
add_body(doc, "正文……")
add_page_number_footer(section)
doc.save("output/xxx.docx")
print("saved")
```

**第 3 步 · 执行**：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "scratch/build_doc.py"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

> 为什么不直接写 `python scratch/build_doc.py`：PATH 里的 `python` 未必是后端那个解释器，
> 用 `sys.executable` 才能保证跑在装了 python-docx 的环境里。**下面所有脚本调用都用这个写法。**

**第 4 步 · 体检并返修**（§6）。返修用 `edit_file` 定点改 `scratch/build_doc.py` 再重跑，
不要每次重写整份脚本。

## 4. ★ 中文字体（最容易出的错）

`run.font.name = "微软雅黑"` **对中文完全无效** —— 它只写 `w:ascii`/`w:hAnsi`（西文），
中文由 `w:eastAsia` 决定。不设的话中文退回主题字体，用户打开就是"字体乱了"。

```python
from docx_helpers import set_run_font
set_run_font(run, "微软雅黑", size_pt=11, bold=True)     # ✅
run.font.name = "微软雅黑"                                # ❌ 中文不生效
```

`apply_chinese_defaults(doc)` 会把 Normal 和 Heading 1–4 一次性设好（顺带关掉 Word 内置
Heading 4 的斜体）。用 `add_body` / `add_heading_cn` 写的内容自动就是对的。
体检脚本专门抓这条。

## 5. 改用户上传的文档

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/inspect_docx.py",
                    "uploads/原文.docx", "--content-only"], capture_output=True, text=True)
print(r.stdout or r.stderr)
```

它按段落序号打印样式和文本、逐表打印内容，据此规划改哪里。然后：

- **只改需要改的 run**，不要整段重建 —— 重建会丢掉原有字体、编号、批注关联。
- 原文的样式约定压倒本技能的规范，跟着它走。
- 改完另存到 `output/`，不要覆盖 `uploads/` 里的原件。
- Word 会把一句话拆进多个 `w:r`，**看得见的短语在 XML 里未必是连续字符串** ——
  跨 run 的替换要先合并 run，或整段重写后手动补格式。

## 6. 交付前体检（必做）

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/inspect_docx.py", "output/xxx.docx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

输出分两段：

- **内容**：页面尺寸、段落数、逐段样式与文本、逐表内容。用它核对错字、顺序、缺漏。
- **体检**：ERROR 必须修完再交付；WARN 逐条复核；INFO 是建议。
  覆盖中文字体缺 `w:eastAsia`、标题层级跳级、表格超出版心、图片超宽、
  目录域没开 updateFields、残留占位符、段落里塞 `\n`、连续空段落。

改完重新生成，再跑一次，直到「结论: 通过」。

**可选 · 看渲染图**（模型支持读图时才有意义）：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/render_docx.py", "output/xxx.docx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

它把每页渲染成 `scratch/preview/<名字>/page-01.png`，再用 `read_file` 逐张查看。
**渲染用的中文字体只有文泉驿正黑**，和用户 Word 里的实际字体宽度不同 ——
行长松紧只作参考，不要为了预览效果反复微调字号。
环境里没有 LibreOffice 时脚本会直说，跳过这一步、以体检结果为准即可。

## 7. 交付纪律

- `output/` 里**只放最终的 `.docx`**。提纲、构建脚本、预览图一律放 `scratch/`。
  （`.md` 和 `.docx` 在交付物排序里同级，往 `output/` 放草稿会挤在一起让用户困惑。）
- 文件名用有意义的中文名，如 `output/2024年度经营分析报告.docx`。
- 收尾时如实说明做了什么、多少页/多少节、有没有目录和页码。
  **不要声称生成了实际不存在的文件。**

## 8. 绝不要做的事

- ❌ 写 `require('docx')` 或任何 Node 脚本 —— 装不上，`npm install` 也会失败。
- ❌ 跑 `unzip`/`zip` 拆装 .docx —— 环境里没有这两个命令。要改 XML 用 Python 的 `zipfile`。
- ❌ `pip install` 任何东西。
- ❌ 用绝对路径 `/output/...`。
- ❌ 只写 `run.font.name` 就以为中文字体设好了。
- ❌ 用手写的 `•` / `1.` 当列表，用 `\n` 当换行。
- ❌ 用单行表格画分隔线（用 `add_hr`）。
- ❌ 把文档降级成 Markdown 或 PDF 交付。用户要的是 .docx。
- ❌ 因为 `ls` 看不到刚生成的文件就重做一遍。
