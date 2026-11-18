# 组织搜索与设置：实现设计

## 1. 当前状态

目标发版线 feat/3.1.0-beta1，真实页面入口为 SystemPage/components/OrganizationAndMembers.tsx → Departments.tsx。左侧搜索可定位任一可见归属，右侧成员列表可在直属与当前部门子树之间切换。

## 2. 约束

遵循 docs/constitution.md C1–C7 和前后端 AGENTS.md。用户已确认聊天方案并授权实现，不另出 PRD。新增数据库查询全部放在 department/domain/repositories，沿用树的 _aget_user_scope 权限入口与现有租户 ContextVar；分组子查询和未投影 Department 的联查使用现有 build_tenant_filter_clause，保持与自动过滤器完全一致，不直接拼接租户 ID。不新增运行时依赖、表或错误码。

## 3. 关键决策

1. 新增组织页专用搜索接口，保留既有 /search 与 /search/global-members 的调用契约，防止人员选择器规则被一起改变。只有组织页需要完全相同规则时才考虑合并。
2. 先分页查询去重用户，再批量读取其可见所属部门和祖先；主属优先，其次选中兼职，最后使用祖先 sort_order/id 组成的树序。路径只投影可见节点，响应不包含隐藏主部门。避免为每个成员查询一次或加载整棵组织树。
3. 定位返回真实页码与有效所属关系筛选；成员列表明确按 UserDepartment.id 排序，定位以同一顺序计数。原查询没有显式顺序，这里补齐稳定顺序。
4. 复用 useSubjectSearch 的取消请求、IME 和增量加载能力；组织树搜索关闭，树保持挂载以保留展开与滚动状态。两组结果分别加载。
5. 设置与流量状态提升到设置弹窗，内容切换时保留挂载；基本设置与流量依次保存，成功模块更新本地基线，失败模块保留编辑内容并明确反馈，避免错误宣称原子保存。
6. 定位期间隐藏旧分页器，待新部门的总数与目标页同时到达后再展示，避免旧总数将目标页纠正回第一页。树展开完成后从最新控制器读取节点，避免异步加载后的旧闭包。
7. 部门移动成功后立即更新父部门基线；后续设置失败时保留其他修改，重试不重复移动。保存期间锁住编辑区；离开有部分已提交的弹窗时刷新页面。
8. 部门标题旁默认勾选直属成员。展开范围使用一次服务端分页查询，避免前端逐部门拉取后合并造成分页、筛选和总数错位。列表按所属关系保留多部门行，直属行排在所有下级行之前并沿用原顺序，因此左侧定位接口计算的页码在两个范围下都有效。归档可见性跟随组织树，编辑按行对应部门执行。若未来改为每人只显示一次或增加列表排序，须同时调整归属投影和定位规则。

重新评估条件：人员选择器也需要统一搜索规则时再合并搜索契约；部门数据量导致包含查询明显变慢时再评估索引或专用检索；成员列表增加排序选项时必须同步定位排序；服务端提供跨基本设置与流量的事务接口后再考虑单次原子保存。

## 4. 数据流与字段

### 4.1 数据流

OrganizationSearchPanel → controllers/API/organization → organization_search endpoint → OrganizationSearchService → OrganizationSearchRepository → scoped SQL。

### 4.2 接口

- GET /api/v1/departments/search/directory：keyword、kind=members/departments、page、limit、include_archived、preferred_department_id；返回 data/total。
- 部门行：id/dept_id/name/status/parent_path。
- 成员行：user_id/user_name/person_id/enabled/is_primary/department；department 仅为可见的实际定位部门，含 id/dept_id/name/status/path。
- GET /api/v1/departments/{dept_id}/members/locate：user_id、limit、is_primary、include_archived；返回 page/is_primary_filter/filter_adjusted。沿用部门 21000/21008/21009 错误。
- GET /api/v1/departments/{dept_id}/members：`include_descendants=true` 时通过 `DepartmentMemberRepository` 分页查询管理范围与部门子树的交集。`include_archived` 控制展开模式的归档范围。响应追加直属数量 `direct_total` 和行所属部门 `department`（dept_id/name/status）；直属请求沿用原响应。

### 4.3 模块职责

Departments 负责选中部门、树展开、定位请求与弹窗入口；MemberTable 负责稳定分页与可见后的高亮；DepartmentSettingsDialog 组合基本设置与流量编辑，不取得其领域写入权。旧 DepartmentPage 路由复用同一入口，避免保留两套交互。

## 5. 已知坑

| 情况 | 后果 | 处理 |
| --- | --- | --- |
| 只按主部门过滤搜索 | 有权限的兼职成员搜索不到 | 对所有可见所属关系去重 |
| 定位只在当前页滚动 | 第二页以后的成员不可见 | 服务端真实页码与稳定排序 |
| 直接显示全局祖先链 | 泄漏管理范围外组织名称 | 按可见路径逐节点裁剪 |
| 页签卸载局部状态 | 未保存的流量修改丢失 | 状态放在弹窗，两块内容保留挂载 |
| 工作区已有 locale/login 等改动 | 覆盖他人修改 | 只追加本功能键，保留已有差异 |
| 分组总数子查询隐藏 Department 表 | ORM 外层自动过滤无法识别，总数泄漏跨租户匹配 | 在内层复用 build_tenant_filter_clause，数据与计数一致过滤；由跨租户 SQL 用例验证 |
| 从小部门定位到大部门第二页 | 旧 total 使共享分页器先把 page=2 改回 1 | MemberTableView 加载期间不挂载分页器；MemberTablePagination.test.tsx 回归 |
| reveal 加载尚未展开的深层分支 | 原闭包内 getNode 找不到刚加载的节点 | Departments 使用 treeRef 读取最新控制器，下一帧后再定位 |
| 移动成功、基本设置更新失败 | 重试再次移动，退出后页面仍是旧路径 | DepartmentSettings 即时更新父部门基线，Dialog 记录部分成功并刷新 |
| 请求保存期间继续编辑 | 请求使用旧值，成功关闭时带走新输入 | DepartmentSettingsDialog 锁住编辑区并阻止关闭 |
| 展开范围后一人有多条归属 | 按人员 ID 定位会高亮到下级兼职行，按当前部门编辑可能打开错误的归属 | MemberTable 用人员与部门标识精确定位，编辑弹窗接收实际行部门 |

## 6. 契约与验证

Incoming：组织树可见范围、现有成员关系、管理视图请求隔离。Outgoing：组织页只读搜索、定位与可选的子树分页；人员选择器沿用直属成员接口的默认行为。

已完成 SQLite 真实 SQL 回归、HTTP endpoint/service/repository 链路、前端组件交互与真实浏览器场景。HTTP 测试替换登录与外部权限范围依赖；浏览器使用实际页面源码与模拟 API，未验证真实部署的登录、网关和 OpenFGA。MySQL/DM8 真实数据库与完整中间件集成按仓库约定交由 CI/目标环境，本次未运行方言编译或真实双数据库联调。命令与结果见 verification.md。

## 修订历史

2026-11-10：按用户已确认截图与聊天方案实现组织搜索、定位与弹窗；实际测试结果另记 verification.md。

2026-11-10：浏览器回归发现并修复旧总数导致跨页定位回退、深层展开闭包过期；补齐移动部分成功与保存中编辑保护，完成本地验证。

2026-11-12：按聊天确认增加标题旁的直属范围复选框和子树成员分页，创建部门入口保留在组织树。
