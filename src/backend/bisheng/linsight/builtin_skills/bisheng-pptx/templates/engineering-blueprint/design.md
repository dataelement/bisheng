# 工程蓝图 · Engineering Blueprint

纸张底色、工程网格、流程盒和反馈路径；用于架构评审、技术方案及执行计划。

## 使用规则

16:9，960×540 点。正文使用 Arial 并由系统回退中文字体；编辑部大标题可用 Georgia，缺失时回退衬线字体。只引用字体名称，不分发字体文件。背景 #F0EAE0，正文 #252824，强调 #B5392A。单页突出一个判断；超出文本容量时拆页，不缩小字号。保持边距 48 点、清晰层次及页脚。图表、表格、关系图均使用可编辑元素。

## 版式

1. 架构封面
2. 分层架构
3. 处理流程
4. 方案比较
5. 责任清单
6. 风险登记
7. 验证路线
8. 执行结论

## 来源

视觉方向参考 html-anything 的 deck-blueprint（Apache-2.0，固定提交 c31204544230578ac814026fecc153c6e36587ae）。本文件、PPTD 页面、示例内容和预览为改编和新增；保留上游许可和署名。 示例句和示例数字均为自编，不代表事实结论。

## Bilingual typography

English previews: source/. Chinese examples: source-zh/. English title/body: Arial / Arial. Chinese macOS: PingFang SC / PingFang SC; Windows: Microsoft YaHei / Microsoft YaHei; Linux: Noto Sans CJK SC / Noto Sans CJK SC. Font names only, no binaries. Use the user's requested output language, independently of the preview language. Reflow long translations; do not reduce text below readable size.

## Expanded composition rules

Twelve editable reference pages. The cover and closing retain the parent style; ten content layouts add information structures with varied density.

1. 架构封面 — 架构封面；以可编辑文本和矢量形状组织信息。
2. Make the system easier to reason about — Asymmetric argument with three supporting evidence rows
3. Design around explicit boundaries — Three layers, nine native nodes, horizontal handoffs and vertical dependencies
4. Make the handoff order visible — Four lifelines with ordered request and response arrows
5. Trace the question to testable branches — Three-branch hypothesis tree with six testable leaves
6. Read the trend and investigate the pause — Labeled six-point trend with common scale and a separate interpretation
7. Choose the next move with evidence — Two-axis decision map with direct labels and a recommended next step
8. Design the test before reading the result — One hypothesis with comparison, measure and a predeclared decision rule
9. A small intervention, a measurable change — Intervention narrative beside paired before and after comparisons
10. Connect each measure to a response — Actual, target and response aligned across four measures
11. Sequence the work around a decision gate — Four timed workstreams and a decision gate
12. 执行结论 — 执行结论；以可编辑文本和矢量形状组织信息。

Choose a layout by the information relationship: evidence and interpretation, hierarchy, change over time, decision criteria, timed dependencies or ordered handoffs. For six or more content pages, use at least four distinct structures when the material supports them; avoid repeating the same composition on adjacent pages. Alternate detailed evidence with a simpler synthesis. A detailed page needs one dominant argument, supporting evidence and a concise interpretation. More detail must come from meaningful relationships, not extra decoration or a smaller font.

Keep the parent palette and typography. Preserve its characteristic rails, paper fields, serif/sans hierarchy and light/dark rhythm. Use body text around 18–22 pt, direct chart labels around 13–16 pt, and 48 pt outer margins on 960 × 540 pt pages. Native text, shapes and connectors remain editable. Rescale the geometry or split a page before shrinking the text. Reference charts drawn with shapes have editable geometry; they do not contain an embedded chart spreadsheet.

New examples are explicitly illustrative: replace every invented value, quote and conclusion with the user's evidence. Retained sourced industry examples remain attributed in their existing notes. Never invent facts to fill a layout. Include units, common baselines, meaningful owners, measurement windows and dependencies as appropriate. English previews do not select the user's output language. Use the existing English/Chinese font pairs and platform fallbacks; reflow translated text.

## Composition finish

Treat an analytical slide as a small argument: a claim at the top, a dominant exhibit, and a concise readout or next decision. A second exhibit must add evidence (a reconciled breakdown, a comparison table, an exception or a test), not repeat the same headline. Do not fill every page with equally sized cards. Keep a quiet synthesis or section break between dense runs.

Use a shared baseline for chart labels, aligned numeric columns and a limited set of type sizes. Distinguish a section label, headline, exhibit label, evidence text and source note by size and spacing before adding color. Keep body text readable; short exhibit labels may be smaller. Avoid single-word last lines, detached punctuation and arbitrary line breaks. Reflow Chinese and English separately.

Put units, population and measurement window beside the relevant exhibit. Directly label the meaningful exception or inflection; use a subtle highlight or a short leader without crossing another label. For paired exhibits with different denominators, state both explicitly. Reconcile subtotals and deltas. Use a common quantitative scale; decorative bars must never imply a different value.

End an evidence page with a concise interpretation, bounded recommendation or open question. A roadmap names owners and a gate; a scorecard distinguishes exceptions from measures that pass. Highlight the one decision or exception, not every cell. Adapt these devices to the parent pack: quiet serif pages, engineering schematics and bold posters should not converge on one visual style.

Inspect a rendered page, not just its bounding boxes: check the reading order, line endings, label collisions, chart contrast and the gap above the footer. Keep labels clear of rules and markers. Use native editable text and geometry. Fictional reference data must be replaced by verified user material or visibly marked as an example.
