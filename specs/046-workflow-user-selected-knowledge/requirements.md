# 需求说明 Requirements: Workflow User Selected Knowledge

## 阅读摘要
- 本文档说明：新增 `自选知识问答` 与 `自选知识检索` 两个 workflow 节点，并在运行 workflow 时由使用者选择知识来源后传递给新增节点。
- 当前状态：`draft`
- 需要重点确认：2026-06-24 需求变更已确认，运行态选择组件需要用 `文档知识库` / `知识空间` TAB 区分；整库 / 整空间选择最多 1 个，文件 / 文件夹只能在当前 TAB 类型内选择，最终文件数最多 20；自选知识选择同时覆盖输入节点的对话框输入和表单输入。
- 阅读摘要用于快速理解；需求追踪、验收标准和验证方式以结构化条目与表格为准。

## 元信息 Metadata
- Feature ID: `046-workflow-user-selected-knowledge`
- Status: `draft`
- Mode: `spec-only`
- Created: `2026-06-23`
- Updated: `2026-06-24`
- Source request: 用户要求复制现有文档知识库问答与文档知识库检索节点，新增运行态自选知识来源能力。

## 需求入口摘要 Intake Summary
- 问题 Problem: 现有文档知识库问答、文档知识库检索节点的数据来源在编排阶段固定，workflow 使用者无法在每次运行时临时选择要检索的知识库、知识空间或文件范围。
- 当前状态 Current state:
  - `文档知识库问答` 对应 workflow 节点 `rag`，节点内配置知识来源、元数据过滤、检索参数、提示词和模型。
  - `文档知识库检索` 对应 workflow 节点 `knowledge_retriever`，节点内配置知识来源、元数据过滤、检索参数和输出变量。
  - 输入节点已支持运行态接收文件，Platform `FlowChat` 会根据输入节点 schema 展示上传能力并把文件传给 workflow。
  - 已有 `045-workflow-knowledge-space-scope` 支持在现有节点配置期选择知识空间，但不覆盖本次“运行态自选知识来源”。
- 目标结果 Target outcome:
  - 新增 `自选知识问答` 与 `自选知识检索` 两个节点。
  - 两个新节点不在节点表单内选择检索范围，也不展示 `metadata_filter`。
  - 当 workflow 包含任一新节点时，运行页面展示自选知识组件，用户选择后才能发送。
  - 输入节点为 `dialog_input` 或 `form_input` 时，自选知识组件均应可用。
  - 运行时选择的知识来源全局传递给所有新节点并用于检索。
- 影响对象 Affected users/systems: workflow 编排者、workflow 使用者、Platform workflow 调试页、已发布 workflow 使用页、workflow websocket 输入 payload、workflow 后端执行引擎、知识库与知识空间权限和检索服务。
- 请求停止点 Requested stopping point: `tasks`

## 范围 Scope

### 包含 Includes
- 新增 workflow 节点 `自选知识问答`，复制现有 `文档知识库问答` 的核心输入输出和问答生成能力，但去掉节点内知识来源选择和元数据过滤。
- 新增 workflow 节点 `自选知识检索`，复制现有 `文档知识库检索` 的核心输入输出和检索能力，但去掉节点内知识来源选择和元数据过滤。
- Platform workflow 调试 / 运行页在检测到 workflow 包含任一新节点时展示自选知识组件。
- 已发布 workflow 使用页在检测到 workflow 包含任一新节点时展示自选知识组件。
- 输入节点使用 `对话框输入` 或 `表单输入` 时，Platform 和已发布 workflow 使用页都应支持同一自选知识组件。
- 自选知识组件以 TAB 区分 `文档知识库` 和 `知识空间`，并在当前 TAB 内以树形勾选方式展示用户有权限使用的来源及文件 / 文件夹。
- 用户可以勾选一个完整知识库或一个完整知识空间作为本轮检索范围。
- 用户也可以在当前 TAB 类型内选择文件或文件夹作为本轮检索范围。
- 整库 / 整空间选择与文件 / 文件夹选择互斥；选择整库 / 整空间时最多只能选择 1 个 source。
- 文件 / 文件夹选择模式下允许在同一 TAB 类型内跨多个知识库或多个知识空间选择，最终展开后的文件总数最多为 20。
- 未选择知识来源时，前端禁止发送并提示用户选择。
- 运行时选择结果全局生效，传递给 workflow 内所有 `自选知识问答` 与 `自选知识检索` 节点。
- 后端执行新节点时重新校验当前用户对所选知识库、知识空间、文件或文件夹的访问权限。

### 不包含 Excludes
- 不修改现有 `文档知识库问答`、`文档知识库检索` 的节点配置和运行行为。
- 不给现有节点增加运行态自选知识能力。
- 不支持一次运行同时选择多个完整知识库或多个完整知识空间。
- 不支持整库 / 整空间选择与文件 / 文件夹选择混合提交。
- 不支持 `文档知识库` 与 `知识空间` 跨 TAB 混合提交。
- 不修改 workflow 节点配置面板的检索范围表单；本需求只覆盖运行页自选知识组件。
- 不新增或恢复元数据过滤能力。
- 不改变知识库、知识空间自身权限模型和入库流程。
- 不在本 spec-only 阶段修改生产代码。

## 需求列表 Requirements

### REQ-001: 新增自选知识节点
作为 `workflow 编排者`，我需要新增自选知识问答和自选知识检索节点，以便把知识来源选择交给 workflow 使用者在运行时决定。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 编排者打开 workflow 节点面板 THEN 系统 SHALL 展示 `自选知识问答` 和 `自选知识检索` 两个可添加节点。
- `AC-REQ-001-02`: WHEN 编排者添加 `自选知识问答` THEN 节点 SHALL 保留现有 `文档知识库问答` 的用户问题、检索高级设置、模型、提示词、输出到用户和输出变量语义，但 SHALL 不展示节点内知识来源选择和 `metadata_filter`。
- `AC-REQ-001-03`: WHEN 编排者添加 `自选知识检索` THEN 节点 SHALL 保留现有 `文档知识库检索` 的用户问题、检索高级设置和 `retrieved_result` 输出语义，但 SHALL 不展示节点内知识来源选择和 `metadata_filter`。
- `AC-REQ-001-04`: WHEN 编排者保存并重新打开包含新节点的 workflow THEN 系统 SHALL 正确回显新节点配置，不要求节点内存在固定知识来源参数。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | frontend test + manual | 节点面板可见两个新增节点；组件测试或浏览器截图。 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | frontend test + code review | 新问答节点参数中无知识来源选择和 `metadata_filter`，其他核心参数与 `rag` 对齐。 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | frontend test + code review | 新检索节点参数中无知识来源选择和 `metadata_filter`，其他核心参数与 `knowledge_retriever` 对齐。 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | integration/manual | 保存后重新打开 workflow，新增节点配置可加载且无必填固定知识来源错误。 |

### REQ-002: 运行页展示自选知识组件
作为 `workflow 使用者`，我需要在运行 workflow 时看到自选知识组件，以便在提问前选择本次检索的数据来源。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN workflow 包含至少一个 `自选知识问答` 或 `自选知识检索` 节点 THEN Platform 调试 / 运行页 SHALL 展示自选知识组件。
- `AC-REQ-002-02`: WHEN workflow 包含至少一个 `自选知识问答` 或 `自选知识检索` 节点 THEN 已发布 workflow 使用页 SHALL 展示自选知识组件。
- `AC-REQ-002-03`: WHEN workflow 不包含任何自选知识节点 THEN 运行页 SHALL 不展示自选知识组件，现有输入和文件上传行为保持不变。
- `AC-REQ-002-04`: WHEN 用户未选择知识来源并点击发送 THEN 前端 SHALL 阻止发送，并展示明确提示。
- `AC-REQ-002-05`: WHEN 用户已选择有效知识来源并点击发送 THEN 前端 SHALL 将选择结果随本轮 workflow 输入提交。
- `AC-REQ-002-06`: WHEN 输入节点处于 `dialog_input` 对话框输入状态且 workflow 包含自选知识节点 THEN Platform 调试 / 运行页和已发布 workflow 使用页 SHALL 在聊天输入框上方展示可操作的自选知识组件。
- `AC-REQ-002-07`: WHEN 输入节点处于 `form_input` 表单输入状态且 workflow 包含自选知识节点 THEN Platform 调试 / 运行页和已发布 workflow 使用页 SHALL 继续展示可操作的自选知识组件，且表单提交时仍携带同一运行态知识选择。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | frontend integration/manual | Platform workflow 页面包含新节点时展示组件。 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | frontend integration/manual | 已发布 workflow 使用页包含新节点时展示组件。 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | regression/manual | 不含新节点的 workflow 不展示组件，原输入框和附件上传可用。 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | frontend test | 未选择来源点击发送时断言未发送 websocket 消息并出现提示。 |
| AC-REQ-002-05 | V-AC-REQ-002-05 | frontend test + websocket payload inspection | 已选择来源后发送 payload 中包含运行态知识选择字段。 |
| AC-REQ-002-06 | V-AC-REQ-002-06 | frontend test + browser smoke | 对话框输入解锁时聊天输入框上方展示自选知识组件，发送链路携带保留字段。 |
| AC-REQ-002-07 | V-AC-REQ-002-07 | frontend test + regression | 表单输入待提交时仍展示可操作自选知识组件，表单提交链路携带保留字段。 |

### REQ-003: 自选知识选择范围和限制
作为 `workflow 使用者`，我需要按知识库或知识空间选择可检索范围，以便控制本次 workflow 检索的数据边界。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 用户打开自选知识组件 THEN 系统 SHALL 以 TAB 区分 `文档知识库` 和 `知识空间`，并在当前 TAB 内以树形结构展示用户有权限使用的来源及其可选文件 / 文件夹。
- `AC-REQ-003-02`: WHEN 用户勾选完整知识库或完整知识空间 THEN 系统 SHALL 将本轮检索范围解释为该完整 source，且每次最多只允许勾选一个完整 source。
- `AC-REQ-003-03`: WHEN 用户已勾选完整 source 后再选择另一个完整 source THEN 系统 SHALL 用新 source 替换旧 source，不得同时保留多个完整 source。
- `AC-REQ-003-04`: WHEN 用户勾选完整 source 后再勾选文件或文件夹 THEN 系统 SHALL 清空完整 source 选择，并切换为文件 / 文件夹选择模式。
- `AC-REQ-003-05`: WHEN 用户处于文件 / 文件夹选择模式 THEN 系统 SHALL 允许在当前 TAB 类型内跨多个知识库或多个知识空间勾选文件或文件夹，但 SHALL NOT 同时保留知识库与知识空间条目。
- `AC-REQ-003-06`: WHEN 用户处于文件 / 文件夹选择模式并勾选完整 source THEN 系统 SHALL 清空已选文件 / 文件夹，并切换为完整 source 选择模式。
- `AC-REQ-003-07`: WHEN 用户选择文件或文件夹后最终展开文件数超过 20 THEN 系统 SHALL 阻止选择完成或阻止发送，并展示超过限制的明确提示。
- `AC-REQ-003-08`: WHEN 用户选择文件夹 THEN 系统 SHALL 将文件夹 ID、所属 source 类型和 source ID 一并提交给后端，由后端按对应知识库或知识空间范围解释。
- `AC-REQ-003-09`: WHEN 知识库、知识空间或目录内容仍在加载 THEN 系统 SHALL 展示可感知的加载状态；WHEN 无匹配数据 THEN 系统 SHALL 展示明确空状态。
- `AC-REQ-003-10`: WHEN 用户在 `文档知识库` 和 `知识空间` TAB 之间切换 THEN 系统 SHALL 清空另一类已选完整 source、文件和文件夹，确保本轮 payload 只包含当前 TAB 类型。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | frontend test/manual | 组件以树形结构展示知识库、知识空间、文件和文件夹。 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | frontend test | 勾选完整知识库或完整知识空间后 payload 表达一个完整 source。 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | frontend test | 勾选第二个完整 source 后旧完整 source 被替换。 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | frontend test | 完整 source 切换到文件 / 文件夹选择时旧完整 source 被清空。 |
| AC-REQ-003-05 | V-AC-REQ-003-05 | frontend test/API mock | 文件 / 文件夹可在同一 TAB 类型内跨多个 source 保留选择，且不能混合知识库和知识空间。 |
| AC-REQ-003-06 | V-AC-REQ-003-06 | frontend test | 文件 / 文件夹选择切换到完整 source 时旧文件 / 文件夹被清空。 |
| AC-REQ-003-07 | V-AC-REQ-003-07 | frontend + backend test | Mock 文件夹展开数超过 20，验证前端阻止和后端兜底拒绝。 |
| AC-REQ-003-08 | V-AC-REQ-003-08 | backend test | 文件夹 payload 带 source 信息，后端按 source 类型解释范围。 |
| AC-REQ-003-09 | V-AC-REQ-003-09 | frontend test/manual | 加载中和空状态可见。 |
| AC-REQ-003-10 | V-AC-REQ-003-10 | frontend test + backend test | 切换 TAB 清空另一类选择，绕过前端提交混合类型 items 时后端拒绝。 |

### REQ-004: 运行态知识选择数据契约
作为 `workflow 运行时`，我需要稳定接收运行页传入的知识选择，以便所有自选知识节点读取同一份来源配置。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 前端提交本轮 workflow 输入 THEN payload SHALL 包含运行态知识选择对象，至少表达选择模式、完整 source 信息、同类型多 source 文件 / 文件夹条目和最终展开文件数。
- `AC-REQ-004-02`: WHEN workflow 进入后端执行 THEN 后端 SHALL 将运行态知识选择保存到 workflow 本轮执行的共享状态中，供所有自选知识节点读取。
- `AC-REQ-004-03`: WHEN workflow 中存在多个自选知识节点 THEN 每个节点 SHALL 读取同一份运行态知识选择，不要求用户重复选择。
- `AC-REQ-004-04`: WHEN payload 缺少运行态知识选择但 workflow 包含自选知识节点 THEN 后端 SHALL 返回明确错误，不得静默使用默认知识库。
- `AC-REQ-004-05`: WHEN payload 包含未知来源类型、多个完整 source、完整 source 与文件 / 文件夹混合、缺失 item 所属 source 信息或不合法范围 THEN 后端 SHALL 拒绝执行并返回明确错误。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | frontend test | 发送 payload snapshot 覆盖完整 source、同类型多 source 文件和同类型多 source 文件夹。 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | backend unit/integration test | workflow 输入处理后 GraphState 或等价共享状态可读取选择对象。 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | backend integration test | 同一 workflow 两个自选节点读取同一选择对象。 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | backend test | 缺少选择时执行失败并返回明确错误。 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | backend test | 非法 payload 被拒绝，不进入检索分支。 |

### REQ-005: 新节点后端检索行为
作为 `workflow 运行时`，我需要新节点根据运行态知识选择执行检索或问答，以便输出结构与现有节点兼容。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN `自选知识检索` 使用完整知识库运行 THEN 后端 SHALL 调用现有文档知识库检索能力，并把范围限制到该知识库。
- `AC-REQ-005-02`: WHEN `自选知识检索` 使用完整知识空间运行 THEN 后端 SHALL 调用现有知识空间检索能力，并把范围限制到该知识空间。
- `AC-REQ-005-03`: WHEN `自选知识检索` 使用同类型多 source 文件 / 文件夹范围运行 THEN 后端 SHALL 按 source 类型和 source ID 分组检索，并只返回所选文件 / 文件夹展开后的结果。
- `AC-REQ-005-04`: WHEN `自选知识问答` 运行 THEN 后端 SHALL 使用同一份运行态选择完成检索和问答生成，并保持现有问答节点的输出语义。
- `AC-REQ-005-05`: WHEN 新节点检索成功 THEN `自选知识检索` SHALL 输出与 `文档知识库检索` 兼容的 `retrieved_result` 结构。
- `AC-REQ-005-06`: WHEN 新节点问答成功 THEN `自选知识问答` SHALL 保持与 `文档知识库问答` 兼容的用户可见输出和下游变量输出。
- `AC-REQ-005-07`: WHEN 检索、权限或范围校验失败 THEN 新节点 SHALL 返回明确节点错误，不得改用其他知识来源。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | backend test | Mock 完整 knowledge source，验证调用文档知识库检索并限制到该 source。 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | backend test | Mock 完整 space source，验证调用知识空间检索并限制到该 source。 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | backend test | Mock 同类型多 source 文件 / 文件夹，验证分组检索和范围过滤。 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | backend test | 自选问答使用运行态选择检索结果生成回答。 |
| AC-REQ-005-05 | V-AC-REQ-005-05 | backend regression test | `retrieved_result` key 和条目字段与现有检索节点兼容。 |
| AC-REQ-005-06 | V-AC-REQ-005-06 | backend regression/manual | 输出用户消息、source documents 和下游变量可用。 |
| AC-REQ-005-07 | V-AC-REQ-005-07 | backend test | 异常路径不降级、不静默改源。 |

### REQ-006: 权限、安全和兼容性
作为 `系统维护者`，我需要自选知识运行时遵守现有权限和兼容性约束，以便不会越权检索或破坏已有 workflow。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 用户选择无权访问的知识库、知识空间、文件或文件夹 THEN 后端 SHALL 拒绝本轮执行，并返回明确错误。
- `AC-REQ-006-02`: WHEN 用户在选择后权限被移除、文件被删除或空间不可用 THEN 后端 SHALL 在运行时重新校验并拒绝或返回明确错误。
- `AC-REQ-006-03`: WHEN workflow 不包含自选知识节点 THEN 前后端 SHALL 保持现有运行行为和 payload 兼容。
- `AC-REQ-006-04`: WHEN 旧 workflow 包含现有 `rag` 或 `knowledge_retriever` 节点 THEN 后端 SHALL 继续按节点内固定知识来源运行。
- `AC-REQ-006-05`: WHEN 前端实现自选知识组件 THEN SHALL 不引入新的 UI 库、HTTP 库或状态管理库。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | backend permission test | 未授权 source/file/folder 被拒绝。 |
| AC-REQ-006-02 | V-AC-REQ-006-02 | backend regression test | 删除或权限变化后运行失败并有明确错误。 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | regression test/manual | 不含新节点 workflow payload 和运行结果不变。 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | backend regression test | 现有 `rag` / `knowledge_retriever` 仍按固定知识来源运行。 |
| AC-REQ-006-05 | V-AC-REQ-006-05 | code review + build | 无新增 UI/HTTP/state 依赖，Platform 和 Client 构建通过。 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: Platform 前端 SHALL 使用现有 `@/controllers/request.ts`、`bs-ui`、`useTranslation()` 和当前状态管理方式，不引入新 UI 或状态库。
- `NFR-002`: Client 前端 SHALL 使用现有 shadcn/lucide、Recoil、react-query v5 和 `useLocalize()` 约束，不混用 Platform 组件。
- `NFR-003`: 后端 SHALL 遵守现有 workflow 节点架构和项目 DDD 分层，不在 endpoint 中直接写 ORM 查询。
- `NFR-004`: 权限校验 SHALL 复用现有知识库和知识空间权限能力，不手写 tenant 条件绕过权限系统。
- `NFR-005`: 运行态知识选择 payload SHALL 不记录用户问题正文以外的敏感内容，只传递必要的 source/file/folder 标识和展示名称。
- `NFR-006`: 新增或修改的前端单文件超过 600 行时 SHALL 拆分组件或 hook。

## 澄清记录 Clarifications

### Session 2026-06-23
- Q: 自选知识组件展示在哪个运行入口？ -> A: `1B`，Platform 和已发布 workflow 使用页都要展示。
- Q: 多个自选知识节点如何使用选择结果？ -> A: `2A`，一次选择，全局传给所有自选知识节点。
- Q: 包含新节点但用户未选择知识来源时怎么处理？ -> A: `5A`，禁止发送并提示选择知识来源。
- Superseded: 2026-06-23 关于单 source 与文件夹范围的旧回答已被 2026-06-24 新需求覆盖。

### Session 2026-06-24
- Q: 当前选择规则是否仍然只允许单知识库 / 单知识空间？ -> A: `1A`，完整知识库或完整知识空间每次最多选择一个；文件 / 文件夹曾按两类来源混选考虑，最终展开文件数最多 20。该回答已被同日后续 TAB 互斥澄清覆盖。
- Q: 截图顶部 tabs 是否必须实现？ -> A: `2C`，无关紧要，本需求不要求新增顶部分类 tabs。该回答已被同日后续 TAB 互斥澄清覆盖。
- Q: 新选择方式覆盖哪些入口？ -> A: `3B`，覆盖 Platform 运行预览和 Client 已发布 workflow 使用页。
- Q: 文件夹选择是否只限知识空间？ -> A: 用户明确“可以跨空间或库来选择文件或文件夹”，因此文件 / 文件夹选择模式下知识库和知识空间都应支持文件夹选择；后端需按所属 source 类型解释。
- Q: 知识库和知识空间改成 TAB 后，文件 / 文件夹是否仍允许跨 `文档知识库` 和 `知识空间` 选择？ -> A: `1B`，不允许，只能在当前 TAB 内选择，切换 TAB 时清空另一类选择。
- Q: TAB 改动覆盖哪些页面？ -> A: `2A`，Platform 调试运行页和 Client 发布使用页都改。
- Q: `知识空间` TAB 内是否继续按知识空间类型分组展示？ -> A: `3A`，继续保留 `公共空间 / 部门空间 / 团队空间 / 个人空间` 分组。
- Q: 自选知识节点是否只支持表单输入，还是也支持对话框输入？ -> A: `1A`，也支持对话框输入，同时保留表单输入支持。
- Q: 对话框输入时自选知识组件展示在哪里？ -> A: `2A`，展示在聊天输入框上方，沿用当前自选知识选择器样式。
- Q: 对话框输入支持覆盖哪些页面？ -> A: `3A`，Platform 调试运行页和 Client 已发布 workflow 使用页都覆盖。

## 假设 Assumptions
- 选择整个知识库或整个知识空间时不受 20 个文件限制；20 个文件限制只适用于用户选择文件或文件夹来缩小范围的场景。该假设来自用户原文“如果选择文件或文件夹每次最多选择 20 个文件”。
- 文件夹的最终文件数以运行时后端重新计算结果为准；前端展示的计数仅用于提前提示。
- 新节点的中文展示名固定为 `自选知识问答` 和 `自选知识检索`；内部节点类型可在设计阶段按项目命名规范确定。

## 风险 Risks
- 现有知识库或知识空间文件夹接口可能不能在前端选择阶段直接返回“最终展开后的文件总数”；实现阶段需要新增计数接口、复用已有文件树接口，或由后端在运行时兜底拒绝超过 20 的范围。
- 当前已实现代码按旧单 `source_id` payload 设计；本次规格更新后，后续实现必须重构前后端选择协议和测试。
- 已发布 workflow 使用页涉及 Platform 与 Client 两套前端实现；如果实际发布入口只落在其中一端，实现阶段需要在 `verification.md` 中记录路由事实和覆盖范围。
- 运行态 payload 需要兼容 workflow 输入校验；如果直接增加 top-level key，会被现有 `GraphEngine.continue_run()` 当作节点 ID 处理，因此设计必须使用安全的保留字段或共享状态注入点。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
