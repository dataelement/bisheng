# /space/grouped 性能优化设计（方案 B）

- 日期：2026-07-06
- 分支：`perf/grouped-spaces-opt`（基于 `origin/feat/2.5.0-sg`，HEAD `55732abe3`）
- worktree：`/Users/zhangguoqing/works/bisheng_2-grouped-perf`
- 状态：设计已批准，待写实现计划

## 1. 背景与问题

`GET /api/v1/knowledge/space/grouped` 是 portal 多个页面（知识库树、搜索）的高频前置依赖，实测偏慢。调用链：

```
endpoint(/grouped) → get_grouped_spaces → _list_accessible_spaces（收集可见 space_id）
  → _format_accessible_spaces（把 id 填充成完整对象）→ 按 space_level 分组
```

热点在 `_format_accessible_spaces`（`knowledge_space_service.py:967`）对每个「非本人创建」的 space 的两轮 per-space 扇出：

- `get_permission_level`（`:995` gather）→ 每 space 1 次 OpenFGA `batch_check`（用于推 `user_role`）
- `_get_effective_permission_ids`（`:1008` gather）→ 每 space 内部 `read_tuples`，且无命中时 fallback 再调一次 `get_permission_level`（用于 `view_space` 过滤）

即 **N 个 space ≥ 2N 次独立 OpenFGA HTTP 往返**，且同一 space 的 `permission_level` 在两轮里被重复计算。此外 grouped **无任何结果缓存**，每次调用全量重算。

已经良好、非瓶颈的部分（不动）：阶段 1 `_list_accessible_spaces`（`:5631`）三个查询已 `asyncio.gather` 并行，`PermissionService.list_accessible_ids` 已走 `PermissionCache`（Redis, TTL=10s）；`_decorate_department_metadata`、`async_count_success_files_batch` 已批量。`_build_resource_lineage` 对 `knowledge_space` 直接返回、无 DB 查询。

## 2. 目标与非目标

**目标**
- ① 把 per-space OpenFGA 扇出批量化：N 次 `batch_check` → 1 次
- ② 消除重复 `permission_level` 计算 + 跨 space 复用 `read_tuples`
- ③ grouped/可见空间结果加 per-user 短 TTL 缓存
- ④ 加分段耗时日志便于后续排查

**硬约束（安全敏感）**：①②③ 不改变任何 space 的最终 `permission_level` / `effective_permission_ids` / `user_role` / 是否入列 的取值——**行为严格等价，不越权不漏权**。

**非目标**
- 不改 portal 侧（P0/P1/P2 另议）
- 不改 `_can_unsubscribe_space` 循环内串行（原分析 ④），仅埋点观测，够快就不动
- 不做缓存主动失效（纯 TTL，已与用户确认）
- 不深度重构 permission 模块（方案 A 已否决）
- 不修复预存的 DB-engine 测试环境问题

## 3. 约束与前提
- 权限行为等价是第一约束
- ③ 纯 TTL 缓存，默认 **15s**，可配置常量
- 测试基线脏：`test_knowledge_space_service.py` 现状 **136 passed / 40 failed**，40 个全为预存的 SQLAlchemy DB-engine 环境失败（`_instantiate_plugins` unpack + `Database context not found, registering default instance`），与本优化无关 → 采用 mock 驱动的 characterization 验证

## 4. 设计详情

### ① 批量 permission_level（合并 OpenFGA）
新增 `PermissionService.get_permission_levels(user_id, object_type, object_ids, login_user) -> dict[str, str | None]`：
- 与逐个 `get_permission_level`（`permission_service.py:835`）**逐分支对齐**：admin 短路 / `_evaluate_tenant_gate`（`:937`）/ `fga.batch_check` / legacy alias / implicit fallback
- 核心：把「未被 tenant gate 短路」的 `object × 4 level`（含 legacy alias）汇成**一个** checks 列表，一次 `fga.batch_check`（`core/openfga/client.py:130` 天然支持 `correlation_id` 多 check），回填每 object 的最高 level
- gate 短路判断、implicit fallback 的 per-object DB 查询用 `asyncio.gather` 并发
- `_format_accessible_spaces:993-1004` 的 gather 改为一次 `get_permission_levels(permission_space_ids)`

### ② tuple_cache 共享 + precomputed level
- `get_effective_permission_ids_async`（`fine_grained_permission_service.py:396`）已有 `tuple_cache` 参数（`:410`）。在 `_format_accessible_spaces` 建**一个 shared `tuple_cache` dict**，透传给 `_get_effective_permission_ids`（`:1811`）→ `get_effective_permission_ids_async` 的 N 个调用，跨 space 复用 `read_tuples`（public/共享祖先命中）
- 新增可选参数 `precomputed_permission_level`：外层已用 ① 算好全部 level，传入后 `:519` 的 fallback 直接使用，**不再第二次调 `get_permission_level`**
- `_get_effective_permission_ids` 增参透传
- 等价性论据：`tuple_cache` 只缓存同一 object 的 `read_tuples` 结果（幂等）；`precomputed_permission_level` 就是同一套 `get_permission_level` 逻辑算出的值

### ③ per-user 短 TTL 缓存
- 缓存对象：`_list_accessible_spaces`（`:5631`）的完整输出（`get_grouped_spaces` 与 `get_spaces_by_level` 都复用它，收益覆盖多端点）。注意 `get_grouped_spaces` 的 `_ensure_personal_spaces()` 副作用在缓存层之外，不受影响
- key：`ksp:accessible:{user_id}:{order_by}`；TTL 默认 15s（模块常量，可配置）；纯 TTL、不主动失效
- 介质：复用 `get_redis_client()`（`permission_cache.py:184` 同一套）；Redis 不可用 → 直算降级
- 序列化：`KnowledgeSpaceInfoResp.model_dump()` ↔ 重建；须保持 pinned 顺序与 `is_favorite`/`can_unsubscribe` 等字段
- 放置：新增小 helper（knowledge 模块内，如 `SpaceListCache`），不污染 `PermissionCache` 语义

### ④ 分段耗时日志（+ ⑤ 日志降级）
- 在 `_list_accessible_spaces` / `_format_accessible_spaces` 用 `time.perf_counter()` 埋点，输出**一行结构化 summary**：`user_id, n_spaces, cache_hit, 各段 ms`（stage1 收集 / get_spaces_by_ids / 批量 level / effective_ids / file_count / decorate / can_unsubscribe）
- 默认 INFO 一行 summary；细分 DEBUG
- ⑤（附带）`core/openfga/client.py:152` 的 `[openfga-debug] batch_check` 日志由 INFO 降 DEBUG，减噪

## 5. 影响文件（feat/2.5.0-sg 行号）
1. `permission/domain/services/permission_service.py` — 新增 `get_permission_levels`；抽出 `get_permission_level`（`:835`）可复用内部逻辑
2. `permission/domain/services/fine_grained_permission_service.py` — `get_effective_permission_ids_async`（`:396`）加 `precomputed_permission_level` 参数
3. `knowledge/domain/services/knowledge_space_service.py` — `_format_accessible_spaces`（`:967`）编排改造（① 批量 level + ② shared tuple_cache + precomputed level）；`_list_accessible_spaces`（`:5631`）加缓存；`_get_effective_permission_ids`（`:1811`）透传；分段日志
4. `core/openfga/client.py` — `batch_check`（`:130`）日志降级（⑤）
5. 新增缓存 helper（knowledge 模块内）
6. `test/` — mock 驱动 characterization + `get_permission_levels` 单测

## 6. 验证策略（mock 驱动的 characterization）
- **基线现状**：`test_knowledge_space_service.py` 136 passed / 40 failed（预存 DB-engine 环境失败，含 `TestGetSpaceInfo`/`TestKnowledgeSquareListing`）。同类的 `TestFineGrainedPermissionRuntime` 为 **passed**，证明 mock/sqlite 驱动的权限逻辑测试可行
- **characterization 单测**：隔离 `_format_accessible_spaces` 与 `get_permission_levels`，mock DAO + OpenFGA（`fga.batch_check` / `read_tuples` / `list_accessible_ids`）。构造 creator / member / public / department + 各权限组合，断言改动前后输出逐字段一致（`id, user_role, space_level, file_num, is_pinned, owner_*, 是否入列`）。参考已 passed 的 `TestFineGrainedPermissionRuntime` 范式
- **`get_permission_levels` 单测**：对一组 object，断言批量结果 == 逐个 `get_permission_level` 结果（覆盖 gate / legacy / implicit 分支）
- **回归**：改动后重跑 `test_knowledge_space_service.py`，确认 passed 数不减少（仍 ≥136 passed，40 个预存失败不新增）
- 运行：`cd src/backend && ./.venv/bin/python -m pytest test/test_knowledge_space_service.py -q`

## 7. 风险与回滚
- 最高风险：② 权限编排改动 → 快照基线兜底，任一字段不等价即回退
- OpenFGA `batch_check` 合并后单请求体变大（约 4N checks）→ 若 N 极大需评估 OpenFGA 单请求上限，必要时分批（如每 100 space 一批），并 `log()` 说明分批，避免静默截断
- 缓存 stale：纯 TTL，权限变更滞后 ≤15s（已接受）
- 三项互相独立、可分别回退：① 保留旧 `get_permission_level`；② `precomputed_permission_level` 为可选参数、`tuple_cache` 可传 `None`；③ 缓存可通过常量关闭

## 8. 附加收益
`get_permission_levels`（①）与 shared `tuple_cache`（②）是通用能力。feat/2.5.0-sg 上同类 per-space 扇出还有 `:3287`/`:3388`、`:4936`、`:5917`/`:5940`（其他可见空间列举路径）。本次先在 grouped 落地，后续可平移复用（非本次目标）。
