# Feature: F031-channel-source-subscription-reconcile（频道信息源订阅状态：同步订阅 + 每日对账）

> **前置步骤**：已完成 Spec Discovery（多轮架构讨论），关键不确定性已与用户对齐：
> - 退订改为「每日对账」驱动，退订延迟 ≤ 1 天**可接受**；
> - 对账粒度先做**纯每日全量**，暂不做「事件触发 + 每日兜底」的近实时方案；
> - 订阅仍保持**同步即时**（19007 上限必须在建频道前校验、用户期望建完很快有文章）。

**关联 PRD**: 无独立 PRD，源自 v2.6.0-beta3 频道模块缺陷收敛（重复订阅 / 过度退订 / `channel_info_source` 悬挂行）
**优先级**: P1（修复共用信息源被过度退订导致的频道静默断更；消除热路径 JSON 全表扫）
**所属版本**: v2.6.0（合入 `feat/2.6.0-beta3` 分支）
**模块编码**: 复用 channel 模块现有错误码（190 段，Owner F026），**不新增错误码**（订阅上限沿用 `InformationSourceSubscriptionLimitError` = 19007）
**依赖**: 外部情报服务 `bisheng_information_client`（`/information/subscribe` `/information/unsubscribe`）；Celery 默认 `celery` 队列 + Beat；与 F026-channel-active-authorization 同改 `channel_service.py`，但领域不重叠（F026 拥有频道授权/`space_channel_member` channel 字段写行为，本特性拥有 `channel_info_source` 订阅生命周期写行为，二者解耦）
**契约登记**: 已在 [release-contract.md](../release-contract.md) 表 1（`ChannelInfoSourceSubscription` 领域归属）、表 3（依赖图）、变更历史登记 F031

> **范围边界**
> - **本次纳入**：
>   1. 确立「订阅意图唯一真相 = 租户内所有 `channel.source_list` 的并集」；
>   2. `channel_info_source` 定位为「已订阅集合 + 展示元数据」的物化视图，**行存在 ⟺ 毕昇认定该源已订阅**；
>   3. 订阅判据切到 `channel_info_source` 主键索引查询（取代 `find_channels_by_source_id` 的 JSON 全表扫）；
>   4. 去掉 `dismiss_channel` / `update_channel` 移除源时的**同步退订**；
>   5. 新增**每日对账** Celery Beat 任务：`desired ↔ channel_info_source ↔ 外部情报服务` 三方收敛（退订 + 兜底补订阅 + 删悬挂行）；
>   6. `ChannelInfoSourceRepository` 新增 `delete_by_ids`。
> - **本次明确排除**：
>   - 「事件触发近实时对账」（写操作往待对账队列丢 source_id）—— 延后，先纯每日全量；
>   - 主动查询外部订阅态做反向校正（情报服务无查询接口，能力不存在）；
>   - 前端改动（无 UI 变化，`channel_info_source` 仍按现状用于列表/详情渲染）；
>   - `find_channels_by_source_id` 方法的删除（保留，本特性只是不再在订阅判据里使用它）。

---

## 1. 概述与用户故事

**故事 A（频道使用者 / 创建者）**：
作为 **多个频道复用同一信息源的用户**，
我希望 **删除或编辑其中一个频道时，不会把仍被其它频道使用的信息源一起退订**，
以便 **其它频道不再出现「文章静默断更」。**

**故事 B（频道创建者）**：
作为 **新建频道时选择了已被其它频道订阅过的信息源的用户**，
我希望 **系统不再对已订阅的源重复发起订阅请求**，
以便 **避免冗余的情报服务调用，并让 19007 上限校验只对真正新增的源计数。**

**故事 C（后端 / 运维）**：
作为 **频道模块的维护者与情报服务容量负责人**，
我希望 **订阅判定走索引查询而非 `JSON_CONTAINS` 全表扫，退订与悬挂行清理收敛到每日凌晨一次批量对账**，
以便 **热路径无不可索引的 JSON 扫描；`channel_info_source` 不再无界增长；订阅态有一个每日自愈的兜底。**

---

## 2. 验收标准

> AC-ID 在本特性内唯一，格式 `AC-NN`。
> tasks.md 中的测试任务必须通过 `覆盖 AC: AC-NN` 追溯到此表。

### 2.1 同步订阅（热路径）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-01 | 已登录用户 | `create_channel`，`source_list` 中部分源在 `channel_info_source` 已存在、部分不存在 | 仅对**不存在**的源调用 `subscribe_information_source`（参数恰为缺失源集合，保持入参顺序去重）；已存在的源不调用 |
| AC-02 | 已登录用户 | `create_channel`，全部源在 `channel_info_source` 已存在 | **不调用** `subscribe_information_source`；正常建频道 |
| AC-03 | 已登录用户 | `create_channel`，对新源 `subscribe` 抛 `InformationSourceSubscriptionLimitError`(19007) | 在持久化频道**之前**中止；不产生 channel / membership / OpenFGA owner 元组 |
| AC-04 | 已登录用户 | `update_channel`，`to_add` 中部分源已在 `channel_info_source` | 仅订阅 `to_add` 中缺失的源；已存在的不订阅 |
| AC-05 | 系统 | 订阅成功后 | 对每个新订阅的源，向 `channel_info_source` 插入元数据行（id / name / icon / type / description），主键冲突时幂等跳过 |

### 2.2 退订改由对账驱动（热路径不退订）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-06 | 已登录用户 | `dismiss_channel`（频道含 `source_list`） | **不调用** `unsubscribe_information_source`；不删除 `channel_info_source` 行；仅删频道与关系 |
| AC-07 | 已登录用户 | `update_channel`，`to_remove` 非空 | **不调用** `unsubscribe_information_source`（移除仅改 `channel.source_list`） |
| AC-08 | 共用源场景 | 频道 A、B 都引用源 X；dismiss A | X 仍订阅、`channel_info_source` 中 X 行仍在；B 文章不受影响 |

### 2.3 每日对账（最终一致性兜底）

| ID | 角色 | 操作 | 预期结果 |
|----|------|------|---------|
| AC-09 | 对账任务 | 某源 X 不在任何 `channel.source_list`（`current - desired`） | 调用 `unsubscribe_information_source([X])` 且删除 `channel_info_source` 中 X 行 |
| AC-10 | 对账任务 | 某源 Y 在 `desired` 但不在 `channel_info_source`（漏订阅 / 同步失败残留） | 调用 `subscribe_information_source([Y])`、补元数据、插入行 |
| AC-11 | 对账任务 | `desired == current` | 不产生任何情报服务调用、不增删行 |
| AC-12 | 对账任务（多租户） | 多个活跃租户 | 按租户分别对账，`desired`/`current`/外部 API-key 均在各自租户上下文内收敛，无跨租户串源 |
| AC-13 | 对账任务 | 单源 `unsubscribe` 或 `subscribe` 抛异常 | 记录日志（`logger.exception`），不中断其余源的对账（逐源/分批隔离失败），本轮失败项留待下一轮自愈 |

---

## 3. 边界情况

- **并发建频道引用同一新源**：两请求都查到 `channel_info_source` 无该源 → 都 `subscribe`（外部按集合幂等）→ 都尝试插行，主键冲突时一方幂等跳过。属可接受的 best-effort，一致性由对账兜底，**不引入分布式锁**。
- **同步订阅成功、插行失败（进程崩溃等）**：外部已订阅但本地无行 → 下次对账 `desired - current` 命中 → 幂等重订阅 + 补行，自愈。
- **退订延迟**：源不再被引用后，最长到下一次对账才退订（≤ 1 天），其间多拉文章无害；已与用户确认可接受。**不支持**「立即强制退订」（如有合规需求需另设手动触发，本期延后）。
- **外部情报服务静默丢订阅**：对账只比 `desired vs channel_info_source`，不查外部，无法发现此类漂移（情报服务无查询接口）。缓解：对账对 `desired` 全集做幂等重订阅可选开启（默认关，避免每天全量重订阅压力），**本期默认不开**，记为已知盲区。
- **`source_list` 含重复 id**：订阅判据按 `dict.fromkeys` 去重后处理。
- **不支持**：信息源元数据（name/icon）的实时刷新——`channel_info_source` 行存在即跳过重拉，元数据可能轻微滞后，可接受。

---

## 4. 架构决策

| ID | 决策 | 选项 | 结论 | 理由 |
|----|------|------|------|------|
| AD-01 | 订阅意图的唯一真相 | A: `channel.source_list` 并集 / B: 独立计数列 / C: `channel_info_source` | **A** 为真相，`channel_info_source` 为其物化视图 | 并集即真相，不引入需双写维护的计数列，避免漂移 |
| AD-02 | 订阅判据数据源 | A: `find_channels_by_source_id`(JSON_CONTAINS) / B: `channel_info_source.find_by_ids`(主键索引) | **B** | A 不可索引、N 次全表扫，违反项目 dual-DB「禁 JSON_CONTAINS」规则；B 为 O(1) 索引命中 |
| AD-03 | 订阅 vs 退订时效 | A: 二者皆同步 / B: 订阅同步、退订对账 | **B**（不对称） | 订阅需即时（19007 校验 + 文章时效）；退订不紧急，交对账可同时根治「过度退订」 |
| AD-04 | `channel_info_source` 行生命周期 | A: 创建即插、退订即删 / B: 与外部订阅态同生共死（均由对账在 1→0 时删） | **B** | 让「行存在 ⟺ 外部已订阅」恒成立，消除「立刻退订却留行 → 漏订阅」的旧反例 |
| AD-05 | 对账触发方式 | A: 纯每日全量 / B: 事件触发 + 每日兜底 | **A**（本期） | 满足最终一致诉求，最简；B 延后 |
| AD-06 | 对账失败隔离 | A: 整批事务 / B: 逐源（或分批）隔离 + 下轮自愈 | **B** | 单源外部调用失败不应阻断其余源；对账本就幂等可重入 |

---

## 5. 数据库 & Domain 模型

**不新增表、不改 `channel_info_source` 表结构。** 现有模型见 `channel/domain/models/channel_info_source.py`（含 `tenant_id` 多租户自动隔离，`id` = 信息源 id 主键）。

仅为 `ChannelInfoSourceRepository` 增加删除能力：

```python
# channel/domain/repositories/interfaces/channel_info_source_repository.py
async def delete_by_ids(self, source_ids: List[str]) -> None:
    """Delete metadata rows for the given source ids (reconcile cleanup)."""
```

`channel.source_list`（JSON 列）维持现状，仍作为每个频道引用源的列表与文章过滤依据。

---

## 6. API 契约

**无新增 / 修改的对外 API。** 退订与对账均为内部行为：

- 对账为 **Celery Beat 周期任务**，非 HTTP 入口。
- 沿用错误码 `InformationSourceSubscriptionLimitError`(19007)，无新增错误码、无需在 release-contract 注册新模块编码。

---

## 7. Service 层逻辑

> 对账业务逻辑落在 **domain service**（`channel/domain/services/channel_service.py`），Celery 任务仅作薄包装做租户遍历 + 调用，遵守 `worker → service → repo` 分层、便于脱离 Celery 直接单测。

### 7.1 核心方法

| 方法 | 位置 | 输入 | 输出 | 职责 |
|------|------|------|------|------|
| `create_channel`（改） | `channel_service.py` | CreateDTO + UserPayload | Channel | 用 `channel_info_source.find_by_ids` 求缺失源 → 仅订阅缺失源（持久化前）→ 持久化 → 补元数据行 |
| `update_channel`（改） | `channel_service.py` | UpdateDTO + UserPayload | Channel | `to_add` 仅订阅缺失源；`to_remove` **不退订**（仅改 source_list）；补元数据行 |
| `dismiss_channel`（改） | `channel_service.py` | channel_id + UserPayload | bool | 删频道与关系；**移除对 `unsubscribe_information_source` 的调用** |
| `reconcile_information_subscriptions`（新，**service**） | `channel_service.py` | 当前租户上下文 | 对账统计（to_sub/to_unsub/failed） | 计算 desired=并集(source_list)、current=channel_info_source；`current-desired` 退订+删行；`desired-current` 订阅+补行；逐源隔离失败 |
| `reconcile_all_tenants`（新，**Celery 薄包装**） | `worker/information/reconcile.py` | — | — | Beat 入口：遍历活跃租户、逐租户注入上下文后调用上面的 service 方法；不含业务逻辑 |

### 7.2 对账任务流程（伪流程，不写实现；业务逻辑均在 service 内）

```
# worker/information/reconcile.py（薄包装）
for each active tenant:                     # Beat 注入租户上下文
    ChannelService.reconcile_information_subscriptions()   # ← 业务逻辑全在 service

# channel_service.py::reconcile_information_subscriptions（service，运行在某租户上下文内）
    desired  = union(channel.source_list)   # 一次批量扫 channel 表，内存求并集
    current  = { row.id for row in channel_info_source }   # 索引/全表一次

    to_unsub = current - desired
    to_sub   = desired - current

    for sid in to_unsub (逐源/分批, 失败隔离):
        unsubscribe_information_source([sid]); channel_info_source.delete_by_ids([sid])
    for sid in to_sub  (逐源/分批, 失败隔离):
        subscribe_information_source([sid]); meta = get_information_source_by_ids([sid]); batch_add(...)
    return {to_sub, to_unsub, failed}
```

### 7.3 调用时机总表（落地后）

| 入口 | subscribe | unsubscribe |
|------|-----------|-------------|
| create_channel | 仅缺失源（持久化前，索引判据） | — |
| update_channel 新增源 | 仅缺失源 | — |
| update_channel 移除源 | — | —（交对账） |
| dismiss_channel | — | —（交对账） |
| 成员退订 / 移除成员 | — | —（本就不涉及信息源） |
| **每日对账** | `desired - current` 兜底补订阅 | `current - desired` 退订 |

### 7.4 权限 / 多租户

- 无新增资源授权，不涉及 `PermissionService.authorize()`。
- `channel` / `channel_info_source` 均多租户自动隔离；对账由 Beat 逐租户注入上下文（参考现有 `worker/information/article.py` 的租户处理与默认 `celery` 队列约定）。

---

## 8. 前端设计

无前端改动。`channel_info_source` 继续用于频道列表 / 详情 / 文章结果的源信息渲染，行为不变。

---

## 9. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `src/backend/bisheng/worker/information/reconcile.py` | Celery Beat 薄包装：遍历活跃租户 → 逐租户调 `ChannelService.reconcile_information_subscriptions()`（不含业务逻辑） |
| `src/backend/test/channel/test_channel_source_subscription.py` | 同步订阅判据 + dismiss/update 不退订的单测 |
| `src/backend/test/channel/test_information_subscription_reconcile.py` | 对账 to_sub/to_unsub/失败隔离单测（直接测 service 方法，不经 Celery） |

### 修改

| 文件 | 变更内容 |
|------|---------|
| `channel/domain/services/channel_service.py` | create/update 订阅判据切到 `channel_info_source.find_by_ids`；删除 dismiss、update-移除 的同步 `unsubscribe`；新增 `reconcile_information_subscriptions()` 对账业务方法 |
| `channel/domain/repositories/interfaces/channel_info_source_repository.py` | 新增 `delete_by_ids` 接口 |
| `channel/domain/repositories/implementations/channel_info_source_repository_impl.py` | 实现 `delete_by_ids` |
| `worker/config.py` / Beat 调度 | 注册每日对账周期任务（走默认 `celery` 队列，凌晨低峰，参考 article 同步的 Beat 配置） |
| `test/channel/test_channel_relation_compat.py` | 同步订阅判据从 `find_channels_by_source_id` 改为 `channel_info_source.find_by_ids` 后，更新对应 mock/断言 |

> 注：当前已合入的过渡实现（create_channel 用 `find_channels_by_source_id`）将在本特性中被替换为 AD-02 的索引判据，**且必须与「去掉同步退订 + 上线对账」同一批合入**（三者为一个闭环，单独换判据会在旧退订语义下漏订阅）。

---

## 10. 非功能要求

- **性能**：热路径订阅判定为主键索引查询（取代 JSON 全表扫）；`source_list` 并集的全表扫描每日仅在对账中执行一次，非每写操作 N 次。
- **正确性**：消除「共用源被过度退订」与「已订阅源被重复订阅」；订阅态每日自愈。
- **兼容性**：不改表结构、不改对外 API、不改前端；沿用现有错误码与 Celery 默认队列。
- **可观测**：对账每轮输出 `to_sub` / `to_unsub` 计数与失败明细日志（`logger.exception`），便于排查情报服务调用异常。
- **多租户**：Beat 逐租户对账，注意「任务数 × 租户数」的既有放大坑，安排在凌晨低峰单次执行。

---

## 相关文档

- 版本契约: [features/v2.6.0/release-contract.md](../release-contract.md)
- 审批/频道订阅参考: `.claude/skills/approval-module`（频道订阅审批链路，与本特性的"信息源情报订阅"是两回事，勿混淆）
- 外部情报客户端: `src/backend/bisheng/core/external/bisheng_information_client/client.py`
- 既有文章同步 Beat: `src/backend/bisheng/worker/information/article.py`
