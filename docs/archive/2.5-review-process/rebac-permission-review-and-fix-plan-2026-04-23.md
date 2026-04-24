# ReBAC 权限问题复核与修复计划

日期: 2026-04-23
分支: `feat/2.5.0`
状态: 文档先行，代码未开始修改

---

## 1. 目的

对 `docs/rebac-permission-bugs-2026-04-23.md` 中的结论逐项复核，区分三类问题：

1. 已被代码证实、会导致权限错判或 403 的真实缺陷
2. 与 PRD/技术方案存在偏差，但当前不一定构成运行时故障
3. 报告方向有参考价值，但根因或修复建议不准确

本文件同时给出修复优先级，作为后续代码修改的执行顺序。

---

## 2. 复核结论总览

### 2.1 已确认的高优先级真实缺陷

1. `_run_async_safe` 存在危险的 `asyncio.run()` fallback，可能在 FastAPI threadpool 中创建临时 event loop，并污染后续 async 资源初始化。
2. `tenant_filter.py` 仍使用 `tenant_id == current_tenant_id`，没有消费 `visible_tenant_ids`，会把 Root 共享给 Child 的资源再次过滤掉。
3. F006 migration 缺少历史 `user_department -> department#member` 的 OpenFGA membership 补数，导致 `fga.check()` / `list_objects()` 不能解析已有部门授权。
4. department / user_group 授权后的权限缓存失效不完整，只清理了直接 user subject。

### 2.2 报告结论基本成立，但修复建议需要收敛

1. `check()` 与 `get_effective_permission_ids_async()` 确实存在双轨语义分叉。
2. 但不能简单“统一走 read_tuples + Python 匹配”，否则会绕开 FGA 的 computed relation、parent 继承、shared_with/shared_to 等语义。
3. 正确方向应是修正 membership 数据与调用边界，而不是把核心鉴权整体降级为 Python tuple 扫描。

### 2.3 偏差存在，但不是当前第一批必须动的代码

1. `list_accessible_ids()` admin 返回 `None`，与 PRD 的“始终返回 list”不一致。
2. relation model / binding 使用 `Config` JSON blob，而不是独立 `relation_definition` 表。
3. 权限列表 API 只返回 direct tuples，没有 inherited 结构。

### 2.4 报告里不够准确或不应按原建议直接改的点

1. “failed_tuples 重试机制不完整”只部分成立：
   - 30 秒 beat 调度是存在的。
   - retry worker 也是存在的。
   - 但是否“完整”要区分调度、批量/单条回退、dead 状态、清理策略几个维度分别评估。
2. “直接切到 ReBAC-only”表述过满：
   - 对已映射资源类型，运行时主链路确实已经转向 ReBAC。
   - 但系统仍保留部分 legacy fallback，尤其对未映射 access type。
3. OpenFGA 双写期并非完全不存在：
   - `dual_model_mode + legacy_model_id` 已在 FGA client / manager 层实现。
   - 但这解决的是 authorization model 灰度，不是旧 RBAC 表与 ReBAC 运行时的双读宽松期。

---

## 3. 逐项复核

## 3.1 Bug 1: `_run_async_safe` 跨 loop 风险

结论: 成立，优先级 P0。

依据:

- `src/backend/bisheng/permission/domain/services/owner_service.py`
  - `_run_async_safe()` 在 AnyIO bridge 失败后直接 `asyncio.run(coro)`。
- `src/backend/bisheng/core/context/base.py`
  - `BaseContextManager` 内含 `asyncio.Lock` / `asyncio.Event`。
- `src/backend/bisheng/core/database/connection.py`
  - async engine 懒初始化。
- `src/backend/bisheng/user/domain/services/auth.py`
  - 注释已明确承认 sync endpoint 中“新建 event loop 调 FGAClient 会跨 loop 失败”。

处理方向:

1. 先消除 threadpool 场景里的 `asyncio.run()`。
2. 优先改为：
   - 能回主 loop 时只走 `anyio.from_thread.run()`
   - 明确无法回主 loop 时直接失败并记录，而不是静默新建 loop
3. 中长期再继续压缩 sync wrapper 的使用面。

---

## 3.2 Bug 2: `check()` 与 `get_effective_permission_ids_async()` 双轨分叉

结论: 问题成立，但报告给的修复建议不成立。

当前现状:

- `PermissionService.check()` / `get_permission_level()` / `list_accessible_ids()`
  - 依赖 FGA `check` / `batch_check` / `list_objects`
- `KnowledgePermissionService` / `ApplicationPermissionService` / `ToolPermissionService`
  - 依赖 `read_tuples(object=...)` + 本地 subject 匹配 + binding/model 解释

问题点:

1. 当历史 membership 没补齐时，FGA 侧的 `check/list_objects` 会比 Python 侧更严格。
2. 知识库细粒度 permission id 又依赖 relation model / binding，导致“列表候选”和“细粒度收口”来自不同路径。

不应直接采用的修复:

- 不应把主鉴权链路统一改成“读 tuples + Python 匹配”。

原因:

1. 无法替代 `list_objects` 的对象枚举能力。
2. 会绕开 computed relation。
3. 会绕开 folder / knowledge_file 的 parent 继承。
4. 会绕开 tenant `shared_with` / `shared_to` 这类模型语义。

正确方向:

1. 先补 membership 数据一致性。
2. 让各路径对 tenant gate / legacy alias / implicit fallback 的边界更一致。
3. 后续再单独治理 relation model runtime 链路，而不是一刀切。

---

## 3.3 Bug 3 / Bug 4: migration 缺少 department membership，导致 FGA 查不到间接授权

结论: 成立，优先级 P1。

依据:

- `src/backend/bisheng/permission/migration/migrate_rbac_to_rebac.py`
  - 只有 6 步，没有 department membership。
- `src/backend/bisheng/department/domain/services/department_change_handler.py`
  - `on_members_added()` 会写 `user:{uid} member department:{dept_id}`。
- `src/backend/bisheng/core/openfga/authorization_model.py`
  - resource relation 支持 `department#member` / `user_group#member`。

影响:

1. 历史 `user_department` 数据不会自动进入 FGA。
2. 升级后只有“新变更的部门成员”会被同步。
3. 历史部门授权资源在 `check()` / `list_accessible_ids()` 上会漏判。

处理方向:

1. 为 F006 增加 department membership step。
2. 保持幂等，纳入 checkpoint 和统计。
3. 补对应 migration 测试。

---

## 3.4 Bug 6: tenant_filter 与 visible_tenant_ids 脱节

结论: 成立，优先级 P0。

依据:

- `src/backend/bisheng/utils/http_middleware.py`
  - Child 用户 `visible_tenant_ids = {leaf_id, 1}`。
- `src/backend/bisheng/common/dependencies/user_deps.py`
  - `get_visible_tenants()` 也按该约定返回。
- `src/backend/bisheng/core/context/tenant.py`
  - 注释明确写 visible_tenant_ids 是给 tenant filter 消费的。
- `src/backend/bisheng/core/database/tenant_filter.py`
  - 当前仍硬编码 `table.c.tenant_id == tid`。

影响:

1. `PermissionService._filter_ids_by_tenant_gate()` 已允许的 Root 共享资源，
2. 到 ORM 层又会被 `tenant_id == leaf_id` 再过滤掉，
3. 最终表现为“accessible_ids 有，列表为空”。

处理方向:

1. tenant filter 读取 `visible_tenant_ids`。
2. 在非 strict 模式下改成 `tenant_id IN (...)`。
3. 保留 `strict_tenant_filter()` 的现有语义。
4. 补 tenant filter 测试，避免 quota 等 strict 场景回归。

---

## 3.5 Bug 7: department/user_group 授权后的缓存失效不完整

结论: 成立，优先级 P2。

依据:

- `src/backend/bisheng/permission/domain/services/permission_service.py`
  - `authorize()` 只在 `subject_type == 'user'` 时把用户加入 `affected_user_ids`。

影响:

- 主要是 10 秒 TTL 内的短暂陈旧。

处理方向:

1. 对 department subject 展开成员 user id。
2. 对 user_group subject 展开 group member user id。
3. 只做缓存失效，不改变 tuple 写入逻辑。

---

## 4. 偏差项复核

## 4.1 偏差 2: `list_accessible_ids()` 返回 `None`

结论: 偏差成立，但不是当前第一批修复。

事实:

- PRD 写的是“始终返回 `list[str]`”。
- 当前实现中 admin 返回 `None`，调用方做“不过滤”语义。
- `UserPayload.rebac_list_accessible()` 和 `/permissions/objects` 端点都沿用了这个约定。

判断:

1. 这是 API 语义偏差，不是权限错判根因。
2. 要改会影响调用方和测试面，属于单独的接口一致性清理。

建议:

- 先不动。
- 如果后续要改，应统一在服务层或调用方收口，避免 `Optional[List[str]]` 继续外扩。

---

## 4.2 偏差 3: 用 Config JSON blob 代替 `relation_definition` 表

结论: 偏差成立，属于设计债，不是当前第一批修复。

事实:

- relation models / bindings 存在 `Config` 表：
  - `permission_relation_models_v1`
  - `permission_relation_model_bindings_v1`

风险:

1. 读改写粒度粗。
2. SQL 不可检索单条 binding。
3. 并发写可能存在 read-modify-write 覆盖风险。
4. 后续 tenant 隔离扩展困难。

但当前报告中的两点需要修正:

1. 资源 ID “跨租户碰撞”不是最强风险，因为当前大多数资源主键本身就是全局唯一。
2. bindings 也不是完全“无清理”，revoke / 删除 model 时已有清理路径。

建议:

- 先记为架构债，不纳入这批 bugfix。

---

## 4.3 偏差 4: 权限列表 API 缺少 `inherited`

结论: 偏差成立，但不是当前第一批修复。

事实:

- 当前 `get_resource_permissions()` 只基于 `fga.read_tuples(object=...)` 返回 direct tuples。
- 没有 inherited 字段。

判断:

1. 这会影响 folder / knowledge_file 这类父级继承资源的“权限展示完整性”。
2. 但它不直接影响 runtime allow/deny 判定。

建议:

- 作为第二阶段 API 增强项处理。
- 修复时要先决定 inherited 的来源：
  - FGA ListUsers
  - 或业务层沿 parent 链逐级聚合

---

## 4.4 偏差 5: failed_tuples 重试机制不完整

结论: 报告表述不准确，只部分成立。

已存在的实现:

1. `worker/permission/retry_failed_tuples.py` 存在。
2. beat 每 30 秒调度存在：
   - `core/config/settings.py`
3. 支持：
   - batch retry
   - batch 失败后 per-item fallback
   - 超限 `dead`

仍可能需要后续评估的点:

1. succeeded 记录清理策略是否足够。
2. 指标/告警是否完整。
3. crash-safe 预写记录与普通失败记录是否需要更清晰区分。

结论:

- 这条不作为当前 bugfix 主任务。

---

## 4.5 偏差 6: 跳过双写期直接切 ReBAC-only

结论: 需要拆成两个层面看。

### A. RBAC 表与 ReBAC 运行时“双读宽松期”

结论: 基本成立。

事实:

- 对已映射 access type，主链路已切到 ReBAC。
- 如果 migration 不完整，会出现“旧系统原本有权限，ReBAC 没补齐，直接拒绝”的情况。

### B. OpenFGA authorization model 灰度双写期

结论: 报告不成立。

事实:

- `dual_model_mode + legacy_model_id` 已存在。
- `FGAClient.write_tuples()` 会在灰度模式下双写到 current model 和 legacy model。

因此:

- “完全没有双写期”不准确。
- 更准确的说法应是：
  - 已支持 FGA model 灰度双写，
  - 但没有长期保留“RBAC 表 + ReBAC 同时放行”的宽松运行时窗口。

建议:

- 当前优先修 migration 完整性，而不是回滚到双读宽松策略。

---

## 5. 本批代码修改范围

本批只处理会直接导致权限错误判定或资源不可见的问题：

1. 修 `_run_async_safe` 的危险 fallback
2. 修 tenant filter 读取 `visible_tenant_ids`
3. 给 F006 migration 补 department membership step
4. 修 department / user_group 授权后的缓存失效

明确不在本批处理的项：

1. `list_accessible_ids()` 返回值语义统一
2. relation_definition 表重构
3. inherited 权限列表 API
4. failed_tuple 体系重构
5. relation model runtime 大重构

---

## 6. 修改顺序

### Phase 1

1. tenant filter IN-list 修复
2. department membership migration 补齐
3. cache invalidate 扩展

### Phase 2

1. `_run_async_safe` fallback 收紧
2. 清点仍在 sync wrapper 中触发 ReBAC 的调用面

### Phase 3

1. 补 pytest
2. 跑与 tenant filter / permission service / migration 直接相关的测试

---

## 7. 预期结果

修完本批后，应该至少解决以下现象：

1. Child 用户能看到 Root 共享资源
2. 历史部门成员的部门授权能被 `check()` / `list_objects()` 正确识别
3. department / user_group 授权变更不再稳定卡 10 秒缓存
4. sync endpoint 不再通过 `asyncio.run()` 新建临时 loop 污染全局 async 资源

---

## 8. 备注

本文件是“代码修改前的执行文档”。后续每个改动项都应以最小 diff 为目标，并补对应回归测试。
