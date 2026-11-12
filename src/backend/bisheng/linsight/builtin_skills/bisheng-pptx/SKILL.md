---
name: bisheng-pptx
description: >-
  制作 PowerPoint 演示文稿（.pptx）时使用：工作汇报、年度总结、党委会/董事会材料、项目方案、经营分析、产品发布、
  培训课件等幻灯片；按用户上传的 .pptx 模板制作；改写、续写或翻新已有 PPT。当用户说到「PPT」「幻灯片」「演示文稿」
  「汇报材料」「宣讲材料」「课件」「deck」「slides」「pptx」，或提出「做一个介绍 X 的 PPT」「按这个模板做一版」
  「把这份材料做成 PPT」时触发。逐页设计版面，经版面检查后导出可编辑的 .pptx（文字、图表、表格都可编辑）。
  如果用户明确要的是网页翻页式 HTML 演示（网页版 PPT、HTML 幻灯片）而不是 .pptx 文件，不要用本技能，改用「网页报告」技能。
metadata:
  display-name: PPT 制作
---

# PPT 制作

你逐页设计版面：每页先定一句结论，再为这句结论选最合适的图形（指标卡、对比条、矩阵、流程、分层图、原生图表、表格），
用 PPTD（YAML 页面描述）写出每个元素的位置和样式，交给引擎检查，修正后导出 .pptx。

## 0. 开工

本技能需要代码执行工具。本次没有代码执行工具时，告诉用户「请勾选代码执行器后重试」，停止。

第一次执行代码先探环境：

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/pptd.py", "env"], capture_output=True, text=True)
print(r.stdout)
```

- 输出「PPT 引擎: 不可用」：把这句原话告诉用户，停止。不要改用 python-pptx 或其他方式生成 PPT。
- 脚本的所有结果都在 stdout，结论看「结论:」那一行。

先判断属于哪种任务：

| 任务 | 做法 |
|---|---|
| 新做一份 PPT | 按第 1–5 步 |
| 改写、续写、翻新用户上传的 .pptx | 先按第 6 步转换，再从第 1 步的大纲开始，只改需要改的页 |
| 「按这个模板做」，用户上传了 .pptx 模板 | 先按第 6 步转换模板，把转换结果当作第 2 步的模板，再按第 1–5 步制作 |

## 1. 先写大纲

确定受众、核心结论、页数（遵循用户要求）。每页写一句结论式标题（不是话题词）和这页的主图形式。
相邻页面换图形形式；不要通篇三列卡片。材料里的数字原样使用，单位、期间、口径写在数字旁。缺数据时写定性内容，不编数字。

## 2. 选模板、读参考

读 `skills/bisheng-pptx/templates/catalog.md` 选一套（用户点名风格就照办；党委会、年度总结、政企汇报用 `gov-red`）。
然后读这套模板的 `design.md` 和 `source-zh/deck.pptd`，再按需要读 3–6 个 `source-zh/pages/*.page` 作为写法参考（不要全部读完）。

- 沿用模板的配色、网格、边距和组件；示例里的公司、数字、结论一律不要继承。
- **字号以本技能为准，不以模板说明为准**：超过 24 字的正文、表格正文 ≥ 11pt，短标签、来源、页脚、表头 ≥ 9pt，页标题 ≥ 24pt。
  模板说明里更小的字号要放大；放不下就删字、改写或拆页，不要缩字。
- **中文字体**：所有文本的 `fontFamily` 写 `{latin: Arial, ea: Microsoft YaHei}`（可放进 `theme.textStyles`）。

## 3. 写 PPTD 工程

工程放在 `scratch/deck/`：`scratch/deck/deck.pptd` 清单 + `scratch/deck/pages/NN.page`。格式见
`skills/bisheng-pptx/references/pptd.md`（必读一次），版面组织见 `skills/bisheng-pptx/references/composition.md`。

- 用 `write_file` 或 Python 写文件均可。多页时可用一个 Python 脚本批量写出所有 `.page`。
- 画布 `size: [960, 540]`，`bounds: [x, y, w, h]`，四周留 ≥ 36 的边距。
- 图表、表格用原生 `chart` / `table` 元素；数值轴从 0 起，除非是指数或明确标注。

## 4. 检查 → 修改 → 导出

```python
import subprocess, sys
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/pptd.py", "check", "scratch/deck"],
                   capture_output=True, text=True)
print(r.stdout)
```

- 输出列出每个问题的文件、页码、元素 ID。**一次改完清单上的全部问题**，再检查一次。
- 最多检查 4 轮。第 4 轮后仍只剩 warning 就导出；仍有 error 则拆页或删减内容后再检查。
- 看到「结论: 通过，可以 render」后导出（文件名用中文标题）：

```python
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/pptd.py", "render", "scratch/deck",
                    "output/<标题>.pptx"], capture_output=True, text=True)
print(r.stdout)
```

看到「已导出」才算交付。不要重复导出同一份文件，不要去 `output/` 反复找文件。

## 5. 交付

告诉用户：文件名、页数、采用的模板、每页主题一句话。如实说明只做了版面检查，没有在 PowerPoint/WPS 里打开验证。

## 6. 转换已有 .pptx

```python
r = subprocess.run([sys.executable, "skills/bisheng-pptx/scripts/pptd.py", "convert", "<上传文件路径>.pptx",
                    "scratch/deck"], capture_output=True, text=True)
print(r.stdout)
```

- 转换得到的工程与第 3 步格式相同，直接在上面修改；改完按第 4 步检查和导出。
- 用作模板时，先读 `scratch/deck/deck.pptd` 和 2–3 个页面，记下配色、字体、网格和装饰元素，再按大纲重写各页，删除模板中的示例页。
- 转换输出里「被简化的效果」「不支持、未转换的内容」以及「导出的文件不带原母版」，交付时如实告诉用户。

## 绝不要做

- 不用 python-pptx 或其它方式另起炉灶生成 PPT；引擎报错就按报错改工程。
- 不把整页做成图片；不使用远程图片 URL。
- 不写带前导斜杠的路径（`/output/...`），一律用相对路径。
- 不 `pip install` / `npm install`。
