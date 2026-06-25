# Requirements: Workflow Knowledge Space Retrieval Scope

## Metadata
- Feature ID: `045-workflow-knowledge-space-scope`
- Status: `draft`
- Mode: `spec-only`
- Created: `2026-06-23`
- Updated: `2026-06-23`
- Source request: Codex thread request to add `知识空间` as a workflow retrieval scope.

## Intake Summary
- Problem: Workflow 的文档知识库检索、文档知识库问答节点目前只能选择现有知识库范围，无法直接以用户已加入或有权限使用的知识空间作为检索范围。
- Current state:
  - 文档知识库检索节点使用 `knowledge_select_multi`，当前检索范围为 `文档知识库` 和 `临时知识库`。
  - 文档知识库问答节点使用 `qa_select_multi`，当前按 QA 知识库列表选择，参数结构与文档知识库检索节点不同。
  - 文档知识库检索节点存在 `metadata_filter` 参数；知识空间不支持该过滤方式。
- Target outcome: 两个节点都能选择知识空间作为检索范围；知识空间选项来自用户加入或有权限使用的全部知识空间；选择知识空间时 UI 隐藏并清空元数据过滤配置。
- Affected users/systems: Workflow 编排用户、Workflow 单节点调试、Workflow 运行时、知识空间权限接口、知识库检索后端、平台前端 workflow editor。
- Requested stopping point: `tasks.md`，本阶段不修改生产代码。

## Scope

### Includes
- 文档知识库检索节点新增 `知识空间` 检索范围，展示顺序为 `文档知识库`、`知识空间`、`临时知识库`。
- 文档知识库问答节点新增知识空间选择能力，并保持该节点原有输入、输出和得分阈值设计。
- 知识空间可选项覆盖用户加入或有权限使用的所有知识空间，不限于用户管理的知识空间。
- 知识空间选择、搜索、分页、多选、必填校验和回显体验与文档知识库选择保持一致。
- 选择知识空间时，带 `metadata_filter` 的文档检索类节点在 UI 中隐藏该表单项，并立即清空保存值。
- 后端 workflow 运行时识别知识空间检索范围，不把知识空间误走临时知识库逻辑。
- 历史 workflow 的旧参数结构继续可加载、可保存、可运行。
- Platform 前端遵守现有 `src/frontend/platform/` 技术栈和组件约束。
- 知识空间选择器按现有 `space_level` 分类树形展示，分类顺序为 `公共空间`、`部门空间`、`团队空间`、`个人空间`。
- 知识空间搜索结果仍保留分类展示，只显示包含匹配子项的分类。
- 知识空间选择器在初次加载、搜索和滚动加载更多请求未返回时显示加载状态，避免用户误判为空列表。

### Excludes
- 不重构 workflow 画布、节点系统或全局表单渲染框架。
- 不改变文档知识库和临时知识库的既有检索行为。
- 不新增独立知识空间管理页面。
- 不改变知识空间自身权限模型、知识空间数据结构或知识入库流程。
- 不为所有 workflow 节点批量增加知识空间检索范围。
- 不在本 spec-only 阶段实现生产代码。

## Requirements

### REQ-001: 文档知识库检索节点支持知识空间检索范围
As a `workflow 编排用户`, I want 在文档知识库检索节点中选择知识空间, so that workflow 可以直接检索我已加入或有权限使用的知识空间内容。

#### Acceptance Criteria
- `AC-REQ-001-01`: WHEN 用户打开文档知识库检索节点的检索范围选择器 THEN 系统 SHALL 按 `文档知识库`、`知识空间`、`临时知识库` 的顺序展示选项。
- `AC-REQ-001-02`: WHEN 用户切换到 `知识空间` THEN 系统 SHALL 加载用户加入或有权限使用的全部知识空间选项，并支持按名称搜索。
- `AC-REQ-001-03`: WHEN 用户选择一个或多个知识空间 THEN 节点参数 SHALL 保存检索范围类型和选中的知识空间 `id/name`，且不与文档知识库或临时知识库选项混存。
- `AC-REQ-001-04`: WHEN 用户重新打开已保存的节点 THEN 系统 SHALL 正确回显已选择的知识空间和当前检索范围。
- `AC-REQ-001-05`: WHEN 文档知识库或临时知识库被选择 THEN 现有行为 SHALL 保持不变。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-001-01 | manual + frontend test | 打开文档知识库检索节点，截图或组件测试验证 Tab 顺序。 |
| AC-REQ-001-02 | frontend test + API test | Mock 知识空间列表接口，验证搜索参数和选项渲染。 |
| AC-REQ-001-03 | frontend test + code review | 检查节点参数保存形态，确认不同检索范围不混选。 |
| AC-REQ-001-04 | frontend test | 使用已保存 `space` 参数初始化组件并验证回显。 |
| AC-REQ-001-05 | regression test + manual | 现有文档知识库、临时知识库选择流程仍可用。 |

### REQ-002: 文档知识库问答节点支持知识空间选择
As a `workflow 编排用户`, I want 文档知识库问答节点也能选择知识空间, so that 问答类 workflow 能复用知识空间内容完成原有节点语义。

#### Acceptance Criteria
- `AC-REQ-002-01`: WHEN 用户打开文档知识库问答节点的知识库选择器 THEN 系统 SHALL 在该节点现有设计基础上增加 `知识空间` 选择能力，不移除原有 QA 知识库选择能力。
- `AC-REQ-002-02`: WHEN 问答节点选择知识空间 THEN 系统 SHALL 使用用户加入或有权限使用的知识空间选项，并支持与原有知识库选择一致的搜索、多选、必填校验和回显体验。
- `AC-REQ-002-03`: WHEN 保存旧版问答节点参数数组 THEN 后端 SHALL 继续按原有 QA 知识库逻辑运行。
- `AC-REQ-002-04`: WHEN 保存新版问答节点知识空间参数 THEN 后端 SHALL 识别知识空间检索范围并执行知识空间检索，不因缺少 QA 知识库专有 metadata 结构而抛错。
- `AC-REQ-002-05`: WHEN 问答节点使用知识空间 THEN 节点对外输入变量、输出变量名和得分阈值参数 SHALL 保持与原节点一致。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-002-01 | manual + frontend test | 打开文档知识库问答节点，验证原选择能力仍存在并新增知识空间入口。 |
| AC-REQ-002-02 | frontend test | Mock 知识空间选项，验证搜索、多选、必填校验、回显。 |
| AC-REQ-002-03 | backend regression test | 使用旧版 `qa_knowledge_id: [{key,label}]` 参数运行节点。 |
| AC-REQ-002-04 | backend test | 使用新版 `space` 参数运行节点，确认不解析不存在的 QA answer metadata。 |
| AC-REQ-002-05 | code review + backend test | 检查节点输入输出 key 和 score 参数兼容。 |

### REQ-003: 知识空间列表权限和搜索行为
As a `workflow 编排用户`, I want 只看到我能使用的知识空间, so that workflow 不会保存我无权访问的检索范围。

#### Acceptance Criteria
- `AC-REQ-003-01`: WHEN 前端请求知识空间选项 THEN 接口 SHALL 返回当前用户加入或有权限使用的知识空间，不限于当前用户管理的知识空间。
- `AC-REQ-003-02`: WHEN 用户输入搜索关键字 THEN 接口或前端 SHALL 按知识空间名称过滤，过滤行为 SHALL 与文档知识库选择器的搜索体验一致。
- `AC-REQ-003-03`: WHEN 知识空间数量超过单页容量 THEN 选择器 SHALL 支持继续加载或分页，避免只显示固定第一页。
- `AC-REQ-003-04`: WHEN 用户无权访问某个知识空间 THEN 该知识空间 SHALL 不出现在选择项中；后端运行时也 SHALL 拒绝或跳过未授权空间，且不得越权检索。
- `AC-REQ-003-05`: WHEN 知识空间被删除、退出或权限被移除 THEN 已保存 workflow 打开时 SHALL 能显示可理解的失效状态，运行时 SHALL 以明确错误或空检索结果处理，不得误检索其他空间。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-003-01 | backend/API test | 验证列表接口覆盖 joined/authorized spaces，非仅 managed spaces。 |
| AC-REQ-003-02 | API/frontend test | 验证 name search 参数或本地过滤结果。 |
| AC-REQ-003-03 | frontend test + manual | 构造多页数据，验证滚动加载或分页加载。 |
| AC-REQ-003-04 | backend test + code review | 运行时权限校验覆盖未授权 space id。 |
| AC-REQ-003-05 | backend/frontend regression test | 删除或 mock 失效 space 后验证回显与运行结果。 |

### REQ-004: 选择知识空间时隐藏并清空元数据过滤
As a `workflow 编排用户`, I want 知识空间检索时不看到无效的元数据过滤项, so that 保存的 workflow 参数不会包含对知识空间无效的过滤条件。

#### Acceptance Criteria
- `AC-REQ-004-01`: WHEN 文档知识库检索节点或文档知识库问答节点的检索范围为 `知识空间` THEN UI SHALL 隐藏 `metadata_filter` 表单项。
- `AC-REQ-004-02`: WHEN 用户在文档知识库检索节点或文档知识库问答节点中从文档知识库切换到 `知识空间` THEN UI SHALL 立即清空节点参数中的 `metadata_filter` 保存值。
- `AC-REQ-004-03`: WHEN 用户保存并重新打开已选择知识空间的文档检索类节点 THEN `metadata_filter` SHALL 继续为空且不可见。
- `AC-REQ-004-04`: WHEN 用户从 `知识空间` 切回文档知识库 THEN UI SHALL 重新显示 `metadata_filter`，但不恢复切换前被清空的旧过滤条件。
- `AC-REQ-004-05`: WHEN 后端收到历史数据中 `space` 检索范围仍携带 `metadata_filter` THEN 后端 SHALL 忽略该过滤配置，不把它应用到知识空间检索。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-004-01 | frontend test + manual | 选择 `知识空间` 后验证表单项不可见。 |
| AC-REQ-004-02 | frontend test | 验证切换事件清空节点参数。 |
| AC-REQ-004-03 | frontend regression test | 保存后重新初始化组件，验证隐藏且为空。 |
| AC-REQ-004-04 | frontend test | 切回文档知识库后显示空过滤条件。 |
| AC-REQ-004-05 | backend test | 构造 stale `metadata_filter` 参数，确认未传入知识空间检索过滤。 |

### REQ-005: 后端 workflow 运行时支持知识空间检索
As a `workflow 运行时`, I want 根据节点参数区分文档知识库、知识空间和临时知识库, so that 新增检索范围不会破坏现有检索分支。

#### Acceptance Criteria
- `AC-REQ-005-01`: WHEN 文档知识库检索节点参数类型为 `knowledge` THEN 后端 SHALL 保持原文档知识库检索逻辑。
- `AC-REQ-005-02`: WHEN 文档知识库检索节点参数类型为 `tmp` THEN 后端 SHALL 保持原临时知识库检索逻辑。
- `AC-REQ-005-03`: WHEN 文档知识库检索节点参数类型为 `space` THEN 后端 SHALL 进入独立知识空间检索分支，不得落入临时知识库分支。
- `AC-REQ-005-04`: WHEN 知识空间检索成功 THEN 文档知识库检索节点 SHALL 返回与原节点兼容的 `retrieved_result` 数据结构。
- `AC-REQ-005-05`: WHEN 文档知识库问答节点参数类型为 `space` THEN 后端 SHALL 保持原节点输入输出契约，并使用知识空间内容完成检索结果组装。
- `AC-REQ-005-06`: WHEN 知识空间检索调用失败 THEN workflow 节点 SHALL 返回明确的节点错误，不得静默改用其他知识库范围。
- `AC-REQ-005-07`: WHEN workflow 运行时使用数据库 `User` 模型执行 `space` 检索 THEN 后端 SHALL 在进入知识空间权限校验前适配为具备 `get_user_group_ids()` 的登录用户对象，不得抛出 `'User' object has no attribute 'get_user_group_ids'`。
- `AC-REQ-005-08`: WHEN workflow 运行时手动创建 `KnowledgeSpaceChatService` 执行 `space` 检索 THEN 后端 SHALL 注入知识文档版本仓库依赖，不得抛出 `'KnowledgeSpaceChatService' object has no attribute 'version_repo'`。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-005-01 | backend regression test | 原文档知识库检索节点测试仍通过。 |
| AC-REQ-005-02 | backend regression test | 原临时知识库检索节点测试仍通过。 |
| AC-REQ-005-03 | backend unit test | Mock 参数 `type=space`，验证调用知识空间分支。 |
| AC-REQ-005-04 | backend integration test | 验证 `retrieved_result` 字段和条目结构兼容。 |
| AC-REQ-005-05 | backend integration test | 问答节点 `space` 参数运行并输出原有 key。 |
| AC-REQ-005-06 | backend test | Mock 知识空间服务异常，验证错误路径。 |
| AC-REQ-005-07 | backend regression test | 构造 ORM-like `User` 传入知识空间检索 helper，验证权限服务收到兼容登录用户对象。 |
| AC-REQ-005-08 | backend regression test | 构造 workflow helper 检索路径，验证 `KnowledgeSpaceChatService` 在调用 `aretrieve_chunks()` 前具备 `version_repo`。 |

### REQ-006: 历史 workflow 兼容性
As a `workflow 维护者`, I want 旧 workflow 不受新增检索范围影响, so that 已发布或已保存流程可以继续运行。

#### Acceptance Criteria
- `AC-REQ-006-01`: WHEN 加载旧版文档知识库检索节点参数 THEN 前端 SHALL 正确识别原 `knowledge` / `tmp` 数据结构。
- `AC-REQ-006-02`: WHEN 加载旧版文档知识库问答节点参数数组 THEN 前端 SHALL 继续按原 QA 知识库选择回显。
- `AC-REQ-006-03`: WHEN 运行旧版 workflow THEN 后端 SHALL 不要求新增 `type` 字段才可运行。
- `AC-REQ-006-04`: WHEN 保存新版 workflow THEN 参数结构 SHALL 明确包含检索范围类型，便于后端稳定分支。
- `AC-REQ-006-05`: WHEN 单节点调试知识空间检索 THEN 行为 SHALL 与文档知识库检索一致；临时知识库单节点调试限制不应误作用于知识空间。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-006-01 | frontend regression test | 使用旧 `knowledge_select_multi` 参数初始化。 |
| AC-REQ-006-02 | frontend regression test | 使用旧 `qa_select_multi` 数组初始化。 |
| AC-REQ-006-03 | backend regression test | 旧参数运行不报新增字段缺失。 |
| AC-REQ-006-04 | code review + frontend test | 检查新版保存 payload。 |
| AC-REQ-006-05 | manual + backend/frontend test | 单节点调试知识空间不触发临时知识库限制。 |

### REQ-007: 知识空间选择器分类展示和加载状态
As a `workflow 编排用户`, I want 知识空间选择器按类型树形分类并在加载时明确提示, so that 我可以更快定位目标知识空间并理解列表正在请求数据。

#### Acceptance Criteria
- `AC-REQ-007-01`: WHEN 文档知识库检索节点切换到 `知识空间` THEN 系统 SHALL 按 `公共空间`、`部门空间`、`团队空间`、`个人空间` 的顺序展示可展开/收起分类节点。
- `AC-REQ-007-02`: WHEN 文档知识库问答节点切换到 `知识空间` THEN 系统 SHALL 使用同样的分类顺序和树形展示方式。
- `AC-REQ-007-03`: WHEN 用户点击分类节点 THEN 系统 SHALL 只展开或收起该分类，不把分类本身保存为已选知识空间。
- `AC-REQ-007-04`: WHEN 用户输入搜索关键字 THEN 系统 SHALL 保留分类展示，只展示包含匹配知识空间的分类，空分类不展示。
- `AC-REQ-007-05`: WHEN 知识空间列表初次加载、搜索或加载更多请求尚未返回 THEN 系统 SHALL 在选择器列表区域展示加载状态。
- `AC-REQ-007-06`: WHEN 知识空间请求返回空结果 THEN 系统 SHALL 展示可理解的空状态，而不是显示空白列表。
- `AC-REQ-007-07`: WHEN 已保存或已选择的检索范围为 `知识空间` 且用户再次打开选择器 THEN 系统 SHALL 加载第一页知识空间列表，不得因列表区域 footer 立即进入视口而抢先触发下一页请求并显示空结果。

#### Verification Methods
| Acceptance ID | Method | Evidence Target |
|---|---|---|
| AC-REQ-007-01 | manual + frontend build | 文档知识库检索节点知识空间列表截图或浏览器检查分类顺序。 |
| AC-REQ-007-02 | manual + frontend build | 文档知识库问答节点知识空间列表截图或浏览器检查分类顺序。 |
| AC-REQ-007-03 | manual | 点击分类节点后验证只折叠展开，不新增 selected badge。 |
| AC-REQ-007-04 | manual | 搜索后验证分类仍存在且空分类隐藏。 |
| AC-REQ-007-05 | manual + code review | 通过延迟请求或快速操作验证 loading 文案/图标可见。 |
| AC-REQ-007-06 | manual + code review | 搜索无结果时验证空状态文案。 |
| AC-REQ-007-07 | manual + frontend build | 已选 `space` 后再次打开两个节点选择器，验证列表能展示第一页知识空间。 |

## Non-Functional Requirements
- `NFR-001`: 新增前端代码 SHALL 使用 Platform 现有 `@/controllers/request.ts`、`bs-ui`、`useTranslation()` 和现有状态管理方式，不引入新 UI 或状态库。
- `NFR-002`: 后端新增或修改逻辑 SHALL 遵守 `Router -> Endpoint -> Service -> Repository -> DB` 分层，不在 endpoint 中直接访问 ORM model。
- `NFR-003`: 知识空间权限校验 SHALL 复用现有权限能力，不通过手写 tenant 条件替代权限系统。
- `NFR-004`: 新增逻辑 SHALL 不改变文档知识库和临时知识库已有运行结果。
- `NFR-005`: 前端单文件如超过 600 行 SHALL 拆分组件或 hook。

## Clarifications
- `CLAR-001`: 知识空间列表范围为“用户加入或有权限使用的所有知识空间”，不是仅用户管理的空间。
- `CLAR-002`: 文档知识库检索、文档知识库问答节点分别参考各自原有设计扩展，不改变原节点输入输出契约。
- `CLAR-003`: 选择知识空间时，元数据过滤要求为“UI 隐藏，并清空保存值”。
- `CLAR-004`: Platform 侧“文档知识库问答”菜单项对应 workflow 节点类型为 `rag`；`REQ-004` 的元数据过滤隐藏/清空要求同时覆盖 `knowledge_retriever` 与 `rag`。
- `CLAR-005`: 知识空间树形分类按现有 `space_level` 四类展示：`公共空间`、`部门空间`、`团队空间`、`个人空间`。
- `CLAR-006`: 分类节点可展开/收起但不可选择；用户只能选择具体知识空间。
- `CLAR-007`: 搜索知识空间后仍保留分类展示，空分类隐藏。
- `CLAR-008`: 本次加载状态范围限定为知识空间选择器列表加载、搜索和滚动加载更多，不包含 workflow 运行时检索 loading。
- `CLAR-009`: 2026-06-23 运行时报错根因为 workflow runtime 的 `BaseNode.init_user_info()` 返回数据库 `User`，而知识空间权限服务需要 `LoginUser/UserPayload` 的 `get_user_group_ids()` 能力；修复范围限定在知识空间检索路径的用户对象适配。
- `CLAR-010`: 2026-06-23 新运行时报错根因为 workflow 知识空间检索 helper 手动实例化 `KnowledgeSpaceChatService`，没有走 FastAPI 依赖工厂，因此缺少 `_build_folder_search_kwargs()` 所需的 `version_repo`；修复范围限定为该 helper 内补齐版本仓库依赖注入。
- `CLAR-011`: 2026-06-23 前端截图显示已处于 `知识空间` tab 时再次打开选择器会展示 `暂无匹配的知识空间`；只读检索判断修复范围限定为两个知识空间选择器的加载/滚动分页竞态，不改变后端检索逻辑。

## Out of Scope Questions for Later
- 是否要让其他 workflow 节点也支持知识空间检索范围。
- 是否要为知识空间检索新增更细粒度的元数据过滤能力。
- 是否要为知识空间选择器提供独立的最近使用或收藏排序。
