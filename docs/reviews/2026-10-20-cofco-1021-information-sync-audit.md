# COFCO 1021 频道对账与文章同步审计

日期：2026-10-20。

## 比较基线与交付范围

- 目标分支：`feat/cofco-1021-3.0.0-beta1`，修改前提交 `70597f9b4c70aa3e68d54beef611299ddcd12236`。
- 已刷新远端的对比基线：`origin/main`，提交 `4218ba7c138a90764a304681c3d8a5875b2c9c1a`。
- 对账修复来源：main 已包含的 `15a19694dc8f7bc485a420a358381923fb95b8ca` 中，`InformationSubscriptionReconcileService.reconcile` 读取完整远端订阅、计算缺失并最终回读验证的行为。
- 本次是针对该故障的适配移植，不合并 main 整套信息源架构。保留 COFCO 的任务名称、每日对账、租户元数据、文章游标、bootstrap 协议和知识空间投递。
- 本次不部署容器，不触发线上订阅、退订或文章补同步；生产动作仍必须通过部署后的容器代码执行。

## 已修复：本地记录错误代替远端订阅

`ChannelService.reconcile_information_subscriptions` 的现行集合定义：

- `desired`：当前租户全部频道引用的信息源并集。
- `current`：当前租户的本地 `channel_info_source` 元数据行。
- `actual`：客户端 `list_all_subscriptions()` 完整分页读取的、当前配置服务与 API Key 的真实订阅。

补订阅改为 `desired - actual`。本地元数据缺失单独计算 `desired - current`：

1. 本地有 27 行、远端为 0：补订阅 27 个源，不重复插入元数据，不重置三个文章同步游标字段。
2. 远端已订阅、本地无行：只补本地元数据，不重复订阅。
3. 首次远端快照失败或不完整：在任何增删操作之前中止；客户端原有分页完整性校验继续生效。
4. 单源失败隔离；同一源不重复累计失败。最终回读验证缺失订阅和本轮拟退订的孤儿，成功响应但远端未改变也记失败。
5. 最终快照读取失败不返回成功统计，异常交给现有 Worker 隔离与记录。
6. Worker 的 Loguru `%s` 改为 `{}`，让租户和统计值真正出现在日志中。

原 F031 spec 的已知盲区明确建立在“情报服务无订阅查询接口”的旧前提上。现在容器客户端已有 `/information/subscriptions`，继续沿用该前提会在服务地址切换后漏订阅。本修复改变的是这一对账判据，未改变 create/update 热路径的本地主键优化。

实现与回归：

- `src/backend/bisheng/channel/domain/services/channel_service.py::reconcile_information_subscriptions`
- `src/backend/bisheng/worker/information/reconcile.py::_reconcile_one_tenant`
- `src/backend/test/channel/test_information_subscription_reconcile.py`

## 尚存的对账差异

以下为对账链路的静态代码结论，不等同于具体部署已经触发故障。

| 项目 | COFCO（本次修复后） | 最新远端 main | 影响与处理 |
|---|---|---|---|
| 调度与任务入口 | `reconcile_all_tenants`，默认每日 04:30 | 每小时调度 `dispatch_information_subscription_reconcile`，再延迟 0–600 秒执行 `reconcile_information_subscriptions` | COFCO 恢复延迟可达一天；保留既有时效约定 |
| 期望订阅范围 | 逐租户读取、逐租户补订阅 | 收集所有活跃租户引用并集后执行一次远端对账 | COFCO 重复读取远端；共享配置时应以平台并集判断最终退订 |
| 多租户退订保护 | 本地孤儿 `current - desired` 驱动退订；没有其他租户引用守卫 | 退订前重新收集平台期望集合和远端快照；不完整则不退订 | **P1 待对齐**：A 租户的孤儿 X 仍被 B 引用时，A 可先退订 X；B 后续补订阅前存在误退订窗口，若 B 失败则继续受影响。`Config` 无租户列，`information_conf` 为全局配置，不能假定各租户使用不同 API Key |
| 远端独有孤儿 | 没有本地行的远端额外订阅不会被清理 | 可清理 `actual - platform_desired` | COFCO 可能长期留下远端孤儿；不能直接把 main 的全量删除放入逐租户循环，否则会误删其他租户订阅 |
| 并发与锁 | 对账无平台 Redis 锁，也不在退订前二次读取期望集合 | `information:subscription-reconcile` 令牌锁；刷新与所有权检查；二次快照 | **P1 待对齐**：多 Beat、手动重入或频道并发修改存在重复操作、使用旧引用集合退订的风险；本文未以一次订阅修复引入整个调度重构 |
| 活跃租户枚举 | Root + 直接活跃子租户 | `TenantDao.aget_active_ids()` 枚举所有活跃租户 | **P1（存在多级租户时）**：COFCO 对账和文章同步均可能漏掉更深层活跃租户；本次未修改租户拓扑语义 |
| 开关与元数据 | 无自动退订开关；只补缺失元数据，已有 name/icon 不刷新 | 有 `information_subscription_auto_unsubscribe_enabled`，并按最终快照 upsert 元数据 | 保留 COFCO 元数据行和行内游标；未引入 main 的整套配置/更新策略 |
| 可观测结果 | 保持 `{to_sub, to_unsub, failed}` 和逐租户日志；补订阅数为尝试数，失败见 `failed` | `converged/drift/unknown`、剩余差集、BS_METRIC | 返回结构保持兼容；不能只看 Celery `succeeded` 判断业务已收敛 |

代码依据：目标 `worker/information/reconcile.py`、`channel_service.py`、`common/models/config.py`、`database/models/tenant.py`；main 同路径及新增的 `channel/domain/services/information_subscription_reconcile_service.py`。

## 文章同步差异

| 项目 | COFCO | 最新远端 main | 判断 |
|---|---|---|---|
| 任务与频率 | `sync_information_article`，默认每半小时，另有每日 05:30 同任务 | `dispatch_information_article_poll` 每 1800 秒，加 0–600 秒随机延迟 | COFCO 05:30 有两次调度，存在重复读和运行开销；保留入口兼容 |
| 来源与租户 | 逐租户读本地源，再匹配远端订阅 | 按完整远端订阅每源拉取一次，再路由各租户 | COFCO 必须有本地元数据才处理，远端独有源不拉取；同一源可能多租户重复调度 |
| 状态存储 | 三个游标在 `channel_info_source`，沿用 `cofco_923_information_cursor` 迁移 | 独立全局 `information_article_sync_state`，以 `source_id` 为键 | 不能整文件覆盖 Repository/模型；本次不改数据库结构 |
| 首次取数 | `/information/articles/{id}/bootstrap`，默认 36 篇，按该接口的最新发布时间契约选取 | 普通 articles 第一页，默认 20 篇；用这页最小 `create_time` 建边界，再扫描 | **有意保留 COFCO**：首次集合、条数和排序口径均不同，覆盖会改变现有产品行为 |
| 增量快照 | 首次响应提供 `snapshot_max_create_time`；后续页面传固定 `max_create_time`，校验快照一致 | 不传固定上界；游标来自已返回文章的最大 `create_time` | **保留 COFCO 的固定快照保护**：远端持续写入时，main 更容易遇到总数/分页变化并失败重试 |
| 未初始化游标 | 游标为空时仍走 bootstrap；成功写入且持锁、CAS 成功后才提交初始水位 | `_ensure_initial_boundary` 单独建边界，再执行分页 | 不互换初始化流程，避免部分写失败时提前承认已完成初始同步 |
| 展示时间 | 写入文章或收集到新文章 ID 后更新当前租户频道 | 写入文章后遍历活跃租户更新关联频道 | COFCO 保留当前更新与投递顺序 |
| 知识空间投递 | 同一任务内收集新 ID，调用 `_sync_new_articles_to_knowledge_spaces`；批量请求，`skip_missing_and_duplicates=True`，随后 touch 配置更新时间 | 独立 route/delivery Celery 任务；校验 header/payload/context 租户；按配置生效时间筛选，逐文章请求，`skip_missing_and_duplicates=False`，分类记录失败 | **行为不同，不能视为同一实现**：COFCO 缺少 main 的配置生效时间边界和独立投递任务/失败分类；保留现有去重、过滤及定制投递 |
| 配置项 | 初始条数与业务时区 | 另有投递开关、抖动、自动退订开关和时区校验 | 不引入新顶层 YAML 配置，避免旧版本启动兼容问题 |
| 动态服务配置 | 每次请求从配置回调读取 URL/Key，走现有配置缓存 | 同样的配置回调机制 | 一致；本次不增加进程内固定地址缓存 |

已核对一致的关键保护：远端 `last_sync_at` 必须为业务时区当天；水位未变跳过；只有远端同步时间变化而文章列表水位不变时只记录检查；增量 `min_create_time` 包含边界；ES 只对原先不存在且写入成功的 ID 发出新文章通知；部分写失败、锁丢失或 CAS 冲突不提交完成游标。ES 写入服务在这两个基线间无差异。

没有把 main 的普通首屏算法、独立状态表或异步知识投递覆盖到 COFCO，也未回退 COFCO 已有 bootstrap、分页上界、字符串布尔参数和定制投递。

## 验证与证据边界

- 改动前同一离线配置下，核心对账/文章链路：37 passed。
- 改动后的扩大回归：**86 passed**。覆盖信息客户端、完整分页、订阅切换、首次/增量文章同步、ES 写入、Redis 锁、租户遍历、频道创建与更新、COFCO 定制守卫。
- 使用 SQLite/Mock 和仅指向本机不可用端口的临时测试配置，不使用生产中间件；Docker 示例 YAML 缺少 `!env` 变量的环境问题已通过独立离线配置避开，未修改实际配置。
- Ruff check、Ruff format check、改动 Python 文件的架构守卫、`git diff --check` 均通过；本次没有 schema、权限模型或前端变更。
- 不把测试成功视为 DM8/生产运行验证；重新构建并部署后仍需通过容器中的原任务检查实际订阅差集与每源文章同步状态。

## 变更审查

按仓库 code-review 七个维度审查本次补丁：边界、权限认证、并发、信息泄漏、测试、风格、文档。补丁范围内未发现阻断项；并发与多租户的已有架构差异见上表，未宣称已与 main 全量对齐。

发布只包含两个运行时代码文件、对账回归测试和本文。文章 Worker、文章 Service、状态 Repository/模型、Docker YAML 均与修改前目标分支一致；主工作区的其他工作未纳入提交。
