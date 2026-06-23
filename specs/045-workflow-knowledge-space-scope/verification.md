# Verification: Workflow Knowledge Space Retrieval Scope

## Metadata
- Feature ID: `045-workflow-knowledge-space-scope`
- Status: `partial-manual-pending`
- Updated: `2026-06-23`

## Overall Status
- Automated verification: `PASS`
- Manual UI verification: `PARTIAL_PASS`
- Completion claim: 不能声明全量完成，因为 workflow editor 浏览器交互、保存后重开、失效知识空间回显、单节点调试仍需要人工或 E2E 验证。

## Commands

| Command | Purpose | Exit Code | Result | Evidence |
|---|---|---:|---|---|
| `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py` | 后端知识空间 option、文档检索 runtime、QA runtime 兼容性回归 | 0 | PASS | `9 passed, 8 warnings in 3.18s`。新增覆盖空 `space` 选择配置抛明确错误、文档知识库检索节点 `space` 分支异常向上抛出为节点错误；保留授权空间选项过滤/分页、显式 `space` 分支、未知类型拒绝、空间检索 helper、QA 旧数组兼容、QA `space` 分支不依赖 QA metadata。 |
| `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py` | T018 workflow ORM `User` 适配为知识空间权限服务兼容登录用户 | 0 | PASS | `11 passed, 8 warnings in 2.81s`。新增覆盖 ORM-like workflow `User` 适配后具备 `get_user_group_ids()`，以及已兼容登录用户对象会保持原样。 |
| `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py` | T019 workflow 知识空间检索注入 `version_repo` 回归验证 | 0 | PASS | `12 passed, 8 warnings in 3.81s`。新增覆盖 `retrieve_knowledge_space_documents_sync()` 手动创建 `KnowledgeSpaceChatService` 后会注入 `KnowledgeDocumentVersionRepositoryImpl`，`aretrieve_chunks()` 调用前可访问 `service.version_repo`。 |
| `cd src/backend && uv run ruff check --select I001 bisheng/workflow/common/knowledge.py test/workflow/test_knowledge_space_scope.py` | 本次修改文件 import 排序定向检查 | 0 | PASS | `All checks passed!`。完整 ruff 未作为通过证据，因为 `knowledge.py` 存在既有 `UP006`、`C403`、`B007`、`B009` 等非本次引入问题。 |
| `cd src/frontend/platform && npm run build` | Platform 前端 TypeScript/Vite 构建验证 | 0 | PASS | Vite build 成功，`8299 modules transformed`，`built in 13.08s`。保留既有警告：Ace script 非 module、Browserslist 数据较旧、`xlsx-populate`/`pdfjs-dist` eval 警告、大 chunk 警告。 |
| `cd src/frontend/platform && npm run build` | T014 bugfix 后 Platform 前端构建验证 | 0 | PASS | Vite build 成功，`8299 modules transformed`，`built in 10.92s`。保留既有警告：Ace script 非 module、Browserslist 数据较旧、`xlsx-populate`/`pdfjs-dist` eval 警告、大 chunk 警告。 |
| `cd src/frontend/platform && npm run build` | T015-T017 知识空间树形分类与加载态前端构建验证 | 0 | PASS | Vite build 成功，`8300 modules transformed`，`built in 13.72s`。保留既有警告：Ace script 非 module、Browserslist 数据较旧、`xlsx-populate`/`pdfjs-dist` eval 警告、大 chunk 警告。 |
| `cd src/frontend/platform && npm run build` | T020 知识空间选择器重开分页竞态修复后的前端构建验证 | 0 | PASS | Vite build 成功，`8300 modules transformed`，`built in 14.12s`。保留既有警告：Ace script 非 module、Browserslist 数据较旧、`xlsx-populate`/`pdfjs-dist` eval 警告、大 chunk 警告。 |
| `cd src/frontend/platform && npx vitest run src/test/workflowKnowledgeSpaceSelectorRace.test.tsx` | T020 已选 `space` 后再次打开选择器不抢跑 page 2 的组件回归测试 | 0 | PASS | `1 passed (1)` test file，`2 tests` passed in `24ms`。覆盖 `KnowledgeSelectItem` 与 `KnowledgeQaSelectItem` 在 page 1 pending 时触发 open + scroll-load，只请求 page 1，不请求 page 2。 |
| Browser manual verification on `http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a` | T014 bugfix 回归验证，不保存 workflow | N/A | PASS | 临时添加“文档知识库问答” (`rag`) 节点，打开检索范围后 Tab 顺序为 `文档知识库`、`知识空间`、`临时知识库`；切换 `知识空间` 后 `inputPlaceholder: 搜索知识空间名称` 且 `hasMetadataFilter: false`；选择 `营销` 后 `hasSelectedMarketing: true` 且 `hasMetadataFilter: false`；切回文档知识库后 `hasMetadataFilter: true`、`hasSelectedMarketing: false`、搜索框恢复 `搜索知识库名称`。重新打开页面确认服务端保存状态未保留临时节点。 |
| Browser manual verification on `http://127.0.0.1:3001/flow/990d6499fb934bbdb51c8f9a00c4be4a` | T015-T017 知识空间树形分类、搜索、加载态和空状态验证，不保存 workflow | N/A | PASS | 临时添加 `knowledge_retriever`，切换 `知识空间` 后列表按 `公共空间(10)`、`部门空间(5)`、`团队空间(7)`、`个人空间(4)` 展示，搜索框 placeholder 为 `搜索知识空间名称`；点击 `公共空间` 后其子项隐藏且 trigger 仍为 `请选择知识库`，分类未作为已选值；搜索 `性能` 后只显示 `个人空间(1)` 与 `性能`；搜索 `不存在的知识空间xyz` 请求中显示 `正在加载知识空间...`，返回后显示 `暂无匹配的知识空间`。重新加载未保存状态后临时添加 `rag`，切换 `知识空间` 后同样展示四类分组和同一搜索 placeholder。 |

## Acceptance Coverage Summary

| Status | Count | Notes |
|---|---:|---|
| PASS | 32 | 有本轮自动化命令、代码复核、浏览器验证或组合证据支撑。 |
| MANUAL_REQUIRED | 8 | 主要是保存后重开、失效状态展示和单节点调试。 |
| FAIL | 0 | 未发现本轮自动化失败项。 |
| NOT_RUN | 0 | 所有 acceptance criterion 均已分类；未执行的浏览器交互项标为 `MANUAL_REQUIRED`。 |

## Acceptance Coverage

| Acceptance ID | Status | Evidence |
|---|---|---|
| AC-REQ-001-01 | MANUAL_REQUIRED | 代码复核显示 `KnowledgeSelectItem.TabsHead` 顺序为 `documentKnowledgeBase` -> `knowledgeSpace` -> `temporarySessionFiles`，前端 build 通过；仍需浏览器打开节点确认实际展示顺序和布局。 |
| AC-REQ-001-02 | MANUAL_REQUIRED | 后端 option 测试覆盖 keyword 过滤，前端代码调用 `getAuthorizedKnowledgeSpaceOptionsApi` 并传递搜索关键字；仍需浏览器确认切换到 `知识空间` 后加载、搜索、空状态可用。 |
| AC-REQ-001-03 | PASS | 代码复核显示 `KnowledgeSelectItem.handleSelect` 保存 `{ type: tabType, value: [...] }`，不同 tab 使用不同 option source；前端 build 通过。 |
| AC-REQ-001-04 | MANUAL_REQUIRED | 代码复核显示 `normalizeKnowledgeValue` 支持 saved scoped value；仍需浏览器或组件测试验证保存后重新打开的真实回显。 |
| AC-REQ-001-05 | PASS | `RagUtils.init_multi_retriever` 保留 `knowledge` / `tmp` 显式分支；后端测试通过，前端 build 通过。 |
| AC-REQ-002-01 | MANUAL_REQUIRED | 代码复核显示 `KnowledgeQaSelectItem` 新增 `qa` / `space` tabs 并保留 QA scope；仍需浏览器确认原 QA 选择能力仍可见可用。 |
| AC-REQ-002-02 | MANUAL_REQUIRED | 代码复核显示 QA selector 使用 authorized space option API、搜索关键字、load-more 和 scoped save shape；仍需浏览器验证搜索、多选、必填校验和回显体验。 |
| AC-REQ-002-03 | PASS | `test_normalize_qa_knowledge_value_preserves_old_array_shape` 通过，旧版 `qa_knowledge_id: [{key,label}]` 归一化为 `qa`。 |
| AC-REQ-002-04 | PASS | `test_qa_space_branch_returns_document_content_without_qa_metadata` 通过，`space` 分支不读取 QA 专用 `metadata.extra.answer`。 |
| AC-REQ-002-05 | PASS | 代码复核显示 QA `space` 分支仍返回 `retrieved_result`，`score` 与 `user_question` 参数保留；后端测试覆盖输出分支。 |
| AC-REQ-003-01 | PASS | `KnowledgeSpaceService.get_authorized_space_options` 复用 `get_grouped_spaces` 后拉平 public/department/team/personal spaces；后端 option 测试通过。 |
| AC-REQ-003-02 | PASS | 后端测试覆盖 keyword 按名称过滤；前端代码在文档检索和 QA selector 中传递搜索关键字。 |
| AC-REQ-003-03 | PASS | 后端测试覆盖分页和 `has_more`；前端代码维护 page/load-more 状态并调用下一页。 |
| AC-REQ-003-04 | PASS | option source 复用权限过滤后的 grouped spaces；runtime 调用 `KnowledgeSpaceChatService.aretrieve_chunks`，其 per-space 检索前执行 `_require_space_view_permission`。 |
| AC-REQ-003-05 | MANUAL_REQUIRED | runtime 对删除或无权 space 会通过 existing service error 失败，不会替换到其他范围；已保存 workflow 打开后的失效 UI 展示仍需带数据浏览器验证。 |
| AC-REQ-004-01 | PASS | 浏览器验证覆盖 `rag`：选择 `space` 后 `hasMetadataFilter: false`；此前浏览器验证覆盖 `knowledge_retriever`：选择 `space` 后 `hasMetadataFilter: false`。 |
| AC-REQ-004-02 | PASS | 浏览器验证覆盖 `rag`：切到 `space` 后立即隐藏 `metadata_filter`，选择 `营销` 后仍保持 `hasMetadataFilter: false`；`Parameter.tsx` 对 `knowledge_retriever` 与 `rag` 在 `space` scope 下均调用 `clearMetadataFilter()`。 |
| AC-REQ-004-03 | MANUAL_REQUIRED | 代码复核显示 render path 会处理 saved `space` scope 下的 stale `metadata_filter`；仍需保存后重新打开验证隐藏且为空。 |
| AC-REQ-004-04 | PASS | 浏览器验证覆盖 `rag`：从 `space` 切回文档知识库后 `hasMetadataFilter: true`、`hasSelectedMarketing: false`，搜索框恢复 `搜索知识库名称`；此前浏览器验证覆盖 `knowledge_retriever` 同样行为。 |
| AC-REQ-004-05 | PASS | `RagUtils.__init__` 在 `_knowledge_type == 'space'` 时使用 `{}` 构造 `ConditionCases`，忽略 stale `metadata_filter`；后端测试覆盖 `space` branch。 |
| AC-REQ-005-01 | PASS | `RagUtils.init_multi_retriever` 保留 `knowledge` -> `init_knowledge_retriever()`；后端专项测试通过。 |
| AC-REQ-005-02 | PASS | `RagUtils.init_multi_retriever` 保留 `tmp` -> `init_file_retriever()`；后端专项测试通过。 |
| AC-REQ-005-03 | PASS | `test_init_multi_retriever_uses_explicit_space_branch` 通过，`space` 不落入 `tmp`。 |
| AC-REQ-005-04 | PASS | `test_retrieve_space_question_uses_space_service` 通过，返回 `Document` 并写入 `knowledge_space_id` metadata。 |
| AC-REQ-005-05 | PASS | QA `space` 分支返回 `retrieved_result`，后端测试验证返回文档内容且设置 graph state。 |
| AC-REQ-005-06 | PASS | `test_init_multi_retriever_rejects_unknown_type`、`test_init_space_retriever_rejects_empty_selection`、`test_knowledge_retriever_space_errors_are_node_errors` 通过；知识空间配置错误和检索异常不被 remap 到其他检索范围。 |
| AC-REQ-005-07 | PASS | `test_knowledge_space_login_user_adapter_accepts_orm_user` 和 `test_knowledge_space_login_user_adapter_preserves_compatible_user` 通过；workflow ORM-like `User` 会在知识空间检索边界适配为具备 `get_user_group_ids()` 的登录用户对象，已兼容对象保持原样。 |
| AC-REQ-005-08 | PASS | `test_knowledge_space_retrieve_helper_injects_version_repo` 通过；workflow helper 创建 `KnowledgeSpaceChatService` 后会注入版本仓库依赖，避免 `_build_folder_search_kwargs()` 访问 `version_repo` 时抛 `AttributeError`。 |
| AC-REQ-006-01 | PASS | 代码复核显示 `KnowledgeSelectItem.normalizeKnowledgeValue` 默认旧值为 `knowledge`，并保留 `knowledge` / `tmp` 类型；前端 build 通过。 |
| AC-REQ-006-02 | PASS | `normalizeQaKnowledgeValue` 对旧数组默认归一化为 `qa`；后端测试通过，前端组件有同名兼容逻辑。 |
| AC-REQ-006-03 | PASS | 后端 normalizer 和 `RagUtils` 默认缺失 type 为旧逻辑；后端专项测试通过。 |
| AC-REQ-006-04 | PASS | 代码复核显示新版 QA template default 为 scoped object，选择器保存 scoped values；前端 build 通过。 |
| AC-REQ-006-05 | MANUAL_REQUIRED | 代码复核显示 `space` 不再按 `tmp` 校验分支处理；单节点调试真实执行仍需浏览器验证。 |
| AC-REQ-007-01 | PASS | 浏览器验证覆盖 `knowledge_retriever`：切换 `知识空间` 后按 `公共空间(10)`、`部门空间(5)`、`团队空间(7)`、`个人空间(4)` 展示。 |
| AC-REQ-007-02 | PASS | 浏览器验证覆盖 `rag`：切换 `知识空间` 后同样展示 `公共空间`、`部门空间`、`团队空间`、`个人空间` 分组。 |
| AC-REQ-007-03 | PASS | 浏览器验证点击 `公共空间` 后公共空间子项如 `营销` 隐藏，trigger 仍为 `请选择知识库`，未新增 selected badge，说明分类只展开/收起不保存。 |
| AC-REQ-007-04 | PASS | 浏览器验证搜索 `性能` 后只保留 `个人空间(1)` 与匹配子项 `性能`，其他空分类隐藏。 |
| AC-REQ-007-05 | PASS | 浏览器验证搜索 `不存在的知识空间xyz` 请求未返回前列表显示 `正在加载知识空间...`；代码复核显示初次加载、搜索和 load-more 均复用 `spaceLoading`。 |
| AC-REQ-007-06 | PASS | 浏览器验证搜索 `不存在的知识空间xyz` 返回后显示 `暂无匹配的知识空间`。 |
| AC-REQ-007-07 | PASS | `workflowKnowledgeSpaceSelectorRace.test.tsx` 覆盖两个节点默认处于 `space` 时，打开选择器并立即触发 footer load-more 不会请求 page 2；代码复核显示 page 1 pending 时 load-more 被 `spaceLoadingRef` 阻止。 |

## Manual Checklist

1. 打开文档知识库检索节点，确认 Tab 顺序为 `文档知识库`、`知识空间`、`临时知识库`，且三项在节点弹窗内不溢出。
2. 切换到 `知识空间`，搜索并选择一个知识空间，保存 workflow 后重新打开，确认选择项正确回显。
3. 从文档知识库切换到 `知识空间`，确认 `metadata_filter` 立即隐藏，并检查保存 payload 中 `metadata_filter.value` 已清空。
4. 从 `知识空间` 切回文档知识库，确认 `metadata_filter` 重新显示，但旧过滤条件不会恢复。
5. 打开文档知识库问答节点，确认原 QA 知识库选择仍可用，并新增 `知识空间` scope。
6. 在文档知识库问答节点中搜索、选择、保存、重新打开知识空间，确认多选、必填校验和回显符合原选择器体验。
7. 使用已删除、退出或权限被移除的知识空间打开已保存 workflow，确认 UI 有可理解的失效状态或至少不误显示为其他空间。
8. 对文档知识库检索节点执行单节点调试，选择 `知识空间` 时确认不会触发临时知识库调试限制。
9. 选择 `知识空间` 后确认四类分组顺序为 `公共空间`、`部门空间`、`团队空间`、`个人空间`，点击分类只折叠展开。
10. 搜索知识空间名称时确认搜索结果仍按分类展示，空分类隐藏；无结果时展示 `暂无匹配的知识空间`。
11. 已选择 `知识空间` 后关闭并再次打开文档知识库检索节点和文档知识库问答节点的选择器，确认默认停留在 `知识空间` 且展示第一页知识空间列表。

## Notes

- P1 follow-up 修复覆盖 `SR-001`、`SR-002`、`CQ-001`：tab 切换提交空 scoped value 并清空 metadata，跨 tab 空选择不再访问 `undefined`，文档知识库检索节点 `space` 分支异常进入节点错误路径。
- T014 bugfix 修复浏览器发现的 `rag` 漏洞：Platform “文档知识库问答” 实际节点类型为 `rag`，此前 `Parameter.tsx` 只对 `knowledge_retriever` 隐藏/清空 `metadata_filter`。修复后 `knowledge_retriever` 与 `rag` 共用同一 hide/clear 判断。
- T018 bugfix 修复 workflow 运行时选择知识空间时报 `'User' object has no attribute 'get_user_group_ids'`：知识空间检索 helper 会在进入 `KnowledgeSpaceChatService` 前将数据库 `User` 适配为 `LoginUser`，从而满足细粒度权限服务的用户组 subject 解析。
- T019 bugfix 修复 workflow 运行时选择知识空间时报 `'KnowledgeSpaceChatService' object has no attribute 'version_repo'`：workflow 手动实例化服务时补齐 `KnowledgeDocumentVersionRepositoryImpl`，与 FastAPI dependency factory 的服务依赖保持一致。
- T020 bugfix 修复已选 `知识空间` 后再次打开选择器误显示空列表：当列表为空时 footer 会立即进入视口触发 load-more，旧实现会在 page 1 未返回前请求 page 2，并通过 request id 机制丢弃 page 1；修复后 page 1 pending 时阻止 page 2 抢跑。
- 早前使用已启动的前后端服务完成 T014-T017 浏览器回归验证；T020 尝试使用 Chrome 验证时发现当前标签页正在运行用户无关任务，为避免干扰未继续接管，改用 Vitest 组件回归测试覆盖竞态。
- 保存后重开、失效空间回显和单节点调试仍保持 `MANUAL_REQUIRED`。
- `uv run ruff check --fix ...` 曾在实现阶段尝试并因既有 lint 问题失败；该命令不作为本轮通过证据。
- 未执行生产数据库迁移或数据变更。
