# Tasks: 任务模式 PPT 内置模板与在线预览

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v3.0.0（分支 `feat/3.0.0/111-taskmode-pptx-templates-preview`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-10-27 用户确认 |
| design.md | ✅ 已评审 | 2026-10-27 用户确认 |
| tasks.md | ✅ 已拆解 | `/sdd-review tasks` 一轮修订后 LGTM（拆分 T001→T017、T012→T018） |
| 实现 | 🔄 进行中 | 10 / 18 完成 |

---

## 开发模式

- 按 Wave 组织任务。同一 Wave 内的任务互不依赖，可以并行。
- 后端走 Test-First：先写测试再写实现，测试放在 `src/backend/test/linsight/`。
- 前端用手动验证，每个任务附验证步骤。
- 设计论证一律指向 design.md 的对应章节，本文不复制。
- 并发子代理不得使用仓库级 git 写操作（见根 AGENTS.md §7）。

---

## Wave 1：模板与基础设施（互不依赖）

- [x] **T001**: 模板生成脚本与 5 套模板（共用版式）
  - **文件**：
    - `src/backend/scripts/pptx_templates/{themes.py, layouts.py, build_templates.py}`
    - 产物：`src/backend/bisheng/linsight/builtin_skills/bisheng-pptx/templates/{catalog.json, <id>/template.pptx, <id>/layouts.json}`
  - **逻辑**：
    - 5 套主题令牌，包含配色、中西文字体、`gov-red` 的标题字体。
    - 14 个共用版式的几何，版式清单见 design §4.4；专属版式由 T017 补充。
    - 插槽按 design §4.3 的约定命名，容量按 design §4.3 的字数口径从"框尺寸 × 字号"算出。
    - 主题 XML 写入 accent 色与 `latin`/`ea` 字体（design 决策 3）；文本框设 `MSO_AUTO_SIZE.NONE`（design §5 第 5 条）。
    - 只用矢量元素，示例文字都标"示例"。
    - 每个 pptx 不超过 500KB。
    - 脚本遵守 `src/backend/scripts/AGENTS.md`，并且可重复运行。
  - **验证**：本地运行脚本，用 LibreOffice 渲染逐页联系表，交给用户看（为 AC-31 做准备）。
  - **覆盖 AC**：AC-01、AC-07
  - **依赖**：无

- [x] **T017**: 各套专属版式
  - **文件**：`src/backend/scripts/pptx_templates/layouts_special.py`，以及重新生成的 `templates/**` 产物
  - **逻辑**：
    - 增加 8 个专属版式：`architecture`、`risk-register`、`scorecard`、`bridge`、`objectives`、`quiz`、`honor-wall`、`feature-hero`。
    - 由 `build_templates.py` 按模板挂载。
    - 插槽和容量约定与 T001 相同。
  - **验证**：同 T001 的联系表。
  - **覆盖 AC**：AC-01
  - **依赖**：T001

- [x] **T002**: 错误码 11025 与三语文案
  - **文件**：
    - `src/backend/bisheng/common/errcode/linsight.py`
    - `src/frontend/packages/locales/src/api_errors/{zh-Hans,en,ja}.json`
    - 重新生成 `api_errors` 产物，不手改生成文件
  - **逻辑**：新增 `LinsightArtifactPreviewError`（Code 11025），文案为"PPT 预览生成失败，请下载后查看"及对应的英文、日文。
  - **覆盖 AC**：AC-23、AC-29
  - **依赖**：无

- [x] **T003**: `convert_ppt_to_pdf` 增加可选 `timeout` 参数
  - **文件**：`src/backend/bisheng/knowledge/rag/pipeline/loader/utils/libreoffice_converter.py`
  - **逻辑**：增加可选参数 `timeout`，默认值保持 180，并透传给 `_convert_file_extension`。既有调用方的行为不变。
  - **覆盖 AC**：AC-21（为其提供条件）
  - **依赖**：无

## Wave 2：技能脚本与预览后端

- [x] **T004**: `Deck` 库单测
  - **文件**：`src/backend/test/linsight/test_pptx_templates.py`
  - **测试**：
    - 每份模板都能打开；`layouts.json` 中的每个插槽在 pptx 里都存在；示例文字一致。（AC-01）
    - 跑一遍 `Deck` 全流程（`add`/`fill`/`drop`/`table`/`chart`/`image`/`save`）后：产物能重新打开、原型页已删除、manifest 中的页数和 `layout_id` 正确、表格行数可增减、图表为原生图表。（AC-05、AC-06）
    - 超容量的填写会写进 manifest 的 `over_capacity`。
  - **覆盖 AC**：AC-01、AC-05、AC-06
  - **依赖**：T001

- [x] **T005**: `deck_template.py` 实现
  - **文件**：`src/backend/bisheng/linsight/builtin_skills/bisheng-pptx/scripts/deck_template.py`
  - **逻辑**：
    - 实现 `Deck.open/add/fill/drop/table/chart/image/save`。
    - 克隆页面时改写 rId（design §5 第 1 条）；图表按 `chart_area` 现放（design 决策 4）；删页同时处理 `drop_rel` 和 `sldId`（design §5 第 3 条）。
    - 中文字体复用 `pptx_helpers.set_font`/`fill_text`。
    - 超容量时立即 `print` 提示。
    - 只当作库使用，不 `sys.exit` 非零。
  - **覆盖 AC**：AC-05、AC-06
  - **依赖**：T004

- [x] **T006**: `list_templates.py`
  - **文件**：`.../bisheng-pptx/scripts/list_templates.py`，测试并入 `test_pptx_templates.py`
  - **逻辑**：
    - 无参数时，以纯文本列出模板：id、名称、适用场景、配色说明、版式数。
    - 传 `<id>` 时，列出该模板的版式表：`layout_id`、适用内容、插槽及容量。
    - 始终 exit 0。
  - **覆盖 AC**：AC-02
  - **依赖**：T001

- [x] **T007**: 新检查单测
  - **文件**：`src/backend/test/linsight/test_pptx_templates.py`
  - **测试**：
    - 坏样本：超容量、示例残留、连续 3 页同一 `layout_id`、封面焦点不足，四项各命中一次，每条都带页码和元素名。
    - 好样本：按模板正确填写的文稿，四项新检查都不报，且模板结构线不触发既有的"文字压装饰线"检查（AC-11）。
    - 没有 manifest 的从零文稿：连续构图检查按轮廓判断；封面检查照常执行。
    - 既有用例保持不变。（AC-12）
  - **覆盖 AC**：AC-10、AC-11、AC-12
  - **依赖**：T005

- [x] **T008**: `deck_checks.py` 与 `inspect_deck.py` 集成
  - **文件**：`.../scripts/deck_checks.py`、`.../scripts/inspect_deck.py`
  - **逻辑**：
    - 新增 `--manifest` 参数，未传时自动查找 `scratch/<名>.manifest.json`。
    - 实现基线差分（design 决策 5）。
    - 新检查一律报 WARN；"结论: 通过"仍只由 `inspect_deck` 打印。
  - **覆盖 AC**：AC-10、AC-11、AC-12
  - **依赖**：T007

- [ ] **T009**: 预览服务单测
  - **文件**：`src/backend/test/linsight/test_artifact_preview_service.py`
  - **测试**：
    - 鉴权：所有者、管理员、`workbench_chat` 分享（`resource_id` 等于会话）、按版本分享都放行；无权限的请求被拒绝。（AC-24、AC-25）
    - 归属校验：带 `..`、跨会话版本前缀、非 ppt/pptx 后缀，三种情况都被拒绝，且不会触发转换。（AC-24）
    - 缓存已存在：直接返回 ready，转换函数不被调用。（AC-22）
    - 锁被占用：返回 `converting`。（AC-27）
    - 转换返回 `None`，或产出 0 页：抛出 11025、释放锁、不写缓存，再次请求会重试。（AC-23）
    - 下载接口改为调用共用函数后，行为与原来一致。（AC-28）
    - MinIO、Redis 和转换函数全部 mock。
  - **覆盖 AC**：AC-22、AC-23、AC-24、AC-25、AC-27、AC-28
  - **依赖**：T002、T003

- [ ] **T010**: 预览服务与接口实现
  - **文件**：
    - `src/backend/bisheng/linsight/domain/services/artifact_preview_service.py`
    - `src/backend/bisheng/linsight/api/endpoints/linsight.py`
  - **逻辑**：
    - 实现 `load_accessible_version` 和 `get_pptx_preview`，细节见 design §4.2、§4.3、决策 6、决策 7。
    - 新增 `POST /workbench/file_preview`。
    - `file_download` 改为调用 `load_accessible_version`。这是共享接口，结果区、分享页、HTML 查看页都在用；行为必须保持不变，由 T009 的回归用例保证。
    - 每个进程用 `Semaphore(2)` 限流；转换超时 120 秒；记录日志。
  - **覆盖 AC**：AC-20、AC-22、AC-23、AC-24、AC-27、AC-28
  - **依赖**：T009

## Wave 3：技能指引、前端、分发

- [ ] **T011**: 重写 SKILL.md 与 references
  - **文件**：`.../bisheng-pptx/{SKILL.md, references/design-zh.md, references/environment.md(新), references/pptx-cookbook.md}`
  - **逻辑**：
    - 正文流程：先写大纲（首读结论、`layout_id`、证据），再用 `list_templates` 选模板，再用 `Deck` 构建，最后用 `inspect` 检查。
    - 路线选择：用户模板优先；其次是内置模板；用户要求自由设计、或模板都不贴合时，才从零生成。
    - E2B 环境下说明限制，并转为从零生成。
    - 环境事实移到 `environment.md`。
    - `design-zh.md` 增加"内容组织"一节，并修订装饰线条款。
    - 遵守品牌和 description 的限制：不超过 1024 字，不写环境声明。
  - **验证**：`test_the_shipped_bundle_is_valid` 通过；人工通读一遍。
  - **覆盖 AC**：AC-02、AC-03、AC-04、AC-08、AC-09
  - **依赖**：T005、T006、T008

- [ ] **T012**: 前端（Client）预览数据层
  - **文件**：
    - `src/frontend/client/src/components/Linsight/Artifacts/{artifactUtils.ts, useSlidesPreview.ts(新)}`
    - `src/frontend/client/src/api/chat/data-service.ts`
  - **逻辑**：
    - 新增 `slides` 预览类型，覆盖 ppt 和 pptx，只作用于任务生成的文件；上传文件仍按解析正文预览。
    - 新增 `getLinsightFilePreviewApi`，出参形如 `{status, file_path?}`，与下载接口同形态，带 `share-token` 和 `skip403Redirect`。
    - hook `useSlidesPreview(file, versionId)` 返回 `{state: 'generating'|'ready'|'failed', url}`：每 2 秒轮询一次，90 秒后放弃；失败结果不写缓存。
    - 补 `artifactUtils` 单测。
    - 新文件不加 `@ts-strict-ignore`。
  - **覆盖 AC**：AC-20、AC-21、AC-23、AC-25、AC-28
  - **依赖**：T010

- [ ] **T018**: 前端（Client）预览渲染与文案
  - **文件**：
    - `src/frontend/client/src/components/Linsight/Artifacts/PreviewBody.tsx`
    - `src/frontend/client/src/locales/{zh-Hans,en,ja}/translation.json`
  - **逻辑**：
    - slides 类型使用 T012 的 hook。
    - generating 状态显示"正在生成预览…"。
    - ready 状态渲染 `<FilePreview fileType="pptx" fileUrl={url} compactMode />`，上方加 AC-26 的提示条。
    - failed 状态沿用现有的图标加"下载查看"兜底。
    - 新增的 key 三语齐全。
  - **验证**：本地起 client，分别验证 ready、converting、失败、分享页四种状态；确认 docx、pdf、md 的预览不变。
  - **覆盖 AC**：AC-20、AC-21、AC-23、AC-25、AC-26、AC-28、AC-29
  - **依赖**：T012

- [x] **T013**: 种子化回归测试
  - **文件**：`src/backend/test/linsight/test_builtin_skill_seeder.py`
  - **测试**：
    - `discover_builtin_bundles()["bisheng-pptx"]` 包含 `templates/**`，字节与磁盘一致。（AC-13）
    - 已被 fork 的内置技能不会被覆盖（复用既有用例并断言）。（AC-14）
  - **覆盖 AC**：AC-13、AC-14
  - **依赖**：T001、T017

## Wave 4：验收

- [ ] **T014**: 模板视觉评审与签字
  - **逻辑**：
    - 交付 5 套模板的联系表，并在 PowerPoint 或 WPS 中打开核对。
    - 按反馈重跑 T001，然后取得设计或产品签字。
    - 结论记入 `evidence/template-review.md`。
  - **覆盖 AC**：AC-07、AC-31
  - **依赖**：T001

- [ ] **T015**: 端到端验收
  - **逻辑**：
    - 在 114 上，用三类题目，在改造前后各跑一次。
    - 把逐页联系表和检查结论归档到 `evidence/`。
    - 在 116 或 180（有 Impress 的环境）上验证 pptx 预览、分享页预览，以及缓存复用。
    - 跑 `/e2e-test`。
  - **覆盖 AC**：AC-02、AC-20、AC-21、AC-22、AC-25、AC-30
  - **依赖**：T011、T018、T014、T017

- [ ] **T016**: 质量门与代码审查
  - **逻辑**：
    - 跑 `pnpm lint`、`pnpm typecheck`、`pnpm check-i18n`、`scripts/arch-guard.sh`，以及相关 pytest。
    - 跑 `/sdd-code-review --base feat/3.0.0`。
    - 回写 design 修订历史，并更新 release-contract 中 F111 的状态。
  - **覆盖 AC**：全部（回归）
  - **依赖**：T015

---

## AC 追溯

| AC | 任务 |
|---|---|
| AC-01 | T001、T017、T004 |
| AC-02 | T006、T011、T015 |
| AC-03、AC-04、AC-08、AC-09 | T011 |
| AC-05、AC-06 | T004、T005 |
| AC-07 | T001、T014 |
| AC-10、AC-11、AC-12 | T007、T008 |
| AC-13、AC-14 | T013 |
| AC-20 | T010、T012、T018、T015 |
| AC-21 | T003、T012、T018、T015 |
| AC-22 | T009、T010、T015 |
| AC-23 | T002、T009、T010、T012、T018 |
| AC-24、AC-27 | T009、T010 |
| AC-25 | T009、T012、T018、T015 |
| AC-26 | T018 |
| AC-28 | T009、T010、T012、T018 |
| AC-29 | T002、T018 |
| AC-30 | T015 |
| AC-31 | T014 |

---

## 实际偏差记录

（实现中如有偏离，在此留一行指针，论证写在 design.md。）

- T001/T005：图表与表格渲染抽成技能包内共享模块 `scripts/deck_render.py`，生成脚本与 `Deck` 共用一份实现（模板样例与真实产出不漂移）→ design §4.5 已补该模块。
- T001：新增 `scripts/pptx_templates/builder.py`（形状、插槽登记、主题 XML 底层），与 themes/layouts/build 并列。
- T017：`bridge` 用瀑布图实现，`deck_render` 增加 `waterfall` 图表类型。
- T008：为让模板自身通过既有检查（不依赖基线扣除），调整了模板：封面标题 44pt、页脚上移并改 10pt、装饰圆环与光晕收进画布内、页码字段声明段落字号 → design §5 第 13 条。
