# 深度研究：html-report 增加网页幻灯片分支

**版本**：v3.1.0-beta1。**优先级**：P1。**流程**：小功能（SDD-Guide §1），只写本 spec，决策记在 PR。**状态**：2026-11-05 用户确认方向（以 bisheng-pptx 为样板；场内用户要的是网页而不是 .pptx）并确认规格；代码已实现；AC-13 已在 114 对比（见 §5）。

**关联问题**：cofco 场内慢会话 svid `f59e076c`。用户用深度研究做 37 页「像 PPT 的网页」。116 分钟里 98.8% 是模型生成，累计输出 28.7 万 token，其中约 14.8 万是作为 write_file / edit_file 参数手写的整页 HTML。F005（check_html 逐页溢出测量）解决「哪页溢出」，但每页的标记仍由模型逐字生成。2026-11-05 在 114（3.1）上跑同一个 37 页改版任务，模型自发调用代码执行器 19–29 次，现写 Python 生成和修改 HTML。

**样板**：内置技能 bisheng-pptx 已经实现「模型只写内容，版式交给模板」——先写逐页大纲，`Deck.add(版式)` 加页、`fill(插槽, 内容)` 填内容，插槽带容量，超容量时提示精简或拆页，返修定点改构建脚本后重跑，交付前跑文本化自检。本分支把同一套做法搬到网页幻灯片，产物从 .pptx 换成单个自包含 HTML。

## 1 目标与范围

作为深度研究的使用者，我希望模型做网页幻灯片时只写每页内容，由技能脚本按模板生成 HTML；改版时只改对应页的内容再重跑脚本。这样同类任务的输出量和耗时下降，版式也更稳定。

本期做：在内置技能 html-report 中增加网页幻灯片分支，包括分流说明、主题与版式模板、构建 API、构建后自检，以及幻灯片专用的内容与设计参考。不做：生成 .pptx（由 bisheng-pptx 负责）、套用用户上传的 .pptx 模板、新的平台工具、截图读图质检、cofco 分支回移（3.1 验证有效后另行决定）。

## 2 验收标准

### 触发与分流

- **AC-01** — WHEN 用户要求网页幻灯片、网页版 PPT、可翻页的汇报页，或要求改版已有的 HTML 幻灯片，THE SYSTEM SHALL 触发 html-report 并进入幻灯片分支；WHEN 用户要的是 .pptx 文件，THE SYSTEM SHALL 交给 bisheng-pptx。两个技能的触发描述互相写明这条分界。
- **AC-02** — WHEN 进入幻灯片分支，THE SYSTEM SHALL 在 SKILL.md 中只增加分流说明；幻灯片的流程、版式表和规则放在 `references/slides-zh.md`，写长页报告时不额外读入。

### 流程（与 bisheng-pptx 一致）

- **AC-03** — WHEN 开始做幻灯片，THE SYSTEM SHALL 引导模型先把逐页大纲写到 `scratch/outline.md`，每页一行「页码 | layout_id | 结论标题 | 支撑证据」，并遵守：标题写结论、一页一个结论、按内容关系选版式、不连续三页用同一版式、不编数字。
- **AC-04** — WHEN 本次有代码执行工具，THE SYSTEM SHALL 引导模型用 write_file 写 `scratch/build_slides.py`，通过构建 API 加页、按插槽填内容、生成 `output/<name>.html`；改版时用 edit_file 定点改构建脚本中对应页再重跑，不手写或整页重写 HTML。
- **AC-05** — WHEN 本次没有代码执行工具，或执行环境看不到技能目录，THE SYSTEM SHALL 如实说明并退回到基于模板 HTML 用文件工具写页面，仍使用模板的版式类名和 CSS 变量。

### 模板与构建 API

- **AC-06** — WHEN 选择主题，THE SYSTEM SHALL 提供与 bisheng-pptx 同名同配色的场景主题（红韵 `gov-red`、蓝图 `blueprint`、经营 `operating`、深空 `tech-dark`、课堂 `classroom`），按主题与场景对照表选择；用户点名风格时照办。主题配色与 bisheng-pptx `templates/catalog.json` 一致，由测试校验，防止两边漂移。
- **AC-07** — WHEN 生成幻灯片，THE SYSTEM SHALL 使用固定 1280×720 的页面，字号、间距和配色由 CSS 变量统一定义；本期实现 bisheng-pptx 五套模板共有的 14 个版式，id 同名：cover、agenda、section、statement、two-column、cards-3、cards-4、kpi-4、chart-insight、compare、process、timeline、table、closing；各主题专属版式（honor-wall、architecture、risk-register、scorecard、bridge、feature-hero、objectives、quiz）不做。模板提供键盘翻页、页码和打印分页（每页一张 16:9）。
- **AC-08** — WHEN 调用构建 API，THE SYSTEM SHALL 提供与 bisheng-pptx `Deck` 对应的方法：`open(主题, footer=)`、`add(版式)`、`fill(页, 插槽, 文本或列表)`、`drop(页, 插槽或分组)`、`chart(...)`（生成内联 SVG）、`table(...)`、`notes(...)`、`save(path)`；`list_layouts.py` 打印每个主题的版式与插槽容量。
- **AC-09** — WHEN 填入的内容超过插槽容量，THE SYSTEM SHALL 打印 `[超容量]` 并给出页码与插槽名，规则是精简文案或拆页，不缩字号、不改框尺寸，不静默截断。
- **AC-10** — WHEN 保存，THE SYSTEM SHALL 输出符合 html-report 现有交付约束的单个文件（样式和脚本内联、不引用外部资源、只用系统字体），分页容器使用 F005 能识别的 `section.slide`，并写 `scratch/<name>.manifest.json` 供自检使用。

### 自检与返修

- **AC-11** — WHEN 生成完成，THE SYSTEM SHALL 引导模型依次跑构建后自检（按 manifest 检查：超容量、残留模板示例文字、空插槽、连续三页同版式、图表区未放图表）和 check_html（逐页溢出、离线可用）；ERROR 必须修完，最多 2 轮；只修报告列出的页。
- **AC-12** — WHEN 收尾，THE SYSTEM SHALL 如实说明页数、所用主题和自检结论；`output/` 只放最终的 HTML（大纲、构建脚本、清单放 `scratch/`）。

### 效果

- **AC-13** — WHEN 同一个 37 页改版任务在 114 上用同一模型执行，THE SYSTEM SHALL 使累计输出 token 和墙钟时间低于 3.1 当前基线（2 次运行：输出 6.7 万 / 8.2 万 token，墙钟 28.2 / 41.5 分钟），报告注明样本量与波动。

## 3 设计取舍

| 取舍 | 决定 | 理由 |
|---|---|---|
| 样板 | bisheng-pptx，而非 Anthropic 官方 pptx | 官方 pptx 依赖 Node / LibreOffice / 看图质检，面向 Claude 自己的沙箱；bisheng-pptx 已在 BiSheng 执行器里跑通「大纲 → 插槽填充 → 容量提示 → 文本化自检」，模型在 PPT 与网页幻灯片之间切换时学到的是同一套做法 |
| 主题配色的来源 | html-report 自带一份主题定义，测试校验与 bisheng-pptx 的 catalog.json 一致 | 技能目录必须自包含（用户可能只挂载其中一个技能），又不能让两份配色各自漂移 |
| 内容规则 | `slides-zh.md` 写一份精简的内容组织规则（结论标题、一页一结论、按关系选版式），与 bisheng-pptx design-zh.md「零、内容组织」同口径 | 同上，自包含 |
| 版式表达不了的页 | 允许 `html(页, 插槽, 片段)` 写受限 HTML 片段，脚本原样嵌入并照常测量 | 保留灵活性；代价是这部分回到手写标记，自检会提示用量 |
| 主题选择 | 模型按场景对照表自行选择，不停下来问用户 | 深度研究常常无人值守 |

借鉴 Anthropic 官方技能（github.com/anthropics/skills，2026-11-05 读取）的只有通用原则：skill-creator 的「多次运行都在现写同类脚本，就把脚本放进技能」与「SKILL.md 放骨架、细节按需读 references」；frontend-design（Apache-2.0，html-report 已在其基础上改编）的设计计划与默认审美复查。pptx 技能许可证为 Proprietary，不复制其文本。

## 4 明确接受的边界

- 版式数量有限；构建 API 与 bisheng-pptx 对齐方法名与语义，但网页版不追求与 .pptx 像素一致。
- 没有代码执行工具时，收益只来自模板和 CSS 变量，输出量下降有限。
- 技能的触发依赖模型判断；挂载与勾选沿用现有机制（全挂载 + 勾选标注）。
- 验收样本量小（每组 2 次），只能说明量级，不作为对外提速宣传依据。

## 5 验收记录

**AC-13（2026-11-05，114，模型 qwen3.8-max，同一个 37 页改版任务，每组 2 次）**：两次都走了幻灯片分支（scratch 下有 outline.md、build_slides.py、manifest），37 页用了 8 种版式。

| 组 | 墙钟（分钟） | 累计输出 token | 调用次数 |
|---|---|---|---|
| 3.1 基线（F005 之前） | 28.2 / 41.5 | 6.7 万 / 8.2 万 | 41 / 62 |
| F005 修正版 | 32.3 / 23.1 | 8.8 万 / 5.5 万 | 30 / 22 |
| F006 | 27.8 / 25.4 | 6.1 万 / 5.3 万 | 59 / 55 |

均值：基线 34.9 分钟、7.45 万 token；F006 26.6 分钟、5.7 万 token（各约 −24%），两次结果也最接近。样本小，只能说明量级。逐页看图发现最高柱的数值标签被截，已修（图表顶部留白）。
