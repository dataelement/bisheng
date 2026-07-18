# Feature: F036-rebac-eval-cost-optim（ReBAC 逐项权限评估成本优化）

> **本文档定位 — 纯 What（需求口径，不随代码漂移）**
> How（继承判定、批量预取、索引结构、函数）一律在 [design.md](./design.md)。

> **前置步骤**：已完成 Spec Discovery。本特性源于 109 压测发现：
> 知识空间「子项列表 / 站内搜索」接口在并发下 P50 升至 22–24s（单请求仅 0.6s），
> 实测归因为 **后端 CPU 打满（并发下 backend ~704%，OpenFGA 146%，DM 查询 1–11ms / OpenFGA 单次 8–15ms 均不慢）**，
> 根因是 `_scan_visible_child_items → _filter_visible_child_items` 对**每个子项**执行一次细粒度 ReBAC 评估
> （逐项 `read_tuples` I/O 扇出 + 逐 tuple 线性扫描整份 bindings 的 CPU），开销随页内项数线性增长。

**关联 PRD**: 2.6 性能优化（OpenFGA / ReBAC 列表）；本特性为 [F027](../027-rebac-list-perf-optim/spec.md) 的延续——F027 解决「扫多少项」（cursor 分页去掉 count/深翻），F036 解决「每项评估多贵」。
**优先级**: P0（并发下常用列表不可用级慢，影响所有租户）
**所属版本**: v2.6.0（合入 `feat/2.6.0-beta4`）
**依赖**: F004（ReBAC core）、F008（resource-rebac-adaptation）、F027（cursor 扫描循环，本特性在其 `_scan_visible_child_items` 上改造）

> **范围边界**
> - **本次纳入**（两项均为**请求内**优化，无跨请求状态、**无开关默认启用**）：
>   - ① **继承快速通道**：页内子项中，lineage（自身 + 各级父文件夹 + 空间）里**不存在任何文件/文件夹级绑定**的项，直接套用「空间级继承决策」（整请求只算一次），不再逐项跑完整 ReBAC；只有 lineage 含更近绑定的项才做完整 `nearest_binding_wins` 评估；owner（`item.user_id==当前用户`）短路可见。
>   - ③ **bindings 建索引**：把本请求已加载的 bindings 预处理为按资源 key 分组的查表，`_resolve_binding_for_tuple` 由「每 tuple 线性扫全表」改 O(1)。
>   - 改造点集中在 `FineGrainedPermissionService` 与 `KnowledgeSpaceService` 的子项可见性过滤链路；同链路被其它 ReBAC 列表复用处一并受益。完整逐项路径以 `_filter_visible_child_items_reference` 保留作等价测试 oracle。
> - **本次明确排除**：
>   - **不改变任何权限语义**：可见性结果必须与改造前逐项评估**逐位等价**（含 INV-7）。语义变更属越权风险，禁止。
>   - **② 整页批量预取 tuple —— 经核实不可行**：OpenFGA `/read` 无多对象批量原语；且其想省的逐项 `read_tuples` I/O 已被 ① 跳过评估覆盖（继承项连自身 tuple 都不读）。详见 design 决策 2。
>   - **不引入跨请求权限缓存**（曾考虑的 models/bindings/部门路径/用户主体跨请求缓存方案已砍）：该缓存只省「每请求构建一次上下文」的边际成本（非每项成本，非本瓶颈），却需把失效逻辑挂进授权/部门/组织同步等**其它领域的写路径**，跨域耦合不划算。若将来 profiling 证明上下文构建成新瓶颈，再按 design §8 用「读侧从数据版本派生 key」的解耦方式引入。
>   - 不改 cursor 协议 / 分页语义（INV-6 归 F027）。
>   - 不改 relation-model / binding 的**数据模型**与授权写入 UI（归 F004/F008/资源授权页）。
>   - 不做 OpenFGA 服务端扩容 / 分库 / 版本升级（运维侧，另议）。
>   - 不做前端改造（本特性纯后端；前端协议不变）。
>   - 不引入新领域对象、新表、新 DAO 入口（release-contract 表 1 记 F036「—（无新增）」）。

---

## 1. 用户故事

作为 **工作台日常使用者**，
我希望 **打开知识空间文件列表 / 站内搜索时，并发高峰下也能秒级返回**，
以便 **不再出现 20 秒以上的卡死等待**。

作为 **负责 OpenFGA / 后端容量的运维**，
我希望 **常用列表对后端 CPU 与 OpenFGA 的开销不随页内项数线性放大**，
以便 **同样机器扛住更高并发，P99 不抖**。

作为 **权限域维护者**，
我希望 **优化只改"怎么算"、绝不改"算出什么"，且不把权限关注点泄漏进其它业务模块**，
以便 **被文件/文件夹单独授权限制的内容不会因为优化而被越权看到，且不引入跨域失效耦合**。

---

## 2. 验收标准

> P0，采用 EARS 句型。AC-ID 本特性内唯一。

### 2.1 语义等价（最高优先级 — 安全红线）

- **AC-01** — THE SYSTEM SHALL 对任意 `(user, space, parent, 过滤条件)`，`/children` 与 `/search` 优化后返回的可见项集合与优化前**逐项评估**结果**完全一致**（同一组 id、同序）。
- **AC-02** — WHERE 某文件/文件夹存在「比空间更近」的绑定且该绑定不授予当前用户 `view_file`/`view_folder`，THE SYSTEM SHALL 在列表与搜索中**均不返回**该项（即继承快速通道**不得**把它当作"无绑定可继承"放行）。
- **AC-03** — THE SYSTEM SHALL 维持 INV-7：列表 UI 不可见的 `file`，其 chunk/文件名/来源不得出现在任何 AI 问答可检索路径（本特性不放宽该子集关系）。
- **AC-04** — WHEN 当前用户对空间无 `view_space`，THE SYSTEM SHALL 维持原有拒绝行为（返 `SpacePermissionDeniedError`），优化不改变入口鉴权。

### 2.2 性能与开销下降（可验证）

- **AC-05** — WHEN 请求 `/children` 一页（page_size=20），THE SYSTEM SHALL 对页内「无更近绑定」的子项**不执行**完整逐项 ReBAC 评估（仅做继承决策套用）；完整评估次数 ≤ 页内「含更近绑定项」数。
- **AC-06** — THE SYSTEM SHALL 将一页内对 OpenFGA 的 tuple 读取合并为常数级批量调用（不随页内项数 N 线性增长的逐项 `read_tuples`）。
- **AC-07** — THE SYSTEM SHALL 使 `_resolve_binding_for_tuple` 不再逐 tuple 线性扫描整份 bindings（改为按 key 命中索引）。
- **AC-08**（基准）— WHEN 以原压测脚本（20 并发持续）压 `/children`，THE SYSTEM SHALL 使 P50 较改造前下降 ≥70% 且不引入新的失败响应（具体阈值与基线记 design §7）。

### 2.3 静态可验证

- **AC-09** — 维护者对改造后代码静态扫描：子项可见性过滤路径存在「继承快速通道」分支（无更近绑定 → 套用一次性空间决策）；存在「整页批量 tuple 预取」调用；bindings 解析经由按 key 的索引结构；**全程无跨请求缓存引入**（`tuple_cache` 等结构生命周期不超出单次请求）。

---

## 3. 边界情况

- **同一请求内项共享祖先**：页内多项同属一个父文件夹/空间 → 该祖先的 tuple 与决策只取一次、跨项复用（不得每项重取）。
- **绑定恰好落在祖先文件夹**：项自身无绑定但某层父文件夹有更近绑定 → 该项**必须**走完整评估（不能当继承项放行）。
- **存疑回落**：任何无法确定"是否有更近绑定"的情形，必须回落完整评估（fail-closed），不得放行。
- **多租户**：沿用现有 tenant 注入，本特性不改链路；不串数据。
- **OpenFGA 不可用**：沿用 `RebacUnavailableError`，不写半页、不误判 `has_more`。

---

## 4. 设计与实现（指针，不复制）

| 你想知道 | 去哪看 |
|---|---|
| 三项优化各自的方案对比与取舍 | design.md §3 决策 1–3 |
| 为什么不做跨请求缓存（耦合权衡） | design.md §3 决策 4 + §8 |
| 今天的数据流、关键函数 | design.md §4 |
| 等价性如何保证、已知坑 | design.md §5 |
| 对外契约、依赖 | design.md §6 |
| 基线与性能验证方法 | design.md §7 |
| 任务拆解与执行顺序 | tasks.md |

---

## 相关文档

- 设计真相: [design.md](./design.md)
- 执行与落档: [tasks.md](./tasks.md)
- 版本契约: [features/v2.6.0/release-contract.md](../release-contract.md)（INV-6 / INV-7 / 表 1）
- 前序特性: [F027 ReBAC 列表性能优化](../027-rebac-list-perf-optim/spec.md)
- 架构文档: `docs/architecture/10-permission-rbac.md`
