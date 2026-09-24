# 设计说明 Design：Token 配置化统一文件同步接口

## 阅读摘要

- 复用 `developer_token.file_sync_rule` 可空 `JsonType` 列，在固定目标 JSON 中增加可空 `folder_id`；缺失/`null` 表示空间根目录，不新增迁移、配置表或草稿状态。
- 认证层新增 `DeveloperTokenPrincipal`，在不破坏其他 Open Endpoints 继续消费 `UserPayload` 的前提下，把本次 Token ID 和原始配置传给统一同步依赖。
- 文件同步服务删除 11 条静态规则，以 Token 配置为唯一规则输入；分类按编码固定，业务域和目标空间按各自模式解析，动态维度共用同一部门来源。
- 管理 API 以 Token 绑定用户为权限主体返回公共/部门空间目录树；保存和运行时再次校验最终节点，目录失效或权限丢失时失败关闭且不回退根目录。
- 本设计已按 T022-T031 实施并通过目录目标及生产组合路由聚焦自动化验证；未修改真实数据库或运行环境配置。

## 元信息 Metadata

- Feature ID: `066-token-configured-filelib-sync`
- Status: `folder-target implemented; manual release verification pending`
- Mode: `implementation`
- Created: `2026-07-22`
- Updated: `2026-08-03`
- Version: `v2.6.0`
- Requirements: [requirements.md](./requirements.md)
- Release Contract: [../release-contract.md](../release-contract.md)

## 设计目标 Design Goals

1. 用一个稳定路由和一个 Token 配置替代“URL 编号即业务规则”。
2. 确保配置只能缩小/确定业务选择，不能扩大 Token 绑定用户权限。
3. 让固定和动态四种组合都由同一解析管线处理，不复制上传流程。
4. 保持 MySQL/DM8、多租户、DDD 分层和现有 Open Endpoints 响应约定。
5. 让已有 Token、其他 Token API 和既有知识上传行为在未配置时保持安全、可预测。
6. 让固定目标可精确落到空间根目录或目录，同时不改变动态目标根目录语义和外部同步响应。
7. 让目标树只暴露绑定用户可上传节点及必要导航祖先，不因系统管理员配置入口扩大可见性或权限。

## 架构与调用链 Architecture

```mermaid
flowchart LR
    C["第三方调用方"] --> R["POST /api/v2/filelib/file/sync"]
    R --> A["DeveloperTokenPrincipal dependency"]
    A --> A1["Token / tenant / user"]
    A1 --> A2["IP -> route allowlist -> rate limit"]
    A2 --> P["FilelibSyncService"]
    P --> P1["校验 Token file_sync_rule"]
    P1 --> P2["解析 params 与动态部门"]
    P2 --> P3["解析固定分类 / 业务域 / 目标空间与目录"]
    P3 --> P4["校验域-空间绑定与最终节点权限"]
    P4 --> P5["add_file(parent_id)、编码、持久化、异步入队"]
```

管理链路继续遵守项目分层：

```text
DeveloperToken Router
  -> Endpoint
  -> DeveloperTokenService
  -> DeveloperTokenRepository / 既有领域 Service
  -> DB
```

- Endpoint 不直接导入 ORM 模型或查询数据库。
- DeveloperTokenService 通过 `ShougangPortalConfigService` 读取分类/业务域，通过 Knowledge 领域公开 Service/Repository 读取空间、目录、祖先与当前路径，并通过 `PermissionService` 按绑定用户过滤；不跨模块导入 API 层。
- FilelibSyncService 继续通过 `FilelibSyncRepository`、`KnowledgeSpaceService` 和 `DepartmentSpaceTargetResolver` 完成业务，不新增 DAO 旁路。

## 配置数据模型 Configuration Model

### 持久化结构

`DeveloperToken.file_sync_rule` 使用以下严格 JSON 结构；字段名和值是 API 与数据库共同契约：

```json
{
  "category": {
    "code": "POLICY",
    "subcategory_code": "MGMT_POLICY"
  },
  "business_domain": {
    "mode": "fixed",
    "code": "SAFETY"
  },
  "target_space": {
    "mode": "fixed",
    "knowledge_id": 118,
    "folder_id": 4096
  },
  "dynamic_source": null
}
```

Pydantic 值对象设计：

```text
DeveloperTokenFileSyncRule
├── category: FileSyncCategoryRule
│   ├── code: str
│   └── subcategory_code: str
├── business_domain: FileSyncBusinessDomainRule
│   ├── mode: "fixed" | "dynamic"
│   └── code: str | null
├── target_space: FileSyncTargetSpaceRule
│   ├── mode: "fixed" | "dynamic"
│   ├── knowledge_id: int | null
│   └── folder_id: int | null
└── dynamic_source: "department_id" | "responsible_person_id" | null
```

所有配置 schema 使用 `extra="forbid"`，编码在保存时 `strip().upper()`，空字符串归一为 `None`。一级分类沿用 `[A-Z0-9_]{1,16}`，二级分类沿用 `[A-Z0-9_-]{1,16}`，业务域复用 `normalize_business_domain_code()`，`knowledge_id`/`folder_id` 非空时必须为正整数。Token 不保存分类、域、空间/目录展示名称或路径快照，也不保存部门到业务域映射，避免名称漂移和第二事实源。

旧 JSON 没有 `folder_id` 时由 schema 默认 `None`，语义等同空间根目录；数据库列和持久化类型均不变化。动态目标必须同时清空 `knowledge_id` 与 `folder_id`。

### 模式真值表

| 业务域模式 | 目标空间模式 | 必填固定值 | `dynamic_source` | 运行时必填 ID |
|---|---|---|---|---|
| fixed | fixed | `business_domain.code`、`target_space.knowledge_id`；`folder_id` 可空 | 必须为空 | 无；其他身份字段按既有元数据默认规则处理 |
| fixed | dynamic | `business_domain.code` | 必填 | 配置选中的一个 ID |
| dynamic | fixed | `target_space.knowledge_id`；`folder_id` 可空 | 必填 | 配置选中的一个 ID |
| dynamic | dynamic | 无固定域/空间值 | 必填 | 配置选中的一个 ID，两个动态维度共用 |

约束：

- 固定模式缺少 `knowledge_id` 拒绝；`folder_id` 可空，非空时必须为所选空间内目录。动态模式携带 `knowledge_id` 或 `folder_id` 拒绝。
- 两个维度均固定时携带 `dynamic_source` 拒绝。
- 任一维度动态时不接受空动态来源，不接受两个来源并存或运行时互相回退。
- 分类永远没有 dynamic 模式。

### 选择单列 JSON 而非新表

- 每个 Token 只有 0 或 1 个体积很小的配置，不需要独立分页、搜索、并发编辑或生命周期。
- 规则总是随 Token 创建/更新原子保存，与现有 `route_whitelist: JsonType` 模式一致。
- 严格 Pydantic schema 和 Service 事实源校验可以控制结构，数据库只负责持久化。
- 如果未来出现多规则、版本、审批或按字段查询需求，需新 Feature 迁移为独立实体；F066 不预建抽象。

## 管理 API 设计 Admin API

### 现有接口扩展

| API | 变化 |
|---|---|
| `POST /api/v1/admin/developer-tokens` | `DeveloperTokenCreate` 增加 `file_sync_rule: DeveloperTokenFileSyncRule | None = None` |
| `PUT /api/v1/admin/developer-tokens/{token_id}` | `DeveloperTokenUpdate` 增加同名可选字段；字段未提交表示不修改，显式 `null` 表示关闭并清空 |
| `GET /api/v1/admin/developer-tokens` | 每行返回非敏感 `file_sync_rule` 和批量解析的 `file_sync_target_display`，供前端生成当前根/路径摘要 |
| `GET /api/v1/admin/developer-tokens/{token_id}` | 返回完整结构化配置或 `null`，以及结构化当前目标展示信息 |

列表不返回服务端拼接的本地化字符串。后端批量解析稳定 ID 的当前事实，返回结构化 DTO：

```text
FileSyncTargetDisplay
├── knowledge_id: int
├── knowledge_name: str | null
├── target_type: "root" | "folder"
├── folder_id: int | null
├── folder_path: list[{id: int, name: str}]
└── stale: bool
```

前端按 DTO 和 mode 生成本地化摘要：

```text
POLICY/MGMT_POLICY · 业务域: SAFETY · 目标: 安全环保部/制度/管理办法
```

Repository/Knowledge 只读契约必须对列表中的空间和目录 ID 批量取数并批量构造路径，禁止逐 Token/逐层查询。路径只用于当前响应，不回写 JSON。若引用失效，DTO 保留稳定 ID、`stale=true`，不得映射成其他当前选项。

### 配置选项接口

新增：

```http
GET /api/v1/admin/developer-tokens/config/file-sync-options
  ?tenant_id={tenant_id}
  &user_id={bound_user_id}
  &space_cursor={optional}
  &space_page_size=50
  &space_keyword={optional}
```

响应：

```json
{
  "tenant_id": 1,
  "categories": [
    {
      "code": "POLICY",
      "label": "政策制度",
      "children": [{"code": "MGMT_POLICY", "label": "管理政策"}]
    }
  ],
  "business_domains": [{"code": "SAFETY", "name": "安全"}],
  "target_space_groups": {
    "data": [
      {
        "space_type": "department",
        "label_key": "developerToken.fileSync.departmentSpaces",
        "spaces": [
          {
            "id": 118,
            "name": "安全环保部-部门库",
            "selectable": false,
            "has_children": true
          }
        ]
      }
    ],
    "has_more": false,
    "next_cursor": null,
    "page_size": 50
  }
}
```

目录子节点使用独立懒加载接口：

```http
GET /api/v1/admin/developer-tokens/config/file-sync-target-children
  ?tenant_id={tenant_id}
  &user_id={bound_user_id}
  &knowledge_id={knowledge_id}
  &parent_id={optional_folder_id}
  &cursor={optional}
  &page_size=50
```

响应只返回目录，使用无 `total` 的游标契约：

```json
{
  "data": [
    {
      "id": 4096,
      "name": "管理办法",
      "selectable": true,
      "navigation_only": false,
      "has_children": false
    }
  ],
  "has_more": false,
  "next_cursor": null,
  "page_size": 50
}
```

约束：

1. 先复用 `_assert_admin_scope()` 校验 operator 是否能管理 `tenant_id`。
2. 在受控租户上下文内调用既有门户配置与 Knowledge 领域读取能力，并在 `finally` 恢复上下文。
3. 分类只返回编码合法且父子关系有效的项；业务域只返回 `enabled=true` 且编码合法的项。
4. `user_id` 必须是本次创建/编辑 Token 的绑定用户且属于目标租户；目标选项的权限主体始终是该用户，不能复用管理员 operator 触发 `super_admin`/tenant admin 短路。
5. 空间仅返回公共/部门类型，按类型分组；根目录 `selectable` 只取决于绑定用户对 `knowledge_space:{id}` 的 `upload_file`，存在授权后代时空间仍可作为不可选导航节点返回。
6. 目录使用 `PermissionService.list_accessible_ids(user_id, "upload_file", "folder", bound_user_payload)` 批量取得授权集合，再通过 Knowledge 领域只读契约加载当前有效目录、必要祖先和后代存在性；仅返回授权目录及必要祖先，祖先 `navigation_only=true`、`selectable=false`，无关兄弟和文件不进入响应。
7. 空间名称支持参数化关键词搜索；空间和目录均使用 `common/cursor.py` 的 v1 base64url 稳定游标、`has_more/next_cursor` 且不返回 `total`，`1 <= page_size <= 200`。游标解析失败映射 `DeveloperTokenInvalidFileSyncTargetCursorError(19814)`/400，不得静默回到首页；目录不做全局关键词搜索，只按展开节点懒加载。
8. `PermissionService` 返回 `None` 代表该权限主体具有不受限访问时，仍需完成租户、空间类型和资源有效性过滤；权限服务异常按失败关闭处理，不返回未过滤树。
9. Endpoint 必须放在 `/{token_id}` 动态路由之前；使用 `/config/...` 避免路径歧义。管理入口继续复用现有仅系统管理员可用的授权边界。
10. 目标租户尚无门户聚合配置时返回 `19813` 并提示先完成门户分类/业务域配置，不返回伪造默认分类或业务域。

管理接口成功响应继续走项目 `resp_200` envelope，失败继续走既有 `BaseErrorCode` 映射；不为 F066 创建第二套响应格式。外部同步接口沿用 F047 的 HTTP/业务码组合，限流沿用 F044 的 Token 级配置和既有 endpoint key。

### 保存校验顺序

```text
解析 Token 目标绑定租户
  -> 校验管理员租户范围
  -> schema 真值表校验并规范化
  -> 读取该租户门户聚合配置
  -> 校验分类 code + subcategory_code 父子关系
  -> 固定域：校验 enabled 域 code
  -> 固定空间：校验公共/部门类型、存在、租户、状态
  -> 固定目录（非空）：校验 DIR、存在、租户、所属空间
  -> 以 Token 绑定用户校验最终根/目录 `upload_file`
  -> 两者固定：校验 domain.space_ids 与 space.business_domain_codes 双向一致
  -> 与 Token 其他字段一起保存和审计
```

更新 Token 绑定用户时，Service 先解析目标租户和新绑定用户，再用该用户校验最终规则：

- payload 显式提交 `file_sync_rule`：校验提交值；
- payload 未提交规则：校验现有规则，包括同租户换绑后的最终节点权限；
- payload 显式提交 `null`：允许清空后换绑；
- 失败时整次更新不持久化。

基础 JSON 结构、字段类型、enum 和 `extra="forbid"` 由 FastAPI/Pydantic 统一返回 422；通过结构校验后的模式真值表、固定引用、租户、绑定用户权限和域-空间绑定错误由 Service 转换为 `DeveloperTokenInvalidFileSyncRuleError(19813)`/400，事务不得写入部分更新。用户消息可描述本租户字段和原因，但不得暴露跨租户资源信息。

## 认证上下文设计 Authentication Context

### 问题

现有 `DeveloperTokenService.authenticate()` 查到了完整 Token，却只返回 `UserPayload`。把 Token ID 或业务规则塞进请求参数会允许伪造；再次按 Header 查询则重复哈希、查询和认证状态，且容易与首次认证产生时序差异。

### 方案

新增不可变认证结果：

```text
DeveloperTokenPrincipal
├── token_id: int
├── tenant_id: int
├── user: UserPayload
└── raw_file_sync_rule: dict | None
```

认证依赖拆分为：

```python
async def get_developer_token_principal(...) -> AsyncGenerator[DeveloperTokenPrincipal, None]: ...

async def get_developer_token_user(
    principal: DeveloperTokenPrincipal = Depends(get_developer_token_principal),
) -> UserPayload:
    return principal.user
```

- 新 `DeveloperTokenService.authenticate_principal()` 复用现有认证逻辑，在完成 IP、路由白名单和限流后构造 principal。
- 现有 `authenticate()` 保留为兼容包装，继续返回 `UserPayload`，避免直接调用方和测试无关破坏。
- 其他 Open Endpoints 仍依赖 `get_developer_token_user`，行为不变。
- Filelib 同步依赖消费 principal；先确认配置存在，再用严格 schema 解析。数据库异常结构只使统一同步失败并记录 token ID，不影响该 Token 调用其他 API。
- principal 只携带非秘密 Token ID 和配置，不携带明文、密文或哈希。
- ContextVar token 由 generator dependency 在 `finally` 中统一 reset，覆盖成功、业务异常、取消和下游依赖失败。

### 安全控制顺序

保持以下顺序，不允许因配置缺失提前短路：

```text
19801 missing token
  -> 19802 invalid token / invalid tenant or user
  -> 19803 disabled
  -> 19804 IP forbidden
  -> 19812 route forbidden
  -> 19805/19806 rate limit
  -> 19906 file_sync_rule missing
  -> file sync params/resource/permission errors
```

这保证路由白名单仍是业务入口前的安全边界。限流与路由的现有相对顺序以代码为准并由回归测试锁定；F066 只要求配置检查发生在两者之后。

## 统一同步 API 与运行时解析 Unified Sync Runtime

### 路由

`open_endpoints/api/endpoints/filelib_sync.py` 最终只保留：

```python
@router.post("/file/sync")
async def sync_file(...): ...
```

删除 `_sync_file(endpoint_code, ...)`、11 个编号 handler 和 `FILELIB_SYNC_RULES`。Endpoint 继续处理 multipart 缺失到 `19905` 的现有映射，把 principal 中的 Token ID/规则交给 `FilelibSyncService`。

生产 `router_rpc` 必须先注册静态 `filelib_sync_router_rpc`，再注册包含 `POST /file/{knowledge_id}` 的 `filelib_router_rpc`。FastAPI/Starlette 按注册顺序匹配同方法路径；静态路由优先可在不修改两个既有 URL 和非法动态路径历史响应的前提下，避免把 `sync` 当成 `knowledge_id`。备选方案是在动态路径声明中增加 `:int` converter，但会把既有非整数路径响应从 422 改为 404，本次最小 bugfix 不采用。

### 解析顺序

```text
1. 严格解析 file_sync_rule；缺失/损坏 -> 19906
2. 解析 params JSON、file_name、external_file_id、文件非空
3. 若存在动态维度，先校验配置指定的 ID 显式存在
4. 解析调用人、责任人、主责单位及 ID/名称一致性，用于动态部门和文件元数据
5. 读取当前租户 ShougangPortalAdminConfig
6. 按 category.code + subcategory_code 解析固定分类
7. 按 business_domain.mode 解析固定或动态域
8. 按 target_space.mode 解析固定根/目录目标或动态根目录空间
9. 校验最终域与空间双向绑定
10. 按 Token 绑定用户校验最终根/目录节点 `upload_file`
11. 执行既有保存、编码、更新、清理和异步入队流程
```

所有业务选择和权限在保存临时文件前完成，避免配置错误产生对象存储副作用。

### 动态部门解析

```text
dynamic_source=department_id
  -> params.department_id 必须显式存在
  -> 当前租户查 Department
  -> selected_department

dynamic_source=responsible_person_id
  -> params.responsible_person_id 必须显式存在
  -> 当前租户查 User
  -> 查唯一 is_primary=1 UserDepartment
  -> selected_department
```

- 缺失指定 ID 返回 `19901`；不得使用调用人默认值或另一个 ID。
- ID 对应对象不存在/不可见返回 `19903`；跨租户使用同样脱敏结果。
- 名称与 ID 同时提供时继续做现有一致性校验。
- 非动态选择字段继续按现有规则补齐文件元数据：责任人默认调用人，主责单位默认调用人主部门。

### 固定分类解析

- 从当前租户门户配置 `portal.document_types` 中按规范化 `category.code` 精确查找。
- 只在该父分类 `children` 中按 `subcategory_code` 查找，不能全局搜索同名子分类。
- 不按 label 识别，不接受请求覆盖；不存在或编码无效返回 `19903`。

### 业务域解析

固定模式：

- 按规范化 code 在当前租户 `portal.domains` 查找唯一 `enabled` 项。
- 零项返回 `19903`；重复 code 视为配置歧义返回 `19904`，不取第一项。

动态模式：

- 使用选定部门 ID 在 `enabled` 域的 `department_ids` 中精确匹配。
- 不读取次要部门，不从部门名称匹配，不向父/子部门继承。
- 零项返回 `19903`；多项返回 `19904`。
- `domains[].department_ids` 始终由门户聚合配置拥有；Token 不保存映射快照。

### 目标知识空间解析

固定模式：

- 按 `knowledge_id` 查询当前租户有效 Knowledge。
- 只允许公共/部门空间；不按名称回退，不允许跨租户或逻辑删除资源。
- `folder_id` 缺失/`null` 解析为 `ResolvedFileSyncTarget(space, folder_id=None)`。
- `folder_id` 非空时读取当前目录，校验 `DIR`、当前有效、同租户且 `knowledge_id` 与所选空间一致，解析为 `ResolvedFileSyncTarget(space, folder_id)`。
- 目录重命名或在同一空间内移动不改变稳定 ID；目录删除、跨空间错配或类型变化返回 `19903`，不回退空间根目录。

动态模式：

- 从选定部门构造由近到远的部门链，调用 F060 `DepartmentSpaceTargetResolver.resolve()`。
- 解析器现有确定性规则保持不变：当前层唯一优先候选成功，无候选才向父级继续，同级多候选抛 `DepartmentKnowledgeSpaceAmbiguousError`。
- `None` 映射 `19903`；歧义映射 `19904`，且上传副作用为零。
- 动态模式 schema 保证 `knowledge_id=None`、`folder_id=None`；解析结果始终为 `ResolvedFileSyncTarget(space, folder_id=None)`，请求参数不得注入目录。

### 域与空间绑定

最终结果必须同时满足：

```text
space.id in domain.space_ids
AND
normalize(domain.code) in normalize(space.business_domain_codes)
```

任一侧缺失均返回 `19903`，不自动修复绑定。即使固定-固定在保存时已校验，运行时仍重新校验以发现资源变更。

### 权限、上传和元数据

- 在创建临时文件或正式持久化前，以 principal.user 对最终节点执行显式权限预检：根目录检查 `knowledge_space:{space.id}#upload_file`，目录检查 `folder:{folder_id}#upload_file`；无权限映射 `19902`。
- 调用现有 `KnowledgeSpaceService.add_file()` 时传入同一 principal.user，由其再次执行既有权限检查；根目录使用 `parent_id=None`，目录使用 `parent_id=folder_id`，继续传 `skip_approval=True`、`enqueue_processing=False`。
- 配置只决定目标，不写 OpenFGA tuple、不调用 `PermissionService.authorize()`，也不从祖先可见性推导目标权限。
- 继续先生成固定编码、持久化 KnowledgeFile，再调用一次 `enqueue_file_processing()`。
- 继续使用现有 duplicate 冲突与失败清理逻辑，不扩大本 Feature 的事务边界。
- `user_metadata` 保留既有字段，并调整来源审计：

```json
{
  "external_file_id": "...",
  "department": "...",
  "department_id": 1024,
  "responsible_person": "...",
  "responsible_person_id": 12,
  "filelib_sync_endpoint": "sync"
}
```

Token ID 只用于受控服务端日志和 Developer Token 审计，不写入 KnowledgeFile 用户元数据。日志可使用 `token_id`、`file_id`、`knowledge_id`、`folder_id`、`user_id` 和请求上下文；不得输出 Header、Token 明文、密文、哈希、完整配置 JSON 或未经授权的目录路径。

无论目标是空间根目录还是目录，外部成功响应继续返回空间级 `knowledge_id`/`knowledge_name`，不增加目录字段；目录路径仅存在于受管理员权限保护的 Token 管理 DTO。

## 安全设计 Security

| Trust Boundary | Control |
|---|---|
| 第三方 -> 统一同步 API | `X-Developer-Token` 认证、IP 白名单、route whitelist、Token 限流；Header 不进入响应、文件元数据或业务日志 |
| multipart/params -> 业务服务 | `params` 继续使用有长度/正整数约束的 Pydantic schema；未知字段保持既有忽略语义，但任何分类/域/空间覆盖字段均不被读取 |
| 文件名/文件 -> 对象存储 | `file_name` 必须是 base name，拒绝 `/` 和 `\\`；非空检查后继续经过现有 Knowledge 上传权限、敏感词、用户/租户容量和文件处理策略，不新增绕过路径或扩大格式范围 |
| Admin UI/API -> Token 配置 | 既有系统管理员授权 + tenant scope；目标选项另以 Token 绑定用户过滤；严格 `extra="forbid"` schema；未知字段、跨租户 ID、无权节点和失效引用均拒绝 |
| Token 配置 -> Portal/Knowledge | 只通过参数化 ORM、Repository 和既有 Service 读取；配置选择不授权，加载/保存/运行时均按绑定用户校验，`add_file` 再次授权 |
| 服务端 -> 浏览器/日志 | React 以文本节点渲染名称/code，不使用 `dangerouslySetInnerHTML`；跨租户错误脱敏；Token secret、完整配置和内部异常栈不输出 |

- Admin 新接口复用现有登录依赖、管理 API 安全中间件和响应处理，不创建匿名或仅靠前端隐藏的入口。
- 外部同步继续使用 F044 rate limiter；配置缺失和业务错误请求同样已经消耗本次认证/限流配额，不能用失败请求绕过限流。
- 固定目标树不能作为 IDOR/目录枚举通道：后端只返回绑定用户授权目录及必要祖先，必要祖先不可选，隐藏无关兄弟；客户端过滤不作为安全控制。
- 保存时同时校验管理员范围和绑定用户权限，运行时按当前 Token 租户重新读取并对绑定用户授权；跨租户不存在与无权场景使用脱敏错误。
- 自动化安全矩阵覆盖 missing/invalid/disabled Token、IP、19812、rate limit、跨租户人员/部门/域/空间/目录、团队/个人空间、深层目录祖先、配置额外字段、路径穿越文件名、权限撤销和 secret 日志扫描。

## 前端设计 Frontend

### 组件拆分

当前 `DeveloperToken.tsx` 为 572 行，不能直接继续堆叠目录树状态和请求。实施时拆分：

```text
DeveloperToken.tsx
├── DeveloperTokenFileSyncRule.tsx
│   ├── 启用/关闭
│   ├── 分类父子选择
│   ├── 业务域 fixed/dynamic
│   ├── 目标 fixed/dynamic
│   └── dynamic_source 条件选择
├── DeveloperTokenFileSyncTargetTree.tsx
│   ├── 公共/部门空间分组与空间名称搜索
│   ├── 根目录/目录单选与导航祖先状态
│   └── 目录游标懒加载
├── useDeveloperTokenFileSyncTargetOptions.ts
│   ├── options/children 请求
│   ├── 节点级 loading/error/cursor
│   └── 租户/绑定用户切换取消与失效处理
├── DeveloperTokenRouteAllowlist.tsx
└── developerTokenFileSyncRuleValidation.ts
    ├── normalizeFileSyncRule
    ├── findInvalidFileSyncRule
    └── formatFileSyncRuleSummary
```

规则组件使用受控 value/onChange；独立 target hook 通过现有 Developer Token controller 请求受保护的 options/children API，树组件只消费 hook 结果，不直接导入 request。租户或绑定用户变化时取消/忽略陈旧响应并清理无效选择。

### 交互规则

1. 默认关闭，提交 `file_sync_rule: null`。
2. 开启后先选父分类，再选该父项下子分类；父分类变化清空子分类。
3. 切换业务域到 fixed 时要求选择域；切换到 dynamic 时清空固定 code。
4. 切换目标到 fixed 时要求选择空间根目录或目录；切换到 dynamic 时同时清空 `knowledge_id`/`folder_id`。
5. 任一动态时显示动态来源；两个都固定时清空并隐藏。
6. 切换 Token 绑定租户或用户后清空旧 options、目录缓存和无效选择，重新加载；不保留跨租户或新用户无权值。
7. 前端只做即时体验校验，后端始终重新校验。
8. 空间节点展开只加载子目录，不触发选择；根/目录单选，导航祖先不可选，节点分页继续使用返回游标。
9. 空间关键词只过滤空间名称；不提供全局目录搜索、文件节点、目录创建/移动/重命名。
10. 列表/编辑摘要消费同一列表/详情响应中的结构化当前路径，不发起逐行请求；失效时展示稳定 ID 和明确警告。

### API 与国际化

- 扩展 `src/frontend/platform/src/controllers/API/developerToken.ts` 的规则、展示 DTO、options/children 游标类型和请求，继续使用 `@/controllers/request.ts` wrapper。
- 更新 `zh-Hans`、`en-US`、`ja` 的 `bs.json` 中现有 Developer Token namespace 同名 key；`dev` 目录当前没有 Developer Token namespace，不为本 Feature 新建一套伪翻译来源。
- 不引入新 UI、表单、状态管理或请求库。

## 数据库兼容 Database Compatibility

- 本次目录目标只扩展既有 `file_sync_rule` JSON schema，不新增 Alembic revision、不改列类型、不做 UPDATE/JSON 转换或 backfill；MySQL/DM8 均继续由既有 `JsonType` 负责持久化。
- 已有规则缺失 `folder_id` 时 schema 默认 `None`，继续上传空间根目录；新保存的根目录规则可规范化为 `folder_id: null`。
- 数据库 downgrade 风险仍沿用初版 F066：若删除整个 `file_sync_rule` 列会丢失全部规则。但本次更重要的应用回退风险是旧版本 `extra=forbid` schema 可能拒绝含 `folder_id` 的 JSON。
- 应用回退前必须导出非秘密规则并清空/转换目录目标，或先部署接受/忽略 `folder_id` 的 forward fix；不得以“数据库列可空”为由声称旧应用兼容。

## 发布、切换与回退 Rollout

### 上线前清单

1. 盘点仍调用 11 个旧 URL 的调用方和对应 Token。
2. 为每个需同步的 Token 手工录入分类、域/目标模式和动态来源；固定目标按绑定用户权限选择空间根目录或目录。
3. 手工把精确路由白名单替换为 `POST /api/v2/filelib/file/sync`；PREFIX 规则也需人工确认覆盖范围。
4. 在预发布使用实际 Token 验证四种模式、固定根目录/目录、动态根目录、权限撤销和文件解析。
5. 同步发布新版接口文档和切换时间。

### 发布顺序

```text
部署支持 folder_id 的后端与 Platform（无新 DB migration）
  -> 管理员配置 Token / whitelist
  -> 调用方切换统一 URL
  -> 核对 404、19812、19906、19903/19904 指标
```

因为产品决定旧 URL 立即移除，配置和调用方切换必须在同一发布窗口内完成；不设计双路由阶段。

### 回退

- 回退目标应用若使用 `extra=forbid`，不会自动忽略 JSON 中的 `folder_id`；先扫描并导出含目录目标的 Token ID/规则，不导出 Token secret。
- 路径 A：把目录目标人工改为空间根目录或清空规则，再回退旧应用；这会改变上传位置，必须获得业务确认。
- 路径 B：保持新应用并发布接受/忽略 `folder_id` 的 forward fix，再进行后续回退；这是生产默认推荐路径。
- 本次没有新 migration 可 downgrade。若同时回退初版 F066 并删除整个列，仍会永久丢失所有 Token 文件同步配置，且调用方/白名单需人工切回旧 URL。

## 文件结构计划 File Structure Plan

下表保留初版 F066 的累计落点作为审计基线；其中 migration 和旧路由收口已经完成，本次目录目标增量不重复创建 migration。

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `features/v2.6.0/release-contract.md` | modify | 登记扩展所有权、依赖、不变量和 199 模块 | REQ-002..REQ-005, REQ-008 |
| `features/v2.6.0/066-token-configured-filelib-sync/{requirements,design,spec,tasks,verification}.md` | modify | F066 需求、设计、任务、验证与评审入口 | REQ-001..REQ-009 |
| `src/backend/bisheng/api/router.py` | modify | 统一同步静态路由先于旧知识库动态上传路由注册，消除生产路由遮蔽 | REQ-001 |
| `src/backend/bisheng/core/database/alembic/versions/<new-revision>.py` | create | 增加可空 JsonType 配置列 | REQ-008 |
| `src/backend/bisheng/developer_token/domain/models/developer_token.py` | modify | 映射 `file_sync_rule` | REQ-002, REQ-008 |
| `src/backend/bisheng/developer_token/domain/schemas/developer_token.py` | modify | 严格规则、principal、options、读写 schema | REQ-002, REQ-003, REQ-005 |
| `src/backend/bisheng/developer_token/domain/schemas/__init__.py` | modify | 导出新增 schema | REQ-002, REQ-005 |
| `src/backend/bisheng/developer_token/domain/services/developer_token_service.py` | modify | 保存/租户校验、options、principal、审计 | REQ-002, REQ-003, REQ-005 |
| `src/backend/bisheng/developer_token/api/dependencies.py` | modify | principal generator 与兼容 user dependency | REQ-005 |
| `src/backend/bisheng/developer_token/api/endpoints/developer_token.py` | modify | options endpoint 与 payload 扩展 | REQ-003, REQ-007 |
| `src/backend/bisheng/common/errcode/developer_token.py` | modify | 初版增加 19813；目录目标增量增加无效游标 19814 | REQ-002, REQ-003, REQ-009 |
| `src/backend/bisheng/common/errcode/filelib_sync.py` | modify | 增加 19906 | REQ-005 |
| `src/backend/bisheng/open_endpoints/api/dependencies.py` | modify | Filelib service 注入 principal/rule/token ID | REQ-005, REQ-006 |
| `src/backend/bisheng/open_endpoints/api/endpoints/filelib_sync.py` | modify | 单一路由并移除 11 个 handler | REQ-001 |
| `src/backend/bisheng/open_endpoints/domain/schemas/filelib_sync.py` | modify | 删除静态规则表/旧策略，保留请求响应值对象 | REQ-001, REQ-004 |
| `src/backend/bisheng/open_endpoints/domain/services/filelib_sync_service.py` | modify | Token 规则解析、固定/动态矩阵与既有上传编排 | REQ-003..REQ-006 |
| `src/backend/bisheng/open_endpoints/domain/repositories/interfaces/filelib_sync_repository.py` | modify | 删除按名称固定域/空间所需的旧查询，补齐租户内有效责任人和全部主部门关系读取契约 | REQ-004, REQ-005 |
| `src/backend/bisheng/open_endpoints/domain/repositories/implementations/filelib_sync_repository_impl.py` | modify | 通过现有租户隔离/用户租户关系校验责任人，返回完整主部门集合供 Service 检测零/多结果，并移除按名称取第一条逻辑 | REQ-004, REQ-005 |
| `src/backend/test/developer_token/test_developer_token_file_sync_rule.py` | create | 配置真值表、选项、保存/换租户校验 | REQ-002, REQ-003 |
| `src/backend/test/developer_token/test_developer_token_dependency.py` | modify | principal、优先级和 ContextVar 生命周期 | REQ-005 |
| `src/backend/test/developer_token/test_developer_token_migration.py` | create | JsonType 迁移与无 backfill | REQ-008 |
| `src/backend/test/open_endpoints/test_filelib_sync.py` | modify | 统一路由、四组合、权限和上传回归 | REQ-001, REQ-004..REQ-006 |
| `src/frontend/platform/src/controllers/API/developerToken.ts` | modify | 规则/options 类型和请求 | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperToken.tsx` | modify | 集成子组件、加载 options、列表摘要 | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenFileSyncRule.tsx` | create | 文件同步业务配置表单 | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenGlobalSettings.tsx` | create | 拆出既有全局设置以满足主页面行数门禁 | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenTable.tsx` | create | 拆出列表并展示本地化规则摘要 | REQ-007 |
| `src/frontend/platform/src/pages/SystemPage/components/developerTokenFileSyncRuleValidation.ts` | create | 规范化、校验和摘要 | REQ-002, REQ-007 |
| `src/frontend/platform/src/components/bs-comp/selectComponent/DepartmentUsersSelect.tsx` | modify | 从组织树挂载关系附带目标租户提示，仅用于 options 请求 | REQ-007 |
| `src/frontend/platform/src/test/developerTokenFileSyncRuleValidation.test.ts` | create | 模式真值表、规范化和摘要 | REQ-007 |
| `src/frontend/platform/src/test/DeveloperTokenFileSyncRule.test.tsx` | create | 模式联动、选项失效和租户切换 | REQ-007 |
| `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` | modify | 同步 Developer Token 国际化文案 | REQ-007 |
| `docs/api/filelib-file-sync.md` | create | 新的统一接口权威文档、配置前置与迁移说明 | REQ-001, REQ-008 |
| `docs/api/filelib-file-sync-split.md` | modify | 改为不含旧 URL 的迁移提示并链接统一文档，保留历史规格引用路径 | REQ-001, REQ-008 |

Repository 变更只收紧本同步链路的确定性和租户语义；不新增通用 DAO 入口，不修改其他业务模块的用户或部门读取行为。

### 本次目录目标增量落点

| Path | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| `src/backend/bisheng/developer_token/domain/schemas/developer_token.py` | modify | `folder_id`、目标树/游标、结构化展示 DTO | REQ-002, REQ-007, REQ-009 |
| `src/backend/bisheng/developer_token/domain/services/developer_token_service.py` | modify | 绑定用户权限主体、保存复核、树编排、批量当前路径摘要 | REQ-003, REQ-005, REQ-009 |
| `src/backend/bisheng/developer_token/domain/repositories/interfaces/developer_token_repository.py` | modify | 批量读取列表目标 ID，避免摘要 N+1 | REQ-007, REQ-009 |
| `src/backend/bisheng/developer_token/domain/repositories/implementations/developer_token_repository_impl.py` | modify | 实现批量目标关联读取 | REQ-007, REQ-009 |
| `src/backend/bisheng/developer_token/api/endpoints/developer_token.py` | modify | options 增加绑定用户，新增目录 children 游标 endpoint 和 19814 映射 | REQ-003, REQ-007, REQ-009 |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | modify | 提供空间/目录/必要祖先/当前路径的领域只读契约，保留 `add_file` 权限语义 | REQ-005, REQ-009 |
| `src/backend/bisheng/knowledge/domain/repositories/interfaces/knowledge_repository.py` | modify | 定义批量目录、祖先、路径和游标读取接口 | REQ-003, REQ-009 |
| `src/backend/bisheng/knowledge/domain/repositories/implementations/knowledge_repository_impl.py` | modify | 参数化实现最小可见树和批量当前路径读取 | REQ-003, REQ-009 |
| `src/backend/bisheng/open_endpoints/domain/services/filelib_sync_service.py` | modify | 解析 `ResolvedFileSyncTarget`、最终节点权限和 `add_file(parent_id)` | REQ-005, REQ-006, REQ-009 |
| `src/backend/test/developer_token/test_developer_token_file_sync_rule.py` | modify | 旧 JSON、目录真值表、换绑复核 | REQ-002, REQ-009 |
| `src/backend/test/developer_token/test_developer_token_file_sync_options.py` | modify | 空间分组、深层祖先、游标、安全和摘要查询次数 | REQ-003, REQ-007, REQ-009 |
| `src/backend/test/open_endpoints/test_filelib_sync_token_rule.py` | modify | 固定根/目录、动态根、失效/权限和响应回归 | REQ-005, REQ-006, REQ-009 |
| `src/frontend/platform/src/controllers/API/developerToken.ts` | modify | 目标规则、display、options/children 游标类型和请求 | REQ-007, REQ-009 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenFileSyncRule.tsx` | modify | 集成固定目标树并保持模式联动 | REQ-007, REQ-009 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenFileSyncTargetTree.tsx` | create | 公共/部门空间分组、根/目录单选和导航祖先 UI | REQ-007, REQ-009 |
| `src/frontend/platform/src/pages/SystemPage/components/useDeveloperTokenFileSyncTargetOptions.ts` | create | 空间搜索、目录游标懒加载、切换取消与缓存 | REQ-007, REQ-009 |
| `src/frontend/platform/src/pages/SystemPage/components/DeveloperTokenTable.tsx` | modify | 使用结构化 DTO 展示当前路径/失效 ID | REQ-007, REQ-009 |
| `src/frontend/platform/src/test/DeveloperTokenFileSyncTargetTree.test.tsx` | create | 单选、展开、祖先、游标、切换和状态文案 | REQ-007, REQ-009 |
| `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/bs.json` | modify | 目标树状态与路径摘要文案 | REQ-007, REQ-009 |
| `docs/api/filelib-file-sync.md` | modify | 固定目录/动态根目录、权限、响应和回退说明 | REQ-008, REQ-009 |

本次不新增 Alembic revision；若实施时发现现有 Knowledge 只读契约无法在不泄露兄弟目录的前提下满足游标树，只允许在 Knowledge 领域 Service/Repository 内扩展，不得在 DeveloperToken Endpoint 直接查询 ORM。

## 测试策略 Testing Strategy

### 后端配置与认证

- Pydantic 真值表：4 种合法组合、`folder_id` 缺失/null/正整数及所有缺失/多余/未知字段。
- 创建、编辑、显式 null、字段未提交、同/跨租户换绑、最终节点权限和审计脱敏。
- options 的管理员范围、绑定用户权限主体、租户上下文恢复、分类父子、enabled 域、公共/部门空间分组、空间搜索和游标分页。
- children 的目录游标、深层授权必要祖先、导航节点不可选、兄弟隐藏、文件/团队/个人空间排除和 PermissionService 失败关闭。
- 列表/详情结构化当前路径、目录移动/重命名、失效稳定 ID 和固定查询次数。
- principal 一次认证、兼容 user dependency、配置损坏只影响 sync。
- 19812 先于 19906；所有失败/取消路径 ContextVar 恢复。

### Filelib 同步矩阵

| 域模式 | 空间模式 | 来源 | 关键验证 |
|---|---|---|---|
| fixed | fixed | none | 无动态 ID 也成功；运行时固定引用和绑定复核 |
| fixed | dynamic | department/person | 只动态解析空间，域不受 ID 影响 |
| dynamic | fixed | department/person | 只动态解析域，空间不受 ID 影响 |
| dynamic | dynamic | department/person | 两者复用同一部门解析结果 |

每组同时覆盖：合法、指定 ID 缺失、对象不存在/跨租户、业务域零/多匹配、空间零/多候选、域空间解绑、无上传权限、重复文件、清理、编码、元数据和一次入队。固定空间额外覆盖根目录/目录 `parent_id`、DIR/所属空间校验、目录删除/移动/重命名、权限撤销和不回退；动态空间锁定 `parent_id=None`。

### 路由与兼容

- 统一路径存在且只允许 POST。
- 11 个旧路径全部不在 OpenAPI/route 集合，调用 404。
- `params`、multipart、自定义错误映射和响应 fixture 回归。
- 其他依赖 `get_developer_token_user` 的 Open Endpoints 回归。
- 使用生产 `router_rpc` 发起 `/api/v2/filelib/file/sync` 请求，断言命中同步 handler 的 `19905` 契约而不是动态 `knowledge_id` 参数校验；该用例覆盖此前“子路由单测通过、生产组合失败”的盲区。

### 数据库与双方言

- 保留初版 F066 迁移回归：既有列仍为 `JsonType`、nullable、无 DML，MySQL 与 Linux DM8 CI 证据不回归。
- 本次 diff 断言不新增 Alembic revision/DDL，旧 JSON 缺失 `folder_id` 在双方言持久化往返后仍解释为根目录。
- 应用回退测试使用旧严格 schema 读取含 `folder_id` JSON，证明必须先清理/转换或 forward fix。

### Frontend

- 独立验证函数覆盖真值表、规范化和摘要。
- 组件覆盖启用/关闭、模式联动、父子分类、动态来源显隐、根/目录单选、展开不选中、空间搜索、目录游标、导航祖先、租户/用户切换和 options 失败。
- TypeScript/Vitest/production build、文件行数与 i18n key parity。

## 验证命令计划 Verification Commands

实施阶段按实际环境执行，规格阶段不声称这些命令已通过：

```bash
cd src/backend
uv run pytest test/developer_token test/open_endpoints/test_filelib_sync.py test/open_endpoints/test_filelib_sync_token_rule.py -q
uv run ruff check bisheng/developer_token bisheng/open_endpoints test/developer_token test/open_endpoints/test_filelib_sync.py
uv run ruff format --check bisheng/developer_token bisheng/open_endpoints test/developer_token test/open_endpoints/test_filelib_sync.py
uv run alembic heads

cd src/frontend/platform
npm run test -- developerTokenFileSyncRuleValidation DeveloperTokenFileSyncRule DeveloperTokenFileSyncTargetTree
npm run build
```

再执行：

```bash
rg -n 'file/sync/(03|04|05|06|07|09|10|11|12|14|15)' src/backend/bisheng docs/api
rg -n 'FILELIB_SYNC_RULES' src/backend/bisheng
```

预期生产代码和新版接口文档无旧路径/静态表命中；历史规格和迁移说明允许保留作为审计记录。

## 需求追踪 Requirements Traceability

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01..05 | 单一路由、删除静态规则与旧 handler、生产组合路由静态优先 | route/OpenAPI、11 路径 404、production-router contract regression |
| REQ-002 | AC-REQ-002-01..05 | nullable JSON、严格 schema、真值表、换租户最终状态校验 | schema/service/multi-tenant tests |
| REQ-003 | AC-REQ-003-01..05 | options API、保存校验、运行时二次校验 | admin API、stale reference、binding tests |
| REQ-004 | AC-REQ-004-01..06 | 动态部门、门户域匹配、F060 resolver、四组合 | parameterized resolver/service matrix |
| REQ-005 | AC-REQ-005-01..05 | principal、认证顺序、上传权限、ContextVar reset | dependency order/lifecycle/IDOR tests |
| REQ-006 | AC-REQ-006-01..05 | 复用 add_file、编码、清理、入队与元数据 | interaction/failure/response regression |
| REQ-007 | AC-REQ-007-01..06 | 前端拆分、options、联动、摘要、i18n | validation/component/build/static tests |
| REQ-008 | AC-REQ-008-01..06 | JsonType migration、无 backfill、rollout/rollback、文档 | migration、CI、发布清单、docs review |
| REQ-009 | AC-REQ-009-01..11 | 可空 folder、权限过滤树、游标、当前路径、最终节点权限与 parent_id | schema/admin API/permission/runtime/response/component/query-count tests |

## 设计决策 Decisions

### Decision 1：规则属于 Token 的可空单值 JSON

- Context: 一个 Token 最多一项配置，结构小且总是随 Token 管理。
- Options considered: 静态代码表；独立配置表；Token JsonType。
- Decision: `DeveloperToken.file_sync_rule: JsonType | NULL`。
- Rationale: 最小数据模型、原子更新、与 route whitelist 一致，且不预建多规则能力。
- Consequences: 查询某个规则字段不适合走数据库过滤；F066 无此需求。

### Decision 2：分类只能固定，域与空间独立 fixed/dynamic

- Context: 用户明确分类永远固定，域与目标可分别固定或动态。
- Options considered: 所有维度统一模式；请求覆盖；独立模式 + 共用来源。
- Decision: 分类固定；两个业务维度独立模式；任一动态时共用一个来源。
- Rationale: 精确表达四种组合并防止同一请求选出两个不相关部门。
- Consequences: 调用方必须显式传配置选中的 ID；不提供 fallback。

### Decision 3：认证返回 principal，兼容依赖继续返回 UserPayload

- Context: 同步链路必须知道本次 Token，但其他接口只需要绑定用户。
- Options considered: 二次查 Token；给 UserPayload 动态挂字段；引入 principal dependency。
- Decision: 新 principal generator，旧 user dependency 委托它。
- Rationale: 一次认证、强类型、secret 不下传、ContextVar 生命周期集中。
- Consequences: dependency tests 需要覆盖 yield/finally 和直接 authenticate 兼容。

### Decision 4：固定值按 code/ID 保存，展示名不入库

- Context: 名称可改且跨租户可能重复。
- Options considered: 名称；code/ID + 名称快照；只保存 code/ID。
- Decision: 只保存稳定 code/ID。
- Rationale: 避免漂移、错误回退和第二事实源。
- Consequences: 列表摘要优先展示 code/ID；编辑时从当前 options 解析名称，失效时明确标记。

### Decision 5：运行时仍做完整资源和权限校验

- Context: 保存后的分类、域、空间、绑定、权限均可能变化。
- Options considered: 信任保存快照；只校验权限；完整二次校验。
- Decision: 完整二次校验，固定-固定也不例外。
- Rationale: 配置不是权限，且 stale 引用必须失败关闭。
- Consequences: 每次同步有少量配置/资源读取成本，可避免错误写入。

### Decision 6：旧 URL 直接移除且不自动迁移

- Context: 用户明确不需要兼容和自动配置推导。
- Options considered: 重定向；灰度双路由；直接移除。
- Decision: 直接移除，管理员手工配置 Token 和 whitelist。
- Rationale: 防止旧编号继续成为隐藏业务事实源；这是产品明确接受的 v2 内 breaking change，虽不采用常规新版本并行/弃用周期，但必须通过发布通知和切换清单补偿。
- Consequences: 发布是明确 breaking change，需要发布窗口清单和调用方协同。

### Decision 7：固定目标以 `knowledge_id + folder_id?` 表达，动态目标只到根目录

- Context: 管理员需要精确选择目录，但现有同步响应、动态部门解析和知识文件归属仍以空间为边界。
- Options considered: 保存路径字符串；为所有模式增加动态目录；稳定空间/目录 ID 且只扩展固定模式。
- Decision: 固定目标保存必填 `knowledge_id` 和可空 `folder_id`；缺失/`null` 为根目录，动态目标两者均为空并解析到根目录。
- Rationale: 稳定 ID 支持重命名/同空间移动，兼容旧 JSON，避免引入动态目录解析和外部响应变化。
- Consequences: 删除/跨空间错配必须失败关闭；管理摘要需要实时批量解析当前路径。

### Decision 8：目标树和保存均以 Token 绑定用户为权限主体

- Context: Token 管理入口由系统管理员操作，但文件最终以 Token 绑定用户上传；按管理员权限列树会把配置误当授权并泄露目录。
- Options considered: 管理员看全量、运行时才拦截；空间级过滤；绑定用户最终节点过滤并展示最小祖先。
- Decision: options、children、保存、换绑和运行时均按绑定用户 `upload_file` 校验；深层权限只返回必要不可选祖先。
- Rationale: 配置阶段即可阻止无效目标，并保持权限事实源唯一、失败关闭和最小披露。
- Consequences: 换绑用户必须复核；权限服务不可用时管理选项也不可用；树查询需避免兄弟泄露和 N+1。

## 风险 / 取舍 Risks / Trade-Offs

| Risk | Impact | Mitigation | Owner / Phase |
|---|---|---|---|
| 旧调用方未切换 | 上线后旧 URL 404 | 上线前盘点、通知、预发布验证；监控旧路径 404 | rollout |
| Token 未配置或 whitelist 未改 | 新接口 403/19812 | 管理清单逐 Token 验证；错误码区分 | rollout |
| 资源配置后失效 | 同步 404/409 | 运行时二次校验、列表/编辑明确原 code/ID、无 fallback | runtime/admin |
| 动态域或空间歧义 | 过去隐式选取变为失败 | 复用确定性 resolver；管理员消除多绑定或调整 Token 为固定 | runtime |
| options 跨租户泄露 | 暴露资源名称/ID | admin scope + 受控租户上下文 + IDOR tests | backend |
| 目标树按管理员而非绑定用户短路 | 保存无权目标或暴露目录 | 为绑定用户构造 `UserPayload` 调 PermissionService；加载/保存/运行时三次复核 | backend/security |
| 深层目录权限泄露兄弟节点 | 用户可推断无权目录名称 | 后端只生成授权目录和必要祖先；祖先不可选；可见性矩阵测试 | backend/security |
| 目录路径摘要 N+1 | Token 列表延迟随行数/深度增长 | 批量空间/目录/祖先读取，query-count 测试 | backend/admin |
| 旧应用严格 schema 拒绝 `folder_id` | 应用回退后 Token 规则读取失败 | 回退前导出并清理/转换目录目标，或 forward fix | rollback |
| DeveloperToken 页面超行数 | 违反 600 行硬限制，维护性下降 | 配置组件、验证/摘要函数独立文件 | frontend |
| JSON 被绕过写入异常结构 | sync 运行异常或其他 Token API 被误伤 | sync 边界严格解析；异常配置只阻断 sync 并脱敏记录 | runtime |
| Alembic 多 head 变化 | migration 接错基线 | 实施前执行 `alembic heads`，不在 spec 固定旧 head | implementation |
| downgrade 丢配置 | 无法自动恢复 Token 规则 | 优先应用回退；降级前导出非秘密配置 | rollback |
| DB 写入与队列非原子 | 文件已持久化但入队失败 | 保持现有行为并如实回归；另立 Feature 处理 | out of scope |
| 静态 `/file/sync` 被先注册的动态 `/file/{knowledge_id}` 遮蔽 | 生产统一接口在认证前返回 `knowledge_id=sync` 的 422 | 静态同步 router 优先注册，并以生产 `router_rpc` API 回归锁定 | backend routing |

## 设计质量门 Design Quality Gate

- [x] 9 个 Requirement、54 条 AC 均映射到设计元素与验证策略。
- [x] Release Contract 的扩展所有权、F044/F047/F060 依赖和 INV-7～INV-9 已对齐。
- [x] 配置 schema、固定根/目录与动态根目录真值表和无 fallback 规则已确定。
- [x] Router → Endpoint → Service → Repository → DB 分层未被绕过。
- [x] 多租户、权限、secret 脱敏和 ContextVar 生命周期已设计。
- [x] 无新 migration、旧 JSON 兼容、MySQL/DM8、应用回退严格 schema 和 downgrade 风险已明确。
- [x] 前端目标树/hook 拆分满足 600 行限制且不引入新技术栈。
- [ ] 目录目标修订设计等待用户确认；确认前不创建生产实现、数据库变更或配置数据。
