# Tasks: 资源权限管理前端

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | SDD Review 通过，5 项修复后确认 |
| tasks.md | ✅ 已拆解 | SDD Review Round 2 LGTM |
| 实现 | ✅ 已完成 | 11 / 11 完成 |

---

## 开发模式

**后端 Test-First（务实版）**：
- T003（后端富化）采用 Test-First：先写测试再实现
- 使用 F000 搭建的 pytest 基础设施（conftest + fixture）

**前端 Test-Alongside（暂缓版）**：
- Platform 前端当前无自动化测试框架
- 前端任务用「手动验证」替代自动化测试，每个任务附验证步骤描述

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（无测试配对）

- [x] **T001**: TypeScript 类型 + 前端 API 封装层
  **文件**:
  - `src/frontend/platform/src/components/bs-comp/permission/types.ts`（新建）
  - `src/frontend/platform/src/controllers/API/permission.ts`（新建）
  **逻辑**:
  **types.ts** — 定义共享 TS 接口：
  ```typescript
  export type ResourceType = 'knowledge_space' | 'folder' | 'knowledge_file' | 'workflow' | 'assistant' | 'tool' | 'channel' | 'dashboard'
  export type RelationLevel = 'owner' | 'manager' | 'editor' | 'viewer'
  export type SubjectType = 'user' | 'department' | 'user_group'
  export interface PermissionEntry {
    subject_type: SubjectType; subject_id: number; subject_name: string | null;
    relation: RelationLevel; include_children?: boolean;
  }
  export interface GrantItem {
    subject_type: SubjectType; subject_id: number; relation: RelationLevel; include_children?: boolean;
  }
  export interface RevokeItem {
    subject_type: SubjectType; subject_id: number; relation: RelationLevel; include_children?: boolean;
  }
  export interface SelectedSubject {
    type: SubjectType; id: number; name: string; include_children?: boolean;
  }
  ```
  **permission.ts** — 4 个 API 函数 + 1 个部门树 API，使用 `@/controllers/request` 的 axios：
  - `checkPermission(objectType, objectId, relation)` → `POST /api/v1/permissions/check`
  - `getResourcePermissions(resourceType, resourceId)` → `GET /api/v1/resources/{type}/{id}/permissions`
  - `authorizeResource(resourceType, resourceId, grants, revokes)` → `POST /api/v1/resources/{type}/{id}/authorize`
  - `getAccessibleObjects(objectType, relation?)` → `GET /api/v1/permissions/objects`
  - `getDepartmentTree()` → `GET /api/v1/departments/tree`（供 SubjectSearchDepartment 使用）
  参考模式：`src/frontend/platform/src/controllers/API/user.ts`
  **覆盖 AC**: AC-14
  **依赖**: 无
  **手动验证**:
  - 在浏览器 DevTools Console 中 import 并调用每个函数
  - 验证 Network 面板中 URL、Method、Payload 正确
  - 验证 401（未登录）和正常响应格式

---

- [x] **T002**: i18n locale 文件
  **文件**:
  - `src/frontend/platform/public/locales/zh-Hans/permission.json`（新建）
  - `src/frontend/platform/public/locales/en-US/permission.json`（新建）
  **逻辑**: 定义 ~45 个翻译键（zh-Hans 为主，en-US 同步），结构如下：
  ```json
  {
    "dialog": { "title": "权限管理", "tabList": "当前权限", "tabGrant": "添加权限", "tabShare": "链接分享" },
    "level": { "owner": "拥有者", "manager": "管理者", "editor": "编辑者", "viewer": "查看者" },
    "subject": { "user": "用户", "department": "部门", "userGroup": "用户组" },
    "action": { "grant": "授权", "revoke": "撤回", "confirmRevoke": "确定要撤回该权限吗？", "submit": "提交", "modify": "修改权限" },
    "search": { "user": "搜索用户...", "department": "搜索部门...", "userGroup": "搜索用户组..." },
    "includeChildren": "包含子部门",
    "empty": { "permissions": "暂无权限记录", "departments": "暂无部门数据", "userGroups": "暂无用户组", "searchResults": "无匹配结果" },
    "comingSoon": "即将推出",
    "managePermission": "权限管理",
    "error": { "permissionDenied": "权限不足，无法执行此操作", "grantFailed": "授权失败", "revokeFailed": "撤回失败" },
    "success": { "grant": "授权成功", "revoke": "已撤回权限", "modify": "权限级别已修改" }
  }
  ```
  ja 翻译文件（`public/locales/ja/permission.json`）同步新建，结构相同。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08（所有前端 AC 的 i18n 基础）
  **依赖**: 无
  **手动验证**:
  - 切换浏览器语言为 en-US/ja，验证无 missing key 控制台警告
  - 验证 JSON 格式合法（无尾逗号等）

---

### 后端 Domain Service（Test-First 配对）

- [x] **T003**: 后端 get_resource_permissions 富化
  **文件**:
  - `src/backend/test/test_permission_enrichment.py`（新建，先写）
  - `src/backend/bisheng/permission/domain/services/permission_service.py`（修改）
  **注意**: 此修改为 F004 `PermissionService` 的兼容性增强（不改变方法签名，仅填充 `ResourcePermissionItem` 已有的可选字段），已在 spec AD-09 中确认。影响范围仅限 `get_resource_permissions()` 一个方法。
  **测试**（先写）:
  ```python
  # test_permission_enrichment.py
  # 测试 PermissionService.get_resource_permissions() 富化逻辑
  # - test_parse_user_tuple: "user:7" → subject_type="user", subject_id=7
  # - test_parse_department_member_tuple: "department:5#member" → 过滤掉（成员关系）
  # - test_parse_department_direct_tuple: "department:5" + relation="viewer" → 保留
  # - test_parse_user_group_tuple: "user_group:3#member" → 过滤掉
  # - test_batch_name_resolution: 批量查用户/部门/组名
  # - test_department_merge: 同 (dept_id, relation) 多条元组合并为 include_children=True
  # - test_empty_tuples: FGA 返回空列表 → 返回空列表
  # - test_unknown_subject_type: 未知格式 → 跳过不报错
  ```
  **实现逻辑**（~50 行修改）:
  1. 在 `get_resource_permissions()` 中，调 `fga.read_tuples(object=...)` 后不直接返回
  2. 解析 `user` 字段：正则 `^(user|department|user_group):(\d+)(#member)?$`
  3. 过滤 `#member` 后缀元组（成员关系非直接授权）
  4. 按 subject_type 分组收集 ID
  5. 批量查 DB：`UserDao.get_user_by_ids()`, `DepartmentDao.get_by_ids()`, `GroupDao.get_by_ids()`
  6. 构建 `ResourcePermissionItem` 列表
  7. 部门元组合并：同 `(dept_id, relation)` 的多条 → `include_children=True`
  **覆盖 AC**: AC-02
  **依赖**: 无
  **测试命令**: `.venv/bin/pytest test/test_permission_enrichment.py -v`

---

### 前端核心组件（手动验证）

- [x] **T004**: PermissionBadge 组件
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/PermissionBadge.tsx`（新建）
  **逻辑**:
  - Props: `{ level: RelationLevel | null; className?: string }`
  - 当 level 为 null/undefined 时不渲染
  - 使用 `Badge` 组件（from `@/components/bs-ui/badge`）
  - 颜色映射：
    - owner → `bg-purple-100 text-purple-700 border-purple-200`
    - manager → `bg-blue-100 text-blue-700 border-blue-200`
    - editor → `bg-green-100 text-green-700 border-green-200`
    - viewer → `bg-gray-100 text-gray-700 border-gray-200`
  - 文字：`useTranslation('permission')` → `t('level.{level}')`
  - 导出：`export function PermissionBadge({...})`（named export，不用 default）
  **覆盖 AC**: AC-08
  **依赖**: T001, T002
  **手动验证**:
  - 临时在某个页面 import 并渲染 4 种 level 的 Badge
  - 验证颜色和文字正确
  - 验证 null level 不渲染

---

- [x] **T005**: RelationSelect + SubjectSearchUser 组件
  **文件**:
  - `src/frontend/platform/src/components/bs-comp/permission/RelationSelect.tsx`（新建）
  - `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchUser.tsx`（新建）
  **逻辑**:
  **RelationSelect**: Props: `{ value: RelationLevel; onChange: (v: RelationLevel) => void }`。使用 `Select` (bs-ui/select)，3 个选项 viewer/editor/manager，i18n label。
  **SubjectSearchUser**: Props: `{ value: SelectedSubject[]; onChange: (v: SelectedSubject[]) => void }`。
  - 搜索输入框 + 300ms debounce（`useRef + setTimeout` 模式）
  - 调 `getUsersApi({ name: keyword, page: 1, pageSize: 20 })` from `@/controllers/API/user.ts`
  - 结果列表：Checkbox + 用户名。已选项高亮。
  - 参考 `src/frontend/platform/src/components/bs-comp/selectComponent/Users.tsx` 的 IntersectionObserver 滚动加载模式
  **覆盖 AC**: AC-11
  **依赖**: T001, T002
  **手动验证**:
  - RelationSelect：渲染 → 选择各级别 → onChange 回调值正确
  - SubjectSearchUser：输入文字 → 300ms 后 API 调用 → 结果展示 → 勾选 → onChange 回调

---

- [x] **T006**: SubjectSearchDepartment + SubjectSearchUserGroup 组件
  **文件**:
  - `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchDepartment.tsx`（新建）
  - `src/frontend/platform/src/components/bs-comp/permission/SubjectSearchUserGroup.tsx`（新建）
  **逻辑**:
  **SubjectSearchDepartment**: Props: `{ value: SelectedSubject[]; onChange; includeChildren: boolean; onIncludeChildrenChange }`。
  - 调 `getDepartmentTree()` from `@/controllers/API/permission.ts`（T001 产出）
  - 递归渲染树节点，ChevronRight 图标展开/折叠
  - 每个节点 Checkbox + 部门名 + 成员数（`member_count` from `DepartmentTreeNode`）
  - 底部 Checkbox "包含子部门"（default true）
  - 搜索输入：前端本地过滤树节点（匹配名称）
  **SubjectSearchUserGroup**: Props: `{ value: SelectedSubject[]; onChange }`。
  - 调 `getUserGroupsApi()` from `@/controllers/API/user.ts`
  - 前端本地搜索过滤 + Checkbox 列表
  **覆盖 AC**: AC-11
  **依赖**: T001, T002
  **手动验证**:
  - 部门树：加载 → 展开/折叠 → 勾选 → include_children toggle → onChange
  - 用户组：加载列表 → 搜索过滤 → 勾选 → onChange

---

- [x] **T007**: PermissionListTab 组件
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/PermissionListTab.tsx`（新建）
  **逻辑**:
  - Props: `{ resourceType: ResourceType; resourceId: string; refreshKey: number }`
  - useEffect 监听 `[resourceType, resourceId, refreshKey]`，调 `getResourcePermissions()`（T001 产出）
  - 表格列（使用 bs-ui/table）：
    - 主体图标：user → UserIcon, department → BuildingIcon, user_group → UsersIcon（from lucide-react 或 bs-icons）
    - 主体名称：`entry.subject_name ?? entry.subject_id`
    - 权限级别：
      - owner → 纯文本 PermissionBadge（不可修改）
      - 非 owner → `RelationSelect` 下拉（AC-06 行内修改）
        - onChange: 调 `authorizeResource(type, id, [grant新], [revoke旧])` → 刷新列表 → Toast
    - 操作列：
      - owner → 无按钮
      - 非 owner → 撤回按钮（Trash2 图标）
        - onClick: `bsConfirm({ title: t('action.confirmRevoke') })` → `authorizeResource(type, id, [], [revoke])` → 刷新 → Toast
  - 加载态：居中 Spinner
  - 空态：`t('empty.permissions')` + 引导文字
  - 错误态：错误信息 + 重试按钮
  - 使用 `captureAndAlertRequestErrorHoc` 包装 API 调用
  **覆盖 AC**: AC-02, AC-06, AC-07, AC-13
  **依赖**: T001, T003, T004, T005（RelationSelect）
  **手动验证**:
  - 对一个有多条权限的资源打开组件，验证表格数据正确
  - 修改权限级别：Select 切换 → 验证 API 调用 payload → 列表刷新
  - 撤回权限：点击 → 确认弹窗 → 验证 API revokes payload → 条目消失
  - owner 行无 Select 下拉和撤回按钮
  - 空权限列表展示空态

---

- [x] **T008**: PermissionGrantTab 组件
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/PermissionGrantTab.tsx`（新建）
  **逻辑**:
  - Props: `{ resourceType: ResourceType; resourceId: string; onSuccess: () => void }`
  - 状态：`subjectType: SubjectType`（default 'user'），`selectedSubjects: SelectedSubject[]`，`relation: RelationLevel`（default 'viewer'），`includeChildren: boolean`（default true），`loading: boolean`
  - RadioGroup (bs-ui/radio 或直接用 button group): [用户] [部门] [用户组]
  - 按 subjectType 条件渲染对应搜索组件（T005, T006 产出）
  - RelationSelect（T005 产出）
  - 已选主体预览区：Badge/Chip 列表（显示已选的用户/部门/组名），支持点击 X 移除
  - 提交按钮：
    - 校验：至少选 1 个主体 + 已选 relation
    - 构建 grants 数组（对每个 selectedSubject 生成 GrantItem）
    - 调 `authorizeResource(type, id, grants, [])` via `captureAndAlertRequestErrorHoc`
    - 成功：Toast → `onSuccess()`
    - 失败：Toast error
    - 提交中 loading 态禁用按钮
  - 切换 subjectType 时清空已选主体
  **覆盖 AC**: AC-03, AC-04, AC-05, AC-10
  **依赖**: T001, T002, T005, T006
  **手动验证**:
  - 选"用户" → 搜索选择 2 个用户 → 选 editor → 提交 → 验证 grants payload
  - 选"部门" → 勾选部门 + include_children → 选 viewer → 提交 → 验证 payload
  - 选"用户组" → 勾选 1 个组 → 选 manager → 提交 → 验证 payload
  - 空选提交 → 验证校验拦截
  - 切换 RadioGroup → 已选主体清空

---

- [x] **T009**: PermissionDialog 主组件
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/PermissionDialog.tsx`（新建）
  **逻辑**:
  - Props: `{ open: boolean; onOpenChange: (v: boolean) => void; resourceType: ResourceType; resourceId: string; resourceName: string }`
  - 使用 `Dialog` + `DialogContent` from bs-ui/dialog，`className="sm:max-w-[680px]"`
  - `DialogHeader` + `DialogTitle`: `{t('dialog.title')} - {resourceName}`
  - `Tabs` from bs-ui/tabs，3 个 Tab：
    - "当前权限" (defaultValue="list") → `<PermissionListTab resourceType={...} resourceId={...} refreshKey={refreshKey} />`
    - "添加权限" → `<PermissionGrantTab resourceType={...} resourceId={...} onSuccess={handleGrantSuccess} />`
    - "链接分享" → `<div className="py-8 text-center text-muted-foreground">{t('comingSoon')}</div>`（disabled Tab trigger）
  - `handleGrantSuccess`: 增加 refreshKey → 切换到"当前权限"Tab
  - 状态：`activeTab: string`，`refreshKey: number`
  - open 由外部控制（controlled component），与 KnowledgeFile 的 CreateModal 模式一致
  **覆盖 AC**: AC-01
  **依赖**: T007, T008
  **手动验证**:
  - 打开 Dialog，验证 3 个 Tab 切换
  - "链接分享"Tab disabled 且显示 Coming Soon
  - 在"添加权限"成功后自动切回"当前权限"且数据刷新
  - 关闭 Dialog 后再打开，数据重新加载

---

### 页面集成（手动验证）

- [x] **T010**: usePermissionLevels Hook
  **文件**: `src/frontend/platform/src/components/bs-comp/permission/usePermissionLevels.ts`（新建）
  **逻辑**:
  ```typescript
  export function usePermissionLevels(resourceType: ResourceType, resourceIds: string[])
    → { levels: Record<string, RelationLevel>, loading: boolean }
  ```
  1. 从 `userContext` 获取当前用户，if admin → 所有 ID 返回 `'owner'`（INV-5 短路）
  2. 非 admin：对每个 resourceId，按 `owner → can_manage → can_edit → can_read` 顺序调 `checkPermission`（T001 产出），首个 `allowed=true` 即为 level（owner→'owner', can_manage→'manager', can_edit→'editor', can_read→'viewer'）
  3. 使用 `Promise.allSettled` 并发所有 check 请求
  4. 结果存 state，resourceIds 变化时重新获取（useEffect dep）
  5. 组件卸载或 ids 变化时取消未完成的请求（AbortController）
  **覆盖 AC**: AC-08, AC-09
  **依赖**: T001
  **手动验证**:
  - 在某个页面临时使用 Hook，传入已知资源 IDs
  - admin 登录 → 所有返回 owner
  - 普通用户 → 验证 Network 面板 check 请求数和短路逻辑

---

- [x] **T011**: 资源页面集成（Badge + Dialog + 入口控制）
  **文件**:
  - `src/frontend/platform/src/pages/KnowledgePage/KnowledgeFile.tsx`（修改）
  - `src/frontend/platform/src/pages/BuildPage/apps.tsx`（修改）
  **逻辑**:
  每个页面统一执行以下集成（badge + dialog 一次性完成，避免多次修改同一文件）：
  1. Import `PermissionDialog`, `PermissionBadge`, `usePermissionLevels`
  2. 在列表数据加载后提取 IDs → 调 `usePermissionLevels(type, ids)`
  3. 在每个资源项/卡片上渲染 `<PermissionBadge level={levels[id]} />`
  4. 新增状态：`permDialogOpen: boolean`，`permTarget: { type, id, name } | null`
  5. 在操作菜单添加"权限管理"入口：
     - **KnowledgeFile**: Select 下拉菜单新增一项"权限管理"
     - **apps.tsx**: CardComponent hover 操作区新增锁图标
  6. 入口可见性（AC-12）：仅 `level === 'owner' || level === 'manager'` 时显示。过渡期兼容：也可用 `data.write` 作为 fallback
  7. 页面底部放置 `<PermissionDialog />` 单例
  **注意**: tools/ 和 Dashboard/ 的集成在 T011b 中完成（文件拆分以满足 ≤ 2 文件原子化要求）
  **覆盖 AC**: AC-01, AC-08, AC-09, AC-12
  **依赖**: T009, T010
  **手动验证**:
  - **知识空间**: 列表页 → Badge 显示 → 操作菜单中"权限管理" → Dialog 打开 → 全流程
  - **应用**: 卡片 → Badge + 锁图标 → Dialog 打开
  - viewer 用户登录 → 入口不可见

---

- [x] **T011b**: 工具 + 仪表盘页面集成（Badge + Dialog + 入口控制）
  **文件**:
  - `src/frontend/platform/src/pages/BuildPage/tools/`（修改，具体文件待确认）
  - `src/frontend/platform/src/pages/Dashboard/`（修改，具体文件待确认）
  **逻辑**: 与 T011 相同的集成模式：
  1. Import + usePermissionLevels + PermissionBadge + PermissionDialog
  2. **tools/**: ToolItem 操作区新增权限管理按钮 + 名称旁 Badge
  3. **Dashboard**: DashboardListItem DropdownMenu 新增"权限管理"项 + 名称旁 Badge
  4. 入口可见性同 T011
  **覆盖 AC**: AC-01, AC-08, AC-09, AC-12
  **依赖**: T009, T010
  **手动验证**:
  - **工具**: 工具项 → Badge + 权限管理按钮 → Dialog 打开
  - **仪表盘**: 列表项 → Badge + DropdownMenu 权限管理 → Dialog 打开
  - viewer 用户登录 → 入口不可见
  - Dialog 内授权/撤回/修改级别全流程

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1**: `DepartmentDao.aget_by_ids()` 方法在 F002 中未提供，T003 中新增（`database/models/department.py`，10 行）
- **偏差 2**: CardComponent (`bs-comp/cardComponent/index.tsx`) 新增 `onPermission` + `permissionBadge` 两个可选 props，用于应用页面的权限入口集成。影响范围：仅 apps.tsx 传入这两个 props
