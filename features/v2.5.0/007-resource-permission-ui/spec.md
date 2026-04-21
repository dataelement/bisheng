# Feature: 资源权限管理前端

> **前置步骤**：本文档编写前必须已完成 Spec Discovery（架构师提问），
> 确保 PRD 中的不确定性已与用户对齐。

**关联 PRD**: [2.5 权限管理体系改造 PRD §3.3](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)、[2.5 技术方案 §4](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20技术方案.md)
**优先级**: P1
**所属版本**: v2.5.0

---

## 范围界定

**IN**:
- 前端资源授权对话框（三类授权主体：用户/部门/用户组）
- 授予权限 UI：选择主体类型 → 搜索/选择主体 → 选择权限级别（viewer/editor/manager）
- 撤回权限 UI：从权限列表中移除授权（二次确认）
- 权限级别徽章：在资源列表页显示当前用户的权限级别（viewer/editor/manager/owner）
- 前端 API 封装层 `src/controllers/API/permission.ts`（包装 F004 的后端 API）
- 前端 `usePermissionLevels` Hook：通过 batch check 获取当前用户对资源的权限级别
- 后端 `get_resource_permissions` 富化：解析 FGA 元组 → 查 user/dept/group 名字 → 返回结构化格式（注：此修改为 F004 `PermissionService` 的**兼容性增强**——不改变方法签名和输入参数，仅填充 `ResourcePermissionItem` 已有的可选字段 `subject_name`。经 Spec Discovery 确认，不属于领域对象越界）
- 适用资源类型：knowledge_space、workflow、assistant、tool、dashboard（5 种有 Platform 前端列表页的类型）。channel 类型组件层面已支持（通过 resourceType 参数），但 Platform 前端当前无 channel 独立列表页，页面集成待 channel 列表页上线后处理
- 通用权限业务组件目录 `src/components/bs-comp/permission/`
- i18n 新增 `permission` namespace（zh-Hans/en-US/ja）

**OUT**:
- 后端权限 API（check/authorize/list_objects）→ F004-rebac-core（已完成）
- 后端权限执行（业务模块中的 check 调用）→ F008-resource-rebac-adaptation
- 文件夹级权限 UI（知识库文件夹）→ 随 F008 知识库适配一起处理
- 继承权限展示（inherited from parent）→ 随 F008 处理，F007 types 预留字段
- 资源列表 API 返回 permission_level 字段 → F008 各模块适配时添加
- 链接分享功能 → 已有实现，F007 仅保留 Tab 占位

**关键决策（已确认）**:
- AD-09: 后端富化 `get_resource_permissions`（Spec Discovery 确认）
- AD-10: 前端 batch check 获取徽章数据（Spec Discovery 确认）
- AD-11: 继承权限 UI 不在 F007 范围（Spec Discovery 确认）

**关键文件（预判）**:
- 新建: `src/frontend/platform/src/controllers/API/permission.ts`
- 新建: `src/frontend/platform/src/components/bs-comp/permission/`（10 个组件文件）
- 新建: `src/frontend/platform/public/locales/{zh-Hans,en-US,ja}/permission.json`
- 修改: `src/backend/bisheng/permission/domain/services/permission_service.py`（get_resource_permissions 富化）
- 修改: 4 个资源列表页（KnowledgeFile, apps, tools, Dashboard）。channel 无前端列表页，暂不集成

**关联不变量**: INV-3, INV-5, INV-7

---

## 1. 概述与用户故事

F007 是 v2.5 权限体系改造的前端核心组件。它提供通用的资源权限管理对话框和权限级别徽章，供所有资源类型（知识空间、工作流、助手、工具、频道、仪表盘）复用。后续 F008 各资源模块适配时，通过传入 `resourceType` + `resourceId` 即可接入权限管理 UI。

### 用户故事

**US-01 资源管理者**：作为资源的 owner 或 manager，我期望能在资源操作菜单中打开权限管理对话框，将资源授权给指定用户、部门或用户组，并能查看和撤回已有的授权关系，以便灵活控制资源协作范围。

**US-02 普通用户**：作为普通用户，我期望在资源列表页看到每个资源上标注的权限级别徽章（owner/manager/editor/viewer），以便快速了解自己对各资源的操作权限。

**US-03 受限用户**：作为仅有 viewer 权限的用户，我期望看不到编辑、删除、权限管理等操作按钮，避免误操作或困惑。

---

## 2. 验收标准

### AC-01: 权限管理对话框打开与结构

- [ ] 在资源操作菜单中点击"权限管理"，弹出 Dialog（max-width 680px）
- [ ] Dialog 标题显示"权限管理 - {资源名称}"
- [ ] Dialog 包含 3 个 Tab：当前权限、添加权限、链接分享（占位，disabled）
- [ ] 默认展示"当前权限"Tab

### AC-02: 当前权限列表展示

- [ ] 调用 `GET /api/v1/resources/{type}/{id}/permissions` 获取权限列表
- [ ] 表格列：主体类型图标（用户/部门/用户组）、主体名称、权限级别 Badge、操作列
- [ ] 权限级别使用 PermissionBadge 组件展示（4 色区分）
- [ ] owner 条目不显示撤回按钮
- [ ] 后端返回格式为 `[{subject_type, subject_id, subject_name, relation, include_children}]`（AD-09 富化）
- [ ] 加载中展示 loading 状态，加载失败展示错误提示

### AC-03: 通过"用户"方式授予权限

- [ ] 在"添加权限"Tab 选择"用户"主体类型
- [ ] 搜索框支持按用户名模糊搜索（300ms 防抖），调用 `GET /api/v1/user/list`
- [ ] 搜索结果列表支持多选（Checkbox）
- [ ] 选择权限级别（viewer/editor/manager）后点击提交
- [ ] 调用 `POST /api/v1/resources/{type}/{id}/authorize`，grants 数组包含 `subject_type: "user"`
- [ ] 成功后 Toast 提示，自动切换到"当前权限"Tab 并刷新列表

### AC-04: 通过"部门"方式授予权限

- [ ] 在"添加权限"Tab 选择"部门"主体类型
- [ ] 展示部门树（调用 `GET /api/v1/departments/tree`），支持展开/折叠
- [ ] 每个部门节点可勾选（Checkbox）
- [ ] 默认勾选"包含子部门"选项（`include_children: true`）
- [ ] 授权 payload 包含 `subject_type: "department"`, `include_children: true`
- [ ] 成功后行为同 AC-03

### AC-05: 通过"用户组"方式授予权限

- [ ] 在"添加权限"Tab 选择"用户组"主体类型
- [ ] 调用 `GET /api/v1/group/list` 获取用户组列表
- [ ] 支持搜索过滤和多选
- [ ] 授权 payload 包含 `subject_type: "user_group"`
- [ ] 成功后行为同 AC-03

### AC-06: 修改权限级别

- [ ] 在"当前权限"列表中，非 owner 条目的权限级别列显示为可点击的 Select 下拉
- [ ] 下拉选项：viewer / editor / manager（当前级别为选中态）
- [ ] 选择新级别后，调用 `POST /api/v1/resources/{type}/{id}/authorize`，同时发送 revokes（旧关系）+ grants（新关系）
- [ ] 成功后 Toast 提示，权限列表刷新
- [ ] owner 条目的权限级别不可修改（无下拉）

### AC-07: 撤回权限

- [ ] 在"当前权限"列表中，非 owner 条目显示撤回按钮
- [ ] 点击撤回按钮弹出二次确认对话框（bsConfirm）
- [ ] 确认后调用 `POST /api/v1/resources/{type}/{id}/authorize`，revokes 数组包含对应条目
- [ ] 成功后 Toast 提示，权限列表刷新

### AC-08: 资源列表页权限徽章

- [ ] 知识空间列表、应用列表、工具列表、仪表盘列表页，每个资源项显示权限级别徽章
- [ ] 徽章颜色区分：owner=紫色、manager=蓝色、editor=绿色、viewer=灰色
- [ ] 权限级别通过前端 `usePermissionLevels` Hook batch check 获取（AD-10）
- [ ] admin 用户显示 owner 徽章（短路逻辑）
- [ ] 徽章文字使用 i18n（permission namespace）

### AC-09: 操作按钮权限控制

- [ ] viewer 级别用户：编辑、删除、权限管理按钮不可见
- [ ] editor 级别用户：权限管理按钮不可见
- [ ] manager/owner 级别用户：所有操作按钮可见
- [ ] 按钮可见性基于 `usePermissionLevels` Hook 返回的 level 判断
- [ ] **过渡策略**：现有页面通过 `data.write` 布尔字段控制按钮。F007 阶段两套机制并行——`data.write` 继续控制编辑/删除按钮（保持现有行为不变），`usePermissionLevels` 仅用于权限管理入口的显隐（AC-12）和权限徽章展示（AC-08）。F008 统一替换 `data.write` 为 `permission_level` 后，所有按钮切换为 level 判断

### AC-10: 重复授权幂等处理

- [ ] 对已有授权关系的主体再次授予相同权限，后端幂等处理，前端不报错
- [ ] 授予不同级别权限时正常覆盖

### AC-11: 主体搜索交互

- [ ] 用户搜索：输入框 300ms 防抖，展示搜索中 loading 状态，结果列表可滚动
- [ ] 部门树：树节点展开/折叠流畅，支持搜索定位（如果节点较多）
- [ ] 用户组搜索：同用户搜索交互模式
- [ ] 空结果展示友好提示

### AC-12: 权限管理入口可见性

- [ ] 仅对当前资源有 can_manage 权限的用户显示"权限管理"操作入口
- [ ] 无 can_manage 权限的用户完全看不到该入口（不是 disabled，而是不渲染）

### AC-13: 空权限列表

- [ ] 新创建资源仅有 owner 一条权限记录
- [ ] 权限列表正确展示 owner 条目
- [ ] "添加权限"Tab 功能正常

### AC-14: 前端 API 封装层

- [ ] `permission.ts` 导出 4 个函数：`checkPermission`, `getResourcePermissions`, `authorizeResource`, `getAccessibleObjects`
- [ ] 所有函数使用 `@/controllers/request` 的 axios 实例
- [ ] 错误处理通过 `captureAndAlertRequestErrorHoc` 统一拦截
- [ ] TypeScript 类型完整覆盖请求/响应

---

## 3. 边界情况

- **OpenFGA 不可用**：`get_resource_permissions` 返回空列表，前端展示空态（"暂无权限数据"）
- **授权 API 返回 19000 (PermissionDenied)**：前端 toast 提示"权限不足，无法执行此操作"
- **部门树为空**：部门选择器展示"暂无部门数据"空态提示
- **用户组为空**：用户组选择器展示"暂无用户组"空态提示
- **权限条目过多（>50）**：权限列表区域固定高度 + 滚动，不分页
- **并发授权**：多个管理者同时操作同一资源的权限，后端幂等处理，刷新后展示最终状态
- **网络错误**：统一由 axios 拦截器处理，toast 提示网络异常
- **资源不存在**：后端返回 404，前端关闭对话框并 toast 提示
- **batch check 性能**：单页最多 20 个资源 × 4 级 check = 80 次请求，使用 Promise.all 并发，admin 用户直接返回 owner 无需请求

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 对话框容器 | A: Dialog (居中弹窗) / B: Sheet (侧边面板) | A: Dialog | 权限管理是聚焦任务，与知识空间 CreateModal 等现有模式一致。680px 宽度足够容纳三 Tab |
| AD-02 | 主体选择交互 | A: 三个独立 Sub-Tab / B: 单搜索+类型切换 / C: RadioGroup+上下文选择器 | C | 三种主体 UX 各异（用户=搜索列表，部门=树，用户组=搜索列表），RadioGroup 清晰标识当前类型，选择器区域按类型切换 |
| AD-03 | 徽章颜色映射 | A: 单色+文字 / B: 4色区分 | B | owner=紫(bg-purple-100/text-purple-700), manager=蓝(bg-blue-100/text-blue-700), editor=绿(bg-green-100/text-green-700), viewer=灰(bg-gray-100/text-gray-700) |
| AD-04 | 部门选择器 | A: 构建树形组件 / B: 平铺搜索列表 | A | 部门层级是核心组织概念，平铺丢失父子上下文，树组件可被 F010 复用 |
| AD-05 | 组件目录位置 | A: bs-ui/permission/ / B: bs-comp/permission/ | B | bs-ui 存放原子 UI 组件（Dialog, Badge, Tabs），权限对话框是多原子组合的业务组件，放 bs-comp/ 符合现有 cardComponent/selectComponent 模式 |
| AD-06 | 状态管理 | A: Zustand store / B: 组件本地状态 | B | 权限对话框是瞬态交互（打开→操作→关闭），无跨页面状态共享需求 |
| AD-07 | i18n namespace | A: 添加到 bs.json / B: 新建 permission.json | B | ~40 个独立 key，避免膨胀通用 namespace。文件：`public/locales/{lang}/permission.json` |
| AD-08 | owner 是否可通过 UI 授予 | A: 可授 / B: 仅 viewer/editor/manager | B | PRD §3.3.1 明确 UI 提供 3 个级别选择，owner 在资源创建时自动分配 |
| AD-09 | 权限列表 API 返回格式 | A: 后端富化 / B: 前端自行解析 / C: 留给 F008 | A: 后端富化 | Spec Discovery 确认。修改 `PermissionService.get_resource_permissions()`，解析 FGA 元组并批量查名字，返回 `List[ResourcePermissionItem]` |
| AD-10 | 徽章权限级别数据源 | A: 前端 batch check / B: 暂不实现 / C: 后端通用接口 | A: 前端 batch check | Spec Discovery 确认。`usePermissionLevels` Hook 按 owner→can_manage→can_edit→can_read 顺序短路 check，F008 后端就绪后可切换数据源 |
| AD-11 | 继承权限 UI | A: F007 不处理 / B: 预实现 | A: 不处理 | Spec Discovery 确认。types.ts 预留 `inherited_from?` 字段，渲染逻辑留给 F008 |

---

## 5. 数据库 & Domain 模型

### 数据库表定义

无新表。

### Domain 模型修改

修改 `PermissionService.get_resource_permissions()` 返回值，从原始 FGA 元组格式转为结构化 `ResourcePermissionItem`。

**现有返回格式**（原始 FGA 元组）:
```python
[{"user": "user:7", "relation": "owner", "object": "knowledge_space:42"}]
```

**富化后返回格式**:
```python
[
    ResourcePermissionItem(
        subject_type="user",
        subject_id=7,
        subject_name="张三",
        relation="owner",
        include_children=None,
    ),
    ResourcePermissionItem(
        subject_type="department",
        subject_id=5,
        subject_name="工程部",
        relation="viewer",
        include_children=True,  # 合并同部门子部门元组
    ),
]
```

`ResourcePermissionItem` 已在 `permission/domain/schemas/permission_schema.py` 中定义（T12b），无需新增 Schema。

---

## 6. API 契约

### 端点列表

F007 前端消费的 4 个端点（均由 F004 实现，F007 只做前端封装）：

| Method | Path | 描述 | 认证 |
|--------|------|------|------|
| POST | `/api/v1/permissions/check` | 检查当前用户对资源的权限 | 是 |
| GET | `/api/v1/permissions/objects` | 列出当前用户可访问的资源 ID | 是 |
| POST | `/api/v1/resources/{type}/{id}/authorize` | 授予/撤回权限 | 是（需 can_manage） |
| GET | `/api/v1/resources/{type}/{id}/permissions` | 查询资源权限列表 | 是（需 can_manage） |

F007 前端依赖的现有端点：

| Method | Path | 描述 | 来源 |
|--------|------|------|------|
| GET | `/api/v1/user/list` | 用户搜索（name/page/pageSize） | 现有 |
| GET | `/api/v1/departments/tree` | 部门树 | F002 |
| GET | `/api/v1/group/list` | 用户组列表 | 现有 |

### 请求/响应示例

**权限检查**:
```json
POST /api/v1/permissions/check
{"object_type": "workflow", "object_id": "42", "relation": "can_manage"}
→ {"status_code": 200, "data": {"allowed": true}}
```

**授权**:
```json
POST /api/v1/resources/knowledge_space/10/authorize
{
  "grants": [
    {"subject_type": "user", "subject_id": 12, "relation": "editor"},
    {"subject_type": "department", "subject_id": 5, "relation": "viewer", "include_children": true}
  ],
  "revokes": [
    {"subject_type": "user_group", "subject_id": 3, "relation": "viewer"}
  ]
}
→ {"status_code": 200, "data": null}
```

**查询权限列表（富化后）**:
```json
GET /api/v1/resources/knowledge_space/10/permissions
→ {
  "status_code": 200,
  "data": [
    {"subject_type": "user", "subject_id": 7, "subject_name": "张三", "relation": "owner", "include_children": null},
    {"subject_type": "department", "subject_id": 5, "subject_name": "工程部", "relation": "viewer", "include_children": true},
    {"subject_type": "user_group", "subject_id": 3, "subject_name": "Alpha项目组", "relation": "editor", "include_children": null}
  ]
}
```

### 错误码表

| HTTP Status | MMMEE Code | Error Class | 场景 | 关联 AC |
|-------------|------------|-------------|------|---------|
| 200 (body) | 19000 | PermissionDeniedError | 无 can_manage 权限 | AC-07, AC-12 |
| 200 (body) | 19003 | PermissionInvalidResourceError | resource_type 不合法 | AC-14 |
| 200 (body) | 19005 | PermissionInvalidRelationError | relation 不合法 | AC-14 |

---

## 7. Service 层逻辑

### 核心方法修改

仅修改 `PermissionService.get_resource_permissions()`（`permission/domain/services/permission_service.py`）：

| 方法 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `get_resource_permissions` | object_type, object_id | `List[ResourcePermissionItem]` | 读取 FGA 元组 → 解析 → 批量查名字 → 返回结构化列表 |

### 富化逻辑流程

1. 调 `fga.read_tuples(object=f'{object_type}:{object_id}')` 获取原始元组
2. 解析每个元组的 `user` 字段：`"user:7"` → `(subject_type="user", subject_id=7)`，`"department:5#member"` → `(subject_type="department", subject_id=5)`
3. 按 subject_type 分组收集 ID
4. 批量查 DB：`UserDao.get_users_by_ids()`, `DepartmentDao.get_by_ids()`, `GroupDao.get_by_ids()`
5. 构建 `ResourcePermissionItem` 列表，填充 `subject_name`
6. 部门元组合并：同一 `(department_id, relation)` 的多条子部门元组合并为一条 `include_children=True`
7. 过滤掉 `user_group` 和 `department` 中的 `#member` 后缀关系（这些是成员关系，非直接授权）

### DAO 调用约定

使用已有的 DAO 方法（无需新增）：
- `UserDao.get_user_by_ids(ids)` — 批量获取用户信息
- `DepartmentDao.get_by_ids(ids)` — 批量获取部门信息（F002 已实现）
- `GroupDao` 相关方法 — 批量获取用户组信息

---

## 8. 前端设计

### 8.1 Platform 前端

> 路径：`src/frontend/platform/src/`

#### 组件树

```
components/bs-comp/permission/          # 权限业务组件目录
├── types.ts                            # TS 类型定义
├── PermissionDialog.tsx                # 主对话框（Dialog + Tabs 编排）
├── PermissionListTab.tsx               # Tab 1: 当前权限列表
├── PermissionGrantTab.tsx              # Tab 2: 添加权限
├── PermissionBadge.tsx                 # 权限级别徽章（独立组件）
├── SubjectSearchUser.tsx               # 用户搜索选择器
├── SubjectSearchDepartment.tsx         # 部门树选择器
├── SubjectSearchUserGroup.tsx          # 用户组搜索选择器
└── RelationSelect.tsx                  # 权限级别下拉选择
```

#### 组件详细设计

**PermissionDialog**:
```
Props: { open, onOpenChange, resourceType, resourceId, resourceName }
├── Dialog (max-w-[680px])
│   ├── DialogHeader: "权限管理 - {resourceName}"
│   └── Tabs (defaultValue="list")
│       ├── TabsTrigger "当前权限" → PermissionListTab
│       ├── TabsTrigger "添加权限" → PermissionGrantTab
│       └── TabsTrigger "链接分享" → disabled placeholder
└── State: activeTab, refreshKey (用于 GrantTab 成功后刷新 ListTab)
```

**PermissionListTab**:
```
Props: { resourceType, resourceId, refreshKey }
├── useEffect: 调用 getResourcePermissions(type, id) 加载数据
├── Table (bs-ui/table)
│   ├── 列: 主体图标 | 主体名称 | 权限级别(Select) | 操作
│   ├── owner 行: 权限级别为纯文本"拥有者"，无操作按钮
│   └── 非 owner 行: 权限级别为 Select 下拉（可修改） + 撤回按钮
│       ├── 修改级别: Select onChange → authorizeResource(revokes旧+grants新)
│       └── 撤回: bsConfirm → authorizeResource(revokes)
├── Loading 态: Spinner
├── 空态: "暂无权限记录"
└── Error 态: 错误提示 + 重试按钮
```

**PermissionGrantTab**:
```
Props: { resourceType, resourceId, onSuccess }
├── RadioGroup: [用户] [部门] [用户组]
├── 选择器区域（按 RadioGroup 值切换）:
│   ├── "user" → SubjectSearchUser
│   ├── "department" → SubjectSearchDepartment
│   └── "user_group" → SubjectSearchUserGroup
├── RelationSelect: viewer | editor | manager
├── 已选主体预览区（Chip/Tag 列表）
└── 提交按钮 → authorizeResource(grants) → onSuccess()
```

**PermissionBadge**:
```
Props: { level: 'owner'|'manager'|'editor'|'viewer', className? }
├── Badge (bs-ui/badge)
│   ├── owner → bg-purple-100 text-purple-700
│   ├── manager → bg-blue-100 text-blue-700
│   ├── editor → bg-green-100 text-green-700
│   └── viewer → bg-gray-100 text-gray-700
└── Label: i18n permission.level.{level}
```

**SubjectSearchUser**:
```
Props: { value: SelectedSubject[], onChange }
├── Search Input (300ms debounce) → getUsersApi({ name })
├── 结果列表: Checkbox + 用户名 + 用户 ID
└── 滚动加载（IntersectionObserver，参考 UsersSelect 模式）
```

**SubjectSearchDepartment**:
```
Props: { value: SelectedSubject[], onChange }
├── getDepartmentTree() 加载部门树
├── 递归渲染树节点 (展开/折叠)
│   └── 每个节点: Checkbox + 部门名 + 成员数
├── "包含子部门" Checkbox (default: true)
└── 搜索输入（前端本地过滤树节点）
```

**SubjectSearchUserGroup**:
```
Props: { value: SelectedSubject[], onChange }
├── getUserGroupsApi() 加载列表
├── Search Input (前端本地过滤)
└── 结果列表: Checkbox + 组名
```

**RelationSelect**:
```
Props: { value, onChange }
└── Select (bs-ui/select): viewer | editor | manager (i18n label)
```

#### usePermissionLevels Hook

```typescript
function usePermissionLevels(resourceType: string, resourceIds: string[])
  → { levels: Record<string, RelationLevel>, loading: boolean }
```

逻辑：
1. admin 用户直接返回所有 ID → `owner`（INV-5 短路）
2. 非 admin：对每个 resourceId，按 `owner → can_manage → can_edit → can_read` 顺序调 `checkPermission`，首个 `allowed=true` 即为该资源的 level
3. 使用 `Promise.allSettled` 并发所有 check 请求
4. 结果缓存在 hook state，resourceIds 变化时重新获取

#### 资源页面集成点

| 页面 | 文件 | 权限对话框入口 | 徽章位置 |
|------|------|--------------|---------|
| 知识空间 | `KnowledgePage/KnowledgeFile.tsx` | Select 菜单新增"权限管理"项 | 库名称右侧 |
| 应用 | `BuildPage/apps.tsx` | CardComponent hover 操作区新增图标 | 卡片 footer 区域 |
| 工具 | `BuildPage/tools/` | ToolItem 操作区新增按钮 | 工具名称右侧 |
| 仪表盘 | `Dashboard/DashboardListItem.tsx` | DropdownMenu 新增"权限管理"项 | 列表项名称右侧 |

#### API 调用模式

```typescript
// controllers/API/permission.ts
import axios from "@/controllers/request"

export async function checkPermission(objectType: string, objectId: string, relation: string) {
  return await axios.post('/api/v1/permissions/check', { object_type: objectType, object_id: objectId, relation })
}

export async function getResourcePermissions(resourceType: string, resourceId: string) {
  return await axios.get(`/api/v1/resources/${resourceType}/${resourceId}/permissions`)
}

export async function authorizeResource(resourceType: string, resourceId: string, grants: GrantItem[], revokes: RevokeItem[]) {
  return await axios.post(`/api/v1/resources/${resourceType}/${resourceId}/authorize`, { grants, revokes })
}

export async function getAccessibleObjects(objectType: string, relation: string = 'can_read') {
  return await axios.get('/api/v1/permissions/objects', { params: { object_type: objectType, relation } })
}
```

#### i18n 键结构

namespace: `permission`

```json
{
  "dialog": { "title": "权限管理", "tabList": "当前权限", "tabGrant": "添加权限", "tabShare": "链接分享" },
  "level": { "owner": "拥有者", "manager": "管理者", "editor": "编辑者", "viewer": "查看者" },
  "subject": { "user": "用户", "department": "部门", "userGroup": "用户组" },
  "action": { "grant": "授权", "revoke": "撤回", "confirm_revoke": "确定要撤回该权限吗？", "submit": "提交" },
  "search": { "user": "搜索用户...", "department": "搜索部门...", "userGroup": "搜索用户组..." },
  "includeChildren": "包含子部门",
  "empty": { "permissions": "暂无权限记录", "departments": "暂无部门数据", "userGroups": "暂无用户组", "searchResults": "无匹配结果" },
  "comingSoon": "即将推出",
  "managePermission": "权限管理"
}
```

### 8.2 Client 前端

不适用。Client 前端为终端用户对话界面，不涉及资源权限管理。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/frontend/platform/src/controllers/API/permission.ts` | 4 个权限 API 封装 + TS 类型 |
| `src/frontend/platform/src/components/bs-comp/permission/types.ts` | 共享 TS 接口定义 |
| `src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx` | 主对话框 |
| `src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx` | 当前权限列表 Tab |
| `src/frontend/platform/src/components/bs-comp/permission/PermissionGrantTab.tsx` | 添加权限 Tab |
| `src/frontend/platform/src/components/bs-comp/permission/PermissionBadge.tsx` | 权限级别徽章 |
| `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchUser.tsx` | 用户搜索选择器 |
| `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchDepartment.tsx` | 部门树选择器 |
| `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchUserGroup.tsx` | 用户组搜索选择器 |
| `src/frontend/platform/src/components/bs-comp/permission/RelationSelect.tsx` | 权限级别下拉 |
| `src/frontend/platform/public/locales/zh-Hans/permission.json` | 中文翻译 |
| `src/frontend/platform/public/locales/en-US/permission.json` | 英文翻译 |
| `src/frontend/platform/public/locales/ja/permission.json` | 日文翻译 |
| `src/backend/test/test_permission_enrichment.py` | 后端富化逻辑测试 |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `src/backend/bisheng/permission/domain/services/permission_service.py` | `get_resource_permissions()` 富化：解析 FGA 元组 + 批量查名字 |
| `src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx` | 集成 PermissionDialog + PermissionBadge |
| `src/frontend/platform/src/pages/BuildPage/apps.tsx` | 集成 PermissionDialog + PermissionBadge |
| `src/frontend/platform/src/pages/BuildPage/tools/` (具体文件待确认) | 集成 PermissionDialog + PermissionBadge |
| `src/frontend/platform/src/pages/Dashboard/` (具体文件待确认) | 集成 PermissionDialog + PermissionBadge |

---

## 10. 非功能要求

- **性能**: batch check 请求使用 Promise.allSettled 并发，admin 短路无需请求。单页 20 资源 × 最多 4 级 check = 最多 80 次 check 请求，每次 < 50ms（Redis 缓存命中），总耗时 < 200ms
- **安全**: 权限管理入口仅 can_manage+ 可见（前端隐藏），后端 authorize/permissions API 独立校验 can_manage 权限（双重保障）
- **兼容**: 不改变现有资源列表 API 响应格式，`usePermissionLevels` Hook 可在 F008 就绪后无缝切换为读取 API 字段
- **可复用**: 所有权限组件设计为通用组件，通过 `resourceType` + `resourceId` 参数适配任意资源类型
- **国际化**: 所有用户可见文字通过 i18n `permission` namespace 管理，支持中/英/日三语

---

## 相关文档

- 版本契约: [features/v2.5.0/release-contract.md](../release-contract.md)
- 权限改造 PRD: [docs/PRD/2.5 权限管理体系改造 PRD](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20权限管理体系改造%20PRD.md)
- ReBAC 技术方案: [docs/PRD/2.5 技术方案](../../docs/PRD/2.5%20权限管理体系改造%20PRD/2.5%20技术方案.md)
- F004 ReBAC 核心 spec: [features/v2.5.0/004-rebac-core/spec.md](../004-rebac-core/spec.md)
