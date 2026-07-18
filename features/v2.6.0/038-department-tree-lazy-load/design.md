# Design: F038-department-tree-lazy-load（部门树懒加载）

> **本文档定位 — 现状快照（Why this How）**
> - [spec.md](./spec.md) 回答 **做什么**；本文回答 **为什么这么实现**；[tasks.md](./tasks.md) 是流水账。
> - 实现变化 → 覆盖更新本文，只留"今天的状态"，但每个决策保留"为什么 + 被否方案 + 何时重审"与坑。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-30（两端懒加载全部落地 + 旧整树端点全下线 + 授权列表/选人两处 path-tree N+1 修复；见修订历史）

---

## 1. 目标与非目标

- **目标**：把"部门树"从一次性整树加载改为**按层懒加载 + 服务端搜索 + 按 id 定位**，在 5 万部门规模下把首屏/展开/搜索降到亚秒级，同时**逐节点等价复刻**改造前的三层权限可见性。覆盖 platform 部门管理树与其全部选部门入口，以及 client 授权部门选择器（知识空间共享 / 频道授权）。顺带移除授权部门列表里代价极大且不展示的"按部门成员数"统计。
- **非目标**：
  - 不做单父节点超宽（上千直接子）的分页（本期单层全量；后续若做走 INV-6）。
  - 不引入整树服务端缓存（懒加载后单请求已足够小）。
  - 不改部门成员列表/成员搜索协议、不改单部门成员数、不改挂载点/子租户机制。
  - 不统一 platform 与 client 两套前端（两套独立应用，各自实现）。

---

## 2. 关键约束

- 全局铁律遵循 `docs/constitution.md` C1–C7（分层 / 双 DB / 多租户自动注入 / 权限统一入口 / 错误码 / 前端 store 不直连 HTTP）。本节只列**本功能特有**约束：
- **C1 分层与 DAO 入口**：Service 不写 ORM、不跨模块导入 models。取数尽量复用现有 `DepartmentDao.aget_children`（单层，但**仅 active**——见下）/ `aget_subtree` / `aget_subtree_ids` / `aget_by_ids`。其中三类查询现有方法不覆盖，需在 **`DepartmentDao` 内（部门查询是其既有职责，非新建 DAO 类/非跨模块新入口，符合 C1 本意）** 扩展：
  - 取子层含归档：`aget_children` 现写死 `status='active'`，导航树需 active+archived → 给它加 `status` 参数（扩展既有方法，非新方法）；
  - **按名搜索**：`WHERE name LIKE :kw AND <scope path filter> LIMIT n` —— 现有方法无 name 匹配，需在 DepartmentDao 新增一个搜索方法；
  - **has_children 批量**：`SELECT parent_id, COUNT(*) ... WHERE parent_id IN (<本层 id>) GROUP BY parent_id` —— 需新增一个批量统计方法。
  range/scope 判定一律留在 Service（用 `path` 前缀 / `admin_paths`），DAO 只接收已算好的 path/ids，不含权限逻辑。
- **双 DB（C2）+ 达梦性能陷阱**：达梦 `dmAsync` 是"假异步"（内部同步 dmPython 阻塞事件循环），且**大 `.in_()` bind 参数序列化随参数量爆炸**（5 万参数级别会到几十秒）。→ 凡按 id 集合查询都必须**避免把全量 id 灌进 `.in_()`**；分层/分父查询天然规避。
- **多租户（C3）**：所有部门查询在租户上下文内，`tenant_id` 由 SQLAlchemy 事件自动注入，不手写。
- **权限范围（C4）**：可见性 = ReBAC/管辖范围 + 物化路径前缀。三层分级语义见 §4.1；**懒加载/搜索/定位必须逐节点等价复刻**。
- **物化路径**：`Department.path` 形如 `/1/21/106/`（祖先 id 链，以 `/` 包裹），`parent_id` / `path` / `status` 均有索引 → `WHERE parent_id=? AND status IN(...)` 与 `path LIKE 'prefix%'` 都走索引。
- **INV-6 边界（版本契约）**：INV-6 要求"走 ReBAC 过滤的高频列表"用 cursor 分页且不返 `total`。本特性的"取子层/搜索"返回**单层/剪枝树、本就不返 `total`、不分页**，故**不套 cursor 信封**；仅当未来做"单父节点超宽分页"时才落 INV-6（走 `common/cursor.py`）。此边界在 §3 决策 6 固化。
- **两套独立前端应用**：platform（Zustand/RQv3/bs-ui/`@/`）与 client（Recoil/RQv5/shadcn/`~/`）不可混用组件（root `AGENTS.md` §4）。
- 上游：F033 提供授权部门列表的子树收敛（`restrict_dept_ids`）；F026 频道授权与知识空间共用同一后端 helper。

---

## 3. 方案对比与选定

### 决策 1：加载模型 —— 整树 / 按层懒加载 / 整树缓存

- **备选**：
  - A. 保留整树，仅做服务端序列化优化（按列查询 + 直建 dict + ORJSONResponse）：6s→~2s。改动小，但响应仍 ~14MB、前端仍渲染 5 万节点，治标。
  - B. **按层懒加载**：首屏取根层，展开取子层，搜索/定位走服务端。响应降到 KB 级，亚秒。
  - C. 整树 + Redis 缓存：首请求慢、后续快，但缓存随权限范围/租户分形、失效复杂。
- **选定**：**B**。
- **原因**：5 万规模下整树是结构性问题（传输 + 前端渲染 + 序列化），A 只压一头；C 的缓存键随"每用户管辖范围"分形、失效面大，收益不抵复杂度。B 单请求天然小、无缓存一致性问题。
- **何时重审**：若产品要求"一次性看到全组织展开态"或出现"单层超宽"成为新瓶颈。

### 决策 2：API 形状 —— 重载旧接口 / 新增语义化端点 + 迁移期并存

- **备选**：
  - A. 给旧整树接口加 `parent_id/depth/keyword` 参数重载。语义含糊、迁移期 picker 需传兼容标记。
  - B. **新增三个语义化端点（取子层 / 搜索 / 定位），旧整树接口迁移期保留、迁完删除**。
  - C. B + 子层游标分页（抗超宽）。
- **选定**：**B**（吸收 B 的 `depth` 思路但 MVP 不做分页，超宽留作 C 后续）。
- **原因**：语义清晰、迁移期向后兼容、易测；超宽分页属过度设计（真实组织单层子节点通常有限，且我们 fanout 不大）。
- **何时重审**：若单父节点直接子节点常态超过数百 → 落 C（按 INV-6 cursor）。

### 决策 3：两端点族**各自** scoping，不强行统一

- **事实**：platform 部门管理树（`/departments/*`）的可见性是**管辖范围**（系统管理员=全树；部门管理员=其 admin 部门子树；租户管理员=其挂载点子树）；client 授权部门列表（`grant-subjects/departments`）的可见性是**租户根子树（`path LIKE root_dept.path%`）减去子租户挂载子树，再可选按 F033 `restrict_dept_ids` 收敛**——两者范围逻辑根本不同。
- **选定**：两端点族**各自实现** children/search/reveal，**只共用机械 helper**（单层取数、`has_children` 批量统计、剪枝树组装），**不共用范围判定**。
- **原因**：强行统一会把两套不同的可见性语义耦合进一个查询，易出越权/漏看；分开后每族的 scoping 与各自旧接口逐节点对齐、可单测。
- **何时重审**：若两族范围语义将来收敛为同一套（不太可能）。

### 决策 4：搜索返回"剪枝树"而非扁平列表

- **备选**：A. 扁平命中列表（点结果再定位）；B. **命中节点 + 其全部祖先组装的剪枝树**（前端直接展开渲染）。
- **选定**：**B**。
- **原因**：复刻今天"输入即过滤、树展开到结果、隐藏无关分支"的体验；剪枝树能直接喂现有树渲染器 + 自动展开祖先逻辑。定位（按 id）复用同一套剪枝组装（seed 从"关键词命中集"换成"单个/一组 id"）。
- **何时重审**：若产品要求搜索结果以"扁平列表 + 路径名"呈现（而非树内展开），或剪枝树在极端命中分布下祖先膨胀过大。

### 决策 5：`has_children` 用批量统计，不逐节点查

- **备选**：A. 逐节点 `EXISTS` 查（N+1）；B. **本层 id 一条 `GROUP BY parent_id` 批量统计**；C. 不返 `has_children`，前端总显示展开箭头、点开再判空。
- **选定**：**B**。
- **原因**：单层节点数有限，一条聚合即可；A 是 N+1；C 会出现"点开才发现是空"的虚假箭头，体验差。
- **达梦注意**：本层 id 数有限（单层），`.in_()` 不会触发决策 §2 的大参数陷阱。
- **何时重审**：若单层节点数常态过大使一次 `GROUP BY` 也变慢（与"单父超宽"同源，届时随分页方案一并改）。

### 决策 6：INV-6 边界固化

- **选定**：取子层/搜索/定位**不套 cursor 信封、不返 `total`、不分页**（语义是"一层/一棵剪枝树"，非翻页列表）；**仅"单父超宽分页"才落 INV-6**。
- **原因**：INV-6 治的是"翻深页 ReBAC 线性退化"，本特性单层有界、无翻页，套 cursor 是负担；但保留 INV-6 作为超宽分页的唯一正确形态，避免将来另造轮子。
- **何时重审**：一旦做"单父超宽分页"（决策 2-C），该层即变为翻页列表，**必须**改套 INV-6 cursor 信封（`common/cursor.py`、`has_more`/`next_cursor`、不返 `total`）。

### 决策 7：响应直接走 ORJSON，绕过 `jsonable_encoder`

- **事实（实测）**：旧整树接口返回 `UnifiedResponseModel`(pydantic) 时，FastAPI 对 ~14MB 结构再跑一遍 `jsonable_encoder`（实测 ~1.4s）+ 标准库 `json`（~0.14s）；这是 6s 里的隐藏大头之一。
- **选定**：懒加载端点**直接构造 dict 树并用 ORJSON 返回**（或等价），跳过 `jsonable_encoder` 全遍历；不经 pydantic 二次建模/dump。
- **原因**：实测 ORJSON 对同结构 ~18ms vs jsonable_encoder ~1.4s。懒加载后单响应虽小，但保持该范式以免回退。
- **何时重审**：若框架升级使默认序列化等价于 ORJSON。

### 决策 8：两前端各自实现懒加载树，不跨应用共用

- **选定**：**platform** 内抽一套可复用懒加载树（hook + 展示组件，置于 bs-comp），供其 8 个消费方复用；**client** 在其授权选择器内自建懒加载实现（Recoil/RQv5/shadcn），由知识空间共享与频道授权两弹窗**在 client 内部共用**（二者本就用同一选择器）。
- **原因**：platform/client 是两套不可混用应用（不同状态库/请求库/UI 库/别名）。跨应用"复用组件"违反架构边界。
- **何时重审**：除非将来 platform 与 client 合并为同一应用（与现行架构相悖，基本不会）。
- **坑**：两应用各有一个**同名** `SubjectSearchDepartment.tsx`（platform 版用部门树接口、client 版用授权接口），切勿混改（见 §5）。

### 决策 9：隐式选中改为按 `path` 判定，不靠递归下传

- **事实**：现 client 选择器把 `ancestorIncluded` 沿递归从父传子来算"隐式选中"——只在整树都渲染时成立。懒加载下子节点可能在祖先未渲染时被单独加载。
- **选定**：每个节点用自身 `path`（祖先 id 链）判断"是否有祖先在'含子部门'选中集中"，得出隐式选中态。
- **原因**：脱离"祖先必须已渲染"的假设；O(path 深度) 每节点，无需整树。
- **何时重审**：若选择语义改为"父含子部门可单独排除某子部门"（决策 10 被推翻），隐式选中需引入"例外集"，判定逻辑随之扩展。

### 决策 10：「含子部门」全有或全无，去掉 materialize；授予真相 = 显式勾选 + flag

- **事实（实测代码）**：client 授权提交的是"显式勾选的部门 + `include_children` 标记"，**后端展开子树**；前端从不枚举后代 id。现"materialize（把隐式选中展开成逐个显式以便单独取消）"需要枚举后代，懒加载下不可行。
- **选定**：**取消单独排除某子部门**，"含子部门"对整子树全有或全无；移除 materialize 路径；隐式选中的子项不可单独取消（取消需改父级开关）。
- **原因**：与"后端展开"的授予模型一致；避免懒加载下枚举后代（可能 5 万）。已与用户确认。
- **何时重审**：若产品强需"父含子部门但排除个别子部门"。

### 决策 11：移除授权部门列表的成员数统计（推翻 F027 AC-16）

- **事实（实测）**：`_list_knowledge_space_grant_departments` 为每个部门统计成员数，用 `COUNT(*) WHERE department_id IN (<全子树 id, 5万>) GROUP BY`；该巨型 `.in_()` 在达梦实测 **66s**（占整接口 ~96%，见 §5），前端实为一个可去除的小角标。
- **选定**：删除该计数查询与 `member_count` 字段（后端），删除 client 角标展示（前端）。**反转 F027 AC-16**（其当时"PRD 未明示移除"而保留）。
- **状态**：已落地（提交 `b8e481872`）；69s→~3s。后续叠加懒加载再降到亚秒。
- **何时重审**：若产品确需在授权选择器展示成员数 → 须换"按 path 子树批量计数"等不爆 `.in_()` 的实现，不可回退原查询。

### 决策 12：变更后刷新用"失效受影响父层"，不整树重拉

- **备选**：A. 变更后整树重拉（旧行为）；B. **只失效受影响父节点的子层缓存**（移动失效新旧两父）；C. 乐观本地改 + 不重拉。
- **选定**：**B**。
- **原因**：与懒加载一致、最小刷新面；A 退回 6s 整树；C 易与服务端真值不一致（如重名校验、排序、`has_children` 变化）。platform 用 react-query 失效对应 query key。
- **何时重审**：若变更涉及大范围结构调整（如批量移动/导入），单父失效不足以反映全貌时，考虑失效更大范围或局部重拉。

---

## 4. 系统现状（接手必读）

### 4.1 后端数据流与三层 scoping（改造前 → 改造后）

**platform 部门管理树**（`bisheng/department/`）：
- 改造前：`DepartmentService.aget_tree`（`department_service.py:411`）一次性 `select(Department).where(status in [active,archived])` 取全量 → 内存建树 → 按 scoping 过滤 → 返回 `DepartmentTreeNode[]`。
- 三层 scoping（须复刻）：
  - 系统管理员 `_is_admin`（`:79`）→ 全树。
  - 部门管理员 → `DepartmentDao.aget_user_admin_departments`（`department.py:686`，OpenFGA `list_objects(admin, department)` + DB grant 回退）取管辖部门，`admin_paths = {d.path}`，可见 ⟺ `dept.path.startswith(任一 admin_path)`。
  - 租户管理员 `_is_tenant_admin`（`:165`）→ `_aget_user_tenant_root_path`（`:192`，挂载点 path）并入 `admin_paths`。
  - 非以上且无管辖 → `DepartmentPermissionDeniedError`。
- **scoping 复用范式**：`aget_global_members_search`（`department_service.py:1242`）已用 `or_(Department.path.like(f"{p}%") for p in admin_paths)` 把同一套范围下推到 SQL——懒加载 children/search 的 scoping **照此范式**。
- 改造后端点（新增，旧 `/tree` 已下线 `a097be203`，`aget_tree` 仅留作 parity oracle）：
  - `GET /departments/children?parent_id=&include_archived=` — 取根层（无 parent_id）或某节点直接子节点，节点带 `has_children`。
  - `GET /departments/search?keyword=&limit=` — 命中 + 祖先剪枝树。
  - `GET /departments/{id}/path-tree` — 根→该 id 的剪枝树（定位/回显）。
  - DAO 复用 `aget_children`(`:357`) / `aget_subtree`(`:378`) / `aget_by_ids`(`:283`)；`has_children` 批量统计。

**client 授权部门列表**（`bisheng/permission/api/endpoints/resource_permission.py`）：
- `get_grant_subject_departments`（`:1427`）→ `_list_knowledge_space_grant_departments`（`:830`）：取**租户 `root_dept_id` 子树**（`path LIKE root_dept.path%`），系统租户时再排除子租户挂载子树（`~path LIKE child_mount%`），可选 `restrict_dept_ids`（F033）收敛 → 建树返回。成员数统计已删（决策 11）。
- 频道授权 `ChannelAuthorizationService.list_grant_departments`（`channel_authorization_service.py:211`）**直接复用**同一 helper（`restrict_dept_ids=None`）→ 改一处覆盖两端。
- 改造后：为该端点族新增"取子层 / 搜索 / 定位"变体，scoping 用其自身的"租户子树 + F033"逻辑（**不复用 platform 的 admin scoping**，决策 3）。

### 4.2 关键数据结构 / 字段约定（对外契约）

`DepartmentTreeNode`（`department_schema.py:86`）现有字段：`id, dept_id, name, parent_id, path, sort_order, source, status, is_tenant_root, mounted_tenant_id, children`。本特性新增两个可选字段（默认值保证向后兼容）：

| 字段 | 类型 | 说明 | 谁消费 |
|---|---|---|---|
| `has_children` | bool=false | 该节点是否有子节点（懒加载用，决定展开箭头） | 两前端的懒加载树 |
| `matched` | bool=false | 搜索/定位剪枝树中是否为命中目标 | 两前端的搜索高亮 |

搜索/定位响应：`{ roots: DepartmentTreeNode[]（剪枝树，children 已填充）, total_matches: int, truncated: bool }`。
取子层响应：`DepartmentTreeNode[]`（单层，`children=[]`，带 `has_children`）。
授权提交（不变）：`grants[] = { subject_type:"department", subject_id, include_children }`，后端展开子树。

### 4.3 关键模块职责

**后端**
| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `department_service.py` | platform 树 scoping + children/search/path-tree 编排 | 不写 ORM（走 DAO） |
| `database/models/department.py`（DAO） | 单层/子树/批量取数 | 不含权限范围逻辑 |
| `resource_permission.py` 授权 children/search/path-tree（`_grant_departments_*` + `_resolve_grant_dept_scope`，租户子树+F033） | 授权树懒加载端点族（全树 `_list_knowledge_space_grant_departments` 已下线） | 不复用 platform admin scoping |
| `department_change_handler.py` | create/move/archive 的 FGA 边（`on_created:31`/`on_moved:43`/`on_archived:63`） | 与缓存失效解耦 |

**platform 前端**（`src/frontend/platform/`，8 个消费方）
| 组件 | 职责 | 不做什么 |
|---|---|---|
| `bs-comp/department/`（新）可复用懒加载树 hook + 展示组件 | 单层加载/展开/搜索/定位、`has_children` 箭头 | 不含权限范围判定（后端定）；不被 client 复用 |
| `DepartmentPage/`、`SystemPage/components/Departments.tsx`、`Roles.tsx` | 主树/系统部门/角色范围，接入懒加载件 | 不自行整树加载/不客户端递归过滤 |
| `bs-comp/department/TreeDepartmentSelect.tsx`、`bs-comp/selectComponent/DepartmentUsersSelect.tsx`、`bs-comp/permission/SubjectSearchDepartment.tsx`(platform 版)、`BuildPage/bench/DepartmentKnowledgeSpaceManagerDialog.tsx`、`DepartmentPage/components/OrganizationMemberEditDialog.tsx` | 各 picker，复用懒加载件 + 定位回显 | 不绕开懒加载件各搞一套 |
| `controllers/API/department.ts` | 新增 children/search/path-tree 封装；迁完删 `getDepartmentTreeApi` | 不直连 axios（走 request 模块，C7） |

**client 前端**（`src/frontend/client/`）
| 组件 | 职责 | 不做什么 |
|---|---|---|
| `components/permission/SubjectSearchDepartment.tsx`(client 版) | 授权部门选择器：自建懒加载/搜索/定位 + 选择语义（决策 9/10） | 不与 platform 同名件混用；不枚举后代来提交（授予走显式+含子部门） |
| `components/permission/PermissionGrantTab.tsx` | 装载选择器；授予提交=显式勾选+含子部门；`disabledIds` 来自资源已有授权 | 不从部门树推导"已授权"集合 |
| `pages/knowledge/SpaceDetail/KnowledgeSpaceShareDialog.tsx`、`pages/Subscription/ChannelPermissionDialog.tsx` | 知识空间/频道两入口，client 内共用上面选择器 | 不各自实现部门树 |
| `api/permission.ts` | `getResourceGrantDepartments` 等；新增 children/search/path-tree 封装 | 不直连 axios（走 `~/api/request.ts`，C7） |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | **达梦大 `.in_()` 灾难**：`COUNT WHERE department_id IN (<5 万 id>)` 在达梦 `dmAsync` 假异步下序列化 bind 参数耗 **66s**（实际只 107 组有成员，慢的全是参数串） | 任何"按全量 id 集合查询"都会随用户量爆炸；授权页卡死 | 决策 11 已删该查询；凡按 id 集查询改分层/按 path 子树 |
| 2 | **`jsonable_encoder` 隐藏开销**：返回 pydantic `UnifiedResponseModel` 时 FastAPI 对 ~14MB 结构再全遍历一遍（实测 ~1.4s），叠加 ORM 全实例化（~3.2s）+ pydantic 两遍建模/dump（~1.9s）才凑成 6s | 只优化 SQL 查询仍慢，找不到真凶 | 决策 7：直建 dict + ORJSON 返回 |
| 3 | **隐式选中必须按 `path` 算，不能靠递归下传**：旧 client 选择器沿父→子递归传 `ancestorIncluded`，懒加载下子节点可能在祖先未渲染时单独出现 | 懒加载出来的子节点"含子部门"隐式选中态全错（漏勾/错勾） | 决策 9：用 `node.path` 祖先 id 链判定 |
| 4 | **搜索/定位祖先必须 clamp 到管辖范围**：回溯祖先时若一路上探到平台根，会泄露管辖范围之上的部门名 | 越权信息泄露（部门名/存在性） | search/path-tree 祖先回溯止于 `admin_paths`/租户范围 |
| 5 | **两个同名 `SubjectSearchDepartment.tsx`**：platform 版（`bs-comp/permission/`，用部门树接口）与 client 版（`components/permission/`，用授权接口）同名不同物、不同应用 | 改错文件/改错应用，破坏另一处 | §4.3 已分列；按路径区分 |
| 6 | **`_list_knowledge_space_grant_departments` 被 F033 + F026 共用**：知识空间授权与频道授权同一 helper（频道传 `restrict_dept_ids=None`） | 改一处影响两端；漏测频道 | 改动同时覆盖两端；测试覆盖两 resource_type |
| 7 | **授权"已授权"集合来自资源已有授权、不来自树**：`PermissionGrantTab` 的 `disabledIds` 由 `getPermissions(resource)` 提供，与是否加载整树无关 | 误以为懒加载会丢失"已授权"判定 | 决策 10 + spec §3 权限安全不变量；验收做等价性核对 |
| 8 | **物化路径格式 `/1/21/106/`**：以 `/` 包裹的祖先 id 链；前缀匹配靠它 | 解析祖先 id、`startswith`/`LIKE` 写错会漏/越权 | 解析按 `/` 切分、去空段 |
| 9 | **授权列表"每个授权部门一次 path-tree"是隐形 N+1**：include_children 授权被**后端展开成每个后代部门一条 tuple**，故权限列表可有几百条部门行；若前端为每行单独取 path-tree 全路径标签，打开界面就是几百并发请求（实测 ~20s） | 成员管理界面卡死；同选人组件按结果页每个不同部门取 path-tree 同理 | **后端**在权限列表响应里直接把部门 `subject_name` 解析成全路径（`_resolve_subject_names` 批量取部门+一次补载祖先名）；选人改 `/user/list?with_department_path`；前端删 per-grant/per-dept path-tree |
| 10 | **看部门设置时不能无条件取「上级部门」path-tree**：子租户管理员的租户根部门、或超管看子租户根，其 parent 在查看者 scope 外 → `path-tree(parent_id)` 越权(21009)/多余根查询 | 进部门设置默认弹越权 toast / 多发一次根查询 | `DepartmentSettings` 仅当当前部门**不是**可见树顶层(`children(null)` 不含它)**且非租户根**时才取父 path-tree；租户根/绝对根一律按"根"对待 |
| 11 | **scope 过滤必须 fail-closed**：`aget_by_name_like` 旧契约把 `path_prefixes=[]`(空 scope) 当 `None`(无 scope) → 非超管空 admin_paths 会退化成租户级 `name LIKE`，虽剪枝丢行但泄露命中计数 | 空 scope 用户搜索泄露租户级匹配数 | `asearch_tree` 对非超管空 admin_paths 短路返空；DAO `[]`→无行(fail-closed)，仅 `None`→无 scope |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /departments/children`、`/departments/search`、`/departments/{id}/path-tree` | HTTP API（platform 范围） | platform 部门树各消费方 |
| 授权页 `grant-subjects/departments` 的 children/search/path-tree 变体 | HTTP API（租户子树/F033 范围） | client 授权选择器（知识空间 + 频道） |
| `DepartmentTreeNode` 增 `has_children` / `matched` 字段 | 响应字段（可选，默认 false） | 两前端 |
| ~~`_list_knowledge_space_grant_departments`~~ + 全树 `grant-subjects/departments`(resource+channel) | **已下线**(`096ebbafa`) | 无(client 已全迁 lazy) |
| `DepartmentService.aget_tree` | 内部 Python(**仅保留作 scope 等价 oracle**,无 HTTP 路由) | `test_department_scope_parity` 等 parity 测试基线 |
| children/search/path-tree 编排方法 | 内部 Python(Service 入口) | platform 部门树端点;改签名/语义需同步各调用方 |
| ~~旧整树接口 `/departments/tree`~~ | **已下线**(`a097be203`) | 无(两端全迁 lazy) |
| `GET /user/list?with_department_path=true` 返回 `department_path`(主属部门全路径) | HTTP API(可选参数,默认不返) | platform `DepartmentUsersSelect` 扁平用户搜索(替代 per-dept path-tree) |
| `GET .../permissions` 部门项 `subject_name` = 全路径(`总公司/研发部/平台组`) | 响应字段语义(后端 `_resolve_subject_names` 批量解析) | 两端 `PermissionListTab`(替代 per-grant path-tree) |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F033 `_resolve_department_space_scope` → `restrict_dept_ids` | 内部 Python | F033 改子树收敛语义会影响授权树范围 |
| F026 频道授权复用 `_list_knowledge_space_grant_departments` | 内部 Python | 改 helper 须保频道语义 |
| `DepartmentDao.aget_user_admin_departments`（OpenFGA + DB 回退） | 内部 Python | OpenFGA 不可用时回退 DB grant（沿用） |
| `Department.path` 物化路径格式 | 隐式数据契约 | 上游若改 path 维护方式会静默坏 scoping |
| 授权提交 `include_children` 由后端展开子树 | 隐式契约 | 后端展开语义变则前端"含子部门"语义需同步 |

---

## 7. 测试与可观测

- **后端单测**（`test/department/`、`test/permission/`，`asyncio_mode=auto`，可无中间件跑）：
  - **scoping 等价性**：构造小部门树 fixture，断言"懒加载 children/search 的可见集" == "旧 aget_tree 在同一 fixture 的可见集"，覆盖系统/部门/租户管理员/非管理员四档与越权 403（防漂移）。
  - search：范围下推、祖先 clamp 不越权、`truncated`、空关键词、剪枝树连通性。
  - 授权树：两 resource_type（知识空间 + 频道）、F033 `restrict_dept_ids`、**无成员数字段 + 无计数查询**（已落地 `test_grant_subject_departments_helper_omits_member_count`，断言只 3 次结构查询、无第 4 次计数）。
- **授权等价性核对**（权限安全不变量）：懒加载前后、相同勾选下提交的 `grants` 必须逐项等价。
- **5 万实测门禁**（达梦压测环境）：`children(根)`、`children(深节点)`、`search(关键词)` 各 **<200ms**；授权列表 **<1s**（对比改造前 6s / 69s）。
- **E2E + 手动**：走 `/e2e-test`，覆盖 懒加载展开 / 搜索定位 / picker 预选回显 / 已授权置灰 / 变更后刷新。
- **可观测**：单父节点子层数超阈值（如 500）`logger.warning`（不静默截断，留 INV-6 分页的信号）。

### 7.1 手动验证（5 万部门压测环境，可操作）

- **环境**：host `192.168.106.105`（`root` / `dataelem`）；后端容器 `bisheng-backend-dm`，代码根 `/app`，服务用默认 `config.yaml`（=`/app/bisheng/config.yaml`）；租户 1、`root_dept_id=1`；已灌 5 万 `source=loadtest` 部门 + 15 万用户。前端：client `http://192.168.106.105:3001/workspace`。登录账号：压测本地用户统一密码 `Test@1234ab`（如 `压测用户_0000000`），或现有管理员账号。
- **后端分段计时范式**（容器内、与服务同 config，**实证定位"哪一步慢"**，已用它定位 member_count 66s / jsonable_encoder 1.4s）：
  ```bash
  cat timing_script.py | SSHPASS='dataelem' sshpass -e ssh -o StrictHostKeyChecking=no root@192.168.106.105 \
    'docker exec -i -e config=config.yaml -e PYTHONPATH=/app bisheng-backend-dm /app/.venv/bin/python - 2>/dev/null'
  ```
  脚本里 `initialize_app_context(config=settings)` + `bypass_tenant_filter()` + `set_current_tenant_id(1)` 后，对 `aget_tree` / 新 children / search / `_list_knowledge_space_grant_departments` 分步 `time.perf_counter()` 计时。
- **端点直测**（带登录 token）：
  - `GET /api/v1/departments/children`（无 `parent_id`=根层）/ `?parent_id=<id>` / `?keyword=` / `/{id}/path-tree`，确认单次 **<200ms**、响应仅单层/剪枝树。
  - `GET /api/v1/permissions/resources/knowledge_space/<id>/grant-subjects/departments`，确认**无 `member_count` 字段**、单次 **<1s**（改造前约 69s）。
- **授权等价性核对**：对同一组勾选，分别在"懒加载前(旧整树)"与"懒加载后"提交，diff 两次 `authorize` 的 `grants` 必须逐项等价（验证 spec §3 权限安全不变量）。

---

## 8. 后续改进 / 不打算做的事

- **单父超宽分页**：本期单层全量；超过数百常态时按 INV-6（`common/cursor.py`）做子层 cursor 分页。
- **整树缓存**：不做（懒加载后无必要）。
- **授权选择器展示成员数**：移除后若要恢复，须用"按 path 子树批量计数"等不爆 `.in_()` 的实现，禁止回退原 `IN(全量 id)` 查询。
- **platform/client 懒加载件统一**：两套独立应用，不统一。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-29 | 初版；决策 1–12；member_count 移除已落地（`b8e481872`，反转 F027 AC-16） | F038 设计；5 万压测实测 |
| 2026-06-30 | 两端懒加载全部落地（platform 8 消费方 + client 授权选择器）；**旧整树端点全部下线**：`GET /departments/tree`（`aget_tree` 保留作 scope 等价 oracle）、全树 `grant-subjects/departments`（resource + channel）、`_list_knowledge_space_grant_departments`；故 §4.1/§4.3/§6.1 中这些已不再是活契约（见下方各处「已下线」标注） | 消费方全迁完，T012 下线 |
| 2026-06-30 | **新增对外契约**：① `GET /user/list?with_department_path=true` 返回每用户主属部门**全路径** `department_path`（默认不返，不影响其它消费方）；② 权限列表 `GET .../permissions` 的**部门 `subject_name` 改为全路径**（`总公司/研发部/平台组`，后端 `_resolve_subject_names` 批量补载祖先名解析） | 两处 path-tree N+1 修复（见 §5 坑 #9） |
| 2026-06-30 | 反直觉坑补充（§5 #9 #10）：授权列表 per-grant path-tree N+1；子租户管理员/超管看部门设置时父在 scope 外不取 path-tree | code review 修复 |
