# COFCO-1021 信息源对账、文章拉取与知识空间投递对齐方案

日期：2026-10-20。状态：定向代码同步及本地回归完成，代码、测试与本文一并交付；尚未部署，真实依赖验收待执行。

## 1. 基线和交付边界

| 项目 | 固定版本 |
|---|---|
| 来源分支 | `feat/3.0.0` |
| 来源提交 | `1ae1d9e6b6b4d1eec7ade44a845c6d1b40e7b163` |
| 来源前序基线 | `52794c664448f6d31494b48e3abead621773d599` |
| 目标分支 | `feat/cofco-1021-3.0.0-beta1` |
| 目标修改前提交 | `70220b0e92276d3d2b71fe0303b478985698dbe8` |
| 目标 worktree | `/Users/zhangguoqing/works/bisheng/.worktrees/feat-cofco-1021-3.0.0-beta1` |

来源提交已修复并推送两处 HTTP 客户端问题：订阅查询请求使用 `page_size`，响应继续解析 `PageSize`；同步和异步文章查询统一将 `return_information` 编码为字符串 `false/true`。目标分支原本已具有这两处修复，此次只同步其新增回归验证。

本次承接来源分支已确认的 F060 行为，采用按模块和方法的定向同步，不合并整个 `feat/3.0.0`。来源 F060 的 spec/design/tasks 曾分别确认；其旧文档仍含独立状态表、首次 20 篇等历史描述，本方案以固定提交的实际代码为准：状态在 `channel_info_source`，首次调用 bootstrap 默认 36 篇。

本文替代此前“相对 origin/main”的审计结论在本次对齐中的用途。`origin/main` 不是本次来源；旧审计文件保留为历史记录。

## 2. 当前差异与本次结果

| 能力 | 目标修改前 | 对齐后的行为 |
|---|---|---|
| 订阅期望集合 | 每个租户单独对账；租户目录清理与退订绑定 | 汇总所有层级活跃租户的频道引用并集 |
| 实际订阅集合 | 70220b0 已修复为完整远端快照 | 继续读远端完整快照，增加全平台锁与取消前二次快照 |
| 频道创建/编辑 | 本地目录没有的来源立即同步订阅 | 只保存期望来源、尽力更新展示元数据，由周期对账订阅 |
| 公共来源目录 | 自动按租户过滤，孤儿目录随对账删除 | 目录和游标公共；退订不删除元数据，不重置游标 |
| 文章任务 | 按 root 和直接子租户重复处理来源 | 完整远端订阅列表逐来源处理，每轮同来源最多一次 |
| 展示时间 | 旧租户文章任务内刷新 | 公共文章成功写入后，逐活跃租户刷新相关频道 |
| 知识投递 | 拉取任务内按租户批量调用旧 hook | 独立路由任务、独立配置投递任务，校验租户上下文 |
| 调度 | 每日 04:30 对账；每 30 分钟和每日 05:30 拉取 | 对账 3600 秒、拉取 1800 秒，各加 0～600 秒随机延迟 |

原有文章同步算法已经与来源相同，本次保留：`InformationArticleSyncService`、状态 Repository、`ChannelInfoSource` 列结构、ES 写入服务、Redis token 锁实现。没有新增表、列或 Alembic revision。

## 3. 订阅对账流程

1. Beat 发布 `dispatch_information_subscription_reconcile`，dispatcher 通过 countdown 发布实际任务。
2. `reconcile_information_subscriptions` 获取平台 token 锁 `information:subscription-reconcile`；锁不可确认时不执行远端变更。
3. 单租户读取默认租户；多租户通过 `TenantDao.aget_active_ids()` 获取全部活跃租户，为每个租户设置并恢复 ContextVar，读取 `channel.source_list` 并集 `desired`。
4. 任一租户或租户枚举失败，标记期望快照不完整，本轮不修改远端。远端完整分页失败、重复 ID、总数变化等也不使用局部集合写入。
5. 对 `desired - actual_before` 逐来源补订阅；单项失败隔离，其余继续。27 个期望来源、远端 0 条时会产生 27 次单来源订阅调用，本地已有元数据不影响该差集。
6. 自动退订开启时，重新读取全部租户并集和完整远端快照，再对远端多余项逐来源取消。二次读取任一失败均不取消。每次远端变更前检查续租。
7. 最后完整回读，输出 `remaining_missing/remaining_extra` 和 `converged/drift/unknown` 等状态；最终回读失败不能声称收敛。元数据 upsert 只更新名称、图标、类型、描述，保留三个游标字段。

公共目录纳入 tenant filter 排除表，并从租户卸载迁移清单中移除。频道、成员、知识空间仍按原来的租户和 F048 权限链读取；公共来源可见不代表其他租户频道或知识文件可见。

部署前须确认 Information API Key 为本部署独占。此设计会取消该 Key 下不在本平台活跃频道并集中的订阅，不支持其他部署或人工流程共用 Key 维护独立订阅。

## 4. 文章拉取与投递

### 4.1 公共文章同步

`dispatch_information_article_poll → sync_information_articles → 完整 subscriptions → 每来源 token 锁 → InformationArticleSyncService`。

- `last_sync_at` 属于配置业务时区的当天才拉取；提前轮询不会把当天永久标记完成。
- 首次使用 `/information/articles/{id}/bootstrap?limit=36`，按上游 bootstrap 协议选择文章，以返回的 `snapshot_max_create_time` 保存游标。
- 增量使用包含边界的 `min_create_time`，一次分页固定快照上界；相同创建秒的文章通过稳定 ID 幂等写入。
- 仅完整分页、完整写入、持锁且 CAS 成功时提交状态；失败不得用 ES 最大时间推进游标。
- 公共新增候选为写前不存在且当前 bulk 明确成功的 ID；部分成功的新增可投递，但公共游标不推进。
- 每来源 `written > 0` 才刷新频道展示时间。服务返回失败时 written 可能为 0，部分成功文章可已入 ES，而展示时间暂未刷新；本次保留来源行为，不承诺失败轮实时更新展示时间。

### 4.2 知识空间投递

`公共新增 ID → route_new_information_articles → 逐租户匹配频道/配置/子频道规则 → deliver_information_articles_to_config`。

配置查询先使用当前租户可见的频道 ID；按配置 ID 回读后再验证所属频道。配置模型本身没有租户隔离字段，不能仅凭配置 ID 信任其归属。

投递任务必须满足 payload、header、当前 ContextVar 三个 tenant_id 相同。使用配置创建人的 `UserPayload(user_id, tenant_id)` 进入目标分支既有 `add_articles_to_knowledge_space`，不使用管理员或系统账号绕过权限。

配置启用且 `max(create_time, update_time) <= detected_at` 才参与投递；保留主/子频道筛选、目标空间和目录。逐篇调用，设置 `skip_missing_and_duplicates=False`，分别记录重名、目标缺失、权限、敏感内容、配额和系统失败；不再把一批文章中的失败隐去。

成功投递不再调用旧 `touch_update_time`。新流程中的 update_time 是配置生效边界，不能同时当最后成功投递时间使用。

采用 F060 既有“一次尽力尝试”契约：没有 outbox、持久投递账本、自动重试或历史补投。ES 写入与消息发送间崩溃、路由发布失败等可能漏投；任务重放仍可能触发重复尝试，由原知识业务约束处理。本次不新增补偿脚本或后台历史回补。

## 5. 改动影响范围

下列路径均相对 `src/backend/bisheng/`，测试位于 `src/backend/test/channel/`。

| 文件/模块 | 实际改动及影响 |
|---|---|
| `channel/domain/services/information_subscription_reconcile_service.py`（新增） | 平台集合差、二次快照、逐来源收敛和指标 |
| `channel/domain/services/information_knowledge_delivery_service.py`（新增） | 按频道配置路由、筛选、真实身份逐篇投递及失败分类 |
| `worker/information/reconcile.py` | 替换每日逐租户入口为 dispatcher 和平台执行任务 |
| `worker/information/article.py` | 公共来源轮询、按来源锁、独立知识路由与跨租户展示刷新 |
| `worker/information/knowledge_delivery.py`（新增） | 路由/投递任务、租户上下文与 payload 校验 |
| `worker/__init__.py` | 注册六个新 Information 任务，保留其他全部 COFCO 注册；显式 re-export |
| `channel/domain/services/channel_service.py` | 仅改信息源元数据 helper、删除旧对账、移除 create/update 同步订阅与一小时后单源任务；保留权限/邀请/公开阅读等目标实现 |
| `channel/domain/repositories/{interfaces,implementations}/channel_info_source_repository*` | 公共元数据幂等 upsert，不删除对账孤儿目录、不覆盖游标 |
| `channel/domain/repositories/{interfaces,implementations}/channel_repository*` | 规范化来源引用、增加当前租户按来源找频道 |
| `channel/domain/repositories/{interfaces,implementations}/channel_knowledge_sync_repository*`（新增） | 只读配置查询，归属校验由服务完成 |
| `channel/domain/models/channel_knowledge_sync.py` | 更新 worker 职责说明；表结构不变 |
| `core/database/tenant_filter.py` | 只加入 `channel_info_source` 公共例外；保留 E+ 等 COFCO 模型发现项 |
| `tenant/domain/services/tenant_mount_service.py` | 只移除公共来源目录的卸载迁移项 |
| `core/config/settings.py` | 只修改 Information 周期、旧任务清理、3 个开关/延迟默认值和时区校验 |
| `initdb_config.yaml` | 在既有 information_conf 内增加3个默认项；不覆盖部署 base_url/api_key |
| 测试 | 同步来源 Service/Worker/Repository/组合链路测试，更新旧任务接口断言，保留 COFCO 游标/迁移测试并增加 27→0 回归 |

### 5.1 用户可感知的变化

- 创建或编辑频道成功表示本地期望已保存，远端订阅是周期最终一致。角色/租户来源配额仍在保存前校验；新增来源额度仍计入频道创建人，不能用编辑人的额度代替。
- 远端 Key 额度、认证、网络错误不再在频道保存时同步阻断，而在后台对账暴露缺口。理想调度条件下，下次订阅检查可等待约 60+10 分钟；后续文章轮询约 30+10 分钟。排队、重试或上游未完成时没有该时限保证。
- 共享来源不因某一个租户删频道而退订；所有活跃租户都无引用才进入全平台多余集合。
- 知识投递延迟和公共文章入库分离。新建/修改/重新启用配置不会自动导入已在 ES 中的历史文章；关闭开关期间文章也不补投。
- 同目录重名等失败由真实业务错误记录，不等同于入库成功；已有知识文件不删除、不重建。

### 5.2 保留的目标行为与数据

不修改前端、HTTP 路径/请求响应结构、频道公开阅读、成员/邀请/初始授权、审批、E+、OpenFGA 模型、知识文件创建审批和中粮配置。`channel/api/dependencies.py` 里的 COFCO `PersonalGrantInviteGate` 保留。

来源配额仍由 `QuotaService._distinct_info_source_ids` 对用户/租户频道引用求并集，不从公共元数据行数计量。来源列表/搜索仍调用既有 Information 客户端。

不新增独立 `information_article_sync_state` 表，不改 `cofco_923_information_cursor` 及后续迁移，不清空 ES、不重置游标、不删除旧知识文件。不复制来源 settings、租户模型发现清单或 ChannelService 的其他差异。

## 6. 验收与已执行验证

| 验收项 | 验证路径/状态 |
|---|---|
| AC-A01：本地27、远端0能补27，重跑幂等且游标保留 | `test_information_infrastructure_integration.py::test_service_switch_resubscribes_27_existing_sources_without_resetting_cursors`，已通过 |
| AC-A02：全层级活跃租户并集、上下文恢复、失败隔离 | reconcile worker / tenant display tests，已通过 |
| AC-A03：不完整快照不退订，最终未知不得报收敛，锁失效停止 | subscription reconcile / Redis lock tests，已通过 |
| AC-A04：频道保存无远端订阅副作用，本地配额与权限保持 | source subscription / quota / unified permission / COFCO tests，已通过 |
| AC-A05：晚到上游、36篇bootstrap、固定快照增量、部分失败不推进、CAS | 原文章同步及适配后的 backport tests，已通过 |
| AC-A06：知识任务租户校验、主子频道筛选、生效时间及真实错误 | knowledge worker/routing/delivery tests，已通过 |
| AC-A07：只剩两个周期dispatcher，旧日/半小时任务被清理，无专用队列 | registration / infrastructure tests，已通过 |
| AC-A08：真实 Information/Redis/ES/MinIO/Celery、多租户普通用户与 DM8 | 尚未执行，发布前隔离环境验收 |

本地验证使用共享 Python 3.11 venv，PYTHONPATH 指向目标 worktree；离线配置及 fake/SQLite 验证不等同真实依赖 E2E。

执行范围：`test/channel`、`test/quota/test_info_source_subscribe_count.py`、`test/cofco`、`test/tenant/test_tenant_filter.py`、`test/tenant/test_tenant_unmount_service_transaction.py`、`test/tenant/test_tenant_unmount_dialect_compat.py`，231 项通过（后续新增测试按最终记录更新）。

额外执行 `test/tenant/test_tenant_mount_service.py` 时，3项会触及未隔离的 DB 连接，在当前 sqlite:// 离线配置下因连接池参数不兼容而失败；加载修改前 HEAD 的 TenantMountService 原代码执行同3项，也复现相同失败。未将其当成本次回归，也未为让其通过修改无关挂载逻辑。

Alembic 静态脚本检查为单 head `f076_subject_id_search_indexes`。不代表已连接生产 DM8 执行迁移。

## 7. 发布和回滚

本次未操作生产服务。发布须由容器内当前版本的 Celery 入口触发，不使用额外修复脚本或直接手工订阅。

1. 保存正式服务地址与密钥配置，核对 Key 独占、活跃租户期望并集、远端订阅、现有游标、Beat 配置及 worker 注册任务；记录快照但不在文档输出密钥。
2. 停止旧 Beat 继续发布旧任务，用旧 worker 排完 active/reserved/scheduled 的旧 Information 消息；注意旧频道编辑曾发布一小时 ETA 单来源任务。不能直接 purge 共享队列。
3. API 和全部默认 worker 切到同一新版本，再启动新 Beat；各节点使用同一 Redis/DB/ES。新代码不注册旧 `sync_information_article` 和 `reconcile_all_tenants`，混部时旧消息会报未注册，故旧消息排空是切换前置条件。
4. 新版本 `CeleryConf` 会移除指向旧 Information 任务的配置项，保留其他定制任务；持久 Beat 状态也要核对最终只有两条 Information dispatcher 周期。只保持一个负责该环境的 Beat。
5. 先在新容器内调用既有任务：`celery -A bisheng.worker.main call bisheng.worker.information.reconcile.reconcile_information_subscriptions`。回读确认 desired/actual/drift，不以消息入队或 Celery SUCCESS 替代27条订阅事实。
6. 再调用 `bisheng.worker.information.article.sync_information_articles`，逐来源核对上游当天就绪时间、终态、数据库游标、ES ID/数量；核对知识配置任务及真实知识文件状态。
7. 自动退订默认 true；若灰度阶段配置为 false，只补齐并报告 extra，完成 Key 归属核对后恢复。知识投递开关默认 true；关闭时不发任务，重新开启不补投历史。
8. 回滚先停止新 Beat，排完新路由和投递消息，再统一回退 API/worker/Beat。保留现有数据和游标。旧版本恢复租户过滤会使公共目录按历史 tenant_id 不可见，旧逐租户清理也存在跨租户误退订风险；不能只切旧镜像后宣称业务语义完全恢复，应暂停旧对账并核验期望/远端集合。

## 8. 代码审查与证据边界

按仓库 sdd-code-review 的边界、权限、并发、泄漏、覆盖、风格、文档7个维度自查：此次新增算法直接取固定来源；频道和租户公共文件逐块改；无新增凭据、对外错误码、权限旁路或数据重建。公共作用域与知识一次投递语义记录于本文。

真实环境 E2E 状态为 PARTIAL：未使用生产 Key 做测试，未声明线上27条已完成订阅，也未声明文章/知识文件已在生产同步完成。

最终静态核对：10个核心服务、worker、游标与锁文件与固定来源提交逐字一致；ChannelService、settings、tenant filter 和 worker 注册按目标分支做局部适配。`git diff --check` 通过；架构守卫无新增 VIOLATION，settings 的历史常量触发既有 RULE-7 warning。所触及 Python 文件的 Ruff 诊断由基线65项降至47项，无新增诊断；剩余均在目标分支已有的模型、租户挂载和任务注册代码中，未将其描述为全文件 lint 通过。

交付自查：边界、权限、并发、信息泄漏、回归覆盖和文档一致性通过本地检查；风格按基线差异检查通过。真实依赖 E2E、DM8、多节点和部署切换验证仍按 AC-A08 执行，未以本地检查替代。
