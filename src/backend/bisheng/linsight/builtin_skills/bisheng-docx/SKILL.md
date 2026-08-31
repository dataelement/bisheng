---
name: bisheng-docx
description: >-
  制作或修改 Word 文档（.docx）时使用：撰写工作报告、分析报告、方案、纪要、通知、公文、
  合同初稿、说明书、简历、周报月报等正式文档；把已有内容整理成带标题层级、目录、页码、
  表格和图表的 Word 文件；读取、改写用户上传的 .docx。当用户说到「Word」「文档」「报告」
  「方案」「纪要」「公文」「通知」「说明书」「docx」「写一份 X」「整理成 Word」
  「导出成 Word」时触发。本技能给出 BiSheng 代码执行器里唯一可行的 python-docx 路径
  （该环境没有 Node/docx-js，中文字体必须显式写 w:eastAsia 才生效），
  内置 GB/T 9704-2012 公文版式为默认档，另有一档给简历宣传稿这类非公文文档；
  还包括目录页码写法、交付前自检与渲染脚本。
  本技能只负责版式落地：同时勾选了公文写作类技能时，文种、结构、文风、措辞以那个技能为准。
  只是把已经写好的回答原样存成 Word、不要求目录页码表格版式的，用 export_docx 更省事。
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

> 灵思自带 `export_docx`（markdown → Word）。**两者分工是硬的，选错路线是本技能最大的失败风险
> —— 动手前先看 §2 的边界表。** 一句话：只要「把刚才的内容存成 Word」用 `export_docx`；
> 要目录、页码、A4 版式、表格列宽、封面、或改用户上传的 .docx，才用本技能。

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
| 单次执行上限 | 本地执行器 **600 秒**，E2B 沙箱 **300 秒**。构建、体检、渲染分三次调用，不要挤在一次里 |
| E2B 沙箱 | 该模式下 `skills/` **结构性不可见**（文件快照早于技能物化）→ 调包内脚本必报 `FileNotFoundError`。出现这个报错就别再试包内脚本，把 cookbook §1 的 `w:eastAsia` 五行 XML 抄进构建脚本自己写 |
| 日志规则 | 执行器二选一：**退出码 0 只回 stdout，非 0 只回 stderr** → 一切诊断用 `print()`，子进程的 stdout/stderr 分两行都打出来 |
| 代码围栏 | 提交给执行器的代码里只要出现三反引号围栏，就**只执行围栏里的内容** —— 别在代码参数里贴 markdown |
| 可见性 | 退出码 0 时执行器会把本轮新增/修改的文件同步进工作区，之后 `ls`/`read_file` 一般能看到。判成功以 **退出码 0 + 日志**为准，不要反复找文件、更不要重做一遍 |
| 交付物排序 | `.md` 与 `.docx` **同为最高档**，同档比修改时间 → 后写的 `.md` 会直接压过 `.docx` 成为用户看到的头条。过程稿一律 `scratch/` |
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

## 2. 选路线（先划清与 `export_docx` 的边界）

`export_docx` 走的是 MarkDocx：读 `output/` 下的 markdown，纯 python-docx 转成 Word。
下面是它的实测产物特征 —— 对照着选，别凭感觉：

| 维度 | `export_docx` | 本技能 |
|---|---|---|
| 输入 | 只吃 `output/` 下的 **markdown**，单向 | 直接写 .docx，也能读改已有 .docx |
| 纸张 | **US Letter 21.6×27.9cm**（不是 A4），左右边距 3.2cm，改不了 | A4 纵/横随选，边距可调 |
| 标题 | 用内置 Heading 样式，中文字体已设（黑体/楷体） | 同样用内置 Heading，字体字号全可控 |
| 目录 / 页码 | **都没有**，也加不了 | `add_toc` + `add_page_number_footer` |
| 表格 | 宽度 auto，无表头底纹、无列宽、不重复表头 | 列宽写到每个单元格、表头按档（企业档深底白字 / 公文档素表加粗）、跨页重复表头 |
| 图片 | 固定 5.7 英寸宽 | 按版心等比缩放 + 图注 |
| 封面、分节、页眉、分隔线 | 没有 | 都有 |
| 代价 | 一次调用，零风险 | 写脚本 + 体检，2–4 轮 |

| 情况 | 做法 |
|---|---|
| 用户只要「把刚才的内容存成 Word」，没提版式要求 | `export_docx`，**不要用本技能** |
| 用户要目录 / 页码 / A4 / 表格列宽 / 封面 / 特定字体字号 | §3 从零构建 |
| 用户上传了 .docx 要改 | §5 改已有文件（`export_docx` 做不到） |
| 用户上传了模板要按样式填 | 用 `Document("uploads/模板.docx")` 打开**模板本身**，样式自动继承 |
| 还勾选了公文写作类技能 | §2.1：文种文风听它的，版式落地仍走本技能 |
| 拿不准 | 按用户原话里的名词判：出现「正式/对外/打印/汇报稿/公文/目录/页码」走本技能，否则走 `export_docx` |

### 2.1 定版式档（决定全篇字体字号，只需定一次）

本技能自带两档。`apply_chinese_defaults()` 选定后，`add_body` / `add_heading_cn` /
`add_table` / `add_toc` / 页码全部自动跟随，**不必逐处传字体**（逐处传的结果通常是
「大部分对、少数几处漏了」，这是本技能历史上最常见的翻车方式）。

| 档 | 什么时候用 | 取值 |
|---|---|---|
| **`gongwen`（默认）** | 公文、通知、报告、请示、函、纪要、制度办法，以及任何"正式行文" | GB/T 9704-2012：标题二号小标宋、正文三号仿宋_GB2312、一级黑体、二级楷体、行距固定 28 磅 → 读 `/skills/bisheng-docx/references/gongwen-gbt9704.md` |
| `modern` | 简历、宣传方案、对外提案、周报月报 —— **明确不是公文**的 | 微软雅黑 11pt 那一套 → 读 `/skills/bisheng-docx/references/design-zh.md` |

```python
apply_chinese_defaults(doc)                     # 公文档，默认，什么都不用做
apply_chinese_defaults(doc, profile="modern")   # 简历 / 宣传稿 / 周报
```

**同时勾选了其他公文技能时**（用户导入的某单位公文规范、gongwen-draft 之类），分工是硬的：

- **文种、结构、文风、措辞听它的；版式落地永远是本技能。**
- 它若给出了明确的字体字号（本单位模板要求华文中宋之类），把取值翻成 dict 传进来，
  **只写有差异的项**，其余自动沿用默认档：

  ```python
  apply_chinese_defaults(doc, profile={"body": {"font": "华文中宋"},
                                       "headings": {1: {"font": "方正小标宋简体"}}})
  ```

  ⚠️ **只改某一级标题就得用上面这种 dict 写法。** 图省事写 `heading_font="方正黑体简体"`
  会**一次覆盖全部四级**，二级标题的楷体_GB2312 跟着没了 —— 而"四级同为三号、靠字体区分层级"
  正是公文最核心的排版特征。对方只规定了一级标题时，其余几级保持默认档。

- 它没给版式取值就用默认公文档，**不要为此去翻它的一堆 references** —— 那会烧掉几轮还找不到。
- ❌ **不要调用其他技能的 Word 导出脚本**（`generate_docx.py`、`export.py` 之类）。
  它们多是给 Windows 桌面环境写的，在这里会因为"系统未安装公文字体"直接退出 ——
  而这个检查在本环境毫无意义：字体名只写进 XML，渲染发生在用户的 Word 里。

## 3. 从零构建

**第 1 步 · 定结构**。先把提纲写到 `scratch/outline.md`。
**提纲、草稿、任何 `.md` 都不许进 `output/`** —— `.md` 和 `.docx` 在交付物排序里同档、按修改时间比，
后写的 `.md` 会顶掉 `.docx` 成为用户看到的头条文件。定清楚几级标题、哪里要表、哪里要图。

**第 2 步 · 写构建脚本**。用 `write_file` 把完整脚本写到 `scratch/build_doc.py`，
**不要把整段代码塞进代码执行器的参数里** —— 参数过长会被截断，导致反复重试却总差一截。
写法读 `/skills/bisheng-docx/references/python-docx-cookbook.md`
（中文字体、标题、目录、页码、表格、图片、列表都有可直接抄的片段），
排版规范按 §2.1 定的档读：公文走 `references/gongwen-gbt9704.md`，
非公文走 `references/design-zh.md`。

骨架长这样：

```python
import sys, os
sys.path.insert(0, "skills/bisheng-docx/scripts")
from docx_helpers import setup_page, apply_chinese_defaults, add_heading_cn, add_body, \
                         add_table, add_toc, add_page_number_footer, add_gongwen_title, \
                         add_signature_block
from docx import Document

os.makedirs("output", exist_ok=True)
doc = Document()
apply_chinese_defaults(doc)        # ★ 必须调，且要在 setup_page 之前：定档（默认公文）
section = setup_page(doc)          # A4 纵向，页边距按档取（公文 3.7/3.5/2.8/2.6）

# —— 公文档 ——
add_gongwen_title(doc, "关于××××的通知")     # 标题：二号小标宋，不进目录
add_body(doc, "各有关部门：", indent=False)   # 主送机关顶格
add_body(doc, "正文……")                      # 自动左空二字
add_heading_cn(doc, "一、xxx", 1)             # 一级：三号黑体
add_heading_cn(doc, "（一）xxx", 2)           # 二级：三号楷体
add_signature_block(doc, "××××公司", "2026年8月27日")

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
set_run_font(run, "仿宋_GB2312", size_pt=16, bold=True)   # ✅
run.font.name = "仿宋_GB2312"                             # ❌ 中文不生效
```

`apply_chinese_defaults(doc)` 会按 §2.1 定的档把 Normal 和 Heading 1–4 一次性设好
（顺带关掉 Word 内置 Heading 4 的斜体）。用 `add_body` / `add_heading_cn` / `add_table`
写的内容自动就是对的，**不需要也不应该逐处传字体名**。体检脚本专门抓这条。

⚠️ 「用户机器可能没装仿宋_GB2312 / 方正小标宋简体」**不是弃用它们的理由**：
.docx 只把字体名写进 XML，渲染发生在用户的 Word 里，服务端装没装完全不影响产物。
公文字体是国标强制项 —— 换成微软雅黑等于交了一份不合规的公文。

## 5. 改用户上传的文档

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/inspect_docx.py",
                    "uploads/原文.docx", "--content-only"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

它按段落序号打印样式和文本、逐表打印内容，据此规划改哪里。然后：

- **只改需要改的 run**，不要整段重建 —— 重建会丢掉原有字体、编号、批注关联。
- 原文的样式约定压倒本技能的规范，跟着它走。
- ❌ **不要调 `apply_chinese_defaults()` 或 `setup_page()`。** 它们按当前版式档重写 Normal、
  Heading 1–4 和页边距 —— 默认档是公文，调一次就把用户原本微软雅黑的公司文档整份刷成三号仿宋。
  这两个函数只属于「从零构建」（§3）。
- 改完另存到 `output/`，不要覆盖 `uploads/` 里的原件。
- Word 会把一句话拆进多个 `w:r`，**看得见的短语在 XML 里未必是连续字符串** ——
  跨 run 的替换要先合并 run，或整段重写后手动补格式。

## 6. 交付前体检（必做）

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/inspect_docx.py", "output/xxx.docx"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

输出分两段：

- **`=== 内容 ===`**：页面尺寸、段落数、逐段样式与文本、逐表内容。用它核对错字、顺序、缺漏。
- **`=== 体检 ===`**：开头会先说明它**按哪个版式档校验**（公文 / 非公文，从文档自身推断）。
  ERROR 必须修完；WARN 逐条复核（确认无误可交付）；INFO 是建议。
  覆盖公文文档混入通用字体、中文字体缺 `w:eastAsia`（含样式继承链）、字号过小、标题层级跳级、表格超出版心、
  表格首行不像表头、长表不重复表头、图片超宽、目录域没开 updateFields、目录域下没有 Heading、
  残留占位符、段落里塞 `\n`、连续空段落、长文档缺页码域。

结尾固定是 `合计: x ERROR / y WARN / z INFO` 加一行结论。**ERROR 清零就会打出「结论: 通过」**，
看到它才算过关；没到就改 `scratch/build_doc.py` 重新生成再跑一次。不要为了消灭 WARN 无限返工。

**可选 · 看渲染图**：

⚠️ **仅在你确知当前模型支持读图时才做。** 这些 PNG 会被编成 base64 图片块发给厂商接口，
而默认的 Qwen/dashscope 通道已知不接收 base64 图片 —— 读图可能直接失败，甚至中断整个请求。
拿不准就跳过这一步，以体检结果为准。

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-docx/scripts/render_docx.py", "output/xxx.docx"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

它把每页渲染成 `scratch/preview/<名字>/page-01.png`，再用 `read_file` 逐张查看。
**渲染用的中文字体只有文泉驿正黑**，和用户 Word 里的实际字体宽度不同 ——
行长松紧只作参考，不要为了预览效果反复微调字号。
环境里没有 LibreOffice（.docx 走的是 Writer 组件）时脚本会直说，跳过这一步、以体检结果为准即可。

## 7. 交付纪律

- `output/` 里**只放最终的 `.docx`**。提纲、构建脚本、预览图、任何 `.md` 一律放 `scratch/`。
  **理由是硬的**：交付物排序里 `.md` 与 `.docx` 同为最高档、同档比修改时间，
  而过程稿总是后写的 → 一份 `output/outline.md` 会永久压在 `.docx` 前面当头条，
  用户点开看到的是草稿。`scratch/` 不会交付，但**跨轮追问会丢**（`output/`、`uploads/` 才会带到下一轮）。
- 文件名用有意义的中文名，如 `output/2024年度经营分析报告.docx`。
- 收尾时如实说明做了什么、多少页/多少节、有没有目录和页码。
  **不要声称生成了实际不存在的文件。**

## 8. 绝不要做的事

- ❌ 写 `require('docx')` 或任何 Node 脚本 —— 装不上，`npm install` 也会失败。
- ❌ 跑 `unzip`/`zip` 拆装 .docx —— 环境里没有这两个命令。要改 XML 用 Python 的 `zipfile`。
- ❌ `pip install` 任何东西。
- ❌ 给代码执行器的路径带前导斜杠（`/output/...`、`/skills/...`）。**两套命名空间别混**：
  `read_file` 读技能文档带斜杠（`/skills/bisheng-docx/references/design-zh.md`），
  代码执行器里的路径一律不带（`skills/bisheng-docx/scripts/inspect_docx.py`、`output/x.docx`）。
- ❌ 只写 `run.font.name` 就以为中文字体设好了。
- ❌ 因为「用户机器上可能没装仿宋_GB2312 / 方正小标宋简体」就换成微软雅黑、宋体。
  字体名只写进 XML，渲染在用户的 Word 里 —— 服务端装没装不影响产物，公文字体是国标强制项。
- ❌ 用手写的 `•` / `1.` 当列表，用 `\n` 当换行。
- ❌ 用单行表格画分隔线（用 `add_hr`）。
- ❌ 把文档降级成 Markdown 或 PDF 交付。用户要的是 .docx。
- ❌ 退出码 0、日志已写明 saved，却因为一时没看到文件就重做一遍。
