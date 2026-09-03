# Design: 知识空间与频道统一权限设置入口（F048 适配）

> 本文是当前实现方案的唯一设计真相：[spec.md](./spec.md) 定义 What，本文定义 Why/How，
> [tasks.md](./tasks.md) 记录执行。实现变化必须覆盖更新本文档。

**版本**: v3.0.0-beta1
**最后更新**: 2026-08-17

## 1. 目标与非目标

### 1.1 目标

- 将普通知识空间和频道的新建/编辑从抽屉与独立权限弹窗整合为完整设置页。
- 创建阶段维护 F048 初始 Grant 草稿；资源与 protected owner 成功后，通过唯一 F048 runtime 应用普通 Grant。
- 编辑阶段复用 F048 context、roster、grantable models 和 mutation，只提交用户触碰的变化，并反馈真实部分成功状态。

### 1.2 非目标

- 不恢复 F044 的 relation、permission_id、binding JSON、旧授权 Service/API 或旧 relation selector。
- 不修改 F048 Catalog、Grant、投影、OpenFGA model、正式迁移和顶级资源固定 `CUSTOM` 的语义。
- 不给知识空间/频道提供权限 mode 切换；不改管理后台部门空间；不纳入邀请确认和文件审批。
- 不宣称业务数据库与 F048/OpenFGA 构成跨存储事务。

## 2. 关键约束与 Constitution Check

遵循 `docs/constitution.md` C1–C8 和本版本 `release-contract.md`；本功能额外受以下约束：

1. F048 是唯一资源权限执行面，业务代码不读取旧权限事实。
2. 创建前没有资源，不得伪造 `VerifiedPermissionTarget` 或调用带资源 ID 的权限接口。
3. `knowledge_space` 和 `channel` 固定 `CUSTOM`，页面不渲染 `ModeHeader`。
4. 资源与 protected owner 先成功；普通 Grant 失败保留资源并允许前向重试。
5. `private/review/public`、广场发布、加入审核与成员表由 knowledge/channel 业务域拥有。
6. 创建候选不接受客户端 tenant_id；部门继续懒加载与服务端搜索。
7. 重复创建必须持久幂等，不能只依赖浏览器按钮或 Redis 短锁。
8. 只改 client SPA；不新增 Recoil、UI 或状态库。
9. 新增可空请求键和唯一索引必须兼容 MySQL/DM8；Alembic 只做 DDL。

### 2.1 Constitution Check

| 条款 | 结论与保证 |
|---|---|
| C1 | 通过。Endpoint 委托业务 Service；业务模块只依赖 `permission.application`；权限模块不查询业务 ORM |
| C2 | 通过。仅普通字符串列和组合唯一索引；无 JSON/MySQL 专属 SQL |
| C3 | 通过。tenant 自动注入；候选不接受 tenant_id；唯一键包含 tenant |
| C4 | 通过。protected owner、预览和普通 Grant 全走 F048；不恢复旧 relation fallback |
| C5/C6 | 通过。优先复用 250 模块错误；不新增密钥或明文配置 |
| C7 | 通过。页面经 client `api/` adapter；hook/组件不直接使用 request |
| C8 | 通过。幂等事实存业务数据库；不使用本地文件共享状态 |

## 3. 方案对比与选定

### D1. 完整页面替代 Drawer 和资源专属权限弹窗

- **备选**：A. 扩展现有 Sheet；B. 新增完整 create/settings 路由。
- **选定**：B。
- **原因**：F044 UI 目标已确认；两个 Drawer 已包含复杂滚动、触摸穿透、嵌套弹层防护，继续扩展会放大移动端问题。
- **何时重新考虑**：产品明确要求保留抽屉并提供完整窄屏权限交互稿。

路由：

- `/workspace/knowledge/create`
- `/workspace/knowledge/space/:spaceId/settings`
- `/workspace/channel/create`
- `/workspace/channel/:channelId/settings`

### D2. 页面级权限草稿，不复用即时写入行为

- **备选**：A. 嵌入当前 `PermissionDialog/PermissionGrantTab`，每次操作立即写入；B. 抽取无副作用 picker/roster，由页面统一保存。
- **选定**：B。
- **原因**：新建没有资源 ID；编辑要求取消不生效和并发反馈。即时 mutation 无法满足统一保存。
- **何时重新考虑**：后端提供覆盖业务字段与 Grant 的单一事务命令，且产品取消统一保存/取消。

通用 `PermissionDialog` 继续服务其他资源类型；知识空间/频道移除独立入口，但共享展示组件不复制。

### D3. 业务域创建入口调用 F048 prospective-owner 协议

- **备选**：A. 预创建隐藏资源后复用资源 API，会留下孤儿和副作用；B. permission endpoint 仅按 resource_type 枚举，会绕过业务创建资格；C. knowledge/channel 先验证本域创建资格，再调用共享 application protocol。
- **选定**：C。
- **原因**：业务域拥有创建能力与配额事实，权限域拥有 Catalog、owner 可授予边界和主体 canonicalization，符合 C1/C4。
- **何时重新考虑**：平台建立权威的统一资源创建 capability gateway。

业务入口返回同形契约：

- `GET /api/v1/knowledge/space/creation-permission-context`
- `GET /api/v1/channel/manager/creation-permission-context`
- 各自同前缀的 `/creation-grant-subjects/users`、`user-groups`、`departments/children`、`departments/search`、`departments/{id}/path-tree`

Endpoint 不查组织 ORM。业务 Service 校验创建资格后调用 `ProspectiveGrantApplicationPort`；后者以当前 tenant、资源类型和未来 protected owner model 返回 active grantable models，并复用 subject directory。

### D4. protected owner 后调用 F048 initial Grant application

- **备选**：A. 前端创建后再请求公开 `grants:mutate`，网络中断下结果不完整；B.业务 Service 在 `authorize_created` 后调用共享 `InitialGrantApplicationPort`；C. 将普通 Grant 塞进 owner create projection，扩大资源生命周期事务。
- **选定**：B。
- **原因**：保持一次创建请求和唯一 F048 写路径，同时明确两阶段事实；普通 Grant 失败不回滚资源或 owner。
- **何时重新考虑**：F048 提供正式的 lifecycle + ordinary grants 统一 durable command。

该协议只接受内部 verified target、actor、expected Catalog release 和 ADD-only 草稿；不接受 HTTP dict、MOVE/REMOVE，也不跳过真实资源上的 manage/grantable/version 校验。

### D5. 业务表保存创建幂等键

- **备选**：A. 仅禁用按钮，挡不住超时重试；B. Redis 短锁，业务提交后缓存前崩溃仍会重复；C. knowledge/channel 表保存可空请求键和 payload hash。
- **选定**：C。
- **原因**：资源本身是持久结果；重试可返回同一资源并恢复 owner/Grant，不依赖进程或 TTL。
- **何时重新考虑**：平台建立通用持久 command/idempotency ledger。

统一页面生成 UUID 并在本页生命周期稳定复用；payload hash 覆盖业务创建字段和规范化后的初始权限草稿，
相同键但任一字段不同均返回冲突。旧调用不传键仍兼容；失败后要修改授权草稿时进入设置页产生新的 mutation，
不得用同一创建请求键改写创建命令。

### D6. 编辑按业务设置 → reload context → Grant mutation 串行保存

- **备选**：A. 并行，private 清理与 Grant 写入竞争；B. 权限先写，业务失败后留下意外授权；C. 业务先写，再按最新 context 写 touched mutations。
- **选定**：C。
- **原因**：private 转换由业务 Service 权威清除普通来源；串行执行可给出准确部分成功状态。
- **何时重新考虑**：出现统一事务命令，或产品拆成两个明确保存按钮。

- 保存为 private：只提交业务更新；后端清理普通来源，前端丢弃权限草稿并 reload。
- 其他情况：业务成功后重新取 context；仍有 manage 且版本有效才提交 mutation。
- 业务失败不写 Grant；Grant 失败不伪报业务失败，提示部分成功并 reload。

### D7. private 复用现有 F048 source 清理

- **备选**：A. 前端按 roster 逐条 REMOVE，会遗漏分页外与并发来源；B. 复用 knowledge/channel Service 的 `remove_ordinary_sources`。
- **选定**：B。
- **原因**：当前后端已覆盖 direct、department、group、subscription 等普通来源，并保留 protected owner；投影提交后才清 membership。
- **何时重新考虑**：产品要求 private 保留某类普通来源，且先明确该来源的 Owner 与保留规则。

### D8. 以 feat/2.6.0 实际页面为 UI 基线，将权限运行时替换为 F048

- **备选**：A. 整体保留 2.6 页面、旧 permission API 和后端实现；B. 不使用 2.6 实际页面，仅根据 Spec 在 beta1 重新设计；C. 先合入 `origin/feat/2.6.0@901fa1ada` 的完整页面与交互，保留其布局、组件、文案和移动端行为，再定点替换 F044 权限数据结构、API 和状态逻辑。
- **选定**：C。
- **原因**：A 会恢复已退役的 relation、`permission_id` 和 binding 运行时，已试合并会导致 7 个后端导入错误和 66 个前端类型错误；B 容易丢失 2.6 已落地的视觉、交互和窄屏细节。C 同时保证 UI 目标不漂移和 F048 作为唯一权限执行面。
- **何时重新考虑**：产品提供了取代 2.6 页面的新交互稿，或 2.6 页面结构无法在不恢复旧权限运行时的前提下适配 F048。

合并冲突按下表裁决，不对整个文件统一选 `ours`/`theirs`：

| 冲突内容 | 权威来源 | 处理原则 |
|---|---|---|
| 完整页面布局、操作区、文案、移动端交互 | `origin/feat/2.6.0` 的 F044 UI | 保留实际 JSX/样式/交互，只做 F048 接口适配所必需的改动 |
| relation、`permission_id`、binding、旧授权 API/Service | beta1 F048 | 删除 2.6 旧实现，改为 context/grants/grantable-models/`grants:mutate` |
| protected owner、多来源、version、Catalog release、投影 | beta1 F048 | 严格保留 F048 契约，禁止 UI 用旧四档关系推导 |
| 自动标签、频道知识同步、网站抓取队列 | beta1 与 2.6 都已存在的业务能力 | 不视为 beta1 独有；合并后按字段、副作用和页面交互逐项回归 |
| F045 个人邀请确认、F046 文件变更审批 | COFCO 专项分支 | 不在 `feat/2.6.0` 中，本特性不合入、不补开发 |

## 4. 系统现状（接手必读）

### 4.1 当前调用链

**知识空间创建**：`knowledge/index.tsx` → `CreateKnowledgeSpaceDrawer` → `createSpaceApi` → `POST /api/v1/knowledge/space` → `KnowledgeSpaceService.create_knowledge_space` → 保存资源 → F048 `authorize_created` 建 fixed CUSTOM + protected owner。

**知识空间编辑**：同一 Drawer → `updateSpaceApi` → `KnowledgeSpaceService.update_knowledge_space`。转 private 时 `clear_space_authorization_for_private/remove_ordinary_sources` 清普通来源，再清非创建者 membership。独立 `KnowledgeSpaceShareDialog/PermissionDialog` 即时管理 Grant。

**频道创建**：`Subscription/index.tsx` → `CreateChannelDrawer` → `createManagerChannelApi` → `ChannelService.create_channel` → 信息源订阅 → 保存频道 → F048 `authorize_created` → creator membership → 知识同步。

**频道编辑**：同一 Drawer → `updateChannelApi` → `ChannelService.update_channel`。转 private 时 F048 `remove_ordinary_sources` 后清 membership/通知。独立 `ChannelPermissionDialog` 包装 F048 `PermissionDialog`。

**F048 UI**：`PermissionDialog` 读取 context、roster/my-permissions；`PermissionGrantTab` 读取模型/候选并直接 mutate；候选 endpoint 必须先对真实资源检查 manage，不能用于创建前。顶级空间/频道固定 CUSTOM。

### 4.1.1 feat/2.6.0 UI 迁移基线

以 `origin/feat/2.6.0@901fa1ada` 为可追溯基线，合并后优先保留：

- `pages/knowledge/SpaceSettings/KnowledgeSpaceSettingsPage.tsx` 及 `useKnowledgeSpaceSettingsForm.ts`：空间创建/编辑同页、自动标签区、固定操作区和部分失败页。
- `pages/Subscription/ChannelSettings/ChannelSettingsPage.tsx`、`ChannelBusinessSettings.tsx` 及 `useChannelSettingsForm.ts`：频道完整页、抓取预览/队列、知识同步和部分失败页。
- `components/permission/PermissionDraftPanel.tsx`、`PermissionDraftPickerDialog.tsx`、`UnifiedPermissionControls.tsx`：权限区的可视结构和交互原语。

上述文件中的 `RelationModel`、relation、`permission_ids`、旧 authorize API 和旧 `PermissionDraftRow`
只是待替换适配层，不是权限真相。实现时保留 UI 结构，将其输入/输出改接 F048 `PermissionDraft`。

### 4.1.2 必须保留的业务能力

| 能力 | 具体功能 | 主要代码/契约 |
|---|---|---|
| 知识空间自动标签 | 租户开关决定是否显示；创建/编辑可开启，选择标签库模式并预览标签，或使用自定义标签文本/文件；提交 `auto_tag_enabled`、`auto_tag_library_id`、`auto_tag_custom_tags` | beta1 `CreateKnowledgeSpaceDrawer.tsx`、`api/knowledge.ts`；2.6 已迁入 `KnowledgeSpaceSettingsPage` |
| 频道知识同步 | 配置主频道和子频道文章自动同步到指定知识空间，并随频道创建/更新提交 `knowledge_sync.main/subs` | `CreateChannel/KnowledgeSyncSection.tsx`、`SyncSpaceItem.tsx`、`api/channels.ts` |
| 网站抓取队列 | 在频道信息源中输入网址后异步抓取/预览，展示排队、进行中、成功/失败状态，支持取消、错误反馈和将成功结果加入信息源；抓取进行中阻止提交 | `hooks/useCrawlQueue.ts`、`CrawlQueuePanel.tsx`、`CrawlPreviewDialog.tsx` |

### 4.2 目标创建数据流

```text
create route
 → 业务创建资格 + prospective-owner context
 → tenant-scoped candidates
 → local PermissionDraft（无服务端写）
 → POST create(resource fields, request id, initial grants)
 → 幂等查找/创建业务资源
 → F048 authorize_created protected owner
 → InitialGrantApplicationPort ADD ordinary grants
 → success | resource_created_permission_failed
 → 进入资源或设置页恢复
```

重试步骤：按 tenant + creator + request ID 查资源；无记录才创建；唯一键竞争读取赢家；相同键但完整 payload hash 不同报冲突；相同载荷复用资源并以稳定派生 key 前向恢复 owner/initial Grant。

初始授权部分失败后只有两条明确路径：

| 场景 | 调用 | 幂等/并发语义 |
|---|---|---|
| 失败页立即重试，且未修改原草稿 | 使用原 `creation_request_id` 和完全相同 payload 重放原创建 POST | 后端返回已创建资源，用稳定派生 key 重试未完成的 initial Grant，不创建第二个资源 |
| 进入设置页、刷新页面或修改授权草稿 | 重新 GET context/grants，以服务端基线生成新 `grants:mutate` 请求 | 使用新 mutation idempotency key 和当前 resource/assignee version；不得改写原创建命令 |

不新增绕过 F048 的 `authorize`/“补权限”公开 endpoint。失败页如无法保证原 payload 规范化后完全相同，必须转入设置页走第二条路径。

### 4.3 目标编辑数据流

```text
settings route
 → detail + F048 context
 → if can_manage: paged roster + grantable models + candidates on demand
 → business form + PermissionDraft
 → save business
 → if private: backend cleanup + reload
 → else reload context + touched ADD/MOVE/REMOVE
 → reload detail/context/roster + exact result
```

### 4.4 页面与草稿

| 页面 | 布局 | 内容 |
|---|---|---|
| Knowledge create/settings | 居中单栏，最大约 648px | 基本信息、访问分享、自动标签、成员权限、固定操作区 |
| Channel create/settings | 桌面双栏、窄屏单栏 | 左侧信息源/筛选/子频道/知识同步，右侧访问分享/成员权限 |

使用 `@bisheng/ui`、语义字体/颜色 token 和主题类；禁止硬编码品牌/灰色、backdrop blur 和新 UI 库。

```ts
interface PermissionDraftAdd {
  clientKey: string;
  modelKey: string;
  subject: PermissionGrantSubjectInput;
  subjectName: string;
}

interface PermissionDraft {
  baselineResourceVersion: number | null;
  baselineCatalogReleaseId: number;
  existingChanges: Record<string,
    | { op: "MOVE"; assigneeId: string; expectedVersion: number; targetModelKey: string }
    | { op: "REMOVE"; assigneeId: string; expectedVersion: number }>;
  additions: PermissionDraftAdd[];
}
```

新建仅允许 additions；编辑变化必须携带 assignee version；protected/inherited/不可编辑项不能进 draft；未触碰 roster 不转换为 REMOVE；草稿只存页面内存，不进 Recoil/localStorage。

### 4.5 应用协议

`ProspectiveGrantApplicationPort`：从当前 Catalog 读取 owner 与可授予 active models；返回 release ID；按业务验证后的 tenant scope 查询候选；不创建 target、不 Check、不写 Grant。

`InitialGrantApplicationPort`：只接受 verified target；重新验证 grantable model、tenant/status/userset 与 Catalog；使用稳定 key 调 F048 durable mutation；返回实际 version/assignee。只有资源和 owner 已完成后的普通 Grant 错误可转换为部分成功；资源/owner 失败必须整体传播。

### 4.6 HTTP 契约

#### 4.6.1 创建前 context 与候选

| 资源 | Context | 候选路径前缀 |
|---|---|---|
| 知识空间 | `GET /api/v1/knowledge/space/creation-permission-context` | `/api/v1/knowledge/space/creation-grant-subjects` |
| 频道 | `GET /api/v1/channel/manager/creation-permission-context` | `/api/v1/channel/manager/creation-grant-subjects` |

两类资源的候选 endpoint 同形：

- `GET {prefix}/users?keyword=&page=1&page_size=50` → `{"data":[GrantUser],"total":number}`。
- `GET {prefix}/user-groups?page=1&page_size=50` → 分页用户组。
- `GET {prefix}/departments/children?parent_id=<optional>` → 当前层 `GrantDepartmentNode[]`。
- `GET {prefix}/departments/search?keyword=&limit=50` → `{"roots":[],"total_matches":number,"truncated":boolean}`。
- `GET {prefix}/departments/{id}/path-tree` → 用于定位已选部门的祖先路径树。

候选响应由 permission application 层按当前 tenant 和 active 状态 canonicalize；请求不接受
`tenant_id`。部门浏览只返回一层，搜索有上限，不提供全树一次加载。

资源创建继续使用原 URL：知识空间 `POST /api/v1/knowledge/space`，频道
`POST /api/v1/channel/manager/create`。以下字段是对原请求/响应的可选扩展，不替换原业务字段。

创建上下文：

```json
{"catalog_release_id":42,"can_configure_initial_permissions":true,"grantable_models":[{"key":"viewer","name":"查看者","level":1,"active":true}]}
```

创建请求在原字段外增加：

```json
{
  "creation_request_id":"uuid",
  "initial_permissions":{
    "expected_catalog_release_id":42,
    "grants":[{"model_key":"editor","subject":{"type":"department","id":"12","userset_relation":"subtree_member","include_children":true}}]
  }
}
```

`initial_permissions` 可省略且只允许 ADD；禁止 tenant/source/protected/level/resource version/assignee ID。

创建响应保持原资源字段位于 `data` 顶层，只追加可选结果，避免破坏既有调用方：

```json
{
  "id":"123",
  "name":"示例资源",
  "initial_permission_result":{"status":"success|failed","error_code":null,"resource_version":2}
}
```

无 grants 时结果可省略；failed 只表示本次原子普通 Grant mutation 未应用，resource + protected owner 已成功；
不回显完整主体或异常文本。后端保持旧 payload 和原资源响应形状；client adapter 只需读取新增可选字段。

#### 4.6.2 创建后 F048 编辑契约

资源路径统一为 `/api/v1/permissions/resources/{resource_type}/{resource_id}`：

| 方法与后缀 | 用途 | 关键并发字段 |
|---|---|---|
| `GET /context` | 资源模式、当前能力、Catalog/resource version | `catalog_release_id`、`resource_version` |
| `GET /grants?cursor=&page_size=` | 分页 roster 与每条来源 | `assignee_id`、`version`、protected/source；不得按用户合并 |
| `GET /my-permissions` | 页面具体动作能力 | 不以角色名/relation 替代 |
| `GET /grantable-models` | 当前 actor 可授予的 active model | 与 context Catalog release 对齐 |
| `POST /grants:mutate` | 原子提交 touched ADD/MOVE/REMOVE | expected resource/catalog/assignee version + mutation idempotency key |
| `GET /grant-subjects/users` | 用户分页/搜索 | `keyword`、`page`、`page_size` |
| `GET /grant-subjects/user-groups` | 用户组分页 | `page`、`page_size` |
| `GET /grant-subjects/departments/children` | 部门懒加载 | `parent_id` 可省略 |
| `GET /grant-subjects/departments/search` | 部门服务端搜索 | `keyword`、`limit` |

设置页不调用 mode-draft endpoint，因为知识空间和频道是 fixed `CUSTOM`。

### 4.7 数据库契约

| 表 | 新列 | 唯一范围 |
|---|---|---|
| knowledge | `creation_request_id VARCHAR(64) NULL`、`creation_payload_hash VARCHAR(64) NULL` | tenant + creator + type + request ID |
| channel | 同上 | tenant + creator + request ID |

存量不回填。hash 覆盖规范化后的完整创建命令（含初始 Grant）；初始 Grant 使用同一请求键派生的 projection
idempotency key保证相同网络重试不重复。修改失败草稿必须在设置页使用新的 mutation key。Alembic revision 只做 DDL。

### 4.8 模块职责

| 模块 | 做什么 | 不做什么 |
|---|---|---|
| create/settings pages | 路由、表单、部分成功恢复、保存编排 | 不直接 request，不鉴权或清权限 |
| `usePermissionDraft` | 本地草稿、touched mutation、只读防护 | 不 HTTP，不持久化 |
| permission views | roster、模型、主体选择共享展示 | 不决定创建资格，不自动提交 |
| client api adapters | F048 编辑 API、创建上下文/候选、envelope 映射 | 不持有页面状态 |
| knowledge/channel Service | 创建资格、CRUD、幂等、private 规则、初始权限编排 | 不查询 F048 SQL/OpenFGA，不构造 tuple |
| Prospective port | owner 策略预览与 tenant directory | 不加载业务资源，不写权限 |
| Initial Grant port | 真实 target 的 ADD-only F048 mutation | 不创建/删除资源，不返回 HTTP response |
| F048 runtime | Catalog、Grant、source、version、projection、OpenFGA | 不拥有业务字段 |

## 5. 已知坑 / 反直觉事实

| # | 事实 | 不知道的后果 | 处理位置 |
|---|---|---|---|
| 1 | 空间/频道固定 CUSTOM | 错误显示 mode switch 并调用必失败 API | page 不渲染 ModeHeader；`FIXED_CUSTOM_TYPES` 不改 |
| 2 | PermissionGrantTab 当前即时写 | 取消后权限已生效；新建无 ID | presentational views + `usePermissionDraft` |
| 3 | 创建前无 verified target | 伪造 target 违反 C4，预创建产生孤儿 | D3 prospective protocol |
| 4 | owner 可授予范围随 Catalog 变 | 页面旧模型可能过期 | context 携带 release；提交再校验 |
| 5 | owner create/每次 mutation 推进 resource version | 使用列表快照稳定冲突 | 后端创建后加载 target；编辑业务保存后 reload context |
| 6 | private 后端已清所有 ordinary sources | 前端 mutation 会竞争或写回 | private 分支丢草稿并 reload |
| 7 | protected owner 与普通 owner 可并存 | 合并角色行会丢来源或误删 | roster 按 assignee/source，protected 锁定 |
| 8 | 同一用户可来自 direct/department/group | 按 user 去重会误判完全失权 | 按 assignee/source 操作 |
| 9 | 频道落库前可能订阅外部信息源 | 数据库 key 不能回滚外部调用 | 保留“已订阅则跳过”；异常真实失败 |
| 10 | beta1 和 2.6 都有自动标签、知识同步和抓取队列，但空间功能分别位于 Drawer 与完整页 | 整文件选 ours/theirs 会丢 UI 或字段/副作用 | D8 逐项裁决；§4.1.2 功能回归 |
| 11 | 403 由 interceptor 统一处理 | 页面分支形成双跳转 | 只处理 domain partial/conflict |
| 12 | 不稳定 localize/callback 曾触发表单重复初始化 | 请求循环、覆盖输入 | primitive effect deps、稳定 adapter、请求次数测试 |
| 13 | 部门必须懒加载 | 大租户冻结和越权放大 | children/search/path-tree |
| 14 | request ID 不替代 F048 projection idempotency | 资源不重复但 Grant 可能重复 | owner 与 initial mutation 各用稳定 key |

## 6. 对外契约与依赖

### 6.1 本特性提供

| 契约 | 形式 | 消费方 |
|---|---|---|
| 四个 create/settings 路由 | client route | 空间列表/详情、频道订阅页/菜单 |
| 两类 creation context/candidates | Design §4.6.1 的 HTTP GET 与同形响应 | client 权限草稿 |
| 扩展后的两类创建请求/部分成功响应 | Design §4.6.1 的 HTTP POST/JSON | client 与既有调用方 |
| 失败后前向重试 | 原创建 POST 同键同 payload 重放，或 Design §4.6.2 F048 mutation | client 失败页/设置页 |
| `ProspectiveGrantApplicationPort` | Python protocol | knowledge/channel Service |
| `InitialGrantApplicationPort` | Python protocol | knowledge/channel Service |

### 6.2 本特性依赖

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F048 active Catalog/owner | runtime | 未就绪必须 fail closed，不能伪造模型 |
| F048 `authorize_created` | Python protocol | 必须成功才能返回可恢复资源 |
| context/roster/grantable/mutate | HTTP/Python | resource/catalog/assignee version 不可丢 |
| subject directory | application port | tenant 与 active 状态必须 canonicalize |
| knowledge/channel create/update | business contract | 保留自动标签、信息源、筛选、同步、通知副作用 |
| bisheng-information | 第三方 HTTP | 频道创建外部订阅失败不能伪报资源成功 |
| MySQL/DM8 | 数据库 | 组合唯一索引与 nullable 行为需双库验证 |
| `@bisheng/ui`/i18n | frontend | 三语言同 PR，不新增库 |

### 6.3 兼容性

- 原创建 URL 不变，新字段可选；旧调用不传 request ID/grants 继续成功。
- 现有 F048 endpoint 不改；统一页面只是新消费者。
- `PermissionDialog` 保留给其他资源；只删除无调用方的空间/频道 wrapper。
- 新 i18n key 同时写 en、zh-Hans、ja；不手改 api_errors 生成物。

## 7. 测试与可观测

### 7.1 自动化

- 权限 application：prospective owner、tenant scope、ADD-only、Catalog/version、canonical subject。
- 业务 Service/API：两类创建、重复 request/hash 冲突、owner 失败、普通 Grant 部分失败/重试、旧 payload。
- 前端：草稿 ADD/MOVE/REMOVE、protected、多来源、无 manage 隐藏、冲突、部分成功、移动布局。
- E2E：空间/频道创建并授权 user/department/group、初始授权失败、编辑并发、private、窄屏。
- 门禁：backend ruff/pytest/arch-guard；frontend lint/typecheck/check-i18n；DM8 中央回归。

### 7.2 手动验证

启动 API 与 client 后访问：

- `http://localhost:4001/workspace/knowledge/create`
- `http://localhost:4001/workspace/knowledge/space/<id>/settings`
- `http://localhost:4001/workspace/channel/create`
- `http://localhost:4001/workspace/channel/<id>/settings`

分别使用创建者、仅 edit、仅 visible、manage 被撤销的同租户测试账号；再以另一租户账号验证候选隔离，不在文档中固化账号或密码。验证 direct/department/group、部分失败恢复、private 清理和 390px 布局，并回归自动标签、知识同步与抓取队列。开发命令以 `src/backend/AGENTS.md` 和 `src/frontend/client/AGENTS.md` 当前记载为准；真实 F048/OpenFGA 与 DM8 场景进入专用集成环境。

### 7.3 可观测性

结构化记录 `resource_type`、request ID、resource ID、resource_created、owner_projection_status、initial_grant_status、permission_error_code；不记录主体名称、完整草稿或异常正文。F048 operation/idempotency/projection 指标沿用现有观测，不建第二套成功口径。

## 8. 后续改进 / 不打算做的事

- 不抽象跨资源万能表单：两类业务差异大，只共享权限草稿与布局原语。
- 不建立平台级通用 command ledger：两个业务表请求键是当前最小持久真相。
- 不开放顶级资源 INHERIT；若需要必须先修改 F048 Spec/Contract。
- 不保留旧独立权限入口作为 fallback，避免双权限 UI。
- 不把创建草稿存浏览器；跨会话草稿需另起服务端实体设计。

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-08-14 | 初版，以 F048 重建并保留 F044 UI 目标 | 用户确认 Discovery 与 Spec |
| 2026-08-14 | 改为先合入 2.6 实际 UI 再替换 F044 权限契约；补齐冲突裁决、HTTP 和失败重试契约 | Design 评审与用户确认实施顺序 |
