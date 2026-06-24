# 设计说明 Design: Workflow User Selected Knowledge

## 阅读摘要
- 本文档说明：如何在现有 workflow 节点、运行态输入和检索能力内实现 `自选知识问答`、`自选知识检索`。
- 设计重点：新增节点复用现有 `rag` / `knowledge_retriever` 能力；运行态知识选择通过输入节点本轮提交携带，并写入 workflow 共享状态供新节点读取；前端在 Platform 和已发布使用页的 `dialog_input` 与 `form_input` 状态都展示 TAB 区分的树形勾选组件。
- 不在本设计中处理：不重构 workflow 画布、不改变现有文档知识节点、不新增元数据过滤。
- 阅读摘要用于快速理解；需求追踪、文件计划、边界承诺和测试策略以结构化表格为准。

## 元信息 Metadata
- Feature ID: `046-workflow-user-selected-knowledge`
- Status: `draft`
- Related requirements: `specs/046-workflow-user-selected-knowledge/requirements.md`
- Created: `2026-06-23`
- Updated: `2026-06-24`

## 上下文 Context
- 现有架构 Existing architecture:
  - Platform workflow 节点模板定义在 `src/frontend/platform/src/controllers/API/workflow.ts`。
  - Platform workflow 运行态输入组件位于 `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatInput.tsx`，输入 payload 由 `ChatPane.tsx` 组装。
  - 输入节点 `InputNode.get_input_schema()` 会返回运行态输入 schema，现有文件上传通过 `dialog_files_content` 随输入节点数据传入。
  - 后端 `GraphEngine.continue_run()` 当前按 `{node_id: node_params}` 把用户输入分发给等待输入的节点。
  - `GraphState` 提供 `variables_pool`，可存放本轮执行共享变量。
  - `KnowledgeRetriever` 继承 `RagUtils` 输出 `retrieved_result`；`RagNode` 继承 `RagUtils` 并使用检索结果生成回答。
  - Client 侧已有 `src/frontend/client/src/components/Chat/Input/ChatKnowledge.tsx` 用于知识库 / 知识空间选择，可作为已发布使用页的组件和交互参考。
- 已检查文件 Relevant files inspected:
  - `specs/045-workflow-knowledge-space-scope/requirements.md`
  - `specs/045-workflow-knowledge-space-scope/design.md`
  - `specs/045-workflow-knowledge-space-scope/tasks.md`
  - `src/frontend/platform/src/controllers/API/workflow.ts`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatInput.tsx`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatPane.tsx`
  - `src/backend/bisheng/workflow/nodes/input/input.py`
  - `src/backend/bisheng/workflow/nodes/base.py`
  - `src/backend/bisheng/workflow/graph/graph_state.py`
  - `src/backend/bisheng/workflow/graph/graph_engine.py`
  - `src/backend/bisheng/workflow/nodes/knowledge_retriever/knowledge_retriever.py`
  - `src/backend/bisheng/workflow/nodes/rag/rag.py`
  - `src/backend/bisheng/workflow/common/knowledge.py`
  - `src/backend/bisheng/workflow/common/runtime_knowledge.py`
  - `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx`
  - `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx`
- 现有测试或验证命令 Existing tests or validation commands:
  - `cd src/frontend/platform && npm run build`
  - `cd src/frontend/platform && npx vitest run <test-file>`
  - `cd src/backend && uv run pytest test/workflow/test_knowledge_space_scope.py`
  - 新功能应新增定向 backend workflow tests 和 frontend component tests。
- 项目约束 Constraints from project guidance:
  - 本次 `sdd-spec` 只允许创建或更新 `specs/<feature-id>/requirements.md`、`design.md`、`tasks.md`。
  - Platform 和 Client 前端不能混用状态、UI、HTTP 层。
  - 后端必须遵守 workflow 节点架构和项目分层约束。
  - 不得改变已有 workflow 节点行为，除非 spec 明确列入。

## 目标 / 非目标 Goals / Non-Goals

### 目标 Goals
- 新增两个节点模板和后端节点类型：`自选知识问答`、`自选知识检索`。
- 新节点复用现有文档知识问答和检索能力，但由运行态选择提供知识来源。
- 在 Platform 和已发布 workflow 使用页根据 workflow 节点类型自动展示自选知识组件。
- 输入节点为对话框输入或表单输入时都允许用户操作同一自选知识组件。
- 定义稳定运行态 payload，使所有新节点共享同一份选择。
- 支持完整知识库 / 完整知识空间选择。
- 支持在 `文档知识库` / `知识空间` TAB 内选择文件 / 文件夹范围。
- 对文件 / 文件夹范围执行最终展开文件数最多 20 的限制。
- 保持现有 `rag`、`knowledge_retriever`、输入节点文件上传和旧 workflow 行为不变。

### 非目标 Non-Goals
- 不把运行态自选能力加到现有节点。
- 不支持一次运行选择多个完整知识库或多个完整知识空间。
- 不支持完整 source 与文件 / 文件夹范围混合提交。
- 不支持 `文档知识库` 与 `知识空间` 跨 TAB 混合选择。
- 不新增元数据过滤。
- 不重做知识库或知识空间选择 API 的权限模型。

## 边界承诺 Boundary Commitments
| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| Existing nodes `rag` / `knowledge_retriever` | 只允许抽取可复用 helper，外部行为保持不变 | 不改现有节点参数、保存结构和运行结果 | 现有节点输出、metadata filter 或知识来源配置发生变化 |
| New self-selected nodes | 新增模板、节点类型、运行逻辑和测试 | 不复用旧节点 type 伪装新语义 | 新节点需要独立配置固定知识来源 |
| Platform `FlowChat` | 在 `dialog_input` 解锁和 `form_input` 待提交状态增加自选知识组件、发送前校验、payload 字段 | 不破坏输入节点文件上传、语音输入、表单输入 | 不含新节点 workflow 的输入行为发生变化 |
| Client published workflow page | 在 `dialog_input` 解锁和 `form_input` 待提交状态增加等价自选知识组件和校验 | 不引入 Platform 组件或 Zustand | 已发布 workflow 入口实际不在 Client 或存在多入口 |
| Workflow input payload | 在当前输入节点数据中增加保留字段，后端写入共享状态 | 不增加会被 `GraphEngine.continue_run()` 误判为节点 ID 的 top-level key | 输入校验因保留字段失败，或 form input exact validation 受影响 |
| Backend runtime | 新节点读取共享选择并调用知识库 / 知识空间检索 | 不绕过权限、不静默默认到其他来源 | 权限、删除、超限、非法 payload 行为发生变化 |

- Allowed dependencies: none

## 需求追踪 Requirements Traceability
| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..04 | 新增 Platform 节点模板、节点面板配置、后端 node manage 映射 | Frontend template tests, browser manual, save/reopen integration |
| REQ-002 | AC-REQ-002-01..07 | `hasUserSelectedKnowledgeNode()` 检测、运行态选择组件、对话框/表单输入可见性、发送前校验、payload 注入 | Frontend component/integration tests, websocket payload snapshot |
| REQ-003 | AC-REQ-003-01..10 | TAB 区分的树形勾选选择组件、完整 source 单选、同 TAB 类型内文件 / 文件夹多选、20 文件限制、TAB 切换清空 | Frontend tests with API mocks, backend count/validation tests |
| REQ-004 | AC-REQ-004-01..05 | Runtime selection payload contract, input reserved field, GraphState shared namespace, backward-compatible parser | Backend workflow tests, payload validation tests |
| REQ-005 | AC-REQ-005-01..07 | 新节点后端执行分支、RagUtils reusable retrieval initialization、按 source 分组的 range filters | Backend unit/integration tests |
| REQ-006 | AC-REQ-006-01..05 | Permission revalidation, stale resource handling, regression coverage, no new deps | Backend permission tests, existing-node regression, build/code review |

## 架构设计 Architecture
- Pattern: 新增节点类型 + 运行态共享参数注入 + 复用现有检索服务。
- Rationale:
  - 新需求语义不同于现有节点的固定知识来源配置，用独立节点类型能避免破坏历史 workflow。
  - 运行态选择是本轮 workflow 的全局输入，不应持久化到节点配置中。
  - `GraphEngine.continue_run()` 以 top-level key 作为节点 ID，运行态选择不能作为 top-level sibling 传入；应作为当前输入节点数据中的保留字段传入，再由后端抽取到 `GraphState`。
- Preserved existing patterns:
  - 继续使用 workflow node 模板、`BaseNode`、`GraphState`、`RagUtils`、callback 日志体系。
  - Platform 使用 `bs-ui`、`useTranslation()` 和现有 API wrapper。
  - Client 使用自身组件、Recoil/react-query 和 `useLocalize()`。
- Architecture change justification, if any: 需要在输入恢复路径增加“保留字段抽取到共享状态”的小型扩展，否则自选知识节点无法在不连线、不重复选择的情况下读取同一份运行态选择。

## 文件结构计划 File Structure Plan
| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/frontend/platform/src/controllers/API/workflow.ts` | modify | 新增两个节点模板，移除固定知识来源和 `metadata_filter` | REQ-001 |
| `src/frontend/platform/public/locales/*/flow.json` | modify | 增加节点名称、自选知识组件文案、错误提示 | REQ-001, REQ-002, REQ-003 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatInput.tsx` | modify | 在对话框输入和表单输入状态展示自选知识组件、发送前校验、把选择写入输入 payload | REQ-002, REQ-004 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/ChatPane.tsx` | modify | 在 websocket input payload 中承载运行态知识选择 | REQ-002, REQ-004 |
| `src/frontend/platform/src/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker.tsx` | modify/create | Platform TAB + 树形勾选自选知识组件，支持完整 source 单选与同类型多 source 文件 / 文件夹多选 | REQ-002, REQ-003 |
| `src/frontend/platform/src/controllers/API/knowledge.ts` 或现有 knowledge API wrapper | modify if needed | 获取知识库目录树、文件 / 文件夹列表、文件计数或校验结果 | REQ-003 |
| `src/frontend/platform/src/controllers/API/knowledgeSpace.ts` | modify if needed | 获取知识空间目录树、文件 / 文件夹列表、展开计数或校验结果 | REQ-003 |
| `src/frontend/client/src/pages/appChat/UserSelectedKnowledgePicker.tsx` | modify/create | 已发布 workflow 使用页树形勾选自选知识 UI | REQ-002, REQ-003 |
| `src/frontend/client/src/pages/appChat/ChatInput.tsx` | modify | 在对话框输入和表单输入状态展示自选知识组件 | REQ-002, REQ-004 |
| `src/frontend/client/src/pages/appChat/useAreaText.ts` | modify | 在对话框输入、引导词输入和表单输入提交前统一校验运行态知识选择 | REQ-002, REQ-004 |
| `src/frontend/client/src/pages/appChat/useWebsocket.ts` | modify | 对话框输入和表单输入 payload 携带运行态知识选择保留字段 | REQ-002, REQ-004 |
| `src/frontend/client/src/api/knowledge.ts` 或现有 API wrapper | modify if needed | Client 侧复用知识库 / 知识空间选择接口 | REQ-002, REQ-003 |
| `src/backend/bisheng/workflow/common/node.py` | modify | 增加新节点类型枚举 | REQ-001, REQ-005 |
| `src/backend/bisheng/workflow/nodes/node_manage.py` | modify | 注册新节点类型到实现类 | REQ-001, REQ-005 |
| `src/backend/bisheng/workflow/graph/graph_engine.py` | modify | 从输入节点数据抽取运行态知识选择并写入共享状态 | REQ-004 |
| `src/backend/bisheng/workflow/graph/graph_state.py` | modify if needed | 提供运行态选择读写 helper 或保留 namespace | REQ-004 |
| `src/backend/bisheng/workflow/common/knowledge.py` | modify | 应用运行态选择到现有知识库 / 知识空间检索参数，保持旧节点行为 | REQ-003, REQ-005, REQ-006 |
| `src/backend/bisheng/workflow/common/runtime_knowledge.py` | modify/create | 封装运行态选择解析、双模式校验、source 分组、文件夹展开和权限兜底 | REQ-003, REQ-004, REQ-006 |
| `src/backend/bisheng/workflow/nodes/user_selected_knowledge_retriever/` | create | 自选知识检索节点实现 | REQ-001, REQ-005 |
| `src/backend/bisheng/workflow/nodes/user_selected_knowledge_rag/` | create | 自选知识问答节点实现 | REQ-001, REQ-005 |
| `src/backend/test/workflow/test_user_selected_knowledge.py` | create | 后端运行态选择、权限、范围和输出回归测试 | REQ-004, REQ-005, REQ-006 |
| `src/frontend/platform/src/test/workflowUserSelectedKnowledge*.test.tsx` | create | Platform 组件和 payload 回归测试 | REQ-001, REQ-002, REQ-003, REQ-004 |
| `src/frontend/client/src/**/__tests__` | create/modify if needed | Client 发布页自选知识组件测试 | REQ-002, REQ-003 |

## 组件与接口 Components and Interfaces

### New Node: User Selected Knowledge Retriever
- Responsibility: 读取用户问题和运行态知识选择，执行检索并输出 `retrieved_result`。
- Inputs: `user_question` 变量、`advanced_retrieval_switch` 参数、GraphState 中的 `__runtime__.user_selected_knowledge`。
- Outputs: 与 `knowledge_retriever` 兼容的 `retrieved_result`。
- Dependencies: `RagUtils` 或从其抽取的检索 helper、知识库检索服务、知识空间检索 helper、权限校验服务。
- Error behavior: 缺少选择、非法范围、超限、未授权、检索异常均抛明确节点错误。
- Requirements: REQ-001, REQ-004, REQ-005, REQ-006

### New Node: User Selected Knowledge RAG
- Responsibility: 读取用户问题、提示词、模型和运行态知识选择，检索后生成回答。
- Inputs: 与 `rag` 对齐的用户问题、system/user prompt、model、temperature、output settings，以及 GraphState 中的运行态知识选择。
- Outputs: 与 `rag` 兼容的用户可见回答、source documents、citation registry 和下游变量。
- Dependencies: `RagNode` 可复用逻辑、LLMService、检索 helper、callback 体系。
- Error behavior: 检索或校验失败时按节点错误处理，不把错误文本当作检索文档生成回答。
- Requirements: REQ-001, REQ-004, REQ-005, REQ-006

### Runtime Knowledge Selection Payload
- Responsibility: 表达本轮 workflow 使用者选择的检索来源和范围。
- Inputs: 前端选择器状态。
- Outputs: 作为输入节点本轮提交的保留字段传给后端。
- Proposed shape:

```json
{
  "mode": "source",
  "whole_source": {
    "source_type": "knowledge",
    "source_id": 123,
    "source_name": "政策知识库"
  },
  "items": [],
  "effective_file_count": null
}
```

```json
{
  "mode": "items",
  "whole_source": null,
  "items": [
    {
      "source_type": "knowledge",
      "source_id": 123,
      "source_name": "政策知识库",
      "ref_type": "file",
      "id": 456,
      "name": "制度.pdf"
    },
    {
      "source_type": "space",
      "source_id": 789,
      "source_name": "营销空间",
      "ref_type": "folder",
      "id": 2001,
      "name": "案例"
    }
  ],
  "effective_file_count": 12
}
```

- Dependencies: 当前输入节点数据 payload；后端 GraphEngine 抽取逻辑。
- Error behavior:
  - `mode` 只能是 `source` 或 `items`。
  - `mode=source` 时 `whole_source` 必填且 `items` 必须为空；`source_type` 只能是 `knowledge` 或 `space`。
  - `mode=items` 时 `whole_source` 必须为空，`items` 至少包含一个条目；每个条目必须包含 `source_type`、`source_id`、`ref_type` 和 `id`。
  - `ref_type` 只能是 `file` 或 `folder`；文件夹条目由后端按所属 `source_type` 和 `source_id` 展开或传递给对应检索适配器。
  - `mode=items` 时 `effective_file_count` 必须小于等于 20；后端仍需重新计算或校验。
  - 实现阶段可在后端 parser 中兼容旧单 `type/source_id/files/folders` shape，便于灰度和已打开页面提交；兼容路径应归一化为新 shape 后再执行校验。
- Requirements: REQ-003, REQ-004

### Platform User Selected Knowledge Picker
- Responsibility: 在 workflow 运行态展示和维护本轮知识选择。
- Inputs: 当前 flow nodes、知识库列表、知识空间列表、知识库目录树、知识空间目录树、当前激活 TAB。
- Outputs: 选择状态和发送 payload。
- Dependencies: Platform API wrappers、`bs-ui`、`useTranslation()`。
- Error behavior: 未选择、超限、无权限、加载失败或无匹配数据时展示明确状态；未选择时禁止发送。
- Visibility model:
  - 当 workflow 包含自选知识节点且输入节点处于 `dialog_input` 解锁状态时，在聊天输入框上方展示组件。
  - 当 workflow 包含自选知识节点且输入节点处于 `form_input` 待提交状态时，仍在聊天输入区上方展示可操作组件，供表单提交复用同一选择。
  - 当 workflow 不含自选知识节点、输入尚未进入待用户输入状态或页面只读时，不展示或禁用组件。
- Selection model:
  - 使用 `文档知识库` / `知识空间` TAB 作为来源类型边界。
  - 完整 source 勾选模式：最多 1 个完整知识库或完整知识空间。
  - 文件 / 文件夹勾选模式：允许在当前 TAB 类型内跨多个知识库或多个知识空间选择文件或文件夹，最终展开文件数最多 20。
  - 两种模式互斥，切换模式时清空另一种模式的选择。
  - 切换 TAB 时清空已选完整 source、文件和文件夹，payload 不得同时包含 `knowledge` 与 `space`。
- Requirements: REQ-002, REQ-003

### Client Published Workflow Picker
- Responsibility: 在已发布 workflow 使用页提供与 Platform 等价的自选知识能力。
- Inputs: 发布页 flow/app 信息、知识库 / 知识空间接口数据。
- Outputs: 与 Platform 相同的数据契约。
- Dependencies: Client API layer、Recoil/react-query v5、现有 `ChatKnowledge` 可复用模式。
- Error behavior: 与 Platform 保持一致，包括 TAB 切换清空、加载、空状态、超限和未选择阻止发送。
- Visibility model: 与 Platform 一致；Client 通过 `currentRunningState.inputDisabled` 和 `inputForm` 判断 `dialog_input` / `form_input` 待用户输入状态。
- Requirements: REQ-002, REQ-003

## 数据 / 状态变化 Data / State Changes
- Entities: none
- Persistence changes: none。运行态选择不写入 workflow 节点配置，不作为版本数据持久化。
- Migration or rollback: none。新增节点不会改变旧 workflow；回滚时移除新增节点模板和运行逻辑即可。
- Compatibility:
  - 旧 workflow 不包含新节点时 payload 不需要新增字段。
  - 现有 `rag` 和 `knowledge_retriever` 仍使用节点内配置的知识来源。
  - 新节点保存数据不包含固定 knowledge selector，因此后端必须依赖运行态共享选择。

## 测试策略 Testing Strategy
| Acceptance ID | Test Type | Target | Notes |
|---|---|---|---|
| AC-REQ-001-01 | frontend/manual | Platform node panel | 验证两个新增节点可添加。 |
| AC-REQ-001-02 | frontend/code review | `workflow.ts` node template | 验证自选问答参数与 `rag` 对齐且无 `knowledge` / `metadata_filter`。 |
| AC-REQ-001-03 | frontend/code review | `workflow.ts` node template | 验证自选检索参数与 `knowledge_retriever` 对齐且无 `knowledge` / `metadata_filter`。 |
| AC-REQ-001-04 | integration/manual | Save/reopen workflow | 验证新节点配置可保存加载。 |
| AC-REQ-002-01 | frontend integration | Platform `FlowChat` | flow 含新节点时展示选择器。 |
| AC-REQ-002-02 | frontend integration | Published workflow page | 发布页展示选择器。 |
| AC-REQ-002-03 | regression | Existing workflows | 不含新节点时不展示选择器。 |
| AC-REQ-002-04 | frontend unit | Send guard | 未选来源禁止发送并 toast。 |
| AC-REQ-002-05 | frontend unit | Payload builder | 已选来源 payload snapshot。 |
| AC-REQ-002-06 | frontend unit/browser | Dialog input visibility | 对话框输入解锁时展示选择器，发送 payload 带保留字段。 |
| AC-REQ-002-07 | frontend unit/regression | Form input visibility | 表单输入待提交时选择器仍可操作，表单提交 payload 带保留字段。 |
| AC-REQ-003-01..10 | frontend + backend | Picker and range validation | 覆盖 TAB 展示、树形展示、完整 source 单选、同类型多 source 文件 / 文件夹多选、TAB 切换清空、模式互斥、20 文件限制、加载和空状态。 |
| AC-REQ-004-01..05 | backend integration | GraphEngine + GraphState | 输入保留字段抽取、非法 payload 拒绝、多节点共享。 |
| AC-REQ-005-01..07 | backend integration | New nodes | 完整 source 和同类型多 source 范围的问答、检索、输出兼容和错误分支。 |
| AC-REQ-006-01..05 | backend/frontend regression | Permission and compatibility | 权限变更、删除、旧 workflow、依赖约束。 |

## 设计决策 Decisions
### Decision: 新增独立节点类型，而不是扩展现有节点
- Context: 现有节点在编排阶段配置固定知识来源，本需求要求运行时由使用者选择。
- Options considered: 扩展现有节点增加“运行时自选”开关；新增独立节点。
- Decision: 新增独立节点。
- Rationale: 避免破坏旧 workflow 和现有节点配置语义；节点名称能清晰表达使用者运行时必须选择知识来源。
- Consequences: 需要新增节点模板、后端类、注册映射和测试，但兼容性风险更低。

### Decision: 运行态选择全局生效
- Context: 用户已确认多个自选知识节点共享一次选择。
- Options considered: 每个节点独立选择；按节点类型选择；全局选择。
- Decision: 全局选择。
- Rationale: 符合用户确认，交互成本最低，也与输入节点文件上传的“本轮输入附带资源”模式接近。
- Consequences: 所有自选知识节点读取同一份选择；如未来需要节点级选择，必须更新 spec。

### Decision: 通过输入节点保留字段传入运行态选择
- Context: `GraphEngine.continue_run()` 将 top-level key 当作节点 ID，不能安全增加 top-level runtime key。
- Options considered: top-level `runtime` key；输入节点数据中的保留字段；持久化到 workflow version。
- Decision: 使用当前输入节点数据中的保留字段，并在后端抽取到 GraphState 保留 namespace。
- Rationale: 与现有 `dialog_files_content` 随输入节点数据传入的模式一致，不污染 workflow version。
- Consequences: 需要更新输入校验逻辑，确保 dialog 和 form 输入都允许该保留字段。

### Decision: 运行态选择使用 `source` / `items` 双模式 payload
- Context: 新需求同时要求完整知识库 / 知识空间单选，以及在同一 TAB 类型内选择文件或文件夹；旧单 `source_id` payload 无法表达多 source 范围。
- Options considered: 保持单 `source_id` 并在其中嵌套范围；改为纯 items 列表；使用 `mode=source` / `mode=items` 双模式。
- Decision: 使用双模式 payload。
- Rationale: 双模式能直接表达互斥关系，后端校验更明确，也能避免完整 source 与明细范围混合提交；TAB 类型互斥由前端清空和后端 `items.source_type` 单一性校验共同保证。
- Consequences: 前后端需要重构选择状态和 parser；实现阶段可兼容旧 shape 并归一化到新 shape；混合 `knowledge` / `space` items 将被拒绝。

### Decision: 后端兜底校验 20 文件限制
- Context: 前端可能无法可靠计算知识空间文件夹最终展开文件数，且权限或文件状态可能在选择后变化。
- Options considered: 仅前端校验；仅后端校验；前后端都校验。
- Decision: 前端尽量提前校验，后端必须兜底校验。
- Rationale: 用户体验和安全都需要覆盖。
- Consequences: 可能需要新增或复用文件范围计数能力。

## 风险 / 取舍 Risks / Trade-Offs
| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 文件夹展开计数接口缺失 | 20 文件限制无法在前端稳定提示 | 后端提供计数 / 校验接口，前端使用；后端运行时兜底拒绝 | Implementation |
| 旧实现仍使用单 `source_id` payload | 新 UI 和后端运行态协议不一致，导致运行时无法表达同类型多 source 文件 / 文件夹 | 先更新 spec，再重构前后端 shared type、parser、测试和浏览器验证 | Implementation |
| Published workflow 入口分散 | 只覆盖 Platform 会漏掉 Client 使用页 | 实现前继续定位发布路由，Platform 和 Client 分别验证 | Implementation |
| 输入 payload 保留字段影响 form validation | 表单输入可能拒绝额外字段 | 更新输入校验允许 reserved runtime field，增加回归测试 | Implementation |
| 选择器只在一种输入状态显示 | 对话框输入或表单输入其中一种场景无法选择知识范围 | 使用统一可见性 helper 覆盖 `dialog_input` 解锁和 `form_input` 待提交两种状态，并对两端补测试 | Implementation |
| 复用 `RagUtils` 时影响旧节点 | 旧节点行为回归 | 抽取 helper 时保持旧分支测试，旧节点不改参数契约 | Implementation |
| 知识库与知识空间的文件夹展开语义不同 | 检索结果不符合用户选择范围 | 分别定义 source type adapter，并用 mock 测试验证调用参数 | Implementation |

## 设计质量门 Design Quality Gate
- [x] Every requirement ID is represented in Requirements Traceability.
- [x] Every acceptance criterion has a verification strategy.
- [x] Boundary Commitments include allowed and disallowed changes.
- [x] Every changed file has one clear responsibility and linked requirement.
- [x] Existing architecture is preserved or changes are justified.
- [x] Runtime prerequisites, migrations, and risky operations are explicit.
- [x] No speculative abstractions are included.
