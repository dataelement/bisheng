# Review: Workflow Knowledge Space Retrieval Scope

## Metadata
- Feature ID: `045-workflow-knowledge-space-scope`
- Status: `CHANGES_REQUESTED`
- Related requirements: `specs/045-workflow-knowledge-space-scope/requirements.md`
- Related design: `specs/045-workflow-knowledge-space-scope/design.md`
- Related tasks: `specs/045-workflow-knowledge-space-scope/tasks.md`
- Related verification: `specs/045-workflow-knowledge-space-scope/verification.md`
- Reviewed: `2026-06-23`
- P1 follow-up: `2026-06-23`
- T014 bugfix follow-up: `2026-06-23`

## Review Summary
- Overall decision: `CHANGES_REQUESTED`
- Spec compliance: P1 findings `SR-001`、`SR-002` 已在 follow-up 中修复；浏览器发现的 `rag` 元数据过滤漏隐藏问题已通过 T014 修复；仍有 P2/P3 证据缺口和语义问题需要后续处理。
- Scope drift: 未发现明显实现了 `Excludes` 中禁止的功能。
- Code quality: P1 tab 切换边界 bug 已修复；仍有知识空间 options API 的大租户性能风险和局部重复逻辑。
- Verification evidence: P1 follow-up 后后端专项测试和 Platform build 已通过；真实 workflow editor UI、保存重开、失效知识空间回显和单节点调试仍未验证。

## P1 Fix Follow-up

| Finding ID | Status | Evidence |
|---|---|---|
| SR-001 | FIXED | `KnowledgeSelectItem.handleTabChange` 切换 scope 时提交 `{ type, value: [] }`；`Parameter.tsx` 在 `space` scope 下清空 `metadata_filter` 并调用 `onFouceUpdate` 触发表单刷新。 |
| SR-002 | FIXED | `KnowledgeRetriever._run` 对 `space` 分支异常重新抛出，`RagUtils.init_space_retriever` 对空选择抛明确错误；`test_knowledge_retriever_space_errors_are_node_errors` 和 `test_init_space_retriever_rejects_empty_selection` 通过。 |
| CQ-001 | FIXED | `KnowledgeSelectItem.handleSelect` 和 `KnowledgeQaSelectItem.handleSelect` 对空数组直接保存空 scoped value；tab 切换时清空当前 value，避免访问 `undefined.value`。 |

## T014 Bugfix Follow-up

| Finding ID | Status | Evidence |
|---|---|---|
| SR-006 | FIXED | Browser verification found Platform “文档知识库问答” is `rag`; before T014, choosing `space -> 营销` left `metadata_filter` visible. `Parameter.tsx` now treats `knowledge_retriever` and `rag` as document retrieval nodes for hide/clear behavior. Build passed and browser verification showed `rag` `space` scope with `hasMetadataFilter: false`, then switching back to document knowledge with `hasMetadataFilter: true` and cleared selected space. |

## Spec Compliance Findings

| ID | Severity | Type | Spec Reference | Implementation Reference | Finding | Required Action |
|---|---|---|---|---|---|---|
| SR-001 | P1 | SPEC_VIOLATION | `REQ-004`, `AC-REQ-004-01`, `AC-REQ-004-02`, `T005` | `KnowledgeSelectItem.tsx`; `Parameter.tsx` | Resolved in P1 follow-up. 原问题：切换到 `知识空间` tab 时没有立即更新父级参数，导致 `metadata_filter` 直到选择空间后才隐藏/清空。 | 已修复；仍需浏览器或组件测试验证真实 UI 即时隐藏。 |
| SR-002 | P1 | SPEC_VIOLATION | `REQ-003`, `AC-REQ-003-05`, `REQ-005`, `AC-REQ-005-06`, `T009` | `knowledge_retriever.py`; `knowledge.py`; `test_knowledge_space_scope.py` | Resolved in P1 follow-up. 原问题：文档知识库检索节点会把 `space` 检索异常包装为普通 output 字符串。 | 已修复并补充后端测试；删除/未授权真实服务 fixture 仍属于 SR-004 的证据缺口。 |
| SR-003 | P2 | SPEC_GAP | `REQ-002`, `AC-REQ-002-05`, `design.md` QARetrieverNode | `qa_retriever.py:31`; `qa_retriever.py:63-69` | QA 节点保留了 `score` 参数，但 `space` 分支调用 `retrieve_knowledge_space_documents_sync(top_k=1)` 时没有传递或应用 `_score`。如果“得分阈值参数保持一致”表示与原 QA 检索一样参与过滤，则当前实现不满足；如果只是保留 UI/API 字段，spec 需要明确该参数在 `space` 分支无效。 | 产品/设计层确认 `score` 对知识空间检索是否生效；若需要生效，扩展知识空间检索接口或结果过滤；若不需要，更新 spec 和 UI 文案避免误导。 |
| SR-004 | P2 | EVIDENCE_GAP | `T009`, `T010`, `AC-REQ-003-05`, `AC-REQ-004-05`, `AC-REQ-005-06` | `test_knowledge_space_scope.py` | `tasks.md` 中 T009/T010 标为完成，但后端测试只覆盖 option 过滤分页、显式 `space` 分支、未知类型、space helper、QA 兼容分支；没有覆盖未授权/删除 space、service 异常路径，也没有直接构造 stale `metadata_filter` 初始化验证。 | 补充对应测试，或把相关 task/verification 状态降级为 `MANUAL_REQUIRED` / `EVIDENCE_GAP`。 |
| SR-005 | P3 | EVIDENCE_GAP | `design.md` i18n, `T002` | `src/frontend/platform/public/locales/dev/flow.json` | Platform 有 `dev` locale 目录，但新增 `knowledgeSpace`、`searchKnowledgeSpaceName`、`noKnowledgeSpace` 只覆盖了 `zh-Hans`、`en-US`、`ja`。如果 `dev` locale 是活跃或开发可选语言，则 locale coverage 未完整。 | 补齐 `dev/flow.json`，或在 spec/review 中明确 `dev` locale 不属于活跃覆盖范围。 |
| SR-006 | P1 | SPEC_VIOLATION | `REQ-004`, `AC-REQ-004-01`, `AC-REQ-004-02`, `AC-REQ-004-04`, `T014` | `Parameter.tsx` | Resolved in T014 bugfix. 原问题：`rag` 选择 `space` 后仍显示 `metadata_filter`，因为隐藏/清空逻辑仅覆盖 `knowledge_retriever`。 | 已修复并通过浏览器回归验证；保存后重开仍属于 `AC-REQ-004-03` 的人工验证缺口。 |

## Code Quality Findings

| ID | Severity | Area | Reference | Finding | Suggested Action |
|---|---|---|---|---|---|
| CQ-001 | P1 | bug | `KnowledgeSelectItem.tsx`; `KnowledgeQaSelectItem.tsx` | Resolved in P1 follow-up. 原问题：跨 tab 删除旧 badge 时空数组会导致访问 `undefined.value`。 | 已修复空数组分支，并在 tab 切换时清空当前 value。 |
| CQ-002 | P2 | performance | `knowledge_space_service.py:4583-4605` | `get_authorized_space_options` 先调用 `get_grouped_spaces` 拉取并格式化全部可见空间，再在内存中 keyword 过滤和分页。大租户空间数量较多时，`page_size` 不能限制后端权限计算和内存开销。 | 如果该接口会用于高频搜索/滚动加载，应改为 service/repository 层按 keyword/page 做分页，并保留权限过滤。 |
| CQ-003 | P3 | maintainability | `KnowledgeSelectItem.tsx`; `KnowledgeQaSelectItem.tsx` | 两个 selector 内部重复了知识空间分页、搜索、tab 切换和 scoped value 归一化逻辑。短期可接受，但后续再加节点或修 bug 时容易出现行为差异。 | 抽取一个局部 hook/helper，例如 `useKnowledgeSpaceOptions` 和 scoped select value normalizer，保持两个节点一致。 |

## Coverage / Evidence Gaps

- `MANUAL_REQUIRED`: `verification.md` 中仍有 11 个 acceptance criteria 依赖真实 workflow editor 操作，包括 tab 展示、搜索/选择、保存重开、metadata hide/clear、失效空间回显和单节点调试。
- `EVIDENCE_GAP`: 未授权/删除知识空间运行时失败路径缺少自动化测试。
- `EVIDENCE_GAP`: stale `metadata_filter` 的后端忽略行为缺少直接测试。
- `EVIDENCE_GAP`: 前端没有组件测试覆盖 tab 切换即清空、旧参数回显和跨 tab 删除边界。

## Coverage Matrix

| Requirement | Acceptance Criteria | Tasks | Evidence | Status |
|---|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | T002, T003, T006, T011, T012 | Code review + Platform build; UI items manual pending | PARTIAL |
| REQ-002 | AC-REQ-002-01..05 | T004, T006, T008, T010, T011, T012 | Backend tests for old array and QA `space`; UI manual pending; score semantics unclear | PARTIAL |
| REQ-003 | AC-REQ-003-01..05 | T001, T003, T004, T009, T010 | Option API test; permission path code review; stale/deleted behavior not tested | PARTIAL |
| REQ-004 | AC-REQ-004-01..05 | T005, T007, T010, T011 | P1 tab-switch clear fixed by code; browser/component verification still pending | PARTIAL |
| REQ-005 | AC-REQ-005-01..06 | T007, T008, T009, T010 | P1 failure-as-node-error fixed by code and backend tests; deleted/unauthorized fixture coverage still pending | PARTIAL |
| REQ-006 | AC-REQ-006-01..05 | T003, T004, T006, T007, T008, T010, T011 | Backend compatibility tests + code review; single-node debug manual pending | PARTIAL |

## Out-of-Scope Changes

- 未发现实现了明确 excluded 的独立知识空间管理页、权限模型变更、全局 workflow 节点批量支持或元数据过滤能力扩展。
- `KnowledgeSelectItem` / `KnowledgeQaSelectItem` 从 legacy `page` 调用改成 `cursor` 调用 `readFileLibDatabase`，与当前 API wrapper contract 一致，未判定为 scope drift。

## Open Questions

- QA 节点选择 `space` 时，`score` 参数是否应该生效？如果不生效，UI 是否应该隐藏或标注该参数对知识空间无效？
- 文档知识库检索节点对 `space` 检索失败时，项目标准的“节点错误”表现是抛异常、设置状态，还是允许 output 中返回错误字符串？
- `dev` locale 是否属于 Platform 活跃语言覆盖范围？
