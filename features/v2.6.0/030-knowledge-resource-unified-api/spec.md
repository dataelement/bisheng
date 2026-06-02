# Feature: F030-knowledge-resource-unified-api（知识资源统一对外 API · v2 filelib 改造）

**关联 PRD**: [../../../docs/PRD/知识空间优化/知识库接口文档.md](../../../docs/PRD/%E7%9F%A5%E8%AF%86%E7%A9%BA%E9%97%B4%E4%BC%98%E5%8C%96/%E7%9F%A5%E8%AF%86%E5%BA%93%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3.md)
**优先级**: P1（对外集成接口，统一文档知识库 / QA 知识库 / 知识空间的 RPC 契约）
**所属版本**: v2.6.0
**模块编码**: 沿用 109（`knowledge`，`common/errcode/knowledge.py`）与 180（`knowledge_space`，`common/errcode/knowledge_space.py`）；本 spec 不新增模块编码，新增错误码见 §6
**依赖**:
- F029（知识空间 AI 问答 - 检索权限过滤）—— F029 在其 spec 中**明确将 `/api/v2/filelib/retrieve` 排除**，理由是"以默认 operator 身份运行而非真实终端用户，需要先定义『代用户检索』协议（如 `on_behalf_of_user_id` 字段）"。**本 Feature 即提供该协议（`user_id` 入参）**，是 F029 的后续。
- F027（ReBAC 列表性能优化）—— 列表/文件列表沿用其 cursor 协议（INV-6）、`common/cursor.py` 编码与 `KnowledgeInvalidCursorError`(10991)。
- 现有 `KnowledgeService`（文档/QA/个人知识库）、`KnowledgeSpaceService`（知识空间）、`KnowledgeSpaceChatService.aretrieve_chunks`（多态检索）、`SpaceFileDao`（层级目录 cursor）、ReBAC `rebac_list_accessible` / `PermissionService`、`PageInfiniteCursorData`。

> **范围边界**
> - **本次纳入**：v2 RPC `/api/v2/filelib/` 下 6 个【改动】接口（列表 / 创建 / 更新 / 检索 / 上传 / 文件列表）+ 验证 4 个【已有】接口（删除 / 清空 / 删除文件 / 批量删除文件）+ 验证元数据层级 8 个【已有】接口。改造目标：让上述接口在**文档知识库(0) / QA 知识库(1) / 知识空间(3)** 三类资源上行为一致、由后端按资源类型自动分派。
> - **本次明确排除**：
>   - **个人知识库 type=2 对外暴露** —— 详见 AD-05。`KnowledgeTypeEnum.PRIVATE` 内部由 workstation / linsight 继续使用，**维持现状不删枚举**；仅 v2 对外 API 不接受、不返回 type=2。
>   - **知识空间 `auth_type` / `is_released` 之外字段的更新** —— 更新接口仅支持 `name` / `description`（AD-06、item 4）。修改 `auth_type`、发布广场、auto-tag 等仍走 v1 `update_space`，不在 v2 覆盖。
>   - **v2 新增"创建文件夹"接口** —— `parent_id` 仅支持已存在目录，不存在直接报错（AD-04、item 3）。建文件夹仍走 v1 `/space/{id}/folders`。
>   - **`auth_type` / `is_released` 作用于文档库 / QA 库** —— 这两个字段仅对知识空间(3)生效；type 0/1 创建时忽略（AD-07、item 6）。
>   - **检索 `tag_match_mode=ALL`** —— 沿用现有限制，仅支持 `ANY`。

---

## 1. 概述与用户故事

**故事 A（外部系统 · 统一列表）**：
作为 **通过 RPC 集成 BiSheng 的外部系统**，
我希望 **用一个列表接口按 `type` 查询某一类知识资源（文档库 / QA 库 / 知识空间），并可选地传 `user_id` 让结果按"某终端用户的可见范围"过滤**，
以便 **不必关心三类资源在内部是不同子系统，也能拿到统一形状的列表与权限点**。

**故事 B（外部系统 · 统一增删改）**：
作为 **外部系统**，
我希望 **创建时用 `type` 指定资源类别（文档库/QA库需 model，知识空间不需要 model），删除/清空/更新时只传资源 ID、由后端自动识别它是知识库还是知识空间**，
以便 **调用方无需自行区分资源子类型**。

**故事 C（外部系统 · 代用户检索）**：
作为 **自带 LLM 的外部 Agent**，
我希望 **对一批知识资源 ID（可含知识空间）做检索，传 `user_id` 时只在该用户有权访问的范围内召回、传 `tags` 时按"传入标签 ∩ 该资源标签集"过滤**，
以便 **检索结果与该用户在 UI 列表里能看到的内容一致，不发生越权召回**（闭合 F029 遗留的 RPC 越权口子）。

**故事 D（外部系统 · 知识空间文件上传到目录）**：
作为 **外部系统**，
我希望 **向知识空间上传文件时可指定 `parent_id` 落到已存在的文件夹，文档库/QA库上传时忽略 `parent_id`**，
以便 **复用知识空间的层级目录能力**。

**故事 E（研发）**：
作为 **后端研发**，
我希望 **v2 filelib endpoint 仅做"按类型/按 row.type 分派"的薄 facade，业务逻辑全部下沉到既有 `KnowledgeService` / `KnowledgeSpaceService`，不在 endpoint 写业务、不新增 DAO 入口**，
以便 **满足 DDD 分层与 arch-guard，且不重复实现两套子系统的逻辑**。

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。权限缺失统一返回现有 `SpacePermissionDeniedError`(18040)（空间）或知识库既有权限错误（库）。

### 2.1 列表 `GET /api/v2/filelib/`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 默认操作人 | `type=0` 不传 user_id | 返回当前默认操作人可见的**文档知识库**列表；游标分页 `PageInfiniteCursorData`（`data` + `page_size` + `has_more` + `next_cursor`，**无 total**，INV-6）；每项含 `permission_ids`（默认操作人视角） |
| AC-02 | 默认操作人 | `type=3` | 返回**"我创建的 + 我加入的"知识空间**（AD-08）；不含部门空间/广场；形状与 AC-01 一致 |
| AC-03 | 默认操作人 | 传 `user_id=X` | 列表仅含用户 X 有权访问的资源；`permission_ids` 为用户 X 的权限点（AD-02） |
| AC-04 | 任意 | 传 `type=2` | 拒绝，返回 `KnowledgeTypeNotSupportedError`(10962)（AD-05） |
| AC-05 | 任意 | 传非法 `type`（如 9） | 返回 `KnowledgeTypeNotSupportedError`(10962) |
| AC-06 | 任意 | `name` 过滤 + 翻页 | 按名称模糊匹配（知识库名 / 知识空间名同一字段）；传上页 `next_cursor` 到 `cursor` 取下一页；`has_more` 正确反映是否还有数据 |
| AC-06b | 任意 | 传非法 `cursor` | 返回 `KnowledgeInvalidCursorError`(10991)（沿用 F027，不静默 fallback 首页，INV-6） |

### 2.2 创建 `POST /api/v2/filelib/`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-07 | 默认操作人 | `type=0` + 合法 `model` | 创建文档知识库，初始化 Milvus + ES 索引，写 OpenFGA owner 元组；返回统一资源对象 |
| AC-08 | 默认操作人 | `type=1`（QA）+ 合法 `model` | 创建 QA 知识库，**不建索引**（首次加 QA 时建）；返回统一资源对象 |
| AC-09 | 默认操作人 | `type=3`（知识空间）**不传 model** | 复用 `create_knowledge_space`，内部使用 workbench LLM embedding；`model` 字段被忽略不报错（AD-03）；受 30/人上限约束（AC-13） |
| AC-10 | 默认操作人 | `type=0` 缺 `model` | 返回 `KnowledgeNoEmbeddingError`(10901) |
| AC-11 | 默认操作人 | 重名创建（type 0/1，同用户） | 返回 `KnowledgeExistError`(10900) |
| AC-12 | 默认操作人 | `type=0/1` 传了 `auth_type`/`is_released` | 字段被忽略（仅 type=3 生效，AD-07）；不报错 |
| AC-13 | 默认操作人 | `type=3` 且已达 30 个空间 | 返回 `SpaceLimitError`(18001) |

### 2.3 更新 `PUT /api/v2/filelib/`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-14 | 默认操作人 | 传 `knowledge_id` + `name` + `description` | 仅更新名称/描述；其它字段不变；按 row.type 分派到对应服务 |
| AC-15 | 默认操作人 | 仅传 `knowledge_id` + `name`（不传 description） | 名称更新；描述置空（按 doc 语义"不传则将描述变为空"，AD-09 标注与现状差异） |
| AC-16 | 默认操作人 | `knowledge_id` 不存在 | 返回 `NotFoundError` |

### 2.4 检索 `POST /api/v2/filelib/retrieve`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-17 | 外部 Agent | `knowledge_base_ids` 含知识库与知识空间混合 ID，不传 user_id | 以默认操作人身份在各资源对应 collection 检索；返回扁平 chunks |
| AC-18 | 外部 Agent | 传 `user_id=X` | 仅在用户 X 有权访问的资源/文件范围内检索（与 F029 列表可见性对齐）；无权资源静默跳过 |
| AC-19 | 外部 Agent | 传 `filters.knowledge_base_filters`（每库各自标签） | 对每个库按其指定标签过滤：过滤集 = `该库传入 tags ∩ 该库已定义标签集`，再做标签过滤（AD-01、item 2）；沿用现有 `filters` 结构，**不引入扁平 tags** |
| AC-20 | 外部 Agent | `top_k` > 200 | 参数校验失败（沿用现有 `le=200`） |

### 2.5 上传 `POST /api/v2/filelib/file/{knowledge_id}`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-21 | 默认操作人 | 上传到知识库（type 0/1），不传 parent_id | 行为同现状；`parent_id` 被忽略 |
| AC-22 | 默认操作人 | 上传到知识空间（type=3）不传 parent_id | 落到空间根目录 |
| AC-23 | 默认操作人 | 上传到知识空间 + 合法 `parent_id`（已存在文件夹） | 文件落到该文件夹（`file_level_path` 正确） |
| AC-24 | 默认操作人 | 上传到知识空间 + `parent_id` 指向不存在目录 | 返回 `SpaceFolderNotFoundError`(18010)（AD-04） |
| AC-25 | 默认操作人 | 向知识库(type 0/1)传 `parent_id` | `parent_id` 被忽略，正常上传（AD-04） |

### 2.6 文件列表 `GET /api/v2/filelib/file/list`（【改动】）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-26 | 默认操作人 | 知识库 ID（type 0/1） | 文件列表；游标分页（`PageInfiniteCursorData` + `writeable`，AD-13）；`writeable`=默认操作人对该库是否有编辑权限 |
| AC-27 | 默认操作人 | 知识空间 ID（type=3）+ 可选 `parent_id` | 走层级目录列表（`SpaceFileDao.async_list_children`，cursor）；`parent_id` 不传=根目录；`writeable`=对应资源（文件夹/文件粒度，AD-10、item 5）可写判定 |
| AC-28 | 默认操作人 | 传 `user_id=X` | 仅返回用户 X 有权访问的文件；`writeable` 按用户 X 的编辑权限判定 |
| AC-29 | 默认操作人 | `status` 多值过滤 | 按统一状态枚举过滤（含 `4 重建中`，AD-11、item 7） |
| AC-29b | 默认操作人 | 知识空间 + `parent_id` 指向不存在目录 | 返回 `SpaceFolderNotFoundError`(18010) |

### 2.7 回归 —— 已有接口（不改逻辑，验证多态正确）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-30 | 默认操作人 | `DELETE /{knowledge_id}` 删知识空间 | 按 row.type 分派到 `KnowledgeSpaceService.delete_space`，级联子资源 + ReBAC tuple 清理；删知识库走 `KnowledgeService.delete_knowledge` |
| AC-31 | 默认操作人 | `DELETE /clear/{knowledge_id}` | 知识库/知识空间均清空内容保留资源本体 |
| AC-32 | 默认操作人 | 元数据层级 8 接口 | 行为与改造前一致；**仅作用于知识库**，知识空间无元数据能力（不暴露、不适用） |

---

## 3. 边界情况

- **ID 多态**：知识空间是 `knowledge` 表中 `type=3` 的行，与知识库 ID 全局唯一同表。凡带 `knowledge_id` 的操作，后端**先查行读 `row.type` 再分派**，调用方无需传 type。
- **type=2（个人库）对外不可达**：列表默认/显式不返回；创建/检索/上传遇 type=2 资源按"不支持"处理（AD-05）。内部 workstation/linsight 仍可正常使用 type=2（不走 v2 filelib）。
- **空间无可见文件**：检索/文件列表对该资源返回空集，不报错。
- **`parent_id` 跨空间**：`parent_id` 必须属于目标 `knowledge_id` 空间，否则视为不存在（`SpaceFolderNotFoundError`）。
- **分页到底**：无更多数据时 `has_more=false`、`next_cursor=null`、`data=[]`；非法 cursor 抛 `KnowledgeInvalidCursorError`(10991)，不静默 fallback 首页（INV-6）。
- **不支持**：v2 建文件夹、空间 auth_type/is_released 后续修改、type=2 暴露、tag_match_mode=ALL（均延后/不做）。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 检索标签结构 | A: 扁平 tags（一份套所有库）/ B: 沿用 `filters` 嵌套（每库各自标签） | **B** | 用户确认：放弃扁平 tags，统一用 `filters`，支持每库指定自己的标签；每库按 `传入 tags ∩ 该库标签集` 求交过滤（item 2）。**检索接口因此无破坏性变更，仅新增 `user_id`** |
| AD-02 | 权限过滤身份 | A: 永远默认操作人 / B: user_id 传则按该用户、否则默认操作人 | **B** | PRD + item 1；闭合 F029 遗留的 RPC 越权口子；`permission_ids` 跟随同一身份 |
| AD-03 | 知识空间创建 model | A: 必填 / B: type=3 忽略 model | **B** | 空间强制用 workbench LLM embedding（item 2）；复用 `create_knowledge_space` |
| AD-04 | parent_id 文件夹 | A: 不存在则自动建 / B: 仅支持已存在、否则报错 | **B** | item 3；v2 不提供建文件夹接口，建目录走 v1 |
| AD-05 | 个人库 type=2 | A: 删枚举 / B: 枚举保留、仅 v2 不暴露 | **B** | `KnowledgeTypeEnum.PRIVATE` 被 workstation(3处)+linsight(3处) 活跃引用，删除是 breaking；item 3 确认"维持现状，仅对外不暴露" |
| AD-06 | 更新字段范围 | A: 全字段 / B: 仅 name+description | **B** | item 4；其它字段走 v1 |
| AD-07 | auth_type/is_released 作用域 | A: 全类型 / B: 仅 type=3 | **B** | item 6；文档/QA 库不支持审批开关 |
| AD-08 | HTTP 是否拆分 + 空间列表口径 | A: 拆三套 URL / B: 统一 URL + service 层分派 | **B**；type=3 列表口径 = **我创建的 + 我加入的**空间（不含部门/广场） | 保留 doc "调用方不区分类型"卖点；同表 ID 多态使分派天然可行；endpoint 仅 facade。列表口径按 item 2 确认 |
| AD-09 | 更新缺 description 语义 | A: 不传则不改 / B: 不传则置空 | **B（按 doc）** | doc 明确"不传则将描述变为空"；需确认 `KnowledgeUpdate` 当前是否如此，可能需调整（见文件清单） |
| AD-10 | writeable 判定 | 统一"当前身份对资源是否可写" | 空间=文件夹/文件可编辑权限；库=库可编辑权限 | item 5 |
| AD-11 | status 枚举 | 统一为 `1处理中/2成功/3失败/4重建中/5排队中/6超时/7违规` | 统一 | item 7 |
| AD-12 | 资源列表分页模型 | A: 游标(cursor) / B: page_num+total | **A（cursor，对齐 v1 + INV-6）** | **INV-6 强制**：走 ReBAC 过滤的列表必须 cursor-based、不返 total。PRD 已同步改为 cursor。入参对齐 v1 `GET /api/v1/knowledge`：`type/name/sort_by/page_size/cursor/user_id`；出参 `PageInfiniteCursorData`。cursor 失败抛 `KnowledgeInvalidCursorError`(10991)，不静默 fallback |
| AD-13 | 文件列表分页模型 | A: cursor / B: page_num+total | **A（cursor）** | 对外统一 `PageInfiniteCursorData` + `writeable`，入参 `knowledge_id/parent_id/keyword/status/page_size/cursor/user_id`。空间路径用现成 cursor 的 `SpaceFileDao.async_list_children`；**知识库路径底层维持现状（offset 查询不变），外层用 F027 AD-15 伪游标包一层**（cursor key=`[page_num]`、取 `page_size+1` 探测 has_more、不算 total）。具体实现见 tasks T-08 |

---

## 5. 数据库 & Domain 模型

**无新建表、无新增领域对象。** 复用 `Knowledge`（含 type=3 知识空间行）、`KnowledgeFile`（含 `file_type`/`file_level_path` 层级）、`KnowledgeRead`（已含 `user_name`/`permission_ids`）。

### 可能的 Schema 微调（实现期确认，非新表）

- **上传不改 `KnowledgeFileProcess`**：v2 上传 endpoint 的 `parent_id` 仅作为 Form 入参，按 row.type 分派——知识库走 `KnowledgeService.aprocess_knowledge_file`（不传 parent_id），知识空间走 `KnowledgeSpaceService.add_file(knowledge_id, file_path, parent_id)`（已原生支持 parent_id）。通用 `KnowledgeFileProcess` 保持不变。
- `RetrieveReq`（`open_endpoints/domain/schemas/filelib.py`）：**仅新增 `user_id: Optional[int]`**；`filters.knowledge_base_filters`（每库各自标签）保持不变；**不引入扁平 tags**。无破坏性变更。
- 列表 endpoint 入参（对齐 v1）：`type / name / sort_by / page_size / cursor / user_id`；出参 `PageInfiniteCursorData`（`common/schemas/api.py`，`{data, page_size, has_more, next_cursor}`）。
- 文件列表 endpoint 入参（对齐 v1）：`knowledge_id / parent_id / keyword / status / page_size / cursor / user_id`；出参 `PageInfiniteCursorData` + `writeable`。

---

## 6. API 契约

> 全部位于 v2 RPC：`open_endpoints/api/endpoints/filelib.py`（资源/文档层级）与 `open_endpoints/api/endpoints/knowledge.py`（元数据层级，已存在）。
> 响应包装：`UnifiedResponseModel`（`resp_200`）。认证：默认操作人（`get_default_operator` / `get_default_operator_async`），叠加可选 `user_id` 代用户过滤。

### 端点列表（本次改动 6 个）

| Method | Path | 描述 | 分派键 |
|--------|------|------|--------|
| GET | `/api/v2/filelib/` | 按 type 查列表（单 type，默认 0，**cursor 分页**） | 入参 `type` |
| POST | `/api/v2/filelib/` | 创建资源 | 请求体 `type`（判别式） |
| PUT | `/api/v2/filelib/` | 更新 name/description | `knowledge_id` → row.type |
| POST | `/api/v2/filelib/retrieve` | 跨资源检索 | 各 id → 各自 collection |
| POST | `/api/v2/filelib/file/{knowledge_id}` | 上传文件（空间支持 parent_id） | path id → row.type |
| GET | `/api/v2/filelib/file/list` | 文件列表（**cursor 分页**，空间支持 parent_id） | 入参 `knowledge_id` → row.type |

### 请求/响应示例

**创建（type=0 文档库）**:
```json
POST /api/v2/filelib/
{ "name": "合同库", "type": 0, "model": "12", "description": "..." }
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "id": 1, "name": "合同库", "type": 0, "model": "12", "state": 1,
    "auth_type": "public", "is_released": false,
    "user_id": 3, "user_name": "operator", "tenant_id": 1,
    "create_time": "2026-06-01T00:00:00", "update_time": "2026-06-01T00:00:00",
    "permission_ids": ["use_kb", "edit_kb"]
  }
}
```

**列表（cursor 分页，`PageInfiniteCursorData`）**:
```json
GET /api/v2/filelib/?type=0&sort_by=update_time&page_size=10&cursor=&user_id=5
```
```json
{
  "status_code": 200,
  "status_message": "SUCCESS",
  "data": {
    "data": [ { "id": 1, "name": "合同库", "type": 0, "permission_ids": ["use_kb"] } ],
    "page_size": 10,
    "has_more": true,
    "next_cursor": "eyJ2IjoxLCJrIjpbIjIwMjYtMDYtMDEiLDFdfQ"
  }
}
```

**检索（沿用 `filters`，新增 `user_id`）**:
```json
POST /api/v2/filelib/retrieve
{
  "query": "付款条款",
  "knowledge_base_ids": [1, 7],
  "filters": { "knowledge_base_filters": [
    { "knowledge_base_id": 1, "tags": ["合同"], "tag_match_mode": "ANY" }
  ] },
  "user_id": 5, "top_k": 10
}
```

### 新增/调整错误码（模块 109）

| HTTP | MMMEE | Error Class | 场景 | 关联 AC |
|------|-------|-------------|------|---------|
| 200(body) | 10962 | `KnowledgeTypeNotSupportedError`（新增） | type 非法 / type=2 对外不支持 | AC-04, AC-05 |
| 200(body) | 10991 | `KnowledgeInvalidCursorError`（复用 F027） | cursor 解析失败 | AC-06b |
| 200(body) | 10900 | `KnowledgeExistError`（复用） | 重名 | AC-11 |
| 200(body) | 10901 | `KnowledgeNoEmbeddingError`（复用） | 文档/QA 库缺 model | AC-10 |
| 200(body) | 18001 | `SpaceLimitError`（复用） | 知识空间超 30/人 | AC-13 |
| 200(body) | 18010 | `SpaceFolderNotFoundError`（复用） | parent_id 目录不存在 | AC-24 |
| 200(body) | 404 | `NotFoundError`（复用） | knowledge_id 不存在 | AC-16 |

> 检索接口**无破坏性变更**：沿用现有 `filters.knowledge_base_filters` 结构，仅新增可选 `user_id`。

### 统一资源出参（列表/创建/更新）

沿用 `KnowledgeRead`：`id / name / type / description / model / state / auth_type / is_released / user_id / user_name / tenant_id / create_time / update_time / permission_ids`。

---

## 7. Service 层逻辑

> **核心原则（AD-08）**：endpoint 仅做 facade 分派，**不写业务、不新增 DAO 入口**。

### 分派矩阵

| 操作 | type 0/1（文档/QA库） | type 3（知识空间） | type 2 |
|------|----------------------|--------------------|--------|
| 创建 | `KnowledgeService.(a)create_knowledge`（QA 跳过建索引） | `KnowledgeSpaceService.create_knowledge_space`（忽略 model） | 拒绝(10962) |
| 列表 | `KnowledgeService.get_knowledge`（facade 适配 page/total） | 知识空间列表口径（AD-08 见下） | 不返回 |
| 更新 | `KnowledgeService.update_knowledge` | `KnowledgeSpaceService.update_knowledge_space`（仅 name/desc） | — |
| 删除/清空 | `KnowledgeService.delete_knowledge(only_clear?)` | `KnowledgeSpaceService.delete_space` / 清空 | — |
| 检索 | `KnowledgeSpaceChatService.aretrieve_chunks`（已多态） | 同左（空间 id 即一个 collection） | — |
| 上传 | `KnowledgeService.aprocess_knowledge_file`（不涉及 parent_id） | `KnowledgeSpaceService.add_file(knowledge_id, file_path, parent_id)`（原生校验目录 + 构造 file_level_path） | — |
| 文件列表 | `KnowledgeService.aget_knowledge_files`（+user_id） | `SpaceFileDao.async_list_children`（+user_id） | — |

### AD-08 知识空间列表口径（已确认）

知识空间在 v1 有 5 种列表（mine/managed/joined/department/square）。v2 单一列表语义 = **"我创建的 + 我加入的"知识空间**（对齐 v1 `/mine` + `/joined`，复用 `_format_member_spaces` / `async_count_spaces_by_user` 等既有路径）；**不含**部门空间、广场。传 `user_id` 时，"我"即该 user_id。

### 代用户身份（AD-02）

新增统一封装：传 `user_id` 时按该 user_id 构造权限上下文（类 `UserPayload`），复用 `rebac_list_accessible` / `PermissionService`；不传则用默认操作人。`permission_ids` 与 `writeable` 均跟随该身份。

### 权限检查

资源操作必须经 `PermissionService.check()`；创建经 `PermissionService.authorize()` / `OwnerService.write_owner_tuple`（现有 create 路径已含）。禁止直查 `role_access`。

---

## 8. 前端设计

**不涉及前端。** 本特性仅改造 v2 RPC 对外集成接口，无 platform/client UI 变更。

---

## 9. 文件清单

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/open_endpoints/api/endpoints/filelib.py` | 6 个端点改为 facade 分派：列表(cursor 对齐 v1 + user_id)、创建(type 判别式)、更新(name/desc)、检索(filters 不变 + user_id)、上传(按 row.type 分派到各自文件新增方法，`parent_id` 仅传给空间 `add_file`)、文件列表(cursor + parent_id + user_id) |
| `src/backend/bisheng/open_endpoints/domain/schemas/filelib.py` | `RetrieveReq` 仅增 `user_id`；`filters` 保持不变（无破坏性） |
| `src/backend/bisheng/knowledge/domain/services/knowledge_service.py` | `aget_knowledge_files` 增 `user_id` 过滤 + cursor 适配出口；`get_knowledge`（已 cursor）直接复用。**上传不改 `KnowledgeFileProcess`** |
| `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py` | 暴露/复用：按 user_id 过滤的空间列表口径；空间文件列表(+user_id)；**上传直接复用现有 `add_file(knowledge_id, file_path, parent_id)`**（已校验目录、构造 file_level_path） |
| `src/backend/bisheng/common/errcode/knowledge.py` | 新增 `KnowledgeTypeNotSupportedError`(10962) |
| `src/backend/bisheng/knowledge/domain/services/`（新建薄分派或复用） | 可选 `KnowledgeFacadeService`：按 type / row.type 路由（仅路由，不含业务） |

### 新建（测试）

| 文件 | 说明 |
|------|------|
| `src/backend/test/knowledge/test_v2_filelib_unified.py` | 覆盖 AC-01~AC-32 的 API 端到端测试（pytest + httpx） |

### 文档

| 文件 | 变更内容 |
|------|---------|
| `features/v2.6.0/release-contract.md` | 登记 F030：新增错误码 10962、`user_id` 代用户检索协议（闭合 F029 遗留项）；检索沿用 `filters` 结构无破坏性变更 |

---

## 10. 非功能要求

- **性能**：列表/文件列表均走 cursor（INV-6），复用 F027 的 keyset 优化路径，**不得为算 total 扫描全部 batch**；检索 `user_id` 过滤复用 F029 双层过滤，单次问答权限解析开销可控。
- **安全**：权限五级链路（`PermissionService`）；多租户 `tenant_id` 自动注入（禁手写）；type=2 对外不可达；代用户检索不得越权召回（对齐 F029 INV-7：AI 检索可见性 ⊆ 列表 UI 可见性）。
- **兼容性**：双 DB（MySQL + DM8）—— `parent_id` 路径匹配复用现有 `SpaceFileDao` 物化路径（已 DM8 兼容），不引入 `JSON_EXTRACT`；列表/文件列表 cursor 协议与 v1 一致（INV-6），PRD 已同步；检索沿用 `filters`，无破坏性变更。

---

## 待确认项（Open Questions）

- ~~**OPEN-1**：知识空间是否需要元数据能力？~~ → **已确认：不需要。** 元数据层级 8 接口仅作用于知识库；知识空间无元数据功能。
- ~~**OPEN-2**：知识空间列表口径？~~ → **已确认：我创建的 + 我加入的**（见 AD-08）。
- ~~**OPEN-3**：检索是否切扁平 tags？~~ → **已确认：不切。** 放弃扁平 tags，统一沿用 `filters.knowledge_base_filters`（每库各自标签）。检索接口仅新增 `user_id`，无破坏性变更。

---

## 相关文档

- 版本契约: [../release-contract.md](../release-contract.md)（写 spec 前必须先阅读）
- 前序 Feature: [../029-knowledge-qa-permission-filter/spec.md](../029-knowledge-qa-permission-filter/spec.md)（本特性闭合其遗留的 RPC 代用户检索项）
- PRD: `docs/PRD/知识空间优化/知识库接口文档.md`
