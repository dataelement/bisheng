# Tasks: F038-department-tree-lazy-load（部门树懒加载）

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0
**分支**: `feat/2.6.0-department-single-root-fga`（已同步 beta4）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 纯 What；用户确认 2026-06-29 |
| design.md | ✅ 已评审 | 决策 1–12 + 接手必读；用户确认 2026-06-29；接手第一入口 |
| tasks.md | ✅ 已拆解 | 本文件 |
| 实现 | 🟡 进行中 | 10 / 16（后端全完 T000-T006；前端 T007 件 + T008 两棵导航树 + T009 共享 picker 已落地&类型干净；T009b/T010/T011/T012/T013 待续，含 5 个测试需补 QueryClientProvider+懒加载断言） |

---

## 开发模式

- **后端 Test-First**：先写测试（红）再实现（绿）；scoping 类任务必须有"懒加载可见集 == 旧 aget_tree 可见集"的等价性断言（防漂移，design §7）。
- **前端**：手动验证（每任务附步骤）；环境与 URL 见 design §7.1（host `192.168.106.105`，client `…:3001/workspace`，账号 `Test@1234ab`）。
- **达梦/中间件/e2e** 在压测环境或 CI 跑，不依赖本地。
- 自包含任务：文件/逻辑/AC 内联；**设计论证指向 design §X，不复制**。

---

## Tasks

### Wave 0 —— member_count 移除（✅ 已完成）

- [x] **T000**: 移除授权部门列表的成员数统计（后端 + 前端 + 测试）
  **文件**: `permission/api/endpoints/resource_permission.py::_list_knowledge_space_grant_departments`、client `components/permission/SubjectSearchDepartment.tsx`、`test/permission/test_permission_api_integration.py`
  **逻辑**: 删除 `COUNT(*) WHERE department_id IN(<全子树>) GROUP BY` 计数 + `member_count` 字段（知识空间与频道共用 helper，一处覆盖两端）；删 client 角标；测试断言无 member_count + 无第 4 次计数查询
  **覆盖 AC**: AC-21, AC-22, AC-23
  **状态**: 已提交 `b8e481872`（达梦 69s→~3s）。详见 design 决策 11

### Wave 1 —— 后端取数基建（无依赖，可并行）

- [x] **T001**: `DepartmentDao` 取数扩展 + 单测 ✅（8/8，aiosqlite）
  **文件**: `database/models/department.py`、`test/department/test_department_dao_lazy.py`
  **逻辑**: ①`aget_children` 加 `status` 参（支持 active+archived，默认仍 active）；②新增**按名搜索**方法 `aget_by_name_like(keyword, path_prefixes, limit)`（`name LIKE` + `or_(path LIKE p%)` + limit）；③新增 **has_children 批量** `aget_children_existence(parent_ids) -> set[int]`（`GROUP BY parent_id`）。range/scope 由 Service 传入 path/ids，DAO 不含权限逻辑（design §2 C1、决策 5）
  **约束**: 仅新增/扩展查询方法，**无 DDL / 无 Alembic 迁移 / 无需回滚**（`has_children`、`matched` 是响应字段，非 DB 列）
  **测试**: 子层含/不含归档、名搜索范围+limit+截断、has_children 批量正确性
  **覆盖 AC**: AC-02, AC-03, AC-06, AC-07, AC-16
  **依赖**: 无

- [x] **T002**: 抽取统一 scope helper `_aget_user_scope` + 等价性单测 ✅ `1af226f5d`
  **文件**: `department/domain/services/department_service.py`、`test/department/test_department_scope_parity.py`
  **逻辑**: 从 `aget_tree` 抽 `_aget_user_scope(login_user) -> (is_sys_admin, admin_paths)`（复用 `_is_admin`/`aget_user_admin_departments`/`_is_tenant_admin`/`_aget_user_tenant_root_path`）；**`aget_tree` 改用同 helper**，防与新端点漂移
  **测试**: 在同一 fixture 树上断言"新 helper 算出的可见集" == "旧 aget_tree 可见集"，覆盖 系统/部门(嵌套去重)/租户管理员/非管理员(403)
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-14
  **依赖**: 无

### Wave 2 —— platform 部门树端点族（admin 范围）

- [x] **T003**: platform children/search/path-tree Service + 端点集成测试 ✅（16/16，aiosqlite + TestClient）
  **文件**: `test/department/test_department_lazy_api.py`
  **逻辑**: TestClient 测 `GET /departments/children`(根层/parent_id/include_archived)、`/departments/search`(命中+祖先剪枝树+truncated+空词)、`/departments/{id}/path-tree`；含越权 parent/定位 403 且不泄露
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07, AC-08, AC-09, AC-10, AC-15
  **依赖**: T001, T002

- [x] **T004**: platform children/search/path-tree Service + 端点实现 ✅
  **文件**: `department/domain/services/department_service.py`(`aget_children_layer`/`asearch_tree`/`aget_path_tree`/`_abuild_pruned_forest` + 模块级 `_parse_path_ids`/`_path_in_scope`/`_topmost_paths`/`_dept_node_dict`)、`department/api/endpoints/department.py`(3 GET 路由 + `_orjson_ok`，置于 `GET /{dept_id}` 之前)、`database/models/department.py`(`aget_children` 支持 `parent_id=None` 根层)
  **逻辑**: Service 用 `_aget_user_scope` 算范围 → 调 DAO 取单层/搜索/祖先 → 组装；端点**直建 dict + ORJSON 返回**绕过 jsonable_encoder（design 决策 7）；搜索/定位祖先 clamp 到 admin_paths（design §5 坑4）；空词早返回（不扫全表）；越权/缺失统一 21009 不泄露（sys-admin 缺失给 21000）。`DepartmentTreeNode` 的 `has_children`/`matched` 字段已在 schema commit 落地
  **测试**: T003 通过
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-06, AC-07, AC-08, AC-09, AC-10, AC-15
  **依赖**: T003

### Wave 3 —— 授权树端点族（租户子树 + F033 范围）

- [x] **T005**: grant-subjects children/search/path-tree 集成测试（知识空间 + 频道）✅（14/14，aiosqlite 直测共享 helper）
  **文件**: `test/permission/test_grant_departments_lazy.py`
  **逻辑**: 测授权树取子层/搜索/定位；覆盖**两 resource_type**（知识空间=带 restrict / 频道=restrict None，同一 helper 两模式）、F033 收敛、范围用"租户子树减子租户挂载"（**非** admin 范围，design 决策 3）；含 ROOT_TENANT 子租户挂载剔除 + 越权返回空不泄露
  **覆盖 AC**: AC-24, AC-26（后端侧）
  **依赖**: T001

- [x] **T006**: grant-subjects children/search/path-tree 实现 ✅
  **文件**: `permission/api/endpoints/resource_permission.py`(`_grant_departments_children`/`_grant_departments_search`/`_grant_departments_path_tree` + `_resolve_grant_dept_scope`/`_grant_build_pruned`/`_grant_dept_lazy_preamble` + 3 KS 端点)、`channel/domain/services/channel_authorization_service.py`(3 复用方法)、`channel/api/endpoints/channel_manager.py`(3 频道端点)
  **逻辑**: 在 `_list_knowledge_space_grant_departments` 同源 scope（租户子树 − 子租户挂载）上加单层/搜索/定位变体；**F033 收敛改用 bound dept 的 `path` 前缀（不灌 id 集，规避达梦大 `.in_()`）**；频道侧 `restrict_root_path=None` 复用同 helper。端点用 `resp_200`（懒加载后单响应小，jsonable_encoder 成本可忽略；决策 7 的 ORJSON 是为整树 14MB 而设）
  **测试**: T005 通过
  **覆盖 AC**: AC-24, AC-26（后端侧）
  **依赖**: T005

### Wave 4 —— platform 前端基建

- [x] **T007**: platform 可复用懒加载树 hook + 展示组件 + API 封装 ✅（`962343050`，tsc 零新增错误）
  **文件**: `bs-comp/department/useLazyDepartmentTree.ts`(新 hook)、`bs-comp/department/LazyDepartmentTree.tsx`(新展示组件)、`bs-comp/department/index.ts`(barrel)、`controllers/API/department.ts`(3 封装)、`types/api/department.ts`(加 `has_children?`/`matched?` + `DepartmentSearchResult`)
  **逻辑**: `useLazyDepartmentTree`——浏览态用规范化懒模型(node map + per-parent childIds，展开时取子层，react-query 缓存 `['dept-children',parentId,includeArchived]`)；搜索态直渲后端剪枝树(debounce 300ms)；`reveal(id)` 取 path-tree 链并把链上每层**整层加载**后展开(回显深层值)；`reloadLayer(parentId)` 失效单层(AC-05)。`LazyDepartmentTree`——箭头用 `has_children`、单层 spinner、`matched` 高亮、truncated 提示；row prefix/suffix slot + isRowDisabled 供导航树(建子按钮/挂载角标/归档)与 picker(勾选框/已授权)复用同一渲染器。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-06, AC-09, AC-10
  **手动验证**: 在接入页（T008）联调
  **⚠️ 接手注意**: 消费方迁移(T008/T009/T009b)是**强耦合大重构**——`DepartmentPage/index.tsx` 把整树 `tree` 串进 4+ 子弹窗(MemberTable/DepartmentSettings/CreateDepartmentDialog)；`TreeDepartmentSelect` 还**导出** `getDepartmentDisplayPath`/`findDepartmentAncestorIds`/`findDepartmentNodeById`(消费方在整树上调用算回显路径)。改 picker 内部懒加载会波及所有用这些 helper 的消费方→须协调改 + 逐步 dev 验证。**别单独改一处**。
  **依赖**: T004

### Wave 5 —— platform 消费方迁移（每项独立小 PR）

- [x] **T008**: 迁移导航树（部门管理页 + 系统管理-部门）✅ `f1275c9d4`（类型干净，net -3 tsc）
  **文件**: `pages/DepartmentPage/index.tsx`、`pages/SystemPage/components/Departments.tsx`（旧 `DepartmentTree.tsx` 弃用，留待 T012 删）+ 连带 `MemberTable.tsx`(祖先链改 path-tree 取)
  **逻辑**: 接入 T007 件；移除整树加载与客户端递归过滤；选中节点由 hook 实时派生(rename/move 后右栏同步)；定位用 `getDepartmentApi(dept_id)→id→reveal`；变更后 `reloadLayer`/`refreshAll` 失效受影响父层（决策 12）
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-16
  **手动验证**: 5 万环境打开秒出根层、展开取子层、搜索定位、建/移/归档后受影响父层刷新
  **依赖**: T007

- [x] **T009**: 迁移共享 picker `TreeDepartmentSelect`（仅改内部）✅ `f1275c9d4`
  **文件**: `bs-comp/department/TreeDepartmentSelect.tsx`（自取数；调用方仅去掉 `nodes`/`loading`/`showMemberCount` props）+ 4 调用方 `CreateDepartmentDialog`/`DepartmentSettings`(移动,`excludeSubtreePath=dept.path`)/`OrganizationMemberEditDialog`/`Roles`
  **逻辑**: 内部 `useLazyDepartmentTree`(autoLoad=open) + 复用 `LazyDepartmentTree`(wheelScrollFix)；trigger label 用 path-tree 取全路径；当前值 `reveal` 展开高亮；`include_archived=false`(归档值仍可经 path-tree 回显, AC-18)
  **覆盖 AC**: AC-10, AC-17, AC-18
  **手动验证**: 父部门选择/移动/角色范围/成员主属部门编辑 各打开秒开、可搜、回显当前值、不含归档
  **依赖**: T007
  **测试欠账已清 ✅ `5163a7353`**: `test-utils` 的 `AllProviders` 加 `QueryClientProvider`(每次 render 新 client)中心修复;3 个测试改 mock 懒加载 API + stub `LazyDepartmentTree`(其 SearchInput 引 SVG，jsdom 渲不了)保留真 hook + 去 `tree` prop。**顺带抓到真 bug**:删除选中部门后 `handleTreeChange` 在 refreshAll 完成前清选择→自动选中重选到陈旧首根(被删的那个);已改 await refreshAll 后再清(两个页面)。全套 11→8 失败文件(剩余皆 pre-existing)。

- [ ] **T009b**: 迁移其余 platform 独立 picker
  **文件**: `bs-comp/selectComponent/DepartmentUsersSelect.tsx`、`bs-comp/permission/SubjectSearchDepartment.tsx`(platform 版)、`BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog.tsx`
  **逻辑**: 三者各接入 T007 件改懒加载 + 搜索 + 定位回显；`DepartmentUsersSelect` 的成员懒加载本就有、只改树部分；默认 `include_archived=false`
  **覆盖 AC**: AC-10, AC-17
  **手动验证**: 部门用户选择器/权限主体选择/知识空间映射 各打开秒开、可搜、不含归档
  **依赖**: T007

### Wave 6 —— client 授权选择器迁移

- [ ] **T010**: client 授权部门选择器懒加载 + 选择语义改造 + API 封装
  **文件**: `client/src/components/permission/SubjectSearchDepartment.tsx`、`PermissionGrantTab.tsx`、`api/permission.ts`
  **逻辑**: 自建懒加载/搜索/定位（Recoil/RQv5）；**隐式选中按 `node.path` 判定**（去递归下传，design 决策 9）；**去掉 materialize、含子部门全有或全无**（决策 10）；打开 reveal 本次 `value`、已授权遇到时置灰"已授权"（不主动全展开）；搜索命中按 已勾选/已授权/隐式 叠加；新增 children/search/path-tree 封装（走 `~/api/request.ts`，C7）
  **覆盖 AC**: AC-24, AC-25, AC-26, AC-27, AC-28
  **手动验证**: 知识空间共享 + 频道授权两入口；秒开、搜索定位、已授权置灰、含子部门隐式选中不可单独取消
  **依赖**: T006

- [ ] **T011**: 授权等价性核对（权限安全不变量）
  **文件**: 手动/脚本
  **逻辑**: 同一组勾选，懒加载前(旧整树) vs 懒加载后 分别提交，diff 两次 `authorize` 的 `grants` 逐项等价（spec §3 权限安全不变量，design §7.1）
  **覆盖 AC**: AC-28
  **依赖**: T010

### Wave 7 —— 下线旧整树接口

- [ ] **T012**: 移除旧整树接口与前端封装 + 静态扫描
  **文件**: `department/api/endpoints/department.py`(删旧 `/tree`)、platform `controllers/API/department.ts`(删 `getDepartmentTreeApi`)
  **逻辑**: 确认无引用后删除；全仓静态扫描无"加载整棵部门树"的调用方
  **覆盖 AC**: AC-20
  **依赖**: T008, T009, T009b, T010（全部消费方迁完）

### Wave 8 —— 性能门禁 + 契约登记

- [ ] **T013**: 5 万实测门禁
  **逻辑**: 105 上 `children(根)`/`children(深节点)`/`search` 各 <200ms、授权列表 <1s（design §7.1 范式）
  **覆盖 AC**: AC-19
  **依赖**: T004, T006

- [ ] **T014**: release-contract 登记 F038 + F027 反转说明
  **文件**: `features/v2.6.0/release-contract.md`、F027 `design.md`/`spec.md`
  **逻辑**: 表1 标"无新增领域对象"、表3 加依赖（F027/F033/F026/F004/F008/F011-13）、变更历史加一行；并在 F027 留 AC-16 反转说明（成员数移除）
  **依赖**: 无（可随时做）

---

## 实际偏差记录

> 只留一行指针，论证在 design.md。推翻已 ★ 确认决策前先停下重新确认。

- （暂无）
