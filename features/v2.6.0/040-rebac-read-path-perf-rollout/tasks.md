# Tasks: F040 ReBAC 读路径性能范式收尾

**关联规格**: [spec.md](./spec.md) · [design.md](./design.md)
**版本**: v2.6.0（分支 `feat/v2.6.0/040-rebac-read-path-perf-rollout`，基于 `feat/2.6.0`）

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-25 用户确认通过（`/sdd-review spec`）。遗留观察：INV-6 豁免论证（B 组全返回）留待 design 给出；详见评审记录。 |
| design.md | ✅ 已评审 | 2026-06-26 用户确认通过（`/sdd-review design`）。Constitution C1–C7 门禁 PASS；两条 medium（E 组版本 key 定主选项、§7 性能阈值落数字）已闭环。INV-6 豁免论证见 design §3 决策 3。 |
| tasks.md | ✅ 已拆解 | 2026-06-26 `/sdd-review tasks` LGTM（21 项检查通过；AC 逐条列举、任务原子化 ≤3 文件、前端 Platform/Client 分区、31 条 AC 全覆盖）。15 个任务 / 5 Wave。 |
| 实现 | 🚧 进行中 | T0·T1·T2·T3·T4·T5·T9·T11 ✅ / 16（T1b·T5方案2 ⏸️）。偏差见下方「实际偏差记录」 |

---

## 开发模式

- **后端 Test-First（务实版）**：等价性是安全红线——每个后端改造任务先写"改造前逐项/全量 oracle == 改造后"的等价测试（红），再改实现（绿）。中间件/DM8/e2e 在 CI 跑。
- **前端手动验证**：每个前端任务附验证步骤（seed 造数后人工走查）。
- **Wave 依赖**：Wave 1 后端基础（E 缓存 + A 上下文/缓存，互相独立可并行）；Wave 2 后端拆分/批量/cursor；Wave 3 前端（依赖 Wave 2 契约）；最后 Wave 4 静态+性能验证。

## 执行记录（TDD，wave 顺序）

### Wave 0 — 治理（基础设施优先）

| # | 任务 | 产物 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|---|
| T0 | 登记 F040 到 `feat/2.6.0` 的 release-contract：表1「无新增领域对象 + 新增对外 API `…/unread-counts`」、表3 依赖 F004·F008·F027·F036·F037、**INV-6 例外条款**（per-user 有界且无深翻可全返回，但 N+1 必批量化）、变更历史。**跨 Feature 影响**：T2/T3/T4 改 `channel_service.py`（F026/F031/F037 邻接）仅改计算机制、不改授权/订阅语义（design §6.3） | `features/v2.6.0/release-contract.md` | 治理 | — | ✅ |

### Wave 1 — 后端基础（基础设施，可并行）

| # | 任务 | 产物 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|---|
| T1 | **E 名册版本派生 key 缓存层（bindings + models）**：新建 `relation_roster_cache`（版本派生 key 的 per-tenant LRU + sentinel-based get_or_build + fail-safe）；`ConfigDao.aget_config_version`（只 `SELECT update_time`，不取 value 大列）；在**源头** `_get_bindings`/`_get_relation_models`（`resource_permission.py`）接入——比改 `knowledge_space_service.py` 覆盖更广（channel/space/所有 ReBAC 路径都受益）。版本=config 行 `update_time`（`onupdate=CURRENT_TIMESTAMP`，写即变、每请求轻量版本校验→跨进程也不会服务旧名册）。先写契约+wiring 测试（命中==实时构建、版本变即失效、tenant 隔离、空值是命中）。**无 DB schema 变更**。8 测试绿、零新增回归/ruff。 | `relation_roster_cache.py`(新) + `resource_permission.py` + `config.py` | AC-21, AC-23, AC-24, AC-25, AC-30 | 无 | ✅ |
| T1b | **E 主体串缓存（AC-22）— 延后**：design §3 决策6 原拟 `max(update_time) over 成员关系` 做版本，**实测发现删除不安全**（用户被移出某组→该 link 行被删除→剩余行 update_time 不变→版本不变→旧主体串仍命中→越权命中已撤销的组权限，安全红线）。安全版本需删除感知（`count(*)+max(update_time)` 或成员 id 集哈希），需另行设计。**待用户裁定**纳入或正式延后（见偏差记录 D1） | `relation_roster_cache.py` + 主体串源头 | AC-22 | 无 | ⏸️ |
| T2 | **A 频道详情上下文复用 + membership 去重**：`get_channel_detail`（`channel_service.py`）传 `context=_build_channel_permission_context(...)`；合并两处 `find_membership`。先写等价测试（permission_ids 不变），后改实现 | `channel_service.py` | AC-04, AC-06 | 无 | ✅ |
| T3 | **A 文章总数 Redis 短 TTL 缓存**：新建 `ArticleCountCache`（key `article:count:{tenant_id}:channel:{id}:main`，TTL 60–120s，miss/Redis 挂回落 ES 并回填）；`get_channel_detail`/`get_channel_square` 接入。先写测试（命中不查 ES、miss 回落） | 新 cache 模块 + `channel_service.py` | AC-07, AC-27 | 无 | ✅ |

### Wave 2 — 后端拆分 / 批量 / cursor

| # | 任务 | 产物 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|---|
| T4 | **A 未读拆独立端点**：新增 `GET /channel/manager/{id}/unread-counts`（service 方法内 `count_articles_batch`/msearch）；`get_channel_detail` 移除 `_calculate_sub_channel_unread_counts` 调用 + 响应去 `sub_channel_unread_counts`。先写等价测试（端点返回与改造前逐子频道计算一致） | `channel_manager.py`(router) + `channel_service.py` + schema | AC-01, AC-05, AC-26 | T2 | ✅ |
| T5 | **B 空间广场批量化**：`_format_accessible_spaces`（`knowledge_space_service.py`）逐空间 `get_permission_level`→单次 `batch_check`、effective_ids→`filter_object_ids_by_permission_async` 共享上下文；`list_uploadable_spaces` 并行+共享上下文。先写等价测试（返回空间集+权限标记不变、全返回契约不动、fail-closed） | `knowledge_space_service.py` | AC-01, AC-03, AC-09, AC-10, AC-11, AC-28(部分) | 无 | ✅ |
| T6a | **C 助手列表 cursor**：`get_all_assistants(name,0,0,...)` 去 fetch-all-slice，改 cursor 边取边筛 / accessible-id 预过滤；复用 `common/cursor.py` + `AppInvalidCursorError`(10550)。先写等价测试（同页结果集不变） | `bisheng/api/services/assistant.py` | AC-01, AC-12, AC-13, AC-14 | 无 | 🔲 |
| T6b | **C 工作台最近·常用·推荐 cursor**：`workflow.py`/`apps.py` 去 `page=0,limit=0`+手切，最近·常用改 cursor、推荐改有界拉取+共享上下文过滤；复用 `AppInvalidCursorError`(10550)。先写等价测试 | `bisheng/api/services/workflow.py`, `bisheng/workstation/api/endpoints/apps.py` | AC-01, AC-12, AC-13, AC-14, AC-15 | 无 | 🔲 |
| T6c | **C 空间文件搜索 cursor**：`search_space_children`（`knowledge_space_service.py`）去 `_paginate_items` 手切，改 `_scan_visible_child_items` 边取边筛范式；复用 `KnowledgeSpaceInvalidCursorError`(18070)。先写等价测试（含 INV-7 不放宽可见性） | `knowledge_space_service.py` | AC-01, AC-02, AC-12, AC-13, AC-14 | 无 | 🔲 |

### Wave 3 — 前端（依赖 Wave 2 契约；分 Platform / Client）

| # | 任务 | 分区 | 产物 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| T7 | **A 频道 ArticleList 改造**：详情不再读 `sub_channel_unread_counts`；进入频道后独立调 `…/unread-counts` 填角标；失败降级 0/不显示。验证：预览弹窗无未读请求、in-channel 角标正常 | **Client** | `src/frontend/client/`：`ArticleList.tsx`, `channels.ts` + TS 类型 | AC-05 | T4 | 🔲 |
| T8a | **C 助手列表无限滚动**：`useInfiniteQuery` + cursor 触底加载 + cursor 错误码 reset + 去「共 X 个」文案 | **Platform** | `src/frontend/platform/`：助手列表组件 + API 封装 | AC-12, AC-13 | T6a | 🔲 |
| T8b | **C 工作台列表 + 文件搜索无限滚动**：`useInfiniteQuery` + cursor 触底 + 错误码 reset | **Client** | `src/frontend/client/`：工作台/文件搜索组件 + API 封装 | AC-12, AC-13 | T6b, T6c | 🔲 |
| T9a | **D 侧栏移除 mount 预取**：`useKnowledgeSpaceActionPermissions` 渲染期批量 `checkPermission` 移除；`KnowledgeSpaceSidebar` 不再首屏预判 | **Client** | `src/frontend/client/`：`useKnowledgeSpacePermissions.ts`, `KnowledgeSpaceSidebar.tsx` | AC-16, AC-29 | 无 | ✅ |
| T9b | **D 菜单按需查权限**：`KnowledgeSpaceItem`/`KnowledgeSpaceCardItem` 菜单 `onOpenChange` 触发该空间 `checkPermission` + 组件级缓存 + 加载/失败 fail-closed + 超管短路。验证：菜单打开才查、按钮集合与改造前一致 | **Client** | `src/frontend/client/`：`KnowledgeSpaceItem.tsx`, `KnowledgeSpaceCardItem.tsx` | AC-17, AC-18, AC-19, AC-20 | T9a | ✅ |

> **横切等价 AC**：AC-01（A/B/C 对象集/permission_ids 等价）由 T4·T5·T6a·T6b·T6c 等价测试覆盖；AC-02（INV-7）由 T6c 覆盖；AC-03（fail-closed）由 T1·T5 覆盖；AC-19·AC-20（D 组按钮等价）由 T9b 覆盖。

### Wave 4 — 验证

| # | 任务 | 产物 | 覆盖 AC | 依赖 | 状态 |
|---|---|---|---|---|---|
| T10 | **静态扫描 + 性能基线**：按 AC-31 grep 断言（详情不再调 `_calculate_sub_channel_unread_counts`、广场无逐空间 `get_permission_level`、C 组无 `page=0,limit=0` 后切片、侧栏无 mount 期批量 `checkPermission`、E 组 key 含版本/哈希且写路径零失效调用）；用 `seed_load_test_org.sh` 造大用户量数据，压 `/channel/manager/{id}`、`/space/joined`、`/children` 深展开，记录 DB/FGA/ES 往返数 + P95 对比 design §7.1，落 `loadtest-report.md` | `loadtest-report.md` | AC-26, AC-27, AC-28, AC-29, AC-30, AC-31 | T1~T9b | 🔲 |

---

## 实际偏差记录

- **D1（T1，影响系统认知）**：E 组**主体串缓存（AC-22）延后**。design §3 决策6 原拟用 `(user_id, max(update_time) over user_group_link+user_department)` 做版本 key — 实现时发现**删除不安全**：用户被移出某用户组时其 link 行被删除，剩余行的 `update_time` 不变 ⇒ 版本不变 ⇒ 旧主体串仍命中 ⇒ 用户保留已撤销组的权限（越权，破坏等价红线）。安全版本需删除感知（`count(*)+max(update_time)` 或成员 id 集哈希）。**bindings/models 不受此影响**（config 写经 `insert_or_update_config`，`update_time` 必变，无删除-不变问题），故 T1 照常落地。论证见 design §5 坑表。
- **D2（T1，正向偏差）**：缓存接入点从 `knowledge_space_service.py` 的 3 个 helper **改到源头** `resource_permission.py` 的 `_get_bindings`/`_get_relation_models`。原因：channel 详情（T2）经 `channel_service._build_channel_permission_context → _get_bindings` 重建名册，不走 knowledge_space_service；改在源头让 **channel + 知识空间 + 所有 ReBAC 路径**都受益，且 per-request memo 仍叠加其上。文件数不变（3 个）。
- **D3（T5，方案1）**：用户裁定 T5 走「方案1 安全版」。已做：`_format_accessible_spaces` 共享 `binding_index`+tuple 缓存跨空间（不再每空间重建索引/重读 tuple，membership/public 合并原样保留→等价）、`list_uploadable_spaces` 串行→`gather`（AC-09）。**未做（AC-08 / 完整 AC-28）**：逐空间 `get_permission_level`→单次跨空间 `batch_check`（需重构 `get_permission_level`，等价风险更大）——保留并行 `gather`，FGA 调用更便宜但仍 O(N)。真要 O(N)→O(1) 另起方案2。注：`/space/joined` 的主要成本是非创建空间的 effective-ids（已优化）；`get_permission_level` 仅作用于「无 membership 行」的空间，对 /joined 多为空集。
- **D4（新增 T11，2026-06-26 用户追加）**：D 组「权限懒加载」扩展到**知识空间文件列表**（原 D 组只覆盖侧栏空间菜单）。现状：`SpaceDetail/index.tsx` 4 个 mount 期 effect 对每文件 ×4 发 `permissions/check`（50 文件≈200 请求）。改：删 eager effect，菜单 `onOpenChange` 打开时才查该文件（rename/download/delete/manage），按文件去重、admin/owner 短路、fail-closed、列表切换清空。客户端 3 文件（`SpaceDetail/index.tsx`、`FileCard.tsx`、`FileTable.tsx`）。tsc 零新增错误；前端手动验证：打开文件列表→0 个 check，点开某文件「⋯」→仅该文件 ≤4 check。
