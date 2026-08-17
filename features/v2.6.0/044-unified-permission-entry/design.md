# Design: 知识空间与频道统一权限设置入口

> **状态**：✅ 已确认并通过设计评审
> **关联 Spec**：[spec.md](./spec.md)
> **版本契约**：[release-contract.md](../release-contract.md)
> **最后更新**：2026-08-07
> **界面参考**：[Figma · BISHENG · node 13051:92477](https://www.figma.com/design/FNt6RR3OZtaJQH6x8enmaZ/BISHENG?node-id=13051-92477&m=dev)

## 1. 目标与非目标

### 1.1 目标

- 将知识空间的新建/编辑、频道的新建/设置改为完整页面，在一个入口承载资源设置和权限设置。
- 页面是否展示权限区域，服从服务端现有细粒度权限结果，不增加角色名称判断。
- 新建时先在本地维护权限草稿；提交时随现有创建请求传入，由后端创建资源后调用现有批量授权服务落地。
- 编辑时只提交用户实际修改的权限项，不用过期快照覆盖其他并发变更。
- 分享转私密继续由后端原有更新事务清理全部非创建者授权。

### 1.2 非目标

- 不改 OpenFGA 模型、权限角色、细粒度权限 ID、授权对象范围或成员关系存储。
- 不引入邀请确认、文件审批、中粮定制的部门空间强制分享规则。
- 不把知识空间和频道的授权写接口合并成新的通用写接口。
- 不合并“包含子部门”产生的多条底层授权记录。

## 2. 关键约束与 Constitution Check

本设计遵循 [Architecture Constitution](../../../docs/constitution.md) C1–C7 和版本级 [release-contract.md](../release-contract.md)，不在本文重抄全局铁律。功能特有约束如下：

- 创建页面提交前没有资源 ID，禁止预创建资源；候选查询必须以“待创建资源”的能力和租户范围执行。
- 资源数据库与 OpenFGA 不具备跨存储事务；初始授权失败沿用现有授权失败/重试语义，不回滚已创建资源。
- 创建请求新增字段必须可选；未传 `initial_permissions` 的现有调用方请求与响应保持兼容。
- 部门选择必须保持 F038 的逐层加载/服务端搜索，不恢复整棵部门树加载。
- 本次只改 client SPA；不得把 client 的 Recoil/react-query v4 代码与 platform SPA 混用。

**Constitution Check：通过。** 候选查询从 API endpoint 下沉为共享 `GrantSubjectQueryService`，endpoint 不直接查询 ORM，授权仍经 `PermissionService` / F026 owner service；无 DDL、手写 tenant 条件、新错误码、密钥或 store HTTP 调用。

## 3. 关键决策

### D1. 使用完整页面替代现有抽屉

- **备选**：继续扩展 `CreateKnowledgeSpaceDrawer` / `CreateChannelDrawer`；使用独立权限弹窗；新建完整页面。
- **选择**：新增完整页面路由，知识空间单栏、频道桌面双栏；窄屏统一堆叠为单栏。
- **原因**：Figma 的信息密度和固定底部操作区已超出抽屉适用范围，也能真正取消独立权限入口。
- **重议条件**：产品明确要求保留抽屉，且能给出权限区在窄宽度下的完整交互稿。

路由：

- `/workspace/knowledge/create`
- `/workspace/knowledge/space/:spaceId/settings`
- `/workspace/channel/create`
- `/workspace/channel/:channelId/settings`

### D2. 权限编辑采用受控本地草稿

- **备选**：复用当前点击即写入的 `PermissionListTab` / `PermissionGrantTab`；页面内维护草稿，保存时写入。
- **选择**：抽取纯展示/选择组件并由页面持有 `PermissionDraft`；禁止选择控件直接调用授权接口。
- **原因**：统一页面必须具备一致的保存/取消语义，新建阶段也没有资源 ID；即时写入无法取消。
- **重议条件**：后端未来提供原子化“资源设置 + 权限集合”命令接口。

### D3. 扩展现有创建请求，由后端编排初始授权

- **备选**：新增无资源 ID 的创建上下文/候选接口后由前端分两步写；新增统一批量写 API；扩展两类资源现有创建请求。
- **选择**：知识空间和频道创建请求各自增加可选 `initial_permissions.grants`；各自的 creation application service 编排资源创建，取得真实 ID 和创建者 owner 后调用该领域现有批量授权 service。编辑仍调用现有资源更新与授权接口。
- **原因**：一次提交符合统一创建页语义；不新增权限写 API，也不把知识空间与频道不同的权限写模型强行合并。创建候选只补一个统一的只读查询路径，关系模型继续复用现有接口。
- **重议条件**：两个领域形成共同的事务边界和统一 relation-model 语义。

### D4. 权限区可见性来自服务端有效能力

- **备选**：按 `admin/owner/editor` 等角色名称控制；按现有细粒度能力及可授予模型控制。
- **选择**：编辑页使用现有 `manage_space_relation` / 频道授权管理能力；创建页按“创建者将获得的 owner 关系”对应的现有细粒度权限配置判断，并从现有 relation-model 配置筛出其可授予模型。创建接口在资源和 owner 建立后再次做权威校验。
- **原因**：角色只是权限来源之一，硬编码会忽略用户级或自定义角色配置。
- **重议条件**：权限中心提供新的、稳定的统一 capability ID，并完成存量迁移。

### D5. 分享转私密由后端权威清理

- **备选**：前端读取授权列表后逐条撤销；调用现有资源更新。
- **选择**：只提交可见性为私密；知识空间 `KnowledgeSpaceService.update_knowledge_space` 和频道 `ChannelService.update_channel` 清理非创建者成员、FGA tuple 与 relation-model binding，并保留/重建创建者 owner。
- **原因**：后端可覆盖隐藏记录和并发状态；前端列表不应成为授权真相。
- **重议条件**：现有 update service 不再承诺该清理语义，届时须先建立新的服务端原子命令。

### D6. Figma 作为结构与交互基准，不复制生成代码

- **备选**：直接采用 Figma 生成代码和原始样式值；在现有 design system 上按结构重建。
- **选择**：复用 `@bisheng/ui`、项目 token、既有表单控件、图标与 i18n；不引入原始 hex、外部 UI 库或 Figma 生成代码。
- **原因**：client 强制使用 `@bisheng/ui` 与主题 token；复制生成代码会绕过品牌主题、i18n 和移动端排版规则。
- **重议条件**：设计系统正式新增对应组件并替换现有组件。

## 4. 详细设计

### 4.0 现状调用链

- 知识空间：列表页打开 `CreateKnowledgeSpaceDrawer` 完成资源创建；资源详情中的独立 `KnowledgeSpaceShareDialog` 读取并即时写入授权。
- 频道：订阅页打开 `CreateChannelDrawer` 完成资源创建；独立 `ChannelPermissionDialog` 经 F026 频道授权接口即时写入关系。
- 两类资源的“分享转私密”均已在各自 update service 内清理非创建者授权；当前前端并不拥有这项清理规则。

目标态保留上述后端写链路，只把前端入口、页面布局和保存编排统一起来。

### 4.1 页面与布局

知识空间页面为约 648px 的居中单栏，依次展示“基础设置”“访问与分享”；频道桌面页为左右两栏，左侧保留全部频道业务设置，右侧展示“访问与分享”。两者底部均使用固定的取消/创建或取消/保存操作区。移动端按基础设置、业务设置、访问与分享顺序单栏排列，不保留独立权限弹窗。

分享区保留现有语义：

| 资源 | 私密 | 分享下的加入方式 | 分享附加设置 |
|---|---|---|---|
| 知识空间 | private | approval / public | 空间广场等现有设置 |
| 频道 | private | review / public | 发布广场等现有设置 |

选择私密后隐藏加入方式、广场和授权列表。私密切换为分享时，若本次页面尚未选择加入方式，则初始化为“需要审核”。

### 4.2 页面数据流

#### 新建

1. 页面从现有 relation-model 接口加载关系模型，并从 §4.5 的统一只读接口按需查询用户、部门和用户组；创建页只覆盖普通知识空间/频道，不套用管理后台部门空间的 F033 特殊候选范围。
2. 页面根据 prospective owner 的现有细粒度权限配置决定是否展示授权区域；有权限时在本地编辑 `PermissionDraft`。
3. 提交时将资源字段和 `initial_permissions.grants` 一并传给现有资源创建 API。
4. 后端先校验授权对象属于当前租户、角色模型有效且部门/用户组不能成为 owner，再调用原资源 create service。创建者成员关系、owner tuple、审计和频道外部副作用只由原 create service 执行一次，creation application service 不重复写入。
5. 获得真实资源 ID 后，后端调用从现有 authorize endpoint 下沉的知识空间 `ResourceAuthorizationService`，或 F026 `ChannelAuthorizationService` 批量授权；全部成功后返回资源及成功状态。
6. 若资源已创建但批量授权失败，创建接口仍返回已创建资源 ID，并将 `initial_permission_result.status` 标为 `failed`、携带现有授权错误码；页面显示“资源已创建，权限未完全设置”，提供“仅重试权限设置”和“进入资源”。重试调用现有 authorize API，不得再次创建资源。

Owner tuple 和初始授权失败**维持现状**：资源创建继续调用 `OwnerService.write_owner_tuple()` 的默认 best-effort 模式，OpenFGA 写失败进入既有 `failed_tuples` 重试链路；初始批量授权继续使用当前知识空间/频道授权服务的校验、错误码和补偿行为。本 Feature 不把两次 OpenFGA 写改成数据库事务，也不新增同步重试循环。

#### 编辑

1. 并行读取资源详情、当前有效能力；仅当具备权限管理能力时读取权限列表和可授予模型。
2. 将权限响应转换为 `baseline` 和可编辑草稿；创建者 owner 行只读且不可删除。
3. 保存资源字段；若仍为分享，再按 `touchedKeys` 计算授权/撤销命令并调用现有授权 API。
4. 若保存为私密，不发送任何后续授权写请求；清空本地草稿并重新读取服务端状态。
5. 任一请求返回失权时展示通用错误并刷新能力/详情；业务组件不新增 403 分支。

资源设置与 OpenFGA 不具备跨存储原子事务，因此编辑保存结果按实际成功步骤反馈，不声称失败步骤已生效。再次加载始终以服务端状态为准。

### 4.3 权限草稿

```ts
type PermissionSubjectType = 'user' | 'department' | 'user_group';
type PermissionRelation = 'owner' | 'manager' | 'editor' | 'viewer';

interface PermissionDraftRow {
  subjectType: PermissionSubjectType;
  subjectId: number;
  subjectName: string;
  relation: PermissionRelation;
  modelId?: string;
  includeChildren?: boolean;
  immutableCreator?: boolean;
}

interface PermissionDraft {
  baseline: PermissionDraftRow[];
  rows: PermissionDraftRow[];
  touchedKeys: string[];
}
```

`subjectType + subjectId + relation/modelId + includeChildren` 组成稳定比较键。仅对用户实际添加、改角色或删除的行生成写命令。未触碰的服务端授权不撤销，从而避免用旧页面快照覆盖并发新增；服务端仍负责最终合法性、重复和授权范围校验。

### 4.4 创建请求与结果契约

创建写入不新增 API 路径，扩展现有：

- `POST /api/v1/knowledge/space`
- `POST /api/v1/channel/manager/create`

两类请求均增加同形的可选字段；具体 grant item 分别复用 `AuthorizeGrantItem` / `ChannelGrantItem`，不允许传 `revokes`：

```json
{
  "initial_permissions": {
    "grants": [
      {
        "subject_type": "user",
        "subject_id": 123,
        "relation": "editor",
        "include_children": false,
        "model_id": "editor"
      }
    ]
  }
}
```

创建响应保留原资源字段，并增加可选结果：

```json
{
  "id": "resource-id",
  "initial_permission_result": {
    "status": "success",
    "error_code": null
  }
}
```

`status` 仅为 `success | failed`。授权为空时不调用授权服务，结果可省略。批量授权失败不回滚或删除已创建资源，`error_code` 复用现有权限写错误码；响应不得返回成员名称或完整授权明细。编辑页继续使用现有资源 ID 版本的候选与 authorize 接口。

### 4.5 创建阶段候选查询

新增一个只读路径：

- `GET /api/v1/permissions/creation-grant-subjects`

查询参数：

- `resource_type=knowledge_space|channel`
- `subject_type=user|department|user_group`
- `operation=list|children|search|path_tree`
- 按 operation 使用现有 `keyword/page/page_size/parent_id/department_id/limit` 参数。

响应继续使用现有 `resp_200(data)` envelope，`data` 按 `subject_type + operation` 保持现有形状：

| 请求 | `data` 形状 | 关键字段 |
|---|---|---|
| `user + list` | `UserGrantSubject[]` | `user_id`, `user_name`, `external_id`, `primary_department_path` |
| `user_group + list` | `UserGroupGrantSubject[]` | `id`, `group_name` |
| `department + children` | `DepartmentGrantNode[]` | `id`, `dept_id`, `name`, `parent_id`, `path`, `sort_order`, `source`, `status`, `has_children`, `matched`, `children` |
| `department + search/path_tree` | `DepartmentGrantTree` | `roots`, `total_matches`, `truncated`；`roots` 中节点同 `DepartmentGrantNode` |

空结果保持现有类型：用户、用户组和部门 children 返回 `[]`，部门 search/path_tree 返回 `{"roots":[],"total_matches":0,"truncated":false}`。无效 `resource_type/subject_type/operation` 使用现有参数/资源错误，无细粒度能力使用现有权限拒绝错误，不为本 Feature 新增错误码。

该接口复用现有 grant-subject helper 和 F038 懒加载结构。它校验登录态和当前 tenant scope，并按“创建者将获得的 owner 关系”的现有细粒度配置判断其是否具备权限管理能力；不新增 web-menu、角色名或另一套 create capability 门禁。不满足 prospective-owner 管理能力时拒绝返回候选。候选范围限定当前 tenant，禁止接受客户端 tenant_id。创建参数仍在后端逐项校验，候选结果不是授权依据。

创建页可授予模型不新增路径，扩展现有 `GET /api/v1/permissions/relation-models/grantable`：默认模式仍要求 `object_type + object_id`；`creation=true` 时只接受 `object_type`、禁止依赖不存在的资源 ID，按 prospective owner 的现有 permission IDs 过滤 relation models。原有编辑调用方与响应形状不变。

不能直接复用 `/api/v1/user/list`：该接口面向组织/用户组管理员，普通资源创建者可能无权访问，其数据范围也不是资源授权候选范围。编辑阶段仍使用带真实资源 ID 的现有候选接口。

现有 `_list_knowledge_space_grant_users`、`_grant_departments_*`、`_list_knowledge_space_grant_user_groups` 从 `permission/api/endpoints/resource_permission.py` 下沉为 `permission/domain/services/grant_subject_query_service.py` 的 `GrantSubjectQueryService` 能力。新接口、现有资源权限接口和 `ChannelAuthorizationService` 只调用该 Service，禁止 domain service 继续反向 import API endpoint；底层取数经 repository/既有 DAO，Service 不写 ORM 查询。两类 creation application service 在创建前调用该 Service 的批量校验能力，只验证当前 tenant 对象存在性、可授予模型与非用户 owner 约束；创建后仍由权威授权 Service 再次校验并写入，不把候选结果当作授权依据。

relation-model 配置读取从 endpoint 模块拆到 `permission/domain/services/relation_model_store.py`。`ResourceAuthorizationService`、`GrantSubjectQueryService` 与 endpoint 共用该纯读取能力，domain 层不得为复用配置而反向 import API endpoint。

同理，知识空间现有 `authorize_resource` endpoint 内的 grant-tier 校验、F033 scope 校验、tuple 写入、relation-model binding 持久化与通知编排下沉为 `permission/domain/services/resource_authorization_service.py` 的 `ResourceAuthorizationService.authorize(...)`。该方法成功返回 `None`，业务失败抛出现有 `BaseErrorCode`，tuple 写失败归一为现有 `PermissionTupleWriteError`；不返回 HTTP response 对象。原 endpoint 只负责 HTTP DTO/response 转换，知识空间 creation application service 调用同一 Service；创建前校验失败直接拒绝，资源已创建后的授权 `BaseErrorCode` 才折叠为 `initial_permission_result.failed`。禁止直接调用底层 `PermissionService.authorize()` 绕过 binding 和细粒度校验。频道仍使用 F026 `ChannelAuthorizationService`，不走通用 Service。

### 4.6 模块职责

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| `client/pages/knowledge` | 知识空间 create/settings 路由、表单与保存编排 | 不直接调用 HTTP，不实现授权校验 |
| `client/pages/Subscription` | 频道 create/settings 路由、业务表单迁移与保存编排 | 不复制频道授权规则，不重放创建副作用 |
| `client/components/permission` | 无副作用的授权列表、候选选择、草稿 diff | 不发 HTTP，不保存服务端权限 |
| `client/api/permission.ts` | 创建候选、关系模型、知识空间权限 API adapter | 不持有页面状态，不吞业务错误 |
| `client/api/channels.ts` | 频道详情、创建/更新及 F026 授权 API adapter | 不推导权限角色，不处理 403 跳转 |
| `GrantSubjectQueryService` | 普通资源创建/编辑共用的用户、部门、用户组候选范围与创建前批量校验 | 不写授权、不接受客户端 tenant_id、不 import API endpoint |
| knowledge/channel creation application service | 编排原 create service 与初始授权 | 不重复写 owner/成员/审计/订阅/同步副作用，不删除授权失败后的资源 |
| `relation_model_store` | 读取并缓存 relation-model 配置，供 domain service 与 endpoint 共用 | 不接收 HTTP DTO，不依赖 API endpoint |
| `ResourceAuthorizationService` / `ChannelAuthorizationService` | 授权、撤销、模型绑定、租户与细粒度能力校验 | 不拥有资源基本信息写入，不绕过 `PermissionService` |
| `KnowledgeSpaceService` / `ChannelService` | 资源 CRUD、私密转换与非创建者权限清理 | 不接收完整权限快照，不根据前端列表清理授权 |

旧的新建抽屉入口改为导航到 create 路由；旧“管理成员/授权管理”菜单项移除，原弹窗组件在无调用方后删除。编辑/频道设置菜单统一导航到 settings 路由，置顶、退出、删除/解散规则不变。

## 5. 已知坑与防护

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 现有权限 Tab 是点击即写，不具备统一页面的取消语义 | 取消表单后权限已经生效，新建阶段还会因没有资源 ID 无法调用 | `client/components/permission/PermissionListTab.tsx`、`PermissionGrantTab.tsx`：拆纯 UI 与 mutation adapter |
| 2 | 创建前没有资源 ID，但普通创建者通常也无权调用组织管理 `/user/list` | 预创建会留下孤儿资源；复用管理接口会让非管理员无法选人或扩大数据范围 | `GrantSubjectQueryService` + `GET .../creation-grant-subjects` |
| 3 | 现有频道候选 Service 反向 import permission API endpoint helper | 继续复用会扩大 Constitution C1 违规，未来 endpoint 重构会直接破坏 domain service | `channel_authorization_service.py:list_grant_*` 改调 `grant_subject_query_service.py` |
| 3a | 知识空间 authorize 的模型校验/binding/通知目前编排在 endpoint，不等于只写 FGA tuple | 创建流程若直接调 `PermissionService.authorize()` 会丢 relation-model binding 并绕过细粒度 grant-tier 校验 | `resource_permission.py:authorize_resource` 下沉 `ResourceAuthorizationService.authorize`，endpoint 与 creation service 共用 |
| 4 | `OwnerService.write_owner_tuple()` 默认是 best-effort | OpenFGA 短暂失败时资源仍已创建；若误当成原子成功，会重复创建或错误回滚 | `owner_service.py:write_owner_tuple` + `failed_tuples` 既有重试；创建结果按 §4.2 反馈 |
| 5 | 分享转私密的清理权威在后端，不在前端授权列表 | 前端逐条 revoke 会漏掉未加载/并发授权，并可能遗留 FGA tuple 或 binding | `KnowledgeSpaceService.update_knowledge_space`、`ChannelService.update_channel` |
| 6 | 频道仍有无 relation-model binding 的历史成员 fallback | 删除 fallback 或按角色名控制新 UI 会改变存量用户能力 | `ChannelAuthorizationService._actor_grant_permissions`；新页面只消费有效 permission IDs |
| 7 | “包含子部门”的一项 UI 授权可能对应不同 scope/多条底层关系 | 只按 subjectId 去重会误撤销另一条授权 | `PermissionDraft` 比较键保留 relation/modelId/includeChildren；authorize service 最终校验 |
| 8 | 资源 DB 与 OpenFGA 不在同一事务 | 授权失败后自动删资源可能和审计、成员、外部副作用再次竞态 | creation application service 返回资源 ID；仅重试现有 authorize API |
| 9 | 频道创建可能先触发情报源订阅并保存知识同步配置 | 权限失败后重放创建会重复外部调用或生成重复频道 | `ChannelService.create_channel`；恢复入口只执行 `ChannelAuthorizationService.authorize_channel` |
| 10 | 页面加载成功不代表提交时仍有权限 | 本地能力缓存会让已失权用户看似保存成功 | 服务端每次写实时校验；`client/api/request.ts` 统一处理 403，业务组件不加 403 分支 |
| 11 | relation 为 owner 不等于该授权对象就是资源创建者 | 把所有 owner 行锁死会禁止调整普通 owner；频道若据此补写 `knowledge_sync` 还会覆盖非创建者更新 | 仅服务端明确的 creator 行设置 `immutableCreator`；频道更新只在详情已返回 `knowledge_sync` 时回传该字段 |

## 6. 契约与依赖

### 6.1 Outgoing contracts

| 契约 | 形式 | 消费者 | 兼容/风险 |
|---|---|---|---|
| `POST /api/v1/knowledge/space` | 现有 HTTP；可选 `initial_permissions.grants` / `initial_permission_result` | client 知识空间创建页、存量调用方 | 未传新字段时保持原行为；不得让授权失败触发客户端重建资源 |
| `POST /api/v1/channel/manager/create` | 现有 HTTP；同形可选字段 | client 频道创建页、存量调用方 | 频道 ID 为 string；不得重放情报源订阅副作用 |
| `GET /api/v1/permissions/creation-grant-subjects` | 新增只读 HTTP；参数见 §4.5 | client 创建页权限选择器 | 只能返回当前 tenant 且具备 prospective-owner 管理能力的候选 |
| 四个 `/workspace/.../create|settings` 路由 | client 页面路由 | 左侧导航、资源 action menu、移动端入口 | 删除独立权限入口后，所有调用点必须迁移，否则产生死链 |
| `GrantSubjectQueryService.query_creation_subjects(...)` | 内部 async Python Service | permission endpoint、knowledge/channel creation endpoint | 参数范围改变会同时影响新建和存量授权候选 |
| `ResourceAuthorizationService.authorize(...)` | 内部 async Python Service | 通用 authorize endpoint、知识空间 creation application service | 必须保持现有 tuple/binding/通知/错误码行为，频道不得调用 |
| knowledge/channel creation application service `create(...)` | 内部 async Python Service | 两个现有 create endpoint | 只调用一次原 create service，再编排初始授权；不得重复 owner/成员/审计/订阅/同步副作用或接管 F026 授权语义 |

不新增数据库表、迁移、环境变量、Celery 任务、权限 ID、角色或错误码。

### 6.2 Incoming contracts

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F026 `ChannelAuthorizationService` | 内部授权 owner service | relation model、租户校验或补偿语义变化会改变频道初始授权结果 |
| F033 部门空间范围 | 版本契约 | 本次创建页不覆盖管理后台部门空间；未来纳入时必须恢复绑定部门子树/user_group 禁用规则 |
| `PermissionService` / OpenFGA | `ResourceAuthorizationService` 和 F026 下层依赖 + 第三方服务 | OpenFGA 不可用时 owner/初始授权按现有失败队列和错误码处理，不能宣称跨存储原子成功 |
| relation-model 配置 | Config + FineGrainedPermissionService | 管理 permission ID 或 grant_tier 变化会改变权限区显隐和可授予模型，前端不得缓存角色名映射 |
| `KnowledgeSpaceService` / `ChannelService` create/update | 内部资源 Service | 返回 ID 类型不同；私密清理语义若变化必须重新评审 D5 |
| Bisheng Information | 频道创建的外部 HTTP 副作用 | 授权重试不得重放频道创建和信息源订阅 |
| `client/api/request.ts` | client 响应拦截器 | 403/业务错误管线变化会影响失权提示，页面不能自行复制处理分支 |

上述归属和依赖登记到版本级 `release-contract.md`；本 Feature 只编排 owner service，不接管其领域写行为。

## 7. 验证策略

### 7.1 自动测试

- 前端单元测试：权限区能力显隐、私密/分享条件字段、默认审核、草稿 diff、创建者不可删除、移动端堆叠、部分失败恢复不重复创建。
- API 测试：创建参数兼容、初始授权成功、跨租户对象拒绝、非法 owner 拒绝、频道 relation model 范围、资源已创建但授权失败的结构化结果。
- 服务集成测试：分享转私密后仅保留创建者；再次转分享不恢复授权；提交时失权被拒绝。
- E2E：覆盖 spec AC-01～AC-25，重点验证仅编辑者不可见权限区、创建后授权失败恢复和旧独立入口消失。

### 7.2 手动验证

1. 启动 API：`cd src/backend && uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log`；启动 client：`cd src/frontend/client && pnpm dev`。
2. 使用三类测试账号：A 具备资源创建+权限管理能力，B 仅 `edit_space`/频道编辑能力，C 只读；不在文档保存凭据。
3. 访问 `/workspace/knowledge/create`、`/workspace/channel/create`；创建后访问对应 `/settings` 路由。A 可见权限区，B 只见可编辑业务字段，C 不见入口。
4. 桌面端对照 Figma 检查知识空间单栏、频道双栏和固定底栏；浏览器宽度缩至 768px 以下检查单栏与完整能力。
5. A 打开设置页后，由另一管理账号撤销 A 的管理能力，再提交；确认服务端拒绝且重新加载后权限区消失。
6. 将含个人、部门、用户组授权的资源转私密，通过现有 `GET .../{resource_id}/permissions` 确认只剩创建者；再转分享确认不恢复。

实现后执行聚焦验证：

- `cd src/backend && uv run pytest test/permission test/knowledge test/channel -k "initial_permission or unified_permission"`
- `cd src/frontend/client && pnpm test:ci -- --runInBand`
- `cd src/frontend/client && pnpm typecheck && pnpm build`

### 7.3 可观测性

- 复用现有 API 错误日志与前端错误提示；新增创建后授权编排日志只记录 resource_type、resource_id、成功/失败数量和 request id，不记录成员名称或 ID 列表。
- 部分失败提示必须携带已创建资源上下文，便于用户恢复和服务端排查。

### 7.4 Spec 追踪

| Spec AC | 设计落点 |
|---|---|
| AC-01～AC-05 | §3 D1、§4.1、§4.6 |
| AC-06～AC-10 | §3 D4、§4.2、§5.4/§5.8 |
| AC-11～AC-16 | §3 D2/D3、§4.2～§4.4、§5.6/§5.7 |
| AC-17～AC-22 | §3 D5、§4.1～§4.4、§5.2/§5.3/§5.5 |
| AC-23～AC-25 | §1.2、§3 D3、§4.6、§6 |

## 8. 后续改进 / 不打算做的事

| 项目 | 本期不做的原因 | 重新考虑条件 |
|---|---|---|
| 资源设置与授权的跨存储原子事务 | DB 与 OpenFGA 无共同事务，强补偿会放大资源创建副作用 | 平台提供可靠 saga/outbox 且两个资源 owner 接受统一事务契约 |
| 邀请确认、待生效状态与审批通知 | 属 PRD §1.2，已由用户确认排除 | 单独立项并明确审批状态机、通知和超时规则 |
| 知识空间/频道授权写 API 统一 | F026 拥有频道 relation binding 与补偿语义，强行合并会越权 | 两领域形成统一 relation model、错误码和事务边界 |
| 部门授权多记录归并 | 底层现状包含 scope 差异，本期只统一 UI | 权限模型提供稳定的部门授权聚合 ID 与迁移方案 |
| 管理后台部门空间创建页改造 | 本期明确只覆盖 client 普通知识空间/频道 | 产品将管理后台创建流程正式纳入同一 Spec |

## 9. 变更历史

| 日期 | 变更 |
|---|---|
| 2026-08-07 | 初版：确定完整页面、本地权限草稿、现有写链路与后端私密清理边界。 |
| 2026-08-07 | 设计确认前调整：现有创建请求携带 `initial_permissions.grants`，后端创建后批量授权；原六个只读路径收敛为一个创建阶段候选查询接口。 |
| 2026-08-07 | 评审修订：候选查询下沉共享 Service；明确现有失败语义；补齐坑、契约、风险、手动验证与延后原因。 |
| 2026-08-07 | tasks 拆解校正：补齐创建候选响应形状和创建前批量校验边界，不改变已确认外部契约。 |
| 2026-08-07 | 实施前契约冻结：原 create service 独占 owner/成员/副作用；授权 Service 使用 `BaseErrorCode`；扩展现有 grantable relation-model 路径的 creation 模式，不新增第二个只读路径。 |
| 2026-08-07 | 实现同步：relation-model 配置下沉为 domain 可复用读取能力；澄清 creation application service 不接管 owner；仅真实创建者行不可编辑，频道同步配置仅对真实创建者回传。 |
