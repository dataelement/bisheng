# Design: F036-rebac-eval-cost-optim（ReBAC 逐项权限评估成本优化）

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0
**最后更新**: 2026-06-15（初版）

---

## 1. 目标与非目标

- **目标**：在**不改变任何可见性结果**的前提下，把知识空间「子项列表 / 站内搜索」的逐项 ReBAC 评估从「每项一次完整评估 + 一次 OpenFGA 读」降为「多数继承项 O(1) 套用 + 少数有绑定项才完整评估 + 整页一次批量读 tuple」，消除并发下后端 CPU 被逐项评估打满的瓶颈。三项优化**全部请求内完成，无任何跨请求状态**。
- **非目标**：不改权限语义/数据模型/cursor 协议/前端；不做 OpenFGA 服务端扩容；**不引入跨请求缓存**（见决策 4）。

---

## 2. 关键约束

- 全局铁律遵循 `docs/constitution.md` C1–C7（双 DB / 多租户 / 分层 / 权限 / 错误码 / 安全）。
- **安全红线（spec AC-01~04 / INV-7）**：优化后可见项集合必须与逐项评估**逐位等价**；任何"快速通道"只能命中「确定无更近绑定」的项，存疑必须回落完整评估（fail-closed）。
- **零跨请求状态**：所有新增结构（bindings 索引、有绑定资源集、父链决策 memo，以及既有的请求级 `tuple_cache`）生命周期都不得超出单次请求 —— 这样无失效问题、无跨域耦合（决策 4）。

---

## 3. 方案对比与选定

### 决策 1：继承快速通道（① — CPU 主收益）

- **备选**：
  - A. 维持现状：对页内每项调用 `get_effective_permission_ids_async` 完整评估。— 简单；CPU O(项数)，并发即打满（实测 704%）。
  - B. 「用户对空间有 view 就放行全部」。— **错误**：文件/文件夹可被单独授权严于空间，会越权（已被否，见 spec 边界）。
  - C. **按"是否有更近绑定"分流**：先用本请求已加载 bindings 派生的「有绑定资源集」判断每项 lineage（自身 + 各级父文件夹 + 空间）是否含**比空间更近**的文件/文件夹级绑定；无 → 套用「空间级继承决策」（整请求算一次）；有 → 走完整 `nearest_binding_wins` 评估。
- **选定**：C
- **原因**：与逐项评估**逐位等价**（`nearest_binding_wins` 下，无更近绑定的项其有效权限恒等于「祖先/空间继承 + membership + public」，与逐项算结果相同），却把完整评估次数从「页内全部」降到「页内有绑定项」（生产中绝大多数文件无单独授权）。「有绑定资源集」来自 bindings 清单（CONFIG 中一份 JSON，本请求本就会加载），是纯内存集合，判定 O(1)/项。
- **何时该重新考虑**：若未来引入「无绑定也能产生 deny 的否定性 tuple」（当前模型为 grant 型 + nearest-binding-wins），则继承项也可能被否，需把这类资源并入「需完整评估集」。

### 决策 2：bindings 索引（③）；整页批量预取（②）经核实不可行、已并入 ①

- **③ bindings 索引（已实现）**：`build_binding_index(bindings)` 预建 `dict[(resource_type, str(resource_id))]→[binding]`（保序），`_resolve_binding_for_tuple` / `_permission_ids_from_bindings` 由"每 tuple 线性扫全 bindings"改 O(1) 命中。每请求构建一次、随 `context` 下传，请求结束即弃。结果逐位等价（保序 ⇒ "首个匹配 wins" 不变）。
- **② 整页批量预取 tuple —— 不实现（不可行）**：
  - 设想是"一次批量读页内项 + 祖先 + 空间的 tuple 灌 `tuple_cache`"。但 **OpenFGA `/read` 只能按单个 `object` 过滤，无多对象批量原语**（见 `core/openfga/client.py:read_tuples`），无法在一次调用里读一组对象。
  - 且 ② 想省的"逐项 `read_tuples` I/O 扇出"，本质上**被 ① 覆盖**：继承快速通道让无更近 binding 的项整项跳过评估（连它自己的 `read_tuples` 都不发），祖先/空间的 tuple 仍由既有请求级 `tuple_cache` 去重。故 ② 没有独立落点。
- **③ 实测收益有限**：本环境 bindings 仅 42 条，线性扫描本就不是瓶颈（见压测报告：FLAG_OFF≈原始基线）。③ 零风险保留，绑定规模大的租户收益更明显；真正消除 CPU 的是 ①。
- **何时该重新考虑 ③ 的构建成本**：单空间绑定数量级膨胀（>数千）使"每请求构建索引"本身变重时，再考虑跨请求缓存（决策 4 的触发条件）。

### 决策 3：请求内复用上下文（不跨请求）

- 现状 `_build_child_permission_context` 每请求已构建一次 `models/bindings/binding_department_paths/user_subject_strings/membership/public` 并在批内复用——**保留并强化**（叠加 ①③ 的派生结构：有绑定资源集、bindings 索引），但**仍限定在单次请求内**。不把任何部分提升为跨请求缓存。

### 决策 4：本期**不**引入跨请求缓存（关键取舍）

- **备选**：
  - A. 跨请求缓存上下文 + 写时 epoch 失效：在 Redis 缓存 models/bindings/部门路径/用户主体，授权/部门/组织同步等写路径 `INCR` epoch 失效。— 省「每请求构建一次上下文」的成本；但**把权限缓存的失效关注点泄漏进授权、部门 CRUD、用户组、SSO/LDAP 同步等其它领域的写路径**，挂点多而散，漏一处即越权 → **跨域耦合过重**。
  - B. **不做跨请求缓存**：只做请求内的 ①③。
- **选定**：B
- **原因**：实测瓶颈是**每项**评估（98 项 × 完整评估 × 线性扫 bindings），不是**每请求一次**的上下文构建（约 5~8 条小查询 + 2 次 JSON parse）。① 直接消掉前者（继承项整项跳过，连其 `read_tuples` 也省），③ 消线性扫描。跨请求缓存只省后者那点边际成本，却引入跨域失效耦合，性价比为负。砍掉它，则"上传/删文件夹/改部门如何使缓存失效"这个问题**根本不存在**。
- **何时该重新考虑**：若上线后 profiling 证明「每请求上下文构建」成为新瓶颈 → 届时引入缓存也**不得**用写时 epoch-bump，改用**读侧从数据自身版本派生 key** 的解耦方式（见 §8），零写侧挂点。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（`/children`，优化后）

`list_space_children`（`knowledge_space_service.py`）
→ 入口鉴权 `_require_read_permission` / `_require_permission_id`（不变）
→ `_scan_visible_child_items`（F027 cursor 批扫）每批：
  1. `SpaceFileDao.async_list_children`（DM 取一批，1–11ms）
  2. `_filter_visible_child_items` 按开关 `_CHILD_PERMISSION_FAST_PATH_ENABLED` 分发：
     - **OFF（默认，oracle）** → `_filter_visible_child_items_full`：每项 `_get_child_item_effective_permission_ids` 完整评估（经 ③ 索引解析；既有行为）。
     - **ON** → `_filter_visible_child_items_fast`【新①】：每项 ——
       · 叶级命中「有绑定资源集」→ 走完整逐项评估（nearest-wins，与 full 一致）；
       · `item.user_id == 当前用户`（owner）→ 直接可见；
       · 否则 → 继承「父链决策」`_chain_effective_permission_ids`（每条祖先链算一次、本请求内 memo）。
→ `_enrich_with_version_info` + `_handle_file_folder_extra_info`（`count_folder` 仍按需，本期不动）
→ cursor 编码返回。

权限上下文（models/bindings/③索引/有绑定资源集/部门路径/用户主体/请求级 `tuple_cache`）每请求构建一次、请求结束即弃，**不跨请求**。

### 4.2 关键数据结构（均为请求内、对外不可见）

| 结构 | 形态 | 生命周期 | 用途 |
|---|---|---|---|
| 有绑定资源集 | `set[(resource_type, resource_id)]`，由本请求 bindings 派生 | 单请求 | ① 判定项 lineage 是否含更近绑定 |
| bindings 索引 | `dict[(resource_type, str(resource_id))] → list[binding]`（保序） | 单请求 | ③ O(1) 解析 |
| 请求级 `tuple_cache` | `dict[tuple_object → list[tuple]]`（既有，按对象去重；祖先/空间天然共享） | 单请求 | 避免重复 `read_tuples`（非批量预取，见决策 2） |
| 父链决策（memo） | `dict[祖先 id 元组 → set[permission_id]]` | 单请求 | ① 同一祖先链只算一次 |

> **对外契约零变化**：`/children`、`/search` 的 request/response 结构与语义不变（INV-6 cursor 协议沿用 F027）。

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `FineGrainedPermissionService`（`permission/domain/services/fine_grained_permission_service.py`） | 单项有效权限评估；新增 `build_binding_index` + 给 `get_effective_permission_ids_async`/`_resolve_binding_for_tuple`/`_permission_ids_from_bindings` 加可选 `binding_index`（③） | 不改判定语义；不引入跨请求状态 |
| `KnowledgeSpaceService`（`knowledge/domain/services/knowledge_space_service.py`） | 子项扫描/过滤编排；`_filter_visible_child_items` 分发 `_full`(oracle)/`_fast`(①)，新增 `_chain_effective_permission_ids` | 不直接写 ORM |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | 单请求只 0.6s，瓶颈只在**并发**（实测 backend 704% CPU）；DM/OpenFGA 单次都快 | 误去优化 DB/加索引，白费力 | 见 spec 前置；本设计针对 per-item CPU/IO |
| 2 | 「空间有 view ≠ 文件有 view」：文件/文件夹可单独授权且**严于**空间 | 做"空间放行全部"会越权泄露 | 决策 1 用「有更近绑定」分流，存疑回落完整评估（fail-closed） |
| 3 | 绑定恰好落在**祖先文件夹**时，项自身无绑定也必须走完整评估 | 只看项自身有无绑定会漏判 → 越权 | ① 的 lineage 命中判定覆盖各级父文件夹，非仅项自身 |
| 4 | bindings 是 CONFIG 表里一份 JSON 全量清单，按 resource 枚举 | 不知道就会去逐资源查库判断"有无绑定" | 「有绑定资源集」直接由该清单内存派生 |
| 5 | `_resolve_binding_for_tuple` 现为每 tuple 线性扫全 bindings | 是 CPU 隐性热点，不索引则 ③ 无效 | 决策 2 建 key 索引 |
| 6 | 刻意**不**做跨请求缓存 | 后人"顺手加个 Redis 缓存"会重新引入跨域失效耦合 | 决策 4 + §8：要加也只能读侧版本派生 key |
| 7 | ① 快速通道**仅在不变量"非 owner 的 file/folder 授权 100% 有 binding"成立时等价**（109 实测裸非 owner 授权=0；`owner` 加性裸 tuple 由 `item.user_id` 短路、`parent` 为结构边均忽略） | 若将来出现"裸非 owner 授权 tuple"（有 tuple 无 binding），开启 ① 后该项会被当继承处理 → 漏显/误显 | 默认 OFF；授权写路径须保证非 owner 授权必写 binding（建议加 arch-guard/测试，见 §8）；开启前须做"有 binding 空间 + 非 admin 用户"端到端 diff |
| 8 | ① 的"父链决策"对**当前用户为 owner 的项**不适用 —— owner 经 `owner` tuple 在叶级 nearest-wins，永远可见 | 漏掉 owner 短路 → owner 看不到自己刚传的文件（false-negative） | `_filter_visible_child_items_fast` 用 `item.user_id == 当前用户` 短路；单测 `test_owner_shortcircuit_required` 守护 |

---

## 6. 对外契约与依赖

### 6.1 Outgoing（我提供 / 影响）
- `/api/v1/knowledge/space/{id}/children`、`/search`：**响应结构与语义不变**，仅更快（契约对前端零变化）。
- `FineGrainedPermissionService.build_binding_index` + 各评估函数的可选 `binding_index` 形参：内部 Python API，供 ReBAC 评估链路复用。

### 6.2 Incoming（我依赖 / 风险点）
- bindings/models 真相在 CONFIG（`permission_relation_*_v1`）：本特性**只读**，每请求加载一次；不改其写入路径（故无跨域挂点）。
- **不变量依赖（① 开启的前提）**：「非 owner 的 file/folder 授权必有 binding」。当前由授权写路径（资源授权 UI）保证；**无机制强制**。风险点：未来若有代码绕过 binding 直接写授权 tuple，① 会失真（见 §5 坑 7）。建议在 authorize 写路径加 arch-guard/测试固化。
- F027 的 `_scan_visible_child_items` cursor 结构：本特性在其内部改造，需保持 cursor 协议（INV-6）不变。
- OpenFGA：`/read` 无多对象批量原语（决策 2 ② 不可行的根因）；不可用时沿用 `RebacUnavailableError`，不写半页、不误判 `has_more`。

---

## 7. 测试与可观测

- **等价性（最重要）**：构造覆盖矩阵——空间公开/私有 × 文件夹有/无绑定 × 文件有/无绑定 × 绑定授予/不授予当前用户 × 部门子树授权 × admin/创建者/成员/外部用户；对每组断言「优化前逐项评估」与「优化后」可见项集合**逐位相等**（含 INV-7 子集关系）；重点覆盖"绑定落祖先文件夹"（坑 3）。
- **性能基线**：用原 Locust 脚本（20 并发持续）压 `/children`，记录改造前 baseline（P50≈22–24s）与改造后；AC-08 要求 P50 降 ≥70%。基线与结果落 tasks.md。
- **可观测**：日志打印每请求「完整评估项数 / 继承项数 / 批量 tuple 读次数」；并发压测时看 `docker stats` backend CPU 应显著下降。

---

## 8. 后续改进 / 不打算做的事

- **跨请求缓存（本期砍）**：仅当 profiling 证明「每请求上下文构建」成为新瓶颈才考虑；届时**禁止**写时 epoch-bump（跨域耦合），只能用**读侧从数据自身版本派生 key**：如 bindings/models 用其 CONFIG 行的 `update_time`、部门树用 `MAX(update_time) per tenant`、用户主体用其成员关系行版本 —— 缓存自己探源版本，零写侧挂点。
- `count_folder`（每文件夹一次聚合查询）本期不并入；若成新热点，下一步批量化为单查询 `GROUP BY 父路径`。
- 「最终可见判定」级缓存（user×item）不做——失效复杂、越权风险高。
- OpenFGA 服务端扩容/只读副本：容量侧另议。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-15 | 初版：请求内优化 ① 继承快速通道 + ③ 绑定索引；② 批量预取经核实不可行（OpenFGA 无多对象读）已并入 ①；明确不做跨请求缓存 | 109 压测定位 per-item ReBAC CPU 瓶颈；缓存跨域耦合权衡后砍除 |
