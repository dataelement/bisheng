# PPT runtime and template provenance

## 参考说明

- **实现方案**：参考 Kimi PPT（Kimi Slides）的 PPTD 文档与示例，采用本地声明式页面工程、校验与可编辑 PPTX 导出的工作流程。
- **模板设计**：部分模板参考并按 MIT 许可改编自 Zara Zhang（GitHub：`zarazhangrui`）的 [`beautiful-html-templates`](https://github.com/zarazhangrui/beautiful-html-templates)，固定版本为 `e5e204fb1f3b06290846e7dcd7aceddabeceec8c`。DSH 重建了原生可编辑版式，并补充中英文示例及字体配对。


The maintained runtime was extracted from the DSH-distributed `dsh-kimi-ppt@0.1.1-rc.2` artifact pinned by Desktop commit `9d4502f`. Its original MIT notice remains in LICENSE. This is maintenance of distributed JavaScript, not a claim that the complete upstream TypeScript source or a legal clean-room process has been recovered.

Historical development studied Kimi Slides client-distributed documentation and example PPTD files. The current product names are dsh-ppt and dsh-ppt-composer. Only legacy storage paths, old RPC aliases and migration checks remain for compatibility. This package does not ship the Kimi executable, its original documentation, or the withdrawn community template packs. The authoring documentation in this edition was rewritten against the local implementation.

The former community reference packs and both user-supplied third-party presentation libraries were removed from this distribution, including derived raster previews and template data. Historical attribution is recorded here without asserting permission to redistribute those excluded works.

## Retained native templates

Modular Logistics System, Swiss Signal Grid, and Nordic Operating Report originated in DSH contribution `de281a1ceccadb00b92df53adb106a2e87ec0b4b` (PR #320). Their native PPTD files and source provenance statements are included. Package review verifies editable native objects, no external raster assets, and renderable source projects. These checks do not independently establish every underlying copyright fact.

## HTML Anything adaptations

Engineering Blueprint and Course Workshop adapt the design directions in `deck-blueprint` and `deck-course-module` from https://github.com/nexu-io/html-anything at `c31204544230578ac814026fecc153c6e36587ae`, licensed under Apache-2.0. Copyright and attribution to the HTML Anything / Nexu contributors are retained. The corresponding source Skill excerpts and license are included in licenses/html-anything.

Modified 2026-09-06 by DSH Desktop contributors: added native PPTD layouts, original example text, editable vectors, previews and semantic indexes. Editorial Notebook is separately authored by DSH and does not reuse guizang-ppt-skill.

Other runtime dependencies retain their own package licenses. No font binary is included in these template packs; font names request installed fonts or renderer fallback.

## Zara template adaptations

Copyright (c) 2026 Zara Zhang. Ten templates adapt beautiful-html-templates at e5e204fb1f3b06290846e7dcd7aceddabeceec8c under MIT. See licenses/zara/LICENSE and the pinned design/HTML source files. DSH rebuilt native editable layouts and expanded each of the ten templates to twelve layouts, added English and Chinese examples, replaced web-only typefaces with documented Office font pairs, and generated new previews.
