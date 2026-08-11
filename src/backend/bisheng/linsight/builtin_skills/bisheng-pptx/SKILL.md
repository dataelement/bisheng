---
name: bisheng-pptx
description: >-
  制作 PowerPoint 演示文稿（.pptx）时使用：从零创建企业介绍、工作汇报、项目方案、产品发布、培训课件等幻灯片；
  按用户提供的模板（.pptx/.potx）套版生成；读取或改写已有 PPT。当用户说到「PPT」「幻灯片」「演示文稿」「汇报材料」
  「宣讲材料」「课件」「deck」「slides」「pptx」，或提出「做一个介绍 X 的 PPT」「按这个模板做一版」
  「把这份材料做成 PPT」时触发。本技能给出 BiSheng 代码执行器里唯一可行的 python-pptx 生成路径
  （该环境没有 Node/pptxgenjs/markitdown/LibreOffice 命令行默认配置），以及中文排版规范、模板套用方法、
  交付前自检脚本。如果用户明确要的是网页翻页式 HTML 演示而不是 .pptx 文件，不要用本技能。
metadata:
  display-name: PPT 制作（BiSheng 适配）
---

# 在 BiSheng 里做 PPTX

## 0. 开工纪律

**这一轮只读文档，不要在同一轮里并行调用别的工具。** 读完本文件（必要时再读 references）之后，
下一轮才开始动手。曾经发生过模型把「读 SKILL.md」和「产出交付物」放进同一轮并行调用，
结果技能等于没读、产出完全跑偏。

**本技能要求已勾选代码执行器（`bisheng_code_interpreter`）。** 没有它就无法生成 .pptx —— 这种情况下
直接告诉用户「请在工具里勾选代码执行器后重试」，不要用 export_docx / export_pdf 拿 Word 或 PDF 顶替。

## 1. 环境事实（照做，不要试探）

| 项 | 事实 |
|---|---|
| **生成方式** | **只有 `python-pptx`**。它是后端 `pyproject.toml` 的正式依赖（main / 2.6 / 3.0 各线都有），`import pptx` 直接可用 |
| 不存在的东西 | Node / npm / `pptxgenjs`、`markitdown`、`defusedxml`、`pdfplumber`/`pdfminer`/`PyPDF2`、`pandoc` 转 pptx |
| 其它可用库 | Pillow（图片）、PyMuPDF(`fitz`)（读 PDF/渲染）、matplotlib（图表图片）、pandas/numpy、openpyxl、python-docx、lxml |
| 禁止 | `pip install`、`npm install`、任何联网假设（生产多为离线内网） |
| 工作目录 | 执行器 cwd = 工作区根，**一律用相对路径** |
| `output/` | 唯一交付区，已自动创建 |
| `scratch/` | 中间产物区，**不会交付**，需自己 `os.makedirs` |
| `uploads/` | 用户上传的原件（模板、素材、资料）在这里 |
| `skills/bisheng-pptx/` | 本技能包，脚本和参考资料在这里，只读 |
| 绝对禁止 | 写 `/output/xxx.pptx` 这种带前导斜杠的路径 —— 文件会被静默丢弃，用户拿不到 |
| 单次执行上限 | 600 秒。构建 + 自检分多次调用，不要挤在一次里 |
| 日志规则 | **成功时只回传 stdout，stderr 被丢弃** → 一切诊断信息用 `print()`，不要只靠 warning |
| 可见性 | 执行器写完会把产物同步到工作区，之后 `ls`/`read_file` 一般能看到。但判成功看**执行结果**：`exitcode 0` + 日志确认写成功即视为已产出，**不要反复找文件、更不要重做一遍** |
| 轮次 | 最后两轮代码执行器会被摘除 → PPT 必须尽早产出，不要拖到收尾 |

### 1.1 先探一次环境（第一次执行代码时顺手做，只花一轮）

```python
import shutil
try:
    import pptx
    print("python-pptx OK", getattr(pptx, "__version__", ""))
except ImportError:
    print("python-pptx MISSING")
print("soffice:", shutil.which("soffice") or shutil.which("libreoffice") or "无（只影响预览渲染，不影响生成）")
```

- `python-pptx MISSING`：正常部署不会出现（它是后端的正式依赖，已在 116 / 180 等环境实测存在）。
  真遇到就是这套环境被裁剪过 —— **不要 `pip install`**（共享的离线环境，装了会污染所有租户）。
  直接告诉用户「当前环境缺少 python-pptx，无法生成 .pptx，需要运维在后端环境补装」，
  并问他是否接受改为其它形式的交付物。不要假装做出来了。
- `soffice` 没有、或后面渲染时报「无法加载源文件」：说明这台机器的 LibreOffice 没装 Impress 组件。
  **只影响 §5 的可选预览渲染，不影响 .pptx 的生成与交付** —— 跳过看图那一步，以体检结果为准即可。

## 2. 选路线

| 情况 | 做法 |
|---|---|
| 用户没给模板，要一份新 PPT | §3 从零创建 |
| 用户上传了 .pptx/.potx 模板，或说「按这个样式/模板做」 | §4 套用模板（**优先级最高，别自己另起炉灶**） |
| 用户上传了已有 PPT 要改内容 | 先 §5 的 `inspect_deck.py` 把内容读出来，再按 §4 的方式打开原文件改写 |
| 用户要的是网页翻页 HTML 演示 | 不属于本技能，按常规交付方式做 |

## 3. 从零创建

**第 1 步 · 定结构**。先把大纲写到 `scratch/outline.md`（**不要写进 `output/`**，否则它会取代 PPT 成为
用户看到的头条交付物）。10–15 页是常见规模：封面 / 目录 / 若干内容页 / 结尾页。

**第 2 步 · 定视觉**。选一套与主题相称的配色和版式节奏，细节读
`/skills/bisheng-pptx/references/design-zh.md`。中文商务、党政国企、科技产品各有惯用调性，不要一律深蓝。

**第 3 步 · 写构建脚本**。用 `write_file` 把完整脚本写到 `scratch/build_deck.py`，
**不要把整段代码塞进代码执行器的参数里** —— 参数过长会被截断，导致反复重试却总是差一截。
写文件工具产生的文件对执行器是可见的。python-pptx 的具体写法读
`/skills/bisheng-pptx/references/pptx-cookbook.md`（画布尺寸、文本框、项目符号、表格、原生图表、图片、
中文字体设置，都有可直接抄的片段）。

**第 4 步 · 执行**：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "scratch/build_deck.py"], capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

> 为什么不直接写 `python scratch/build_deck.py`：`python` 在 PATH 里未必是后端那个解释器，
> 用 `sys.executable` 才能保证跑在装了 python-pptx 的环境里。**下面所有脚本调用都用这个写法。**

**第 5 步 · 自检并返修**（§5）。返修时用 `edit_file` 定点改 `scratch/build_deck.py` 再重跑，
不要每次重写整份脚本。

## 4. 套用用户模板

**第 1 步 · 探版式**：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/probe_template.py", "uploads/模板.pptx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

它会打印画布尺寸、主题配色与字体、每个版式的索引与占位符 idx、以及模板自带的页。

**第 2 步 · 以模板为基底生成**：

- `prs = Presentation("uploads/模板.pptx")` —— **打开模板本身**，不要 `Presentation()` 空开再仿色。
  这样母版、主题色、字体、页眉页脚全部自动继承。
- `slide = prs.slides.add_slide(prs.slide_layouts[i])`，`i` 用第 1 步打印的索引。
- 填占位符：用本技能包的 **`fill_text(shape, "文字")`**（`pptx_helpers`，见 cookbook §7），
  它保留模板给这个占位符设定的字号、字色和项目符号。
  **不要用 `text_frame.text = "..."`** —— 那会把整段塌成一个无格式 run，模板的样式全丢。
- **模板自带的示例页要删掉**（cookbook 有删除页的片段）。删页放在所有内容写完之前做，避免误删刚写的页。
- 模板里的占位图形若用不到就整组删除，不要只清空文字 —— 会留下孤零零的空框。
- 保存到 `output/`，扩展名保持 `.pptx`。

**注意**：模板文件是二进制，**不要用 `read_file` 去读它**（会被拦截），只能由代码执行器打开。

## 5. 交付前自检（必做）

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/inspect_deck.py", "output/xxx.pptx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

输出分两段：

- **内容**：逐页文本 + 备注。用它核对错字、顺序、缺漏 —— 这是 `markitdown` 在本环境的替代品。
- **体检**：ERROR 必须修完再交付；WARN 逐条复核；INFO 是设计建议。检查覆盖文字溢出、
  自动撑高的框会压到谁、超出画布、文字区域重叠、字号过小、贴边、残留占位符（XXX/待填/"单击此处"）、
  整页无视觉元素。

改完重新生成，再跑一次，直到「结论: 通过」。

**可选 · 看渲染图**（模型支持读图时才有意义）：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/render_deck.py", "output/xxx.pptx"],
                   capture_output=True, text=True)
print(r.stdout or r.stderr)
```

它把每页渲染成 `scratch/preview/<名字>/slide-N.png`，再用 `read_file` 逐张查看。
**渲染用的中文字体只有文泉驿正黑**，和用户 PowerPoint 里的实际字体宽度不同 ——
预览里的文字松紧只作参考，容器留约 10% 余量即可，不要为了预览效果反复微调字号。
如果环境里没有 LibreOffice，脚本会直说，跳过这一步、以体检结果为准即可。

## 6. 交付纪律

- `output/` 里**只放最终的 `.pptx`**。大纲、构建脚本、预览图、中间版本一律放 `scratch/`。
  （同时放一个 `.md` 会让它顶掉 PPT 成为用户看到的头条文件。）
- 文件名用有意义的中文名，如 `output/思源电气企业介绍.pptx`。
- 收尾时如实说明做了什么、多少页、用了什么风格。**不要声称生成了实际不存在的文件** ——
  .pptx 不在系统的幻影交付物检测清单里，写错了没人兜底。
- 用户拿到的是可下载的 .pptx 文件（当前前端不支持在线预览 PPT），收尾话术不要说「点击预览」。

## 7. 排版底线（细则见 references/design-zh.md）

- 标题 32–44pt 加粗，小标题 20–24pt，正文 14–18pt，注释 10–12pt；正文不要小于 12pt。
- 每页留 ≥0.5 英寸边距；内容块之间 0.3–0.5 英寸，全篇统一。
- 除封面外，每页都该有一个视觉元素（图表 / 图形 / 图标 / 表格），不要通篇「标题 + 三行要点」。
- 正文左对齐，只有标题居中。
- 字体写「微软雅黑」「黑体」「等线」这类用户端一定有的中文字体（渲染由用户的 PowerPoint 完成）。
- **一条装饰性线条都不要**：标题上下的横线、章节编号旁的竖线、页面底部的横贯细线、
  页眉页脚色带、侧边色条、卡片单边描边，全部不要。这是最常被违反的一条，
  既是"一眼 AI"的签名，也是自检里「文字压在装饰线上」的主要来源。用留白和字号层级做分隔。
- 文字绝不允许溢出容器；放不下就精简文案或换版式，不要一味缩字号。

## 8. 绝不要做的事

- ❌ 写 `require('pptxgenjs')` 或任何 Node 脚本 —— 装不上，`npm install` 也会失败。
- ❌ 跑 `markitdown` / `soffice` 命令行做内容 QA —— 用 §5 的两个脚本。
- ❌ `pip install` 任何东西。
- ❌ 用绝对路径 `/output/...`。
- ❌ 把 PPT 降级成 Word/PDF/Markdown 交付。用户要的是 .pptx。
- ❌ 因为 `ls` 看不到刚生成的文件就重做一遍。
