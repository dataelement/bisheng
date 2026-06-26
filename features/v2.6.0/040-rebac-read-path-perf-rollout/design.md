# Design: F040 ReBAC 读路径性能范式收尾

> **本文档定位 — 现状快照（Why this How）**
> spec 回答做什么；本文回答**为什么这么实现**：关键决策、运行时不直观的事实、对外契约。
> 调整原则见 `docs/SDD-Guide.md` §3-§4：实现变化覆盖更新本文，保留"为什么 + 被否方案"。

**关联**: [spec.md](./spec.md) · [tasks.md](./tasks.md)
**版本**: v2.6.0（分支 `feat/v2.6.0/040-rebac-read-path-perf-rollout`，基于 `feat/2.6.0`）
**最后更新**: 2026-06-25（初版）

> 下文 file:line 锚点取自 2026-06-25 探查（部分在 `feat/2.6.0-beta4` 工作树测得）；`feat/2.6.0` 基底行号可能略有漂移，**以函数名为准**，实现时按名定位。

---

## 1. 目标与非目标

- **目标**：把 F027（cursor 分页解决"扫多少"）/ F036（继承快速通道解决"每项多贵"）/ F037（频道权限上下文一次构建复用）三条**已验证范式**，铺到尚未覆盖的高频读路径——频道详情预览、知识空间广场列表、工作台/应用列表、侧边栏权限检查、以及每请求重建权限"名册"的成本。统一原则：**只改"怎么算/怎么取"，不改"算出什么"**（语义对改造前逐位等价）。
- **非目标**：
  - 不改 OpenFGA 模型、relation-model/binding 数据模型、授权写入 UI。
  - 不引入 F036 否决的那类跨请求缓存（提 `permission_cache` TTL / 写路径挂失效钩子）。
  - 不做侧边栏 `/children` 的前端并发去重、N 个文件夹 LIKE 计数合并（另案）。
  - 不做 OpenFGA/DB/ES 扩容等运维侧动作。
  - 不改 `/space/joined`·`/space/department` 的全返回契约、不改其前端。

---

## 2. 关键约束

- 全局架构铁律遵循 `docs/constitution.md` C1–C7（双 DB / 多租户 / 分层 / 权限 / 错误码）。
- **INV-6**（F027）：走 ReBAC 过滤的高频列表用 cursor 分页。本特性 C 组遵循；B 组申请豁免（见决策 3）。
- **INV-7**（F029）：知识空间内容"AI 问答可见性 ⊆ 列表 UI 可见性"。本特性 C 组文件搜索不放宽该子集关系。
- **零跨域失效耦合**（F036 design §3 决策 4）：任何缓存不得把失效逻辑挂进授权/部门/组织同步等其它领域写路径。E 组用版本派生 key 满足此约束（决策 6）。
- **语义等价红线**（spec AC-01/05/19/24）：可见集、permission_ids、订阅态、菜单按钮、缓存命中结果，必须与改造前逐位一致。
- **双 DB / 多租户**：所有缓存 key 含 `tenant_id`；ES/Redis/DM8 行为差异在坑表（§5）记录。

---

## 3. 方案对比与选定

### 决策 1：频道详情慢——拆出独立未读端点（而非批量化或加开关）

- **背景实证**：`get_channel_detail`（[channel_service.py:1683](../../../src/backend/bisheng/channel/domain/services/channel_service.py)）单请求 ES count 次数 = `1`（文章总数）`+ S×(1+⌈R/1000⌉)`（未读，S=子频道数、R=用户已读数）。即"贵"的是**未读**不是文章总数；且未读 **per-user、不可缓存**。预览弹窗 `ChannelPreviewDrawer` 根本不渲染未读，却照付这笔钱（且 `staleTime:0` 每开必算）。
- **备选**：
  - A. 单接口加 `?include_unread=false` 开关，预览传 false — 改动最小；但响应形状随参数变、in-channel 仍走重接口。
  - B. 预览/详情两个完整接口 — 两者 ~90% 字段重复，维护双 schema。
  - C. **把唯一贵的未读拆为独立懒加载端点** `GET /channel/manager/{id}/unread-counts`；详情接口对所有调用方都变廉价（不含未读）。
- **选定**：C。
- **原因**：预览与 in-channel 详情 ~90% 字段相同，真正差异只有 `sub_channel_unread_counts` 一项贵的（`knowledge_sync` 仅创建者、1 查询；`filter_rules` 免费）。拆"整个详情"会复制大量字段（否 B）；开关让响应形状随参数漂移、且 in-channel 仍重（否 A）。拆未读后：①详情对预览+in-channel 都廉价、可复用；②未读成为可独立懒加载/独立刷新的资源；③未读端点内部用 `count_articles_batch`（ES `msearch`）把 `S×(1+⌈R/1000⌉)` 次 count 合并为 1~2 次 HTTP 往返。
- **何时该重新考虑**：若未来 in-channel 也需在详情首屏同步显示未读（产品改 UI），或 R 极大致 msearch 服务端计算仍是瓶颈（见坑 §5-#3）→ 考虑未读预聚合/物化。

### 决策 2：频道文章总数加 Redis 短 TTL 缓存（而非事件失效）

- **备选**：
  - A. **短 TTL（60–120s）缓存** `article:count:{tenant_id}:channel:{channel_id}:main` — 简单；最长 ≤TTL 滞后。
  - B. 写路径事件失效 — 0 滞后；但文章摄入是异步 Celery（`worker/information/article.py`），给 worker 加 Redis 硬依赖、且要反查受影响频道。
- **选定**：A。
- **原因**：文章总数与用户无关、跨用户共享、可缓存（区别于 per-user 未读）；摄入异步、非实时一致，≤TTL 滞后对"文章数角标"可接受；ES 摄入后本就有 `_refresh_index`，秒级可见。事件失效的跨进程耦合代价不值（与 F036 决策同源思路）。miss/Redis 挂回落实时 ES count 并回填（坑 §5-#5）。
- **何时该重新考虑**：若产品要求文章数实时精确（如计费），改 B 或在摄入后定向失效。

### 决策 3：空间广场 batch_check + 共享上下文，保持全返回——INV-6 豁免论证

- **背景实证**：`_format_accessible_spaces`（[knowledge_space_service.py:292](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)，N+1 在 316–345）对每个可访问空间逐个 `get_permission_level` + `_get_effective_permission_ids`；`/joined`·`/department` **无分页、全量返回**；`list_uploadable_spaces`（~2004）还是串行 for。
- **备选**：
  - A. 按 INV-6 把 `/joined`·`/department` 也改 cursor 无限滚动。
  - B. **保持全返回，仅消 N+1**：逐空间 `get_permission_level` → 单次 `batch_check`（[core/openfga/client.py:83](../../../src/backend/bisheng/core/openfga/client.py)）；逐空间 `_get_effective_permission_ids` → `filter_object_ids_by_permission_async`（[fine_grained_permission_service.py:586](../../../src/backend/bisheng/permission/domain/services/fine_grained_permission_service.py)）一次建上下文跨空间共享；`list_uploadable_spaces` 并行 + 共享上下文。
- **选定**：B（用户 2026-06-25 确认）。
- **INV-6 豁免论证**（评审 medium 项，必须立住）：INV-6 的目的是**避免大列表深翻时 O(N×page×ReBAC) 的扫描+count**。`/joined`·`/department` 的结果集是**按"用户已加入空间 / 部门子树空间"天然有界**的 per-user 集合（量级数个~数十个），**不随租户资源总量增长**，且**无 page/深翻语义**。其真实成本是逐空间 N+1 权限检查，B 方案已根除（O(N) FGA → O(1) batch + 共享上下文）。强行 cursor 化会给"我加入的空间"侧栏引入无限滚动 UX 复杂度却无收益。**故登记 INV-6 例外**：*WHERE 列表结果集由 per-user 成员关系/部门子树天然有界且无深翻语义，可保留全返回，但 N+1 逐项权限检查必须批量化*。该例外写入 release-contract 变更历史。
- **何时该重新考虑**：若某租户单用户可加入空间数膨胀到数百+（异常组织形态），再评估 cursor 化。

### 决策 4：C 组列表去 fetch-all——cursor 优先、小集合可有界拉取

- **背景实证**（2026-06-25 核实，5 端点**均**仍 fetch-all）：助手列表 `get_all_assistants(name,0,0,...)`（[assistant.py:65](../../../src/backend/bisheng/api/services/assistant.py)）、工作台常用 `get_all_apps(...,page=0,limit=0)`（[workflow.py:815](../../../src/backend/bisheng/api/services/workflow.py)）、工作台最近（[apps.py:105](../../../src/backend/bisheng/workstation/api/endpoints/apps.py)）、空间文件搜索 `search_space_children`→`_paginate_items`（[knowledge_space_service.py:2845](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)）。
- **备选 / 选定（按端点分流）**：
  - 保留分页语义的列表（助手、最近、常用、文件搜索）→ **INV-6 cursor**，复用 F027 `common/cursor.py` 与 `_scan_visible_child_items`（[:2690](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)）的"边取边筛、凑够即停"范式；文件搜索带 keyword，优先用 `list_accessible_ids` 预过滤把权限推进 SQL 再分页。
  - 本身无需深翻的小集合（"推荐"capped）→ 有界拉取 + 共享上下文过滤，不强制 cursor（AC-15）。
- **原因**：fetch-all 成本 O(租户该资源总量)，随增长失控；cursor/边取边筛把成本压到 O(可见集)。复用既有范式零新机制。错误码复用 F027 `AppInvalidCursorError`(10550)/`KnowledgeSpaceInvalidCursorError`(18070)，**不新增**。
- **何时该重新考虑**：keyword 搜索若命中率极低致边取边筛扫批过多，改 ES/全文索引预过滤。

### 决策 5：侧边栏权限检查懒加载——菜单打开才查（而非批量端点）

- **背景实证**：`useKnowledgeSpaceActionPermissions`（[useKnowledgeSpacePermissions.ts:35](../../../src/frontend/client/src/pages/knowledge/hooks/useKnowledgeSpacePermissions.ts)）在侧栏 mount 时对**全部空间 × 4 权限**（edit/delete/share/manage_relation）`checkPermission`（[api/permission.ts:119](../../../src/frontend/client/src/api/permission.ts)，单查无 batch）→ N×4 并发请求；菜单组件只读预取 props。
- **备选**：
  - A. 后端加 `POST /permissions/batch-check` 批量端点，前端首屏一次批量。
  - B. **前端懒加载**：删 mount 预取，在「⋯」菜单 `onOpenChange` 时查**该空间**权限。
- **选定**：B（用户确认）。
- **原因**：B 把首屏 `permissions/check` 从 O(N×权限数) 降为 **0**——绝大多数空间用户根本不点菜单。一次只查一个空间、用户触发，天然规避后端单查端点无 batch 的限制（无需 A 的后端改造）。组件级缓存避免重复打开重查；查询中禁用态、失败 fail-closed（隐藏受限项），等价红线由 AC-19 守。超管短路不触发 check。
- **何时该重新考虑**：若产品需菜单"零延迟"展开，再考虑 A 的批量端点或预取首屏可视空间。

### 决策 6：每请求重建"名册"——版本派生 key 跨请求缓存（F036 §8 背书路径）

- **背景实证**（2026-06-25 核实，问题真实存在）：service 每请求新建（[dependencies.py:108](../../../src/backend/bisheng/knowledge/api/dependencies.py) `get_knowledge_space_service`，FastAPI `Depends`）→ 每个 `/children` 请求 `_get_relation_bindings`（[:682](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)）→ `_get_bindings`（[resource_permission.py:292](../../../src/backend/bisheng/permission/api/endpoints/resource_permission.py)）→ `ConfigDao.aget_config_by_key`（[common/models/config.py:80](../../../src/backend/bisheng/common/models/config.py)，**无缓存**）做 `SELECT config` + `json.loads(整份名册)` + 全量 legacy 扫描；`build_binding_index` 每请求重建索引；`_get_current_user_subject_strings`（[:883](../../../src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py)）每请求查用户组/部门。展开 N 层 = 翻 N 遍名册。**F036 优化的是逐项评估，刻意推迟了此项**。
- **备选**：
  - A. 提 `permission_cache` TTL / 写路径挂失效钩子跨请求复用上下文 — **F036 已否决**（跨域失效耦合）。
  - B. **版本派生 key 缓存**：按 bindings/models 配置行的**版本/内容哈希**派生 key，缓存"已解析+已建索引"的名册；按**用户主体版本**（用户组/部门变更版本）派生 key 缓存主体串。读侧自然失效，零写路径钩子。
- **选定**：B（F036 design §8 明确背书的"读侧从数据版本派生 key"路径，与被否决的 A 本质不同）。
- **主选项（v1 定稿，tasks 仅实测调参，不再悬空）**：
  - **名册版本来源 = config 行 `update_time`**：bindings/models 存于 `config` 表单行 JSON，`_save_bindings`/`_save_relation_models`（resource_permission.py）经 `ConfigDao.insert_or_update_config` 写入即刷新 `update_time`。每请求先发**轻量版本读**——只 `SELECT update_time WHERE key=...`（**不取 `value` JSON 大列**），拿到版本字符串；与缓存版本一致即复用"已解析 + 已建索引"结构（跳过 value 传输 + `json.loads` + `build_binding_index` + legacy 扫描，这才是 CPU 大头）；版本变 / miss 才走完整 `aget_config_by_key` + 解析 + 建索引 + 回填。
    - **fallback**：若某 DB 视图取不到稳定 `update_time`，退化为 `xxhash(value)` 内容哈希作版本（此时省的只是 CPU、不省 value 传输）。
  - **主体串版本 = 用户组/部门成员关系变更版本**：key = `(user_id, max(update_time) over user_group_link + user_department for this user)`——成员关系一变，聚合版本变、key 失效。该聚合为轻量索引查询。
  - **缓存介质 = 进程内 LRU（按 `tenant_id` 分桶）**：名册是租户级共享、命中率高、无需跨进程强一致；多 worker 各持一份可接受（各自按版本独立失效，不会串旧）。**fallback**：若多 worker 命中率实测过低，改 Redis 共享（key 同样含版本）。
  - **fail-safe**：版本不可得 → 回落实时构建、不写缓存（绝不返回可疑旧名册，AC-24）；按 `tenant_id` 分桶隔离（AC-25）。
  - tasks 阶段只需实测确认轻量版本读确实够快（单行/聚合）、并定 LRU 容量；**机制本身不再开放**。
- **与 F036 边界（必须立住）**：A（被否）的失效靠**写路径主动 invalidate**，耦合授权/部门/组织域；B（本决策）的失效靠**读侧 key 随数据版本自然变化**，零写路径介入——这正是 F036 §8 留的口子。两者不同，不构成对 F036 决策的推翻。
- **何时该重新考虑**：若名册（bindings JSON）膨胀到单次解析仍慢、或多 worker 命中率低 → 评估 Redis 共享或预解析物化。

---

## 4. 系统现状（接手必读）

### 4.1 数据流（按能力组）

- **A 频道详情**：`GET /channel/manager/{id}` → `get_channel_detail`（channel_service.py:1683）。改造后：权限走 `_get_channel_permission_ids(context=_build_channel_permission_context(...))`（:197/:227，仿 `get_my_channels`:619）；`article_count` 经 Redis 缓存层取数；**移除** `_calculate_sub_channel_unread_counts` 调用；membership 单查复用。新端点 `GET /channel/manager/{id}/unread-counts` → 新 service 方法（内部 `count_articles_batch`，article_es_service.py:587）。
- **B 空间广场**：`/space/joined`→`get_my_followed_spaces`(:1792)、`/space/department`→部门空间服务 → 均经 `_format_accessible_spaces`(:292)。改造后逐空间 N+1 → `batch_check` + `filter_object_ids_by_permission_async` 共享上下文；契约不变（全返回）。
- **C 工作台/应用列表**：各端点去 `page=0,limit=0` 全捞 + `_paginate_items` 手切，改 cursor 边取边筛 / accessible-id 预过滤（决策 4）。
- **D 侧边栏懒加载**：`KnowledgeSpaceSidebar`(:188) 移除 mount 预取；`KnowledgeSpaceItem`/`KnowledgeSpaceCardItem` 菜单 `onOpenChange`(:180) 触发该空间 `checkPermission`，组件级缓存。
- **E 名册缓存**：`_get_relation_bindings`/`_get_relation_models_map`/`_get_current_user_subject_strings` 改为先查版本派生 key 缓存，命中复用、未命中构建并回填。

### 4.2 对外契约（API request/response）

| 契约 | 形式 | 说明 |
|---|---|---|
| `GET /channel/manager/{id}` | 响应**移除** `sub_channel_unread_counts` | 详情变廉价；前端 `ChannelDetailResponse` TS 类型同步去字段（Optional，向后兼容） |
| `GET /channel/manager/{id}/unread-counts` | **新增**，响应 `{ <sub_channel_name>: <unread:int> }` | per-user 懒加载；in-channel `ArticleList` 进入后调 |
| 助手/工作台/文件搜索列表 | 改 INV-6 cursor envelope（`data`/`page_size`/`has_more`/`next_cursor`，不返 `total`） | 复用 F027 `common/cursor.py`、`*InvalidCursorError` |
| `/space/joined`·`/space/department` | **不变**（全返回） | 仅后端权限计算批量化 |

### 4.3 关键模块职责

| 模块 / 文件 | 职责 | 不做什么 |
|---|---|---|
| `channel_service.py` | 频道详情编排（廉价化）+ 新未读端点服务 | 详情不再算未读；不重建 ReBAC 上下文 |
| `article_es_service.py` | ES 文章 count（`count_articles`/`count_articles_batch`） | 不持有缓存（缓存在 service 层封装） |
| `knowledge_space_service.py` | 空间广场/文件列表/名册装配 | 列表不 fetch-all-slice；名册经版本 key 缓存 |
| `fine_grained_permission_service.py` | 共享上下文细粒度评估（F036 范式） | 语义不变 |
| `useKnowledgeSpacePermissions.ts`（client） | 改为懒加载 hook（菜单触发） | 不在 mount 期批量预取 |

---

## 5. 已知坑 / 反直觉事实

| # | 反直觉事实 | 如果不知道会怎样 | 在哪处理 |
|---|---|---|---|
| 1 | `KnowledgeSpaceService` 是 FastAPI `Depends` **每请求新建**，`self.__dict__` 上的所有缓存（名册/模型/主体串/effective_ids）只在**单请求内**有效 | 误以为跨请求复用，E 组优化无从谈起 | E 组在 service 之上加版本 key 缓存（决策 6） |
| 2 | `ConfigDao.aget_config_by_key`（config.py:80）**无任何缓存**，每调一次 `SELECT config` | 误以为名册读取廉价；其实每请求 DB 读 + 全量 `json.loads` + legacy 扫描 | E 组版本 key 缓存（CPU 大头是解析/建索引，非 DB 往返） |
| 3 | `count_articles_batch`（msearch）只省**HTTP 往返**，ES 服务端仍执行 N 次 count | 误以为 batch 后未读零成本；R（用户已读）极大时服务端计算仍涨 | 决策 1 拆未读+batch 解决往返；服务端计算列入 §8 后续 |
| 4 | 子频道未读是 **per-user**（依赖用户已读 ID 集），**不可跨用户缓存** | 误把未读塞进共享缓存→串用户数据 | 仅文章总数缓存（决策 2）；未读靠拆端点+batch（决策 1） |
| 5 | 缓存 miss / Redis 不可用必须回落实时取数，不可报错阻塞主流程 | 详情/列表因缓存层挂掉而 500 | A/E 组均 fail-safe 回落 + 一行 reason 注释（遵循后端 CLAUDE.md 错误处理） |
| 6 | F036 继承快速通道：无更近绑定的项套用一次性祖先决策；**有更近绑定必须完整评估** | 优化时误放行被单独限权的项 → 越权（破 INV-7） | C 组文件搜索复用 `_filter_visible_child_items`，不改其判定 |
| 7 | `feat/2.6.0` 比 `feat/2.6.0-beta4` 落后 22 commit；本 feature 锚点行号可能漂移；037/038 编号在该分支已有占用（本 feature 为 039） | 按旧行号改错位置 / 撞号 | 以函数名定位；编号已避让为 039 |
| 8 | `search_space_children`（文件**搜索**，:2845）与 `list_space_children`（**浏览**，:2762）是两个方法；浏览已 F027 cursor，搜索仍 fetch-all | 误以为搜索已优化而漏改 | 决策 4 明确只改搜索 |
| 9 | **E 组主体串版本不能用 `max(update_time)`**：用户被移出某用户组时，其成员 link 行被**删除**——剩余行的 `update_time` 不变 ⇒ 版本不变 ⇒ 缓存仍命中旧主体串 | 用户保留已撤销组的权限（越权，破坏等价红线 AC-01） | bindings/models 用 `update_time` 安全（写经 `insert_or_update_config` 必 bump，无删除问题）；**主体串缓存（AC-22）延后**，需删除感知版本（`count(*)+max(update_time)` 或成员 id 集哈希），见 tasks 偏差 D1 |
| 10 | E 组缓存是**进程内**的，但安全不靠"进程间同步"——靠**每请求一次轻量 `aget_config_version` 校验**：任一进程 commit 新 bindings → `update_time` 变 → 其它进程下次读版本即 miss → 重建 | 误以为多 worker 会服务旧名册而不敢用进程内缓存 | 版本校验是 source-of-truth 比对，跨进程天然一致（决策 6） |

---

## 6. 对外契约与依赖

### 6.1 我提供给别人的（Outgoing）

| 契约 | 形式 | 谁在用 |
|---|---|---|
| `GET /channel/manager/{id}/unread-counts` | 新增 HTTP API | client `ArticleList`（in-channel 未读角标） |
| `GET /channel/manager/{id}`（去 unread 字段） | 响应契约变更 | client 预览 Drawer + ArticleList |
| 助手/工作台/文件搜索列表 cursor 协议 | HTTP（INV-6） | 对应前端列表（改 `useInfiniteQuery`/触底加载） |

### 6.2 我依赖别人的（Incoming）

| 依赖 | 形式 | 风险点 |
|---|---|---|
| F037 `_build_channel_permission_context` | 内部 Python API（channel_service.py:227） | F037 改其签名会影响 A 组 |
| F036 `filter_object_ids_by_permission_async` / 继承快速通道 | 内部 Python API | F036 改语义会影响 B/C/E |
| F027 `common/cursor.py` + `*InvalidCursorError` | 内部模块 + 错误码 | cursor schema 变更 |
| `config` 表 bindings/models JSON | 隐式数据契约 | E 组版本判定依赖其 update_time/内容稳定性 |
| OpenFGA `batch_check` | HTTP RPC | B 组依赖其批量语义 |

### 6.3 领域邻接声明（不越界）

F040 仅改"计算/取数机制"，**不**拥有也不改下列 Feature 的语义：F026（频道授权/`space_channel_member` channel 字段）、F031（`channel_info_source` 订阅生命周期）、F033（部门空间授权收敛）、F037（频道权限上下文 helper 的归属）。A 组读频道详情、B 组读部门空间集，均不改其授权/订阅规则。

---

## 7. 测试与可观测

- **语义等价（最高优先）**：以改造前逐项评估/全量过滤为 oracle，对 A/B/C 同输入断言可见集、permission_ids、未读数逐位一致；E 组断言"缓存命中结果 == 实时构建结果"。复用 F036 的 `_filter_visible_child_items_reference` 思路。

### 7.1 性能目标值（落地数字，对应 spec §2.7 各 AC）

> 用 `scripts/seed_load_test_org.py`（本分支已带，灌大用户量部门树 + ReBAC 边）造数据；以下为**改造后**目标，与改造前基线对比；指标=单请求对 DB/FGA/ES 的往返数 + P95。

| 场景 | 改造前 | 目标（改造后） | 对应 AC |
|---|---|---|---|
| `/channel/manager/{id}` 对 ES 的 count 往返 | `1 + S×(1+⌈R/1000⌉)` | **≤1**（仅文章总数；命中文章缓存为 **0**） | AC-26/27 |
| 频道详情权限上下文构建 | 重建（~5–10 DB+FGA 往返） | 复用 F037 context；命中 E 缓存额外往返 ≈ 0（仅 1 次轻量版本读） | AC-26 |
| 频道详情 membership 查询 | 2 次 | **1 次** | AC-26 |
| 未读端点 `…/unread-counts` ES 往返 | `S×(1+⌈R/1000⌉)` 次 count | **1~2 次 msearch** | AC-26 |
| `/space/joined` 对 FGA 的调用 | O(N)（N 空间各独立 `get_permission_level`+effective） | **≤2 批**（1 `batch_check` + 1 共享上下文 read）；上下文构建 O(N)→O(1) | AC-28 |
| C 组列表扫描量 | O(租户该资源总量) | O(可见集 + 页规模)，深翻不线性退化 | spec §2.4 |
| 打开含 N 空间侧栏首屏 `permissions/check` | O(N×4) | **0**（仅菜单点开按需） | AC-29 |
| 连续展开 N 层文件夹的名册重建 | N 次（DB value 读 + `json.loads` + 建索引 + 主体串） | **1 次**（其余 N−1 命中 E 缓存；每次仅 1 轻量版本读） | AC-30 |

> 注（坑 §5-#3）：未读端点的 msearch 只压缩 HTTP 往返；R 极大时 ES 服务端仍执行 O(R/1000) 次 count，P95 目标以"往返数"而非"服务端算力"为准，服务端优化列 §8。

### 7.2 静态可验证 + 手动验证

- **静态**：按 spec AC-31 grep（详情不再调 `_calculate_sub_channel_unread_counts`、广场无逐空间 `get_permission_level` 循环、C 组无 `page=0,limit=0` 后切片、侧栏无 mount 期批量 `checkPermission`、E 组 key 含版本/哈希且授权/部门/组织同步写路径零失效调用）。
- **手动跑一遍**（cwd `src/backend/`）：
  ```bash
  config=config.yaml bash scripts/seed_load_test_org.sh --departments 200 --users 50000 --apply   # 造压测数据
  ```
  登录该租户用户 → 打开知识空间界面（观察首屏无 `permissions/check` 批量）→ 逐层展开文件夹（观察 `/children` 名册不重复重建）→ 打开频道广场预览（观察 detail 无未读计算）。
- **多租户/DM8/ES**：中间件相关在 CI 跑（见 SDD-Guide §6）。

---

## 8. 后续改进 / 不打算做的事

- **侧边栏前端并发去重 + N 文件夹 LIKE 计数合 GROUP BY**：本期排除（另案），E 组已解后端重建税。
- **未读 ES 服务端计算**：R 极大时 msearch 仍 O(R/1000) 次服务端 count；若成瓶颈，考虑未读预聚合/物化视图（触发：单用户已读 ≫ 万级且未读端点 P95 退化）。
- **E 组 Redis 共享 + 名册预解析物化**：多 worker 命中率低或名册 JSON 膨胀时再上（决策 6 触发条件）。
- **C 组前端 `useInfiniteQuery` 改造**：随后端 cursor 化在 tasks 落地；与 F027 已有前端范式对齐。

---

## 修订历史

| 日期 | 改动 | 触发原因 |
|---|---|---|
| 2026-06-25 | 初版（5 组能力 + INV-6 豁免论证 + E 组/F036 边界） | feature design 起草 |
