# Design: Workflow Knowledge Space Retrieval Scope

## Metadata
- Feature ID: `045-workflow-knowledge-space-scope`
- Status: `draft`
- Related requirements: `specs/045-workflow-knowledge-space-scope/requirements.md`
- Created: `2026-06-23`
- Updated: `2026-06-23`

## Context
- Existing architecture:
  - Platform workflow editor lives under `src/frontend/platform/src/pages/BuildPage/flow/`.
  - Workflow node templates are defined in `src/frontend/platform/src/controllers/API/workflow.ts`.
  - 文档知识库检索节点使用 `KnowledgeSelectItem` 渲染 `knowledge_select_multi`。
  - 文档知识库问答节点使用 `KnowledgeQaSelectItem` 渲染 `qa_select_multi`。
  - 元数据过滤由 `MetadataFilter` 和节点参数渲染层按 `metadata_filter` 参数展示。
  - 文档知识库检索运行时通过 `KnowledgeRetriever` 和 `RagUtils` 初始化 retriever。
  - 文档知识库问答运行时通过 `QARetrieverNode` 初始化 QA retriever。
  - 知识空间现有 API 和服务位于 `bisheng/knowledge` 模块及 Platform `knowledgeSpace` API wrapper。
- Relevant files inspected:
  - `src/frontend/platform/src/controllers/API/workflow.ts`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem.tsx`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeQaSelectItem.tsx`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/MetadataFilter.tsx`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/Parameter.tsx`
  - `src/frontend/platform/src/util/flowCompatible.ts`
  - `src/frontend/platform/src/controllers/API/knowledgeSpace.ts`
  - `src/frontend/platform/src/controllers/API/departmentKnowledgeSpace.ts`
  - `src/backend/bisheng/workflow/nodes/knowledge_retriever/knowledge_retriever.py`
  - `src/backend/bisheng/workflow/nodes/qa_retriever/qa_retriever.py`
  - `src/backend/bisheng/workflow/common/knowledge.py`
  - `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`
  - `src/backend/bisheng/knowledge/domain/services/knowledge_space_chat_service.py`
- Constraints from project guidance:
  - Frontend Platform must use Zustand/context patterns already present, `react-query` v3 style where server state hooks are added, `@/controllers/request.ts`, `bs-ui`, and existing i18n files.
  - Workflow editor uses `@xyflow/react`; do not introduce `react-flow-renderer`.
  - Backend must preserve DDD layering and permission service boundaries.
  - This spec-only phase must not modify production code.

## Goals / Non-Goals

### Goals
- Add `知识空间` retrieval scope to the existing document knowledge retrieval node.
- Add knowledge space selection to the existing document knowledge QA node without removing old QA knowledge base behavior.
- List selectable spaces from the user's joined or otherwise authorized knowledge spaces.
- Display knowledge space options as an expandable tree grouped by `space_level` in the order public, department, team, personal.
- Show an explicit loading state while the knowledge space selector is loading, searching, or loading more options.
- Hide and clear metadata filters when the active retrieval scope is `space`.
- Extend workflow runtime so `space` is a first-class branch and does not fall through to temporary knowledge base retrieval.
- Preserve old workflow parameter compatibility.

### Non-Goals
- Do not redesign all workflow node parameter schemas.
- Do not alter knowledge space permission semantics.
- Do not add metadata filtering for knowledge spaces in this phase.
- Do not change the output variable names of either node.
- Do not change existing document knowledge base or temporary knowledge base retrieval behavior.

## Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | `KnowledgeSelectItem` adds `space` tab between `knowledge` and `tmp`; parameter shape remains scoped by type | Frontend tests + manual workflow editor check |
| REQ-002 | AC-REQ-002-01..05 | `KnowledgeQaSelectItem` accepts old array and new scoped value; backend QA branch recognizes `space` | Frontend tests + backend regression tests |
| REQ-003 | AC-REQ-003-01..05 | Authorized knowledge space option API and runtime permission validation | API tests + backend service tests |
| REQ-004 | AC-REQ-004-01..05 | Parameter rendering hides `metadata_filter`; tab switch clears value; backend ignores stale filters for `space` | Frontend tests + backend test |
| REQ-005 | AC-REQ-005-01..08 | `RagUtils` and `QARetrieverNode` add explicit knowledge space retrieval branches and inject workflow-only service dependencies | Backend unit/integration tests |
| REQ-006 | AC-REQ-006-01..05 | Compatibility parser handles old and new parameter shapes | Regression tests + manual old workflow load |
| REQ-007 | AC-REQ-007-01..06 | Knowledge space options are grouped by `space_level` and rendered as expandable non-selectable category nodes; selector loading and empty states are visible | Manual workflow editor check + Platform build |

## Architecture
- Frontend:
  - Keep workflow node configuration in `workflow.ts`.
  - Extend selection components rather than introducing a new UI library.
  - Use a common local type for retrieval scopes where practical:
    - `knowledge`: existing document knowledge base.
    - `space`: knowledge space.
    - `tmp`: existing temporary knowledge base, only where the node already supports it.
    - `qa`: existing QA knowledge base scope for the QA node when a distinct backend branch is needed.
  - Add a reusable option-loading helper or hook only if it removes duplication between `KnowledgeSelectItem` and `KnowledgeQaSelectItem`.
- Backend:
  - Add an explicit `space` retrieval branch in workflow runtime.
  - Reuse existing knowledge space domain services for retrieval and permission checks wherever possible.
  - Do not query knowledge space tables directly from workflow nodes if an existing service/repository abstraction exists.
  - Runtime must treat stale `metadata_filter` on `space` as ignored.
- Compatibility:
  - Existing `knowledge: { type: "knowledge" | "tmp", value: [...] }` remains valid.
  - Existing `qa_knowledge_id: [{ key, label }]` remains valid and is interpreted as the original QA knowledge base scope.
  - New QA node saved form may use a scoped object such as `{ type: "qa" | "space", value: [...] }`; backend must normalize both shapes before execution.

## Data Contract

### Document knowledge retrieval node
- Existing parameter:
  - `knowledge`: `{ type: "knowledge" | "tmp", value: Array<{ key: number|string, label: string }> }`
- New parameter:
  - `knowledge`: `{ type: "knowledge" | "space" | "tmp", value: Array<{ key: number|string, label: string }> }`
- Rules:
  - `type="knowledge"` means existing document knowledge base ids.
  - `type="space"` means knowledge space ids.
  - `type="tmp"` means existing temporary file variable ids.
  - Switching between types clears incompatible selections except where existing behavior intentionally keeps current-tab selections.

### Document knowledge QA node
- Existing parameter:
  - `qa_knowledge_id`: `Array<{ key: number|string, label: string }>`
- New normalized parameter:
  - `qa_knowledge_id`: `{ type: "qa" | "space", value: Array<{ key: number|string, label: string }> }`
- Compatibility rules:
  - If `qa_knowledge_id` is an array, normalize to `{ type: "qa", value: qa_knowledge_id }`.
  - If `qa_knowledge_id.type` is missing, normalize to `qa`.
  - If `qa_knowledge_id.type === "space"`, use selected ids as knowledge space ids and do not parse QA-only `metadata.extra.answer` without a guard.

### Metadata filter
- Existing parameter:
  - `metadata_filter`: object accepted by `ConditionCases`.
- New behavior:
  - Frontend removes or resets `metadata_filter` to `{}` when the document retrieval node active scope becomes `space`.
  - Backend ignores `metadata_filter` whenever normalized retrieval scope is `space`.

## Frontend Design

### KnowledgeSelectItem
- Add `KnowledgeType.Space = "space"`.
- Render tabs in order:
  - `文档知识库`
  - `知识空间`
  - `临时知识库`
- Use three-column tab layout or an equivalent responsive layout that does not overflow inside the node popover.
- Load document knowledge options through the existing `readFileLibDatabase` flow.
- Load temporary options through the existing workflow input-file scan.
- Load knowledge space options through an authorized-space API that supports name search and pagination/load-more.
- For knowledge space scope, group returned options by `space_level` and render them in this fixed order:
  - `public`: `公共空间`
  - `department`: `部门空间`
  - `team`: `团队空间`
  - `personal`: `个人空间`
- Category nodes are expandable/collapsible and not selectable; selected values remain concrete knowledge space ids only.
- Search keeps the tree structure by grouping the filtered API result; groups without child options are hidden.
- The list area shows loading feedback while the knowledge space option request is pending, including initial load, search, and load-more.
- If the filtered knowledge space result is empty after loading, render an explicit empty state.
- Load-more must not start while an initial knowledge-space request is still pending. When the current tab opens directly on `space`, the empty list footer can be visible immediately; the selector must let page 1 settle before requesting page 2 so the first-page result is not discarded by the request id guard.
- Keep `hideSearch` only for temporary knowledge base; knowledge space should allow search like document knowledge base.
- Persist selected spaces with `type: "space"` and `value` as `{ key, label }[]`.

### KnowledgeQaSelectItem
- Preserve old array value support.
- Add a retrieval scope control matching the node's current UI style:
  - Existing QA knowledge base scope.
  - New knowledge space scope.
- Do not add temporary knowledge base unless the current node already supports it.
- Search, pagination, selection, required validation, and disabled/invalid handling should mirror the existing QA knowledge selection UX.
- Knowledge space scope uses the same grouped tree display, expand/collapse behavior, loading state, and empty state as the document knowledge retrieval node.
- Knowledge space scope uses the same pending-request guard so reopening the selector on an already selected `space` tab cannot skip page 1.
- Save new values in a scoped object while retaining backward compatibility with old array values.

### Metadata filter visibility
- The parameter rendering layer should determine whether `metadata_filter` should be rendered by inspecting the same node's active retrieval scope.
- The hide/clear behavior applies to document retrieval nodes that use `knowledge_select_multi` and expose `metadata_filter`, currently `knowledge_retriever` and `rag`.
- If the active scope changes to `space`, update node data so `metadata_filter.value` becomes `{}` before save.
- If the active scope changes back to document knowledge base, render an empty metadata filter rather than restoring the old cleared value.
- Keep this logic local to affected nodes and avoid hiding metadata filters globally for unrelated components.

### i18n
- Add or reuse Platform `flow.json` keys for:
  - `knowledgeSpace`
  - knowledge space search placeholder
  - no authorized knowledge spaces empty state
  - invalid or deleted knowledge space display, if needed
- Update all active locale files used by Platform workflow editor, at minimum `zh-Hans` and `en-US`; mirror existing locale coverage if more files already contain matching namespace keys.

## Backend Design

### Authorized knowledge space option API
- Preferred path: reuse or extend existing knowledge space API/service to return spaces the current user has joined or is otherwise authorized to use.
- Required capability:
  - name search
  - pagination or load-more compatible response
  - id/name fields for frontend options
  - permission filtering through existing knowledge space permission model
- If no existing endpoint covers joined plus authorized spaces with search/pagination, add a narrow endpoint under the existing knowledge space module rather than embedding list logic in workflow frontend-specific code.

### KnowledgeRetriever / RagUtils
- Normalize retrieval scope in `RagUtils.__init__`.
- Change `init_multi_retriever()` from binary branch to explicit branches:
  - `knowledge` -> existing `init_knowledge_retriever()`
  - `space` -> new `init_space_retriever()`
  - `tmp` -> existing `init_file_retriever()`
- `init_space_retriever()` should:
  - validate selected space ids are non-empty.
  - call existing knowledge space retrieval service or repository-backed service with current user context.
  - preserve retrieved result output shape expected by `KnowledgeRetriever._run()`.
  - skip metadata filter conversion and application.
- Unknown types should fail with a clear workflow node error rather than defaulting to temporary file retrieval.

### QARetrieverNode
- Normalize `qa_knowledge_id` before initialization.
- Branch by normalized scope:
  - `qa` -> current behavior.
  - `space` -> knowledge space retrieval behavior.
- For `space`, preserve `user_question`, `score`, and output key semantics.
- Guard QA-only metadata parsing:
  - Existing QA branch may keep reading `metadata.extra.answer`.
  - Space branch must not assume `metadata.extra.answer` exists.
- The final result must remain assignable to the existing `retrieved_result` output so downstream workflow nodes do not need schema changes.

### Permission and failure behavior
- Option listing filters by current user's joined/authorized spaces.
- Runtime revalidates access because workflow definitions can be stale or tampered with.
- Workflow runtime may initialize `BaseNode.user_info` from the database `User` model. Before calling `KnowledgeSpaceChatService`, the knowledge-space retrieval helper must adapt that object to a `LoginUser`-compatible object when it lacks `get_user_group_ids()`.
- If the caller already passes `LoginUser` or `UserPayload`, keep the object unchanged so endpoint and test paths retain existing behavior.
- Workflow runtime creates `KnowledgeSpaceChatService` outside FastAPI dependency injection, so the helper must explicitly create and assign `KnowledgeDocumentVersionRepositoryImpl` to `service.version_repo` before calling `aretrieve_chunks()`. This preserves the same dependency contract as `get_knowledge_space_chat_service()`.
- If no selected authorized space remains:
  - return an explicit node error when configuration is invalid or unauthorized.
  - return empty retrieval only when the selected spaces are valid but produce no hits.
- Do not silently replace selected spaces with document knowledge bases or temporary files.

## File Structure Plan
| Path | Create / Modify | Responsibility | Requirements |
|---|---|---|---|
| `src/frontend/platform/src/controllers/API/knowledgeSpace.ts` | modify | Add or expose authorized searchable knowledge space option API wrapper | REQ-003 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeSelectItem.tsx` | modify | Add `space` tab, grouped tree option display, and option-loading behavior | REQ-001, REQ-003, REQ-006, REQ-007 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/KnowledgeQaSelectItem.tsx` | modify | Add knowledge space selection while preserving old array values; reuse grouped tree display and loading behavior | REQ-002, REQ-003, REQ-006, REQ-007 |
| `src/frontend/platform/src/components/bs-ui/select/multi.tsx` | modify if needed | Add optional grouped-option rendering and loading/empty states without changing existing flat-option behavior | REQ-007 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/Parameter.tsx` | modify | Hide and clear `metadata_filter` for `knowledge_retriever` and `rag` when scope is `space` | REQ-004 |
| `src/frontend/platform/src/controllers/API/workflow.ts` | modify if needed | Adjust node template defaults for new scoped QA value or labels | REQ-002, REQ-006 |
| `src/frontend/platform/src/util/flowCompatible.ts` | modify if needed | Normalize old workflow node params | REQ-006 |
| `src/frontend/platform/public/locales/*/flow.json` | modify | Add labels and empty/search text | REQ-001, REQ-002, REQ-003 |
| `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py` | modify if needed | Provide authorized searchable/paginated option API | REQ-003 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | modify if needed | Centralize authorized space listing | REQ-003 |
| `src/backend/bisheng/workflow/common/knowledge.py` | modify | Add explicit `space` retrieval branch | REQ-004, REQ-005, REQ-006 |
| `src/backend/bisheng/workflow/nodes/qa_retriever/qa_retriever.py` | modify | Normalize old/new QA params and add `space` branch | REQ-002, REQ-005, REQ-006 |
| `src/backend/test/workflow/test_knowledge_space_scope.py` | create | Backend runtime regression tests | REQ-002, REQ-004, REQ-005, REQ-006 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowNode/component/__tests__/` | create/modify if test setup exists | Frontend component regression tests | REQ-001, REQ-002, REQ-004, REQ-006 |

## Testing Strategy
| Area | Target | Notes |
|---|---|---|
| Frontend component | `KnowledgeSelectItem` | Verify tab order, search, selection, saved value, old value回显。 |
| Frontend component | `KnowledgeQaSelectItem` | Verify old array compatibility and new `space` scoped value。 |
| Frontend component | Knowledge space grouped selector | Verify fixed group order, expand/collapse-only group headers, grouped search result, loading state, and empty state。 |
| Frontend parameter rendering | `Parameter.tsx` or equivalent | Verify `metadata_filter` hidden and cleared when scope is `space`。 |
| Backend workflow runtime | `RagUtils` | Verify `knowledge`/`tmp` regressions and new `space` branch。 |
| Backend workflow runtime | knowledge-space login user adapter | Verify ORM-like workflow `User` is adapted before permission service calls。 |
| Backend QA runtime | `QARetrieverNode` | Verify old array params and new `space` params。 |
| Permission/API | knowledge space option endpoint | Verify joined/authorized spaces are included and unauthorized spaces excluded。 |
| Static verification | Platform build/typecheck | `cd src/frontend/platform && npm run build` or project-approved equivalent。 |
| Backend verification | workflow tests | `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`。 |

## Decisions

### Decision: Use `space` as the workflow retrieval scope value
- Context: Existing document knowledge retrieval stores `knowledge.type` as a short string.
- Options considered: `knowledge_space`, `space`, numeric enum.
- Decision: Use `space`.
- Rationale: It is concise, consistent with existing `knowledge` and `tmp`, and avoids leaking API route names into workflow params.
- Consequences: Backend must treat unknown types as invalid and must not route them to temporary knowledge base retrieval.

### Decision: Normalize QA params instead of breaking old arrays
- Context: `qa_retriever` currently stores `qa_knowledge_id` as an array, while scoped selection needs a type.
- Options considered: Replace old array with object only; support both array and object.
- Decision: Support both array and object, normalize internally.
- Rationale: Existing workflow definitions must remain runnable.
- Consequences: Frontend and backend need compatibility helpers until all saved workflows are naturally updated.

### Decision: Clear metadata filter on switch to knowledge space
- Context: 用户明确要求选择知识空间时 UI 隐藏并清空保存值。
- Options considered: Hide only; hide and backend ignore; hide and clear.
- Decision: Hide and clear in frontend, also ignore stale backend values defensively.
- Rationale: Avoid invalid hidden config affecting future runs and preserve runtime safety for stale workflow data.
- Consequences: Switching back to document knowledge base will not restore old metadata filters.

### Decision: Adapt workflow ORM `User` only at knowledge-space retrieval boundary
- Context: Workflow nodes historically store `self.user_info` as the database `User` model, but knowledge-space permission checks require `LoginUser/UserPayload` methods such as `get_user_group_ids()`.
- Options considered: Change `BaseNode.init_user_info()` globally; adapt inside knowledge-space retrieval helper.
- Decision: Adapt inside the knowledge-space retrieval helper only.
- Rationale: Keeps the fix scoped to the failing path and avoids changing every workflow node's `user_info` type.
- Consequences: Future workflow features that call permission services directly should use the same boundary pattern or explicitly construct `LoginUser`.

## Open Risks
- Existing knowledge space APIs may not provide a single searchable/paginated “joined or authorized” list; implementation may need a narrow backend API addition.
- Knowledge space retrieval result metadata may differ from QA retriever expectations; QA `space` branch must avoid QA-only metadata assumptions.
- UI popover width may need responsive adjustment for three tabs inside workflow node parameter panels.
