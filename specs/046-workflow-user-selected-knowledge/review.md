# Review: Workflow User Selected Knowledge

## Metadata
- Feature ID: `046-workflow-user-selected-knowledge`
- Status: `P1_FIXED_P2_OPEN`
- Related requirements: `specs/046-workflow-user-selected-knowledge/requirements.md`
- Related design: `specs/046-workflow-user-selected-knowledge/design.md`
- Related tasks: `specs/046-workflow-user-selected-knowledge/tasks.md`
- Related verification: `specs/046-workflow-user-selected-knowledge/verification.md`
- Reviewed: `2026-06-24`

## Review Summary
- Overall decision: `P1_FIXED_P2_OPEN`
- Spec compliance: 原 2 个 P1 问题已修复并补充验证证据；P2/P3 问题仍保留，包括 workflow 输入阶段缺少选择的提前拒绝、无关变更剥离、分页/计数/重复实现风险。
- Scope drift: 当前 worktree 包含 telemetry、vite config、`celerybeat-schedule.db` 等 046 spec 未列入的变更，需要从本功能变更集中剥离或补充独立 spec / 说明。
- Code quality: 选择器存在分页缺失、重复计数和前后端重复实现风险。
- Verification evidence: pytest、build、helper tests、Platform/Client 选择器组件测试有效；浏览器冒烟仍明确 blocked。

## P1 Fix Follow-up

| ID | Resolution | Evidence |
|---|---|---|
| SR-001 | FIXED | `src/backend/bisheng/workflow/common/knowledge.py` 对 runtime knowledge selection 固定启用 `_knowledge_auth`，并在 `init_knowledge_retriever()` 通过 `_runtime_selection_required` 强制 `check_auth=True`；`test_runtime_knowledge_retriever_forces_backend_permission_check` 已覆盖。 |
| SR-002 | FIXED_FOR_P1 | 已补充后端 runtime 回归、Platform 选择器组件测试、Client 选择器组件测试；最新验证为 backend `27 passed`、Platform `6 passed`、Client `6 passed`。浏览器冒烟仍因本地 3001 未监听保留为 blocked。 |

## Spec Compliance Findings
| ID | Severity | Type | Spec Reference | Implementation Reference | Finding | Required Action |
|---|---|---|---|---|---|---|
| SR-001 | P1 | SPEC_VIOLATION | `REQ-006`, `AC-REQ-006-01`, `AC-REQ-006-02`, `NFR-004`, `T011` | `src/backend/bisheng/workflow/common/knowledge.py:403-428`, `src/backend/bisheng/workflow/common/knowledge.py:524-540`, `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/RetrievalWeightSlider.tsx:67-87` | 知识库来源运行时只校验文件存在、所属知识库、文件类型和成功状态；真正的知识库权限校验仍由 `_knowledge_auth` 决定。新节点模板的 `advanced_retrieval_switch` 默认 `{}`，`search_switch` 组件默认写入 `user_auth: false`，因此运行态自选知识库可以走 `KnowledgeDao.get_list_by_ids()`，没有无条件重新校验当前用户对所选知识库 / 文件的访问权限。前端列表传 `permission_id=use_kb` 不能作为安全边界。 | 对自选知识节点强制后端权限校验，不能受节点高级检索开关影响。建议在 `apply_runtime_knowledge_selection()` 或 `init_knowledge_retriever()` 中对 runtime selection 固定 `check_auth=True`，或显式调用 `KnowledgePermissionService` / `PermissionService` 校验 `use_kb` 与文件可见性，并补充未授权、权限移除、文件删除回归测试。 |
| SR-002 | P1 | EVIDENCE_GAP | `T014`, `T015`, `verification.md`, `AC-REQ-002-01..05`, `AC-REQ-003-01..08`, `AC-REQ-004-03..04`, `AC-REQ-006-01..04` | `src/frontend/platform/src/test/workflowUserSelectedKnowledge.test.ts:1-57`, `src/frontend/client/src/pages/appChat/userSelectedKnowledge.test.ts:1-57`, `src/backend/test/workflow/test_user_selected_knowledge.py:27-231`, `specs/046-workflow-user-selected-knowledge/verification.md:26-43` | `tasks.md` 已勾选 T014/T015，`verification.md` 将 REQ-001 到 REQ-006 记为 PASS，但当前证据主要是 helper tests、build 和部分后端 unit tests。没有组件 / 集成测试或浏览器证据覆盖：运行页真实展示选择器、未选择时阻止 websocket 发送、选择来源替换、知识库不允许文件夹、知识空间文件夹 payload、前端超限阻止、保存重开新节点配置。后端 T014 done condition 中的缺少选择、多个自选节点共享同一选择、整库/整空间无范围检索、未授权 / 删除资源、旧节点行为回归也没有完整专项测试证据。 | 将 `verification.md` 中缺证据的 acceptance 降级为 `MANUAL_REQUIRED` / `NOT_RUN`，或补齐 Platform/Client 组件测试、payload snapshot、后端集成测试和浏览器冒烟证据后再保持 PASS。T014/T015 不应在缺少 done condition 证据时保持全量完成。 |
| SR-003 | P2 | SPEC_VIOLATION | `AC-REQ-004-04`, `REQ-004`, `T010` | `src/backend/bisheng/workflow/graph/graph_engine.py:333-379`, `src/backend/bisheng/workflow/common/knowledge.py:386-391` | 后端只在 input node data 内存在 `__runtime_knowledge_selection` 时抽取并校验；如果 payload 缺失，`GraphEngine` 不会根据 workflow 是否包含自选知识节点提前拒绝，而是等自选知识节点实际执行时才报错。对于包含自选知识节点但该节点被条件分支跳过的 workflow，后端可能不会按 `AC-REQ-004-04` 要求返回“缺少运行态知识选择”的明确错误。 | 在 `continue_run` / `acontinue_run` 输入阶段根据当前 workflow nodes 判断是否包含自选知识节点；包含时要求本轮 input payload 带保留字段并通过解析校验。若设计上允许条件分支跳过时不选择，需要先更新 requirements。 |
| SR-004 | P2 | SCOPE_DRIFT | `design.md File Structure Plan`, `tasks.md Boundaries` | `git diff --name-only`: `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py`, `src/backend/bisheng/worker/telemetry/mid_table.py`, `src/backend/test/test_knowledge_space_content_telemetry.py`, `src/backend/celerybeat-schedule.db`, `src/frontend/client/vite.config.ts`, `src/frontend/platform/vite.config.mts` | 当前 worktree 中存在多个 046 spec 未列入、也不属于自选知识节点实现边界的变更。它们会扩大 review 和回归范围，并违反 SDD “不实现 tasks.md 未列出的任务 / 避免无关重写”原则。 | 将无关变更从本功能变更集中剥离；如果这些变更必须一起交付，需要补充独立 spec 或在 046 retrospective 中明确 scope change、风险和验证证据。 |

## Code Quality Findings
| ID | Severity | Area | Reference | Finding | Suggested Action |
|---|---|---|---|---|---|
| CQ-001 | P2 | bug / UX | `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx:138-146`, `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx:145-153`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py:5667-5677` | 前端 `effective_file_count` 使用 `selectedFiles.length + selectedFolders folderStats`，没有按最终展开文件去重。用户选择一个包含 20 个文件的文件夹后，再单独选择其中一个文件，后端会用 `seen` 去重并认为最终仍是 20 个文件，但前端会计算为 21 并阻止发送。反向地，文件夹 stats 异步未返回前也可能短暂低估。 | 前端应使用后端计数 / 解析接口返回的最终去重文件数，或在选择文件夹时禁止选择其子文件并等待 stats 完成后才允许发送。 |
| CQ-002 | P2 | scalability / UX | `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx:99-108`, `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx:165-183`, `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx:105-123`, `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx:172-190` | 选择器固定拉取知识库 80 条、知识库文件 200 条、知识空间 children 100 条，未实现分页 / load more。用户拥有更多知识库、空间或文件时，运行态选择器无法选择超出第一页的数据。 | 复用现有分页 / cursor 模式，至少对来源列表和文件树提供加载更多或搜索到后端分页结果。 |
| CQ-003 | P3 | maintainability | `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx`, `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx`, `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/userSelectedKnowledge.ts`, `src/frontend/client/src/pages/appChat/userSelectedKnowledge.ts` | Platform 和 Client 各复制了一套选择器、类型和校验逻辑，且包含硬编码中文文案。后续修复计数、分页、错误状态时容易两端漂移。 | 至少抽出纯函数测试用 shared helper；文案接入各自 i18n 系统。UI 组件可继续分端实现，但核心 selection normalize / validate / count 逻辑不要重复。 |

## Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Evidence | Status |
|---|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | T004, T009, T014, T015, T016, T017 | Node templates, backend registration, build; no save/reopen browser evidence | PARTIAL |
| REQ-002 | AC-REQ-002-01..05 | T001, T005, T007, T008, T015, T016, T017 | Helper tests detect node type; Platform/Client picker component tests cover runtime selection UI payload; browser send-guard evidence still blocked | PARTIAL |
| REQ-003 | AC-REQ-003-01..08 | T003, T005, T006, T008, T011, T014, T015, T016, T017 | Backend tests cover folder/file scope; Platform/Client component tests cover knowledge/space payload and over-limit state; count overlap issue remains | PARTIAL |
| REQ-004 | AC-REQ-004-01..05 | T002, T007, T008, T010, T011, T014, T015, T016, T017 | Payload field and GraphState extraction tested; missing-selection workflow-level behavior not enforced | FAIL |
| REQ-005 | AC-REQ-005-01..07 | T012, T013, T014, T016, T017 | New node classes and partial backend tests; no full RAG answer/output integration evidence | PARTIAL |
| REQ-006 | AC-REQ-006-01..05 | T003, T008, T009, T011, T012, T013, T014, T015, T016, T017 | Space permission path covered by existing service; runtime knowledge path now forces `check_auth=True`; real DB/browser unauthorized evidence still not run | PARTIAL |

## Out-of-Scope Changes
- `src/backend/bisheng/telemetry/domain/mid_table/knowledge_space_content.py`, `src/backend/bisheng/worker/telemetry/mid_table.py`, `src/backend/test/test_knowledge_space_content_telemetry.py`: telemetry retry/preview changes are unrelated to 046 self-selected workflow knowledge.
- `src/backend/celerybeat-schedule.db`: generated runtime database file should not be included in this feature review/commit.
- `src/frontend/client/vite.config.ts`, `src/frontend/platform/vite.config.mts`: vite config changes are not listed in 046 design/tasks.
- Broad format churn in `src/backend/bisheng/worker/workflow/redis_callback.py`, `src/backend/bisheng/workflow/common/node.py`, `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py` increases review noise; keep only behaviorally required hunks where possible.

## Open Questions
- 是否要求“包含自选知识节点但条件分支未执行该节点”时仍必须选择知识来源？当前 requirements 写的是必须后端拒绝；如果希望允许跳过，需要更新 `AC-REQ-004-04`。
- 自选知识库来源是否应固定按 `use_kb` 校验，还是复用某个现有工作流运行权限模型？当前 requirements 明确要求后端重新校验访问权限，建议固定 `use_kb`。
