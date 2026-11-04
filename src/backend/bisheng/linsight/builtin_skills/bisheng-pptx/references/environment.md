# 运行环境事实（照做，不要试探）

SKILL.md §0 的探测已经覆盖最关键的三件事。下面是遇到问题时再查的细节。

| 项 | 事实 |
|---|---|
| **生成方式** | **只有 `python-pptx`**，`import pptx` 直接可用。内置模板的 `Deck` 也基于它 |
| 不存在的东西 | Node / npm / `pptxgenjs`、`markitdown`、`defusedxml`、`pdfplumber`/`pdfminer`/`PyPDF2`、`pdftoppm`、`zip`/`unzip` |
| 存在但本技能不用 | `pandoc` 能 `-o out.pptx`，但只产出「标题＋项目符号」的裸版式，配色版式图表全不可控，做出来必是"一眼 AI" |
| 其它可用库 | Pillow（图片）、PyMuPDF(`fitz`)（读 PDF/渲染）、matplotlib（只在原生图表做不了时出图）、pandas/numpy、openpyxl、python-docx、lxml |
| 禁止 | `pip install`、`npm install`、任何联网假设（生产多为离线内网） |
| 工作目录 | 执行器 cwd = 工作区根，**一律用相对路径** |
| `output/` | 唯一交付区，已自动创建 |
| `scratch/` | 中间产物区（大纲、构建脚本、模板清单、预览图），**不会交付** |
| `uploads/` | 用户上传的原件（模板、素材、资料） |
| `skills/bisheng-pptx/` | 本技能包：`scripts/` 脚本、`templates/` 内置模板、`references/` 参考，只读 |
| 绝对禁止 | 写 `/output/xxx.pptx` 这种带前导斜杠的路径 —— 文件会被静默丢弃 |
| 单次执行上限 | 600 秒。构建与自检分两次调用 |
| 日志规则 | **成功时只回传 stdout，stderr 被丢弃** → 诊断信息用 `print()` |
| 可见性 | 判成功看**执行结果**：`exitcode 0` + 日志确认写成功即视为已产出，**不要反复找文件、更不要重做** |
| 轮次 | 最后两轮代码执行器会被摘除 → PPT 必须尽早产出 |

## 技能目录不可见时（`skills 可见: False`）

当前执行环境（例如隔离沙箱）看不到 `skills/` 目录：内置模板、`Deck`、自检脚本都调不动。

- **不要反复重试路径**。
- 告诉用户：「当前执行环境无法使用内置模板与自检脚本，改为直接生成，版式质量可能不如模板版」。
- 按 `references/freeform.md` 用纯 python-pptx 内联写法生成（cookbook 的片段都可用，把需要的辅助函数抄进构建脚本）。
- 自检改为自己按 `design-zh.md` 逐页核对文字是否超框、是否压字。

## 可选：渲染成图片逐页查看

> ⚠️ 仅在你确知当前模型支持读图时才做。渲染出的 PNG 会以 base64 图片发给模型厂商，
> 部分通道（例如 dashscope）**不接收 base64 图片**，读图会直接失败甚至中断任务。拿不准就跳过，以体检结果为准。

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/render_deck.py", "output/xxx.pptx"],
                   capture_output=True, text=True)
print(r.stdout or "(no stdout)")
print(r.stderr[-2000:] if r.stderr else "(no stderr)")
```

它把每页渲染成 `scratch/preview/<名字>/slide-N.png`，再用 `read_file` 逐张查看。
渲染用的中文字体与用户 PowerPoint 里的不同，文字松紧只作参考，不要为预览效果反复微调字号。
没有 LibreOffice（或没装 Impress 组件）时脚本会直说，跳过即可，不影响生成与交付。
