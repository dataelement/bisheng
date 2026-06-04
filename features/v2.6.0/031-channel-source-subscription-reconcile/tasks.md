# Tasks: F031-channel-source-subscription-reconcile（频道信息源订阅状态：同步订阅 + 每日对账）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.6.0

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-06-04 用户确认；两条 medium（契约登记 / 对账逻辑下沉 service）已修订 |
| tasks.md | ✅ 已拆解 | 2026-06-04 /sdd-review tasks 通过（2 个 medium 修复后 LGTM） |
| 实现 | ✅ 完成 | 8 / 8 完成（2026-06-04，全部测试通过） |

---

## 开发模式

**后端 Test-First**：先写测试（红）→ 再写实现（绿）。
本特性纯后端、无新表、无对外 API、无前端、无新错误码（沿用 19007）。

**闭环约束（重要）**：本特性的三件事——①订阅判据切到 `channel_info_source`、②去掉 dismiss/update 的同步退订、③上线每日对账——**必须同批合入**。单独换判据会在旧退订语义下漏订阅（详见 spec §4 AD-04 / §9 注）。当前已合入的过渡实现（`create_channel` 用 `find_channels_by_source_id`）将在 T003 被替换。

**自包含任务**：每个任务内联文件、逻辑、测试上下文，实现阶段不需要回读 spec.md。

---

## Tasks

### 基础设施（Repository 能力，无测试配对）

- [x] **T001**: `ChannelInfoSourceRepository.delete_by_ids`
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/channel_info_source_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/channel_info_source_repository_impl.py`
  **逻辑**: 新增 `async def delete_by_ids(self, source_ids: list[str]) -> None`：按 `id IN (...)` 删除元数据行（对账 `to_unsub` 清理用）。空列表直接返回，不发 SQL。
  **约束**: 依赖多租户自动注入（`channel_info_source` 含 `tenant_id`），调用方保证已处于目标租户上下文。无 DDL / 无表结构变更，无需迁移与回滚。
  **依赖**: 无

- [x] **T002**: `ChannelRepository.find_all_referenced_source_ids`
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/channel_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/channel_repository_impl.py`
  **逻辑**: 新增 `async def find_all_referenced_source_ids(self) -> set[str]`：读取当前租户所有 `channel.source_list` 列，在 Python 内展开求并集，返回去重 source_id 集合（即对账的 `desired`）。**不**用 `JSON_CONTAINS` / `JSON_EXTRACT`——只 `SELECT source_list`（JSON 列原样取出）后内存展开，DM8 兼容。
  **约束**: 多租户自动注入；对账批量调用一次，可接受全表读 `source_list` 列。无 DDL，无需迁移与回滚。
  **依赖**: 无

### 后端 Service —— 同步订阅判据 + 去同步退订（Test-First）

- [x] **T003**: 同步订阅判据 + dismiss/update 不退订 —— 单测（红）
  **文件**: `src/backend/test/channel/test_channel_source_subscription.py`（新建），并改 `src/backend/test/channel/test_channel_relation_compat.py`
  **逻辑/用例**（mock `bisheng_information_client`、`channel_info_source_repository`、`channel_repository`）：
  - `test_create_subscribes_only_missing_sources`：`source_list=[A,B]`，`channel_info_source.find_by_ids` 返回 `[A]` → 断言 `subscribe_information_source` 仅以 `['B']` 调用一次 → **AC-01**
  - `test_create_skips_subscribe_when_all_present`：全部已在 `channel_info_source` → `subscribe` 不被调用 → **AC-02**
  - `test_create_aborts_before_persist_on_limit`：对缺失源 subscribe 抛 `InformationSourceSubscriptionLimitError(19007)` → 频道/membership/owner 元组均未写 → **AC-03**（迁移自既有 `test_channel_relation_compat.py::test_create_channel_aborts_before_persist_when_subscription_limit_exceeded`，并把其 `channel_repository` mock 从 `find_channels_by_source_id` 改为 `channel_info_source.find_by_ids` 语义）
  - `test_create_inserts_metadata_rows_for_new_sources`：缺失源订阅后，`get_information_source_by_ids` + `batch_add` 被以缺失源调用 → **AC-05**
  - `test_update_add_subscribes_only_missing`：`to_add` 中部分已在 `channel_info_source` → 仅订阅缺失 → **AC-04**
  - `test_update_remove_does_not_unsubscribe`：`to_remove` 非空 → `unsubscribe_information_source` 不被调用 → **AC-07**
  - `test_dismiss_does_not_unsubscribe`：dismiss 含 source_list 的频道 → `unsubscribe_information_source` 不被调用、`channel_info_source.delete_by_ids` 不被调用 → **AC-06**
  - `test_dismiss_shared_source_stays_subscribed`：频道 A、B 都引用源 X，dismiss A（B 仍引用 X）→ 断言整个 dismiss 流程**完全不调用** `unsubscribe_information_source`、不删 X 行（X 在情报服务侧保持订阅，B 不受影响）→ **AC-08**
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08
  **基础设施**: 复用 `test_channel_relation_compat.py` 既有 `_service()` / `_LoginUser` 模式（`SimpleNamespace` + `AsyncMock`），无需新 conftest。
  **依赖**: 无（针对现有 service 签名写红测）

- [x] **T004**: Service 改造 —— 订阅判据切 `channel_info_source` + 删同步退订（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/channel_service.py`
  **跨 Feature 提示**: 本文件与 F026-channel-active-authorization 共享，但二者领域解耦（F026 拥有频道授权/`space_channel_member` channel 字段写行为，F031 拥有 `channel_info_source` 订阅生命周期；已在 release-contract 表1登记）。本任务只改 `create_channel` / `update_channel` / `dismiss_channel` 三个方法内的**信息源订阅副作用**，不碰授权相关代码。
  **逻辑**:
  1. `create_channel`：删除现有 `find_channels_by_source_id` 判据；改为 `existing = channel_info_source.find_by_ids(source_list)` → `missing = dict.fromkeys(source_list) 中不在 existing 的` → `if missing: subscribe(missing)`（**仍在持久化频道之前**，保留 19007 中止不变量）→ 用 `missing` 拉元数据并 `batch_add`。`missing` 同时驱动「订阅」与「元数据补行」，去掉重复的 find_by_ids。
  2. `update_channel`：`to_add` 用 `channel_info_source.find_by_ids` 求缺失子集后仅订阅缺失；**删除 `unsubscribe_information_source(to_remove)` 调用**；`to_remove` 仅体现在 `channel.source_list` 更新与 `source_list_changed` 标记上；保留既有元数据同步块。
  3. `dismiss_channel`：**删除** 末尾 `unsubscribe_information_source(channel.source_list)` 调用块（连同其 `get_bisheng_information_client()` 局部获取，若仅此处使用）。
  4. `find_channels_by_source_id` 方法保留（不删），本特性仅不再在订阅判据中使用它。
  **测试**: T003 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08
  **依赖**: T003

### 后端 Service —— 每日对账（Test-First）

- [x] **T005**: 对账 service 方法 —— 单测（红）
  **文件**: `src/backend/test/channel/test_information_subscription_reconcile.py`（新建）
  **逻辑/用例**（直接测 `ChannelService.reconcile_information_subscriptions()`，mock 三个依赖，**不经 Celery**）：
  - `test_reconcile_unsubscribes_and_deletes_orphan`：`desired={A}`、`current={A,X}` → `unsubscribe(['X'])` + `channel_info_source.delete_by_ids(['X'])`；A 不动 → **AC-09**
  - `test_reconcile_subscribes_and_inserts_missing`：`desired={A,Y}`、`current={A}` → `subscribe(['Y'])` + `get_information_source_by_ids(['Y'])` + `batch_add` 插 Y 行 → **AC-10**
  - `test_reconcile_noop_when_equal`：`desired==current` → 无 subscribe/unsubscribe/增删行 → **AC-11**
  - `test_reconcile_isolates_per_source_failure`：对某源 unsubscribe 抛异常 → 其余源照常处理、方法不抛、返回统计含 `failed` 且记录日志 → **AC-13**
  - `test_reconcile_returns_counts`：返回 `{to_sub, to_unsub, failed}` 统计结构 → 支撑 §10 可观测
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-13
  **依赖**: T001, T002

- [x] **T006**: 对账 service 方法 —— 实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/channel_service.py`
  **逻辑**: 新增 `async def reconcile_information_subscriptions(self) -> dict`（运行在调用方注入的某租户上下文内）：
  - `desired = channel_repository.find_all_referenced_source_ids()`（T002）
  - `current = { s.id for s in 全量 channel_info_source }`（用现有 `get_by_page` 全量取或按需在 T001 同文件补 `find_all()`；以单次扫拿全量 id 为准）
  - `to_unsub = current - desired`；`to_sub = desired - current`
  - 逐源（或分批）处理，**单源失败用 `try/except` + `logger.exception` 隔离**，不中断其余：`to_unsub` → `unsubscribe([sid])`（T-client）+ `delete_by_ids([sid])`（T001）；`to_sub` → `subscribe([sid])` + 拉元数据 + `batch_add`
  - 返回 `{"to_sub": n, "to_unsub": m, "failed": k}`
  **约束**: 复用 T004 中「订阅 + 补元数据」的内部逻辑（在 T004 抽成私有 helper 共用，避免重复）。
  **测试**: T005 全部通过。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-13
  **依赖**: T001, T002, T004, T005

### Worker —— Beat 薄包装（Test-First）

- [x] **T007**: `reconcile_all_tenants` 薄包装 —— 单测（红）
  **文件**: `src/backend/test/channel/test_information_reconcile_worker.py`（新建）
  **逻辑/用例**（mock 活跃租户来源 + `ChannelService.reconcile_information_subscriptions`）：
  - `test_reconcile_all_tenants_iterates_each_tenant`：给定 3 个活跃租户 → service 方法被各调用一次，且每次调用前 `current_tenant_id` 被设为对应租户 → **AC-12**
  - `test_reconcile_all_tenants_isolates_tenant_failure`：某租户对账抛异常 → 其余租户照常处理、任务不整体失败、记录日志 → **AC-12**
  **覆盖 AC**: AC-12
  **依赖**: 无（mock service，针对 T008 将定义的 `reconcile_all_tenants` 签名写红测；与 T008 配对）

- [x] **T008**: `reconcile_all_tenants` Celery Beat 任务（薄包装）+ 调度注册（绿）
  **文件**:
  - `src/backend/bisheng/worker/information/reconcile.py`（新建）
  - Beat 调度配置（参考 `worker/information/article.py` 注册方式 + `worker/config.py`）
  **逻辑**: 定义 `reconcile_all_tenants` 任务：遍历活跃租户 → 逐租户 `set_current_tenant_id(tenant_id)`（ContextVar，Beat 内部迭代注入，非 Celery headers 传参）后构造 `ChannelService` 并 `await reconcile_information_subscriptions()` → 汇总/记日志。**任务体不含业务逻辑**，仅租户遍历 + 调用 service（worker → service → repo 分层）。
  **约束**:
  - 走默认 `celery` 队列（审批/文章同步同款，不配 `task_routes`）。
  - Beat 凌晨低峰执行；与文章同步 Beat（05:30）错开（建议 04:30），避免叠加（多租户放大坑）。
  - 单租户对账失败不影响其余租户（外层再包一层 try/except + 日志）。
  **测试**: T007 全部通过。
  **覆盖 AC**: AC-12
  **依赖**: T006, T007

---

## 实际偏差记录

> 完成后，在此记录实现与 spec.md 的偏差，供后续参考。

- **偏差 1（新增 repo 方法）**: 除 `delete_by_ids` 外，给 `ChannelInfoSourceRepository` 同时加了 `find_all()`（spec T006 已预留"按需补 find_all()"），对账用它一次性取全量 current。
- **偏差 2（共享 helper）**: T004 抽出 `ChannelService._sync_channel_info_source_metadata()`（拉元数据 + batch_add），被 create/update/reconcile 三处复用，避免重复；update 的文章定时同步（`sync_information_article.apply_async`）仍保留在 update_channel 内、不进 helper。
- **偏差 3（worker 构造 service 的方式）**: worker 用 `_channel_service_session()` async 上下文管理器开 `get_async_db_session` 并构造 `ChannelService`，其中 `space_channel_member_repository=None`（对账方法不依赖它）。这是 spec 未细化的实现细节。
- **偏差 4（对账时间）**: 按评审建议定在 04:30（`30 4 * * *`），早于文章同步 05:30。
- **未做（spec 已声明排除）**: 事件触发近实时对账、外部订阅态反向校正、对账对 desired 全量幂等重订阅（默认关）均未实现，符合 spec §3 范围边界。
- **code-review 修订（2026-06-04）**:
  - 删除死代码 `ChannelRepository.find_channels_by_source_id`（接口+impl，及 impl 中随之失效的 `json_array_contains` 导入）——本特性后已无任何调用方。
  - `ChannelInfoSourceRepository.batch_add` 改为捕获 `IntegrityError` 后回滚 + 重查去重 + 仅插新行，落实 spec §3 / AC-05 声称的"主键冲突幂等跳过"（并发同时新增同一信息源场景）；新增 `test_batch_add_idempotent_on_integrity_error` 覆盖回滚/重试逻辑。
