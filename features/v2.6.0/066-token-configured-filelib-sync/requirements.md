# 需求说明 Requirements：Token 配置化统一文件同步接口

## 阅读摘要

- 本文档把现有 11 个请求结构相同、仅固定业务规则不同的文件同步接口收口为一个 `POST /api/v2/filelib/file/sync`。
- 文件分类始终由开发者 Token 固定；业务域与目标知识空间分别支持固定或动态解析，动态部分共用一个来源选择：`department_id` 或 `responsible_person_id`。
- Token 业务配置只负责选择规则，不授予权限；路由白名单和 Token 绑定用户的知识空间上传权限仍是独立且必须通过的安全边界。
- 固定目标可选择公共/部门知识空间根目录或其下任意层级目录；目标树按 Token 绑定用户的 `upload_file` 权限过滤，动态目标继续落到解析空间根目录。
- 本 Feature 立即移除 11 个旧 URL，不自动迁移已有 Token 配置或路由白名单；上线前由管理员显式配置。
- 当前状态：初版统一接口与固定目录目标均已实现并完成自动化验证；真实双库、预发布切流和应用回退等待 T021 人工验证。

## 元信息 Metadata

- Feature ID: `066-token-configured-filelib-sync`
- Status: `route-shadowing bugfix complete; manual release verification pending`
- Mode: `implementation`
- Created: `2026-07-22`
- Updated: `2026-08-03`
- Version: `v2.6.0`
- Source request: 在已完成的统一同步接口上，把固定目标选择器改为按公共/部门空间分组的权限过滤树；可选择空间根目录或目录，目录目标按 Token 绑定用户上传权限过滤并上传到该目录。
- Requested stopping point: 完成目录目标实现与自动化验收；真实环境发布操作需后续单独授权。

## 需求入口摘要 Intake Summary

- 问题 Problem: 现有 11 个接口的认证、multipart 入参、响应和上传流程完全相同，只靠 URL 末尾编号选择硬编码规则；新增或调整业务规则必须改代码、增加路由并重新发布。
- 当前状态 Current state: 初版 F066 已统一为 `/file/sync`，Token 固定目标只保存 `knowledge_id`，管理页使用平铺空间选择器，同步始终以 `parent_id=None` 写入根目录；旧配置和自动化证据记录在当前 Feature 中。
- 目标结果 Target outcome: 固定目标在不改变外部同步请求/响应的前提下，保存稳定 `knowledge_id + folder_id?`；管理员按 Token 绑定用户权限选择空间根目录或目录，运行时再次复核并写入最终节点。
- 影响对象 Affected users/systems: 开发者 Token 管理后台、Token 管理 API 与数据模型、开发者 Token 认证依赖、Open Endpoints Filelib 同步路由与服务、首钢门户分类/业务域配置、部门知识空间解析、接口文档及自动化测试。

## 现状证据 Current Evidence

- `docs/api/filelib-file-sync-split.md` 定义 11 个接口，共享 `file`、`params`、成功响应、错误语义和异步解析流程，仅文件分类、业务域、同步位置不同。
- `open_endpoints/api/endpoints/filelib_sync.py` 注册 11 个 `POST /file/sync/{code}` 路由，并按 code 从 `FILELIB_SYNC_RULES` 取规则。
- `DeveloperToken` 当前使用 `JsonType` 保存 `route_whitelist`，尚无文件同步业务配置字段。
- `DeveloperTokenService.authenticate()` 在完成 Token、IP、路由白名单和限流校验后只返回绑定用户的 `UserPayload`，下游无法可靠识别本次使用的 Token。
- `FilelibSyncService` 当前先校验空间根目录权限，再以 `parent_id=None` 调用 `KnowledgeSpaceService.add_file()`；后者已支持目录 `parent_id` 并按目录检查 `upload_file`。
- `PermissionService.list_accessible_ids()` 已支持按用户列出 `knowledge_space`/`folder` 的关系对象，可作为权限过滤事实源；OpenFGA 不可用时保持失败关闭。
- `UserSelectedKnowledgePicker.tsx` 已有空间类型分组和目录懒加载交互，可参考但不能直接复用其文件多选和硬编码文案契约。
- 当前 `DeveloperToken.tsx` 为 572 行；目录树状态和请求逻辑必须继续拆分，所有 Platform TypeScript 文件不超过 600 行。
- 生产组合路由中 `filelib_router_rpc` 先于 `filelib_sync_router_rpc` 注册；已有 `POST /filelib/file/{knowledge_id}` 会先匹配 `/filelib/file/sync` 并把 `sync` 当作整数 ID 校验，导致统一接口在进入认证和业务服务前返回 422。现有测试只注册同步子路由，未覆盖该组合顺序。

## 术语与配置模型 Terminology

- **文件同步业务配置**：`DeveloperToken.file_sync_rule`，可空；空表示该 Token 未开通统一文件同步业务。
- **固定分类**：配置中的一级分类编码和二级分类编码，二者始终必填且必须存在父子关系；请求参数不能覆盖。
- **业务域模式**：`fixed` 表示配置固定业务域编码；`dynamic` 表示按动态来源解析出的部门，从当前租户 `domains[].department_ids` 取得业务域。
- **目标空间模式**：`fixed` 表示配置固定 `knowledge_id` 和可空 `folder_id`，空目录表示空间根目录；`dynamic` 表示按动态来源解析部门并调用既有确定性部门知识空间解析器，目标始终为解析空间根目录。
- **目标节点**：固定模式下最终选择的知识空间根目录或目录；只有该节点对 Token 绑定用户具备 `upload_file` 时才可选择、保存和调用。
- **导航祖先**：绑定用户仅拥有深层目录上传权限时，为到达该目录而展示的空间和祖先目录；导航祖先不可选择，且不得因此展示无关兄弟目录。
- **动态来源**：只允许 `department_id` 或 `responsible_person_id`。只要业务域或目标空间至少一项为动态，就必须配置一个且仅一个共用动态来源。
- **完整配置**：分类编码齐全；每个固定维度有固定值；固定目标的 `folder_id` 为正整数或空；动态目标的 `knowledge_id`/`folder_id` 均为空；存在动态维度时有动态来源；不存在与模式冲突的多余固定值。系统不保存草稿态或部分配置。

## 范围 Scope

### 包含 Includes

- 新增统一 `POST /api/v2/filelib/file/sync` multipart 接口。
- 移除 11 个 `/api/v2/filelib/file/sync/{code}` 路由和生产代码中的静态规则表。
- 在每个开发者 Token 上增加可空、结构化、完整保存的 `file_sync_rule`。
- Token 创建、编辑、详情、列表接口读写文件同步业务配置，并记录审计摘要。
- 管理页配置固定分类、业务域固定/动态、目标知识空间固定/动态和动态来源；固定目标使用按公共/部门空间分组的单选树，可选择空间根目录或目录。
- 分类与业务域选项严格限定在 Token 绑定租户；目标树加载、保存和运行时校验均按 Token 绑定用户对最终节点的 `upload_file` 权限失败关闭。
- 认证依赖向统一同步链路传递本次 Token ID 及已校验配置，同时保持其他开发者 Token API 的 `UserPayload` 使用方式兼容。
- 动态来源缺失、固定引用失效、动态解析失败、域与空间未绑定、无上传权限等失败关闭规则。
- 保留既有 multipart 入参、成功响应、文件元数据、跳过审批、重复文件冲突、固定编码、失败清理和异步解析行为；固定目录目标只改变 `add_file(parent_id)`。
- 复用已上线的 MySQL/DM8 兼容 `file_sync_rule` JSON 列；新增可空 `folder_id` 不新增数据库迁移或数据回填，缺失/`null` 均表示根目录。
- 更新接口文档、后端测试、Platform 管理页测试和三语种文案。

### 不包含 Excludes

- 不允许请求参数动态指定或覆盖一级/二级文件分类。
- 不允许一个 Token 配置多条文件同步规则，不根据请求字段在多条规则之间路由。
- 不引入 Token 配置草稿、版本历史、定时生效或审批流程。
- 不复制 `domains[].department_ids` 到 Token、新表或其他配置；不修改首钢门户配置写入契约。
- 不修改部门组织关系、知识空间绑定、业务域与空间绑定或知识文件所有权。
- 不让配置替代 Token 路由白名单、租户校验、OpenFGA/知识空间上传权限。
- 不允许选择团队空间、个人空间、知识文件；不提供目录创建、移动、重命名、全局目录搜索或多目标选择。
- 不允许动态目标指定目录；动态目标始终上传到解析出的知识空间根目录。
- 不在外部同步成功响应中新增 `folder_id`、目录路径或其他目录字段，不在目标失效时回退到空间根目录。
- 不为旧 URL 提供重定向、兼容代理或灰度双写。
- 不自动把旧接口编号推导成 Token 配置，不自动重写现有 `route_whitelist`。
- 不把 `external_file_id` 改成幂等键；重复提交继续分别进入既有上传流程。
- 不修复现有数据库写入与 Celery 入队之间的非原子边界。
- 本次规格更新允许修改本 Feature 的 SDD 文档；在实施获得单独确认前，不修改生产代码，不执行 Alembic upgrade/downgrade。

## 外部接口契约 External API Contract

```http
POST /api/v2/filelib/file/sync
X-Developer-Token: bst_xxx
Content-Type: multipart/form-data
```

请求体保持两个字段：

| 字段 | 类型 | 必填 | 契约 |
|---|---|---:|---|
| `file` | file | 是 | 非空文件二进制 |
| `params` | string(JSON) | 是 | 保持 `external_file_id`、`file_name`、`department`、`department_id`、`responsible_person`、`responsible_person_id` 字段与 ID/名称一致性校验 |

成功响应继续使用现有 `resp_200` 包装及以下 `data`：`external_file_id`、`file_id`、`file_encoding`、`knowledge_id`、`knowledge_name`、`status`。选择目录不新增目录 ID、目录路径或目录名称字段。

## 需求列表 Requirements

### REQ-001：统一路由替代 11 个固定规则路由

作为第三方调用方，我需要只调用一个稳定 URL，以便业务规则调整不再依赖新增接口编号。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN F066 上线 THEN OpenAPI SHALL 只注册 `POST /api/v2/filelib/file/sync` 作为本组同步入口。
- `AC-REQ-001-02`: WHEN 调用任一旧 URL `/file/sync/{03|04|05|06|07|09|10|11|12|14|15}` THEN 路由 SHALL 不存在，不执行认证后业务处理，不提供重定向或兼容响应。
- `AC-REQ-001-03`: WHEN 调用统一接口 THEN Header、multipart 字段、`params` 字段、成功响应结构和文件状态枚举 SHALL 与既有接口保持兼容。
- `AC-REQ-001-04`: WHEN 同一 `external_file_id` 重复提交 THEN 系统 SHALL 沿用既有非幂等语义，分别执行上传，不新增预占或唯一约束。
- `AC-REQ-001-05`: WHEN 通过生产 `router_rpc` 调用 `POST /api/v2/filelib/file/sync` THEN 请求 SHALL 命中统一同步 handler，不得被 `POST /filelib/file/{knowledge_id}` 解析为 `knowledge_id="sync"`；旧知识库上传接口及统一接口 URL SHALL 保持不变。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | route/OpenAPI automated test | 路由集合只含统一路径 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | API regression | 11 个旧路径全部 404，业务 service mock 调用为 0 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | contract test | multipart 与响应 fixture 保持字段、类型和状态语义 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | service regression | 相同 `external_file_id` 两次均进入上传流程 |
| AC-REQ-001-05 | V-AC-REQ-001-05 | production-router API regression | 真实 `router_rpc` 下缺少 `params` 返回同步接口业务码 `19905`，而非 `knowledge_id` 整数解析 422 |

### REQ-002：每个 Token 最多一份完整业务配置

作为开发者 Token 管理员，我需要把调用方固定业务与 Token 绑定，以便统一接口能确定性选择规则。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN 创建或编辑 Token THEN 管理员 MAY 不配置文件同步业务；数据库 SHALL 保存 `NULL`，该 Token 的其他已授权 API 能力 SHALL 不受影响。
- `AC-REQ-002-02`: WHEN 启用文件同步业务 THEN 系统 SHALL 一次保存一份完整配置，不接受空分类、部分固定值、固定目标缺少 `knowledge_id`、动态目标残留 `knowledge_id`/`folder_id`、动态维度缺少动态来源或其他模式冲突字段；固定目标 `folder_id` 可缺失或为 `null`；结构/类型错误使用请求校验错误，跨字段或资源错误使用稳定业务错误，二者均不得写库。
- `AC-REQ-002-03`: WHEN 配置存在 THEN 一级分类编码和二级分类编码 SHALL 始终固定且必填；请求中的任何同名或扩展字段 SHALL NOT 覆盖 Token 配置。
- `AC-REQ-002-04`: WHEN 业务域和目标空间均为固定 THEN `dynamic_source` SHALL 为空，目标 SHALL 保存 `knowledge_id` 和可空 `folder_id`；WHEN 任一维度为动态 THEN `dynamic_source` SHALL 为 `department_id` 或 `responsible_person_id` 并同时服务所有动态维度，动态目标的 `knowledge_id`/`folder_id` SHALL 均为空。
- `AC-REQ-002-05`: WHEN Token 绑定用户发生任何调整 THEN 系统 SHALL 按新绑定用户重新校验租户、固定引用和最终目标节点 `upload_file` 权限；配置无效时拒绝更新，除非同一请求明确清空或替换无效配置。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | API/service test | 可空配置不影响其他 Token endpoint |
| AC-REQ-002-02 | V-AC-REQ-002-02 | schema + service parameterized test | 旧配置无 `folder_id` 可读；目录字段类型、模式真值表、422/400 分层及不写库 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | schema/API security test | 分类缺失拒绝，请求无法覆盖固定分类 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | truth-table unit test | 四种 fixed/dynamic 组合、可空目录与动态来源约束完整覆盖 |
| AC-REQ-002-05 | V-AC-REQ-002-05 | rebind admin test | 同租户/跨租户换绑均重新校验权限，或显式清空/替换，无越权引用残留 |

### REQ-003：配置选项和固定引用必须受租户与当前状态约束

作为管理员，我需要只能选择当前有效资源，以减少配置错误和跨租户引用。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN 管理页加载配置选项 THEN 系统 SHALL 只返回管理员有权管理的目标租户内、当前首钢门户聚合配置中的合法分类父子树和已启用业务域；固定目标只返回公共/部门空间及其目录，并按 Token 绑定用户 `upload_file` 权限过滤可选节点。
- `AC-REQ-003-02`: WHEN 保存分类 THEN 系统 SHALL 按稳定编码校验一级分类存在、二级分类存在且属于所选一级分类，不按展示名称作为身份。
- `AC-REQ-003-03`: WHEN 保存固定业务域、固定知识空间或固定目录 THEN 系统 SHALL 校验资源存在、有效且属于 Token 绑定租户；目录还 SHALL 为 `DIR` 类型并属于所选空间；跨租户、删除、停用、空间不匹配或类型不合法均拒绝保存。
- `AC-REQ-003-04`: WHEN 业务域和目标空间均固定 THEN 系统 SHALL 在保存时校验该域与空间双向绑定一致；其他包含动态维度的组合 SHALL 在运行时使用最终解析结果校验绑定。
- `AC-REQ-003-05`: WHEN 配置保存后分类、业务域、知识空间、目录或绑定被删除、停用、移出租户或目录不再属于所选空间 THEN 下一次同步 SHALL 返回 404/19903，不回退到名称、旧路径快照、空间根目录、其他资源或动态路径。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | admin API integration | 分类/域租户隔离；公共/部门目标树按绑定用户权限过滤并使用游标懒加载 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | validation unit test | 编码规范、父子关系及名称变更场景 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | service/security test | 固定域/空间/目录存在性、状态、类型、所属空间和租户矩阵 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | service test | 固定-固定保存时校验；混合模式运行时校验 |
| AC-REQ-003-05 | V-AC-REQ-003-05 | stale-reference regression | 配置后删除/停用/解绑/目录错配均 fail closed 且不回退根目录 |

### REQ-004：动态业务按配置来源确定性解析

作为 Token 管理员，我需要选择动态业务使用主责单位还是责任人主部门，以便不同调用方采用一致的部门语义。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: IF `dynamic_source=department_id` AND 任一维度为动态 THEN 请求 SHALL 显式提供合法 `params.department_id`；缺失或空值返回 400/19901，不使用调用人默认部门或 `responsible_person_id` 回退。
- `AC-REQ-004-02`: IF `dynamic_source=responsible_person_id` AND 任一维度为动态 THEN 请求 SHALL 显式提供合法 `params.responsible_person_id`；系统 SHALL 解析该用户在当前租户的唯一主部门；缺失 ID、用户不存在、无主部门或跨租户均明确失败，不使用调用人或 `department_id` 回退。
- `AC-REQ-004-03`: WHEN 业务域为动态 THEN 系统 SHALL 只在当前租户已启用 `domains[].department_ids` 中按解析出的部门 ID 精确匹配；零个或多个匹配均返回 404/409，不按部门名称或父子部门继承。
- `AC-REQ-004-04`: WHEN 目标空间为动态 THEN 系统 SHALL 把同一解析部门交给 F060 `DepartmentSpaceTargetResolver`；唯一候选成功，零候选返回 404，多候选返回 409，且文件保存尚未开始。
- `AC-REQ-004-05`: WHEN 一个维度固定、另一个动态 THEN 固定维度 SHALL 完全忽略动态来源，动态维度 SHALL 使用配置的唯一来源；两者解析完成后仍校验域与空间绑定。
- `AC-REQ-004-06`: WHEN `department`/`responsible_person` 名称与对应 ID 同时提供 THEN 系统 SHALL 保留现有名称一致性校验；未参与动态选择的字段仍按现有规则用于文件元数据默认与校验。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | API/service test | department 来源缺失、合法、跨租户且无 fallback |
| AC-REQ-004-02 | V-AC-REQ-004-02 | repository/service test | 责任人主部门、无主部门、跨租户、缺失 ID 矩阵 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | portal config resolver test | 精确零/一/多业务域匹配，不继承父子部门 |
| AC-REQ-004-04 | V-AC-REQ-004-04 | resolver integration | F060 唯一/缺失/歧义路径及上传副作用为 0 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | parameterized matrix | fixed/dynamic 四组合的解析调用次数和最终绑定 |
| AC-REQ-004-06 | V-AC-REQ-004-06 | regression | ID/名称一致性和元数据默认行为不回归 |

### REQ-005：Token 安全控制和资源权限保持独立

作为平台安全管理员，我需要业务配置不能扩大 Token 的访问范围。

#### 验收标准 Acceptance Criteria

- `AC-REQ-005-01`: WHEN 请求到达统一接口 THEN 系统 SHALL 按现有顺序校验 Token 存在/有效/启用、租户与用户状态、IP、路由白名单和限流；路由白名单不允许统一路径时返回 `19812`，不得读取或执行文件同步业务配置。
- `AC-REQ-005-02`: WHEN Token 没有 `file_sync_rule` THEN 统一接口 SHALL 返回 403/19906；同一 Token 调用其他路由白名单允许的 API SHALL 继续按原行为执行。
- `AC-REQ-005-03`: WHEN 最终目标节点解析完成 THEN 系统 SHALL 使用 Token 绑定用户校验该空间根目录或目录节点的 `upload_file` 权限；无权限返回 403/19902，即使管理员已为 Token 固定该节点也不得放行。
- `AC-REQ-005-04`: WHEN 请求、配置或资源 ID 跨租户 THEN 系统 SHALL 失败关闭，不在响应或普通日志中暴露其他租户资源名称或详情。
- `AC-REQ-005-05`: WHEN 认证上下文结束、业务抛错或依赖提前退出 THEN 系统 SHALL 可靠恢复当前租户和可见租户 ContextVar，不污染后续请求。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | dependency/API order test | 19812 优先于配置缺失与业务查询，service mock 未调用 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | API regression | 无配置统一同步 403，其他 Token API 正常 |
| AC-REQ-005-03 | V-AC-REQ-005-03 | permission integration | 固定根目录/固定目录/动态根目录均校验最终节点权限，权限丢失失败关闭 |
| AC-REQ-005-04 | V-AC-REQ-005-04 | tenant/IDOR test | 跨租户分类、域、空间、人员、部门全部拒绝并脱敏 |
| AC-REQ-005-05 | V-AC-REQ-005-05 | dependency lifecycle test | success/error/cancel 路径均恢复 ContextVar |

### REQ-006：既有文件写入和异步处理语义保持不变

作为同步接口调用方，我需要接口合并不改变文件进入知识库后的行为。

#### 验收标准 Acceptance Criteria

- `AC-REQ-006-01`: WHEN 所有解析与权限校验通过 THEN 系统 SHALL 使用 `params.file_name` 保存原始文件到最终目标节点；空间根目录传递 `parent_id=None`，固定目录传递其稳定 `folder_id`，并传递固定分类、最终业务域、`skip_approval=True` 和 `enqueue_processing=False`。
- `AC-REQ-006-02`: WHEN 知识文件创建成功 THEN 系统 SHALL 生成既有 `SGGF-{一级分类编码}-{业务域编码}-{YYYYMM}{8位序号}` 固定编码、持久化元数据后再提交异步解析，成功响应通常返回排队状态。
- `AC-REQ-006-03`: WHEN 上传校验判定名称或内容重复 THEN 系统 SHALL 返回 409/19904；WHEN 在正式持久化前失败 THEN 系统 SHALL 沿用现有文件记录与临时对象清理边界。
- `AC-REQ-006-04`: WHEN 写入用户元数据 THEN 系统 SHALL 保留 `external_file_id`、主责单位、责任人字段，并把来源标记改为统一值 `filelib_sync_endpoint="sync"`；Token ID 只进入受控服务端日志/审计，不写入文件元数据，不保存 Token 明文、密文或哈希。
- `AC-REQ-006-05`: WHEN 同步成功响应返回 THEN 字段和含义 SHALL 与旧接口一致；成功只表示已持久化并排队，不代表解析完成。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01 | V-AC-REQ-006-01 | service interaction test | 根目录/目录的 `add_file(parent_id)`、跳审批与延迟入队参数正确 |
| AC-REQ-006-02 | V-AC-REQ-006-02 | encoding/queue regression | 编码生成、持久化先于一次 enqueue |
| AC-REQ-006-03 | V-AC-REQ-006-03 | failure regression | 重复冲突、记录清理、临时对象清理 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | metadata security test | 既有元数据 + sync 标记，文件元数据无 Token 标识或 secret |
| AC-REQ-006-05 | V-AC-REQ-006-05 | response contract | data 字段、类型与排队语义不变 |

### REQ-007：Developer Token 管理页可配置且可识别

作为 Token 管理员，我需要在现有创建/编辑流程中完成配置并在列表快速识别业务用途。

#### 验收标准 Acceptance Criteria

- `AC-REQ-007-01`: WHEN 打开 Token 创建或编辑弹窗 THEN 管理员 SHALL 可选择“不启用文件同步业务”或配置分类、业务域模式、目标空间模式及动态来源；固定目标 SHALL 使用单选树选择空间根目录或目录，展开节点不得隐式选中，字段按模式联动并阻止不完整提交。
- `AC-REQ-007-02`: WHEN 选择目标租户、Token 绑定用户或编辑已有 Token THEN 页面 SHALL 重新加载有效选项并重新校验目标；切换租户或用户不得静默提交陈旧、跨租户或新用户无权上传的节点。
- `AC-REQ-007-03`: WHEN Token 列表或编辑详情展示 THEN SHALL 显示“未配置”或包含固定目标当前完整路径/空间根目录的结构化摘要；目录重命名或同空间移动后展示当前路径，失效引用保留稳定 ID 并明确提示，不显示成另一个有效资源。
- `AC-REQ-007-04`: WHEN 保存成功 THEN 页面 SHALL 刷新列表和详情；后端审计 SHALL 记录配置前后摘要，但不得记录 Token 明文、密文或哈希。
- `AC-REQ-007-05`: 新 UI SHALL 从当前 572 行 `DeveloperToken.tsx` 抽取独立目标树组件和请求/状态 hook，所有 Platform TypeScript 文件 SHALL 不超过 600 行，并使用现有 `bs-ui`、Zustand/局部状态、request wrapper 和 `useTranslation()`。
- `AC-REQ-007-06`: 新增用户可见文案 SHALL 同步覆盖 Platform 现有三种语言资源；加载、空结果、无权限、导航祖先、空间根目录和失效引用 SHALL 有明确提示。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01 | V-AC-REQ-007-01 | component + validation test | 模式联动、根目录/目录单选、展开不选中、禁用清空配置 |
| AC-REQ-007-02 | V-AC-REQ-007-02 | component/API test | 租户/用户切换刷新选项并阻止陈旧或无权 ID |
| AC-REQ-007-03 | V-AC-REQ-007-03 | component snapshot/DOM test | 未配置、根目录、当前目录路径和失效稳定 ID 摘要 |
| AC-REQ-007-04 | V-AC-REQ-007-04 | frontend/API + audit test | 刷新、前后摘要、无 secret |
| AC-REQ-007-05 | V-AC-REQ-007-05 | Vitest/build/static check | 独立目标树/hook、文件行数、导入边界、定向测试与 production build |
| AC-REQ-007-06 | V-AC-REQ-007-06 | i18n key parity + DOM test | zh/en/ja 键一致且目标树各状态有可见文案 |

### REQ-008：迁移、上线和回退必须显式可控

作为发布负责人，我需要在不误配现有 Token 的前提下切换新接口。

#### 验收标准 Acceptance Criteria

- `AC-REQ-008-01`: WHEN 执行 schema upgrade THEN 系统 SHALL 通过 Alembic 为 `developer_token` 增加可空 `JsonType` 列 `file_sync_rule`，不执行业务数据回填，并兼容 MySQL 与 DM8。
- `AC-REQ-008-02`: WHEN 升级已有环境 THEN 所有现有 Token SHALL 保持 `file_sync_rule=NULL`；系统 SHALL NOT 根据 Token 名称、旧路由白名单或接口调用历史自动推导配置。
- `AC-REQ-008-03`: WHEN 准备上线 THEN 管理员 SHALL 在切流前逐个配置需同步的 Token，并手工把路由白名单从旧 URL 替换为 `POST /api/v2/filelib/file/sync`；系统 SHALL 不自动修改白名单。
- `AC-REQ-008-04`: WHEN 应用回退到不认识 `folder_id` 且对 JSON 采用 `extra=forbid` 的旧版本 THEN 发布负责人 SHALL 先导出并清空目录目标或采用前向修复；不得假设保留可空 JSON 列即可兼容。WHEN 执行数据库 downgrade THEN 既有删除列风险保持不变，执行前必须备份或接受配置丢失。
- `AC-REQ-008-05`: WHEN 发布验证 THEN 自动化 SHALL 覆盖 Token 配置真值表、认证优先级、固定根目录/固定目录/动态根目录、租户与绑定用户权限、树形游标加载、11 个旧路由移除、迁移幂等和既有同步回归；真实 DM8 验证 SHALL 在 Linux CI/预发布环境完成。
- `AC-REQ-008-06`: 接口文档 SHALL 明确统一 URL、Token 配置前置条件、固定目录与动态根目录规则、绑定用户权限过滤、无自动迁移、旧 URL 移除和新错误语义，且外部成功响应 SHALL 保持不变。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-008-01 | V-AC-REQ-008-01 | migration unit + disposable DB | 列类型、可空、幂等 upgrade/downgrade；MySQL/DM8 helper |
| AC-REQ-008-02 | V-AC-REQ-008-02 | migration data test | 既有行全为 NULL、无 DML/backfill |
| AC-REQ-008-03 | V-AC-REQ-008-03 | rollout checklist/manual | Token 与路由白名单逐项核对证据 |
| AC-REQ-008-04 | V-AC-REQ-008-04 | migration/application rollback review | 旧应用严格 schema 的 `folder_id` 风险、导出/清理与 downgrade 数据风险明确 |
| AC-REQ-008-05 | V-AC-REQ-008-05 | backend/frontend/CI suite | 目录与权限矩阵、Ruff、前端 build、Linux DM8 结果 |
| AC-REQ-008-06 | V-AC-REQ-008-06 | documentation review | 根/目录目标、动态根目录、权限、响应和错误表完整 |

### REQ-009：固定目标可选择知识空间根目录或目录

作为 Developer Token 管理员，我需要在绑定用户实际可上传的公共/部门知识空间树中选择固定目标，以便统一同步接口把文件准确上传到空间根目录或指定目录，且配置本身不扩大用户权限。

#### 验收标准 Acceptance Criteria

- `AC-REQ-009-01`: WHEN 固定目标配置缺失 `folder_id` 或其值为 `null` THEN 系统 SHALL 将目标解释为空间根目录并兼容所有已保存配置；WHEN `folder_id` 为正整数 THEN 系统 SHALL 将其解释为目录稳定 ID；本次变更 SHALL 不新增数据库列、迁移或回填。
- `AC-REQ-009-02`: WHEN 目标空间模式为 `dynamic` THEN `knowledge_id` 和 `folder_id` SHALL 均为空；运行时解析出的目标 SHALL 始终为空间根目录，请求参数和其他配置均不得动态指定目录。
- `AC-REQ-009-03`: WHEN 管理员打开固定目标树 THEN 入口 SHALL 复用既有 Token 管理仅系统管理员可用的授权边界；顶层 SHALL 只按公共空间、部门空间分组并只包含当前 Token 绑定租户；团队空间、个人空间和知识文件 SHALL 不返回、不展示且不可通过构造请求保存。
- `AC-REQ-009-04`: WHEN 加载目标选项、保存配置或执行同步 THEN 系统 SHALL 以 Token 绑定用户为权限主体检查最终节点的 `upload_file`；管理员身份和 Token 配置 SHALL 不授予或放大该权限，权限服务不可用时 SHALL 失败关闭。
- `AC-REQ-009-05`: WHEN 绑定用户只拥有深层目录的 `upload_file` THEN 树 SHALL 展示所属空间和必要祖先作为不可选择的导航节点，只允许有权限的目录可选，并隐藏无关兄弟目录；空间根目录只有在用户拥有该空间根目录权限时才可选。
- `AC-REQ-009-06`: WHEN 使用目标树 THEN 选择 SHALL 为单选，展开空间/目录不得隐式选中；空间名称支持关键词搜索，目录按展开节点使用统一游标懒加载并只返回目录；无效游标 SHALL 返回 400/19814 且不得静默回到首页；本 Feature SHALL 不提供全局目录搜索、目录操作或文件选择。
- `AC-REQ-009-07`: WHEN 保存固定目录 THEN 系统 SHALL 再次校验目录存在、当前有效、类型为 `DIR`、属于所选知识空间和租户，并校验绑定用户权限；任一条件不满足 SHALL 返回 400/19813 且不写库。WHEN 换绑用户 THEN 同一规则适用，除非请求同时清空或替换配置。
- `AC-REQ-009-08`: WHEN 已配置目录重命名或在同一空间内移动 THEN 稳定 `folder_id` SHALL 继续有效且管理页展示当前路径；WHEN 目录删除、跨空间错配或引用失效 THEN 同步 SHALL 返回 404/19903 且不得回退根目录；WHEN 权限被撤销 THEN 返回 403/19902。
- `AC-REQ-009-09`: WHEN 运行时固定目标通过复核 THEN 根目录上传 SHALL 调用 `add_file(parent_id=None)`，目录上传 SHALL 调用 `add_file(parent_id=folder_id)`；目标解析与权限校验 SHALL 在正式文件持久化和临时对象创建前完成，`KnowledgeSpaceService.add_file()` 仍 SHALL 按最终节点再次执行既有权限检查。
- `AC-REQ-009-10`: WHEN 文件上传到目录并成功返回 THEN 外部同步响应 SHALL 继续只返回既有 `knowledge_id`、`knowledge_name` 等字段，不新增目录 ID、路径或名称，也不改变 `knowledge_id` 的空间语义。
- `AC-REQ-009-11`: WHEN Token 列表或编辑详情读取固定目标 THEN 管理 API SHALL 提供结构化的当前空间名称、当前目录完整路径和失效状态用于展示；路径 SHALL 由稳定 ID 批量解析，不持久化路径快照、不产生逐 Token N+1 查询，根目录 SHALL 有明确结构化标识。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-009-01 | V-AC-REQ-009-01 | schema compatibility + persistence test | 缺失/null/正整数目录三态、旧 JSON 可读且无新迁移 |
| AC-REQ-009-02 | V-AC-REQ-009-02 | truth-table + runtime test | 动态配置拒绝目录字段，解析后只使用根目录 |
| AC-REQ-009-03 | V-AC-REQ-009-03 | admin API security test | 非系统管理员拒绝；仅公共/部门分组；团队/个人/文件及跨租户 ID 不可枚举或保存 |
| AC-REQ-009-04 | V-AC-REQ-009-04 | PermissionService integration | 加载/保存/运行时均以绑定用户检查 `upload_file`，管理员不短路，服务异常失败关闭 |
| AC-REQ-009-05 | V-AC-REQ-009-05 | tree visibility matrix | 深层权限只返回必要祖先和授权目录，祖先不可选、兄弟隐藏、根权限独立 |
| AC-REQ-009-06 | V-AC-REQ-009-06 | API cursor + component interaction test | 空间搜索、统一游标/无效游标 19814、目录懒加载、单选、展开不选中且无文件/目录操作 |
| AC-REQ-009-07 | V-AC-REQ-009-07 | save/rebind parameterized test | 类型、所属空间、租户、权限和用户换绑矩阵；失败 19813 且不写库 |
| AC-REQ-009-08 | V-AC-REQ-009-08 | stale/move/permission regression | 重命名/同空间移动继续有效；删除/错配 19903、权限丢失 19902、均无 fallback |
| AC-REQ-009-09 | V-AC-REQ-009-09 | service order + interaction test | 权限先于文件副作用，根/目录 `parent_id` 正确且 add_file 二次校验 |
| AC-REQ-009-10 | V-AC-REQ-009-10 | external response contract | 根目录与目录成功响应字段集合、类型和空间语义完全一致 |
| AC-REQ-009-11 | V-AC-REQ-009-11 | repository query-count + admin DTO/DOM test | 批量当前路径、根标识、失效稳定 ID，无路径快照和 N+1 |

## 错误契约 Error Contract

| 场景 | HTTP | 业务码 | 说明 |
|---|---:|---:|---|
| Token 路由白名单不允许统一路径 | 既有映射 | `19812` | 必须先于文件同步配置读取返回 |
| Token 文件同步配置 JSON 结构、类型或 enum 无效 | 422 | 现有请求校验 | 字段级 Pydantic 错误，不进入持久化 |
| Token 文件同步配置跨字段规则、固定引用或绑定用户目标权限校验失败 | 400 | `19813` | 新增 `developer_token_invalid_file_sync_rule`；保存失败不写库 |
| 目标树空间/目录游标无效 | 400 | `19814` | 新增 `developer_token_invalid_file_sync_target_cursor`；不回退首页 |
| Token 未配置文件同步业务 | 403 | `19906` | 新增 `filelib_sync_rule_missing` |
| 动态来源 ID 缺失、格式错误、名称与 ID 不一致 | 400 | `19901` | 复用 `filelib_sync_invalid_params` |
| 运行时绑定用户无最终根目录/目录上传权限 | 403 | `19902` | 复用 `filelib_sync_permission_denied`，不回退其他节点 |
| 分类、域、空间、目录、人员、部门或绑定不存在/失效/错配 | 404 | `19903` | 复用 `filelib_sync_not_found`，目录失效不回退空间根目录 |
| 多业务域或多目标空间歧义、重复文件 | 409 | `19904` | 复用 `filelib_sync_conflict` |
| multipart 缺失 | 422 | `19905` | 复用 `filelib_sync_multipart_invalid` |

业务错误响应继续走现有 Open Endpoints 异常映射；跨租户场景不得通过错误消息确认资源是否存在。

## 边界承诺 Boundary Commitments

| Area | Allowed Changes | Disallowed Changes | Change Requires |
|---|---|---|---|
| DeveloperToken | 在既有 `file_sync_rule` JSON 中增加可空 `folder_id`、按绑定用户过滤目标树、保存校验和结构化当前路径摘要 | 保存路径快照、多规则、草稿、把配置或管理员身份当权限 | 新用户需求与规格更新 |
| Open Endpoints | 单一路由、从 Token 规则解析根/目录目标、按最终节点复核权限、保留上传链路 | 兼容旧 URL、请求覆盖分类/目录、目录失效回退根目录、绕过权限 | 单独兼容方案评审 |
| Portal config | 只读当前租户分类/域及 `department_ids` | 新建映射表、复制映射、修改聚合配置 | 上游 Owner Feature 变更 |
| Knowledge | 通过领域 Service/Repository 读取空间、目录、祖先和当前路径，调用既有 `PermissionService` 与 `KnowledgeSpaceService.add_file()` | Endpoint 直查 ORM、修改空间归属/授权/文件所有权、把导航祖先当授权 | Knowledge Owner Feature |
| Frontend | 现有 Token 页拆分独立单选目标树和 hook，并增加结构化根/路径摘要 | 新 UI/state/request 库、文件选择/目录操作、单文件超 600 行 | 前端架构评审 |
| Migration | 复用既有可空 `JsonType` 列、无新迁移/回填；发布文档记录旧应用严格 schema 风险 | 为 `folder_id` 新增关系列、自动业务迁移、直接操作真实数据库 | 发布负责人单独批准 |

- Allowed dependencies: F044 Developer Token、F047 Filelib Sync、F060 DepartmentSpaceTargetResolver、现有 ShougangPortalConfigService、KnowledgeSpaceService、Knowledge 只读目录契约与 `PermissionService`。

## 风险与回退 Risks and Rollback

- 旧 URL 立即移除是明确不兼容变更；未及时切换的第三方会收到 404。缓解方式是上线前完成调用方、Token 配置和路由白名单清单核对。
- 已有 Token 默认无配置，统一接口会返回 403；这是防止错误推导业务规则的预期失败关闭行为。
- 配置引用会随资源删除或停用而失效；运行时二次校验并返回 404，管理员修复配置后恢复，不自动改写目标。
- 目录权限过滤需要同时构造必要祖先和隐藏无关兄弟；实现若先返回全树再前端过滤会泄露目录名称，必须在后端按绑定用户生成最小可见树，并用游标限制单次查询。
- 目录重命名或同空间移动后仍按稳定 ID 生效，管理摘要必须实时批量解析当前路径；若逐 Token 逐层查询会形成 N+1，需用批量路径查询和查询次数测试约束。
- 绑定用户权限撤销会使已保存配置在下一次调用失败，这是预期失败关闭；重新授权、换目标或清空配置后恢复，不自动回退空间根目录。
- 动态部门存在多业务域或多目标空间时明确冲突，可能使过去隐式选择成功的调用失败；不得用排序取第一条规避。
- 数据库 downgrade 删除 `file_sync_rule` 配置数据不可逆；此外，旧应用若对 JSON 使用 `extra=forbid`，即使保留列也可能无法读取含 `folder_id` 的规则。应用回退前必须导出并清空目录目标，或发布能够忽略/接受该字段的前向修复。
- macOS 不具备真实 DM8 驱动；本地只能做方言无关单元/迁移检查，真实 DM8 证据来自 Linux CI 或预发布环境。

## 澄清记录 Clarifications

- 固定目标：选择 `A`，可选择知识空间根目录或目录；动态目标始终落到解析空间根目录。
- 空间范围：选择 `A`，仅公共空间和部门空间；Token 管理沿用现有仅系统管理员可用的授权边界。
- 数据兼容：选择 `A`，在既有 JSON 配置中增加可空 `folder_id`；缺失/`null` 兼容为根目录，不新增迁移和回填。
- 权限主体：按照 Token 绑定用户过滤空间和目录；配置加载、保存、换绑和运行时均重新校验 `upload_file`。
- 深层权限：选择 `A`，只展示到授权目录所需的空间/祖先导航节点，祖先不可选择并隐藏无关兄弟。
- 交互：空间按名称搜索，目录按节点游标懒加载；展开不等于选择，根目录和目录均为单选目标。
- 引用生命周期：目录重命名或同空间移动继续按稳定 ID 有效；删除、跨空间错配或权限丢失失败关闭，不回退根目录。
- 展示与响应：Token 管理页展示当前完整路径；外部同步成功响应不增加目录字段。

## 需求质量门 Requirements Quality Gate

- [x] 每个 Requirement 使用稳定 `REQ-xxx` ID。
- [x] 每个 Acceptance Criterion 使用稳定 `AC-REQ-xxx-yy` ID。
- [x] 每个 Acceptance Criterion 均有验证方式和证据目标。
- [x] 固定/动态四种组合、动态来源缺失和无 fallback 已明确定义。
- [x] 多租户、路由白名单、上传权限和 ContextVar 生命周期已覆盖。
- [x] 固定根目录/目录、动态根目录、深层权限祖先、游标懒加载和换绑复核已明确定义。
- [x] 54 条 Acceptance Criteria 均有唯一 Verification ID 和证据目标。
- [x] 旧 URL、已有 Token、路由白名单、迁移与回退兼容边界已明确。
- [x] 非目标和停止点已明确；当前只更新 SDD 文档，不包含生产实现。
