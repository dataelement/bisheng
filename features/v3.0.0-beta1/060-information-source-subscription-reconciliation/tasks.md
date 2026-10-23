# Tasks: 信息源订阅对账、公共文章同步与知识空间一次投递

**关联规格**: [spec.md](./spec.md)

**关联设计**: [design.md](./design.md)

**版本**: v3.0.0-beta1 / F060

---

## 状态

| 步骤 | 状态 | 备注 |
|---|---|---|
| spec.md | ✅ 已评审 | 2026-08-21 用户确认；37 条 AC。 |
| design.md | ✅ 已评审 | 2026-08-25 用户确认；Constitution Check C1～C8 PASS。 |
| tasks.md | ✅ 已确认 | 2026-08-26 用户确认进入开发；43 项。 |
| 实现 | 🟡 本地完成，外部验证待执行 | 42 / 43 完成；T042 真实依赖 E2E、DM8 与多节点验证待测试环境。 |

---

## 开发模式与共同约束

- **Test-First**：每个后端业务实现任务均依赖对应红测；基础配置、ORM/Repository 声明按 SDD 规则作为基础设施先落，后续由 Wave 6 集成测试验证。
- **任务原子化**：单任务最多修改 1～2 个文件；同一文件的多次任务是按能力增量扩展，后续不得覆盖前序已通过行为。
- **纯后端**：无新 HTTP API、无 Platform/Client 前端、无新业务错误码；相关“不改”契约由测试锁定，不创建空前端任务。
- **租户传递**：平台级任务自身不代表某个租户，显式枚举活跃租户并逐个设置/恢复 ContextVar；路由任务在目标 tenant Context 中发布单配置任务，由既有 `before_task_publish` 写入 Celery `tenant_id` header，Worker 的 `task_prerun` 在任务体前恢复 ContextVar。消息参数中的 `tenant_id` 只用于校验与可观测，必须与 header 恢复值一致。
- **失败边界**：订阅/文章依靠后续周期重试；知识投递任务不调用 `retry()`、不配置 `autoretry_for`、不建立 delivery/outbox。任何偏离须先更新 Design 再经过确认。
- **队列边界**：不新增 Information 专用队列或专用 Worker，不修改 `task_routes`；六个 Information 任务均使用默认 `celery` queue。文件被知识空间接受后的既有解析/向量化任务继续使用原有 `knowledge_celery`，不计入本 Feature 的新增任务。
- **双数据库/多节点**：不写 MySQL 专属 JSON SQL，不用节点本地文件做共享状态；DM8 在中央回归执行，本地测试不得伪称完成 DM8 验证。

---

## Wave 1：基础设施与外部契约

### 基础配置、模型与 Repository（无 Test-First 配对）

- [x] **T001**: Information 类型化配置与 Dispatcher 默认周期
  **文件**:
  - `src/backend/bisheng/core/config/settings.py`
  - `src/backend/bisheng/initdb_config.yaml`
  **逻辑**: 在 `IntelligenceCenterConf` 增加并校验 `information_initial_article_limit=20`（1～100）、`information_sync_jitter_seconds=600`（非负）、`information_subscription_auto_unsubscribe_enabled=true`、`information_knowledge_delivery_enabled=true`、`information_business_timezone=Asia/Shanghai`。用 3600 秒订阅 Dispatcher 和 1800 秒文章 Dispatcher 替换旧每日/半小时直执任务默认项；保留既有自定义 `celery_task.beat_schedule` 覆盖能力，配置 backfill 不覆盖运维值。
  **回滚**: 回滚应用时保留 DB 中新增 YAML key（旧版本忽略）；恢复旧 Beat 项前必须停掉新 Dispatcher，禁止两套算法并行。
  **覆盖 AC**: AC-06, AC-10, AC-20, AC-22, AC-32
  **依赖**: 无

- [x] **T002**: 公共文章同步状态 SQLModel
  **文件**: `src/backend/bisheng/channel/domain/models/information_article_sync_state.py`
  **逻辑**: 新增 `InformationArticleSyncState(table=True)`：`source_id CHAR(36)` 主键，三个 nullable `BIGINT` 字段 `article_cursor_create_time/processed_remote_sync_at/processed_article_list_updated_at`，以及双数据库兼容的 `create_time/update_time`。不含 `tenant_id`、API Key、任务或知识投递字段；文件位于自动模型发现目录。
  **回滚**: 独立新表由 `create_all(checkfirst=True)` 创建，不新增 Alembic revision；应用回滚保留表和进度，后续重装可复用，物理删表需另行 DBA 评审。
  **覆盖 AC**: AC-13, AC-16, AC-17, AC-18, AC-20, AC-21, AC-35
  **依赖**: 无

- [x] **T003**: 公共状态 Repository 接口与实现
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/information_article_sync_state_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/information_article_sync_state_repository_impl.py`
  **逻辑**: 定义 `find_by_source_id(source_id)`、`create_initial_boundary_if_absent(source_id, cursor)`（主键冲突后回读胜者）、`commit_if_unchanged(source_id, expected_state, next_cursor, remote_sync_at, article_list_updated_at)`。提交方法使用短事务与 `SELECT ... FOR UPDATE`/旧值比较，冲突返回 false，不覆盖更新者；所有 SQL 位于 Repository。
  **接口产出**: `InformationArticleSyncService` 只依赖该接口，不直接持有 Session。
  **覆盖 AC**: AC-16, AC-17, AC-18, AC-20, AC-21, AC-35
  **依赖**: T002

- [x] **T004**: `channel_info_source` 公共目录兼容语义
  **文件**:
  - `src/backend/bisheng/core/database/tenant_filter.py`
  - `src/backend/bisheng/tenant/domain/services/tenant_mount_service.py`
  **逻辑**: 将 `channel_info_source` 加入 tenant filter 的显式全局排除集合，并从租户卸载迁移表清单移除；保留 ORM `tenant_id` 兼容列和存量值，不做数据迁移。注释说明仅移除强制导入项不能阻止 metadata 自动发现。
  **跨 Feature 影响**: F060 已在 v3 release-contract 接管 `ChannelInfoSource` 生命周期；仅改变该表读取/卸载语义，不改变 `channel`、知识或其他租户表。
  **回滚**: 恢复过滤会让公共目录再次按历史 tenant 值不可见，不建议数据层回滚；应用回滚需与旧 F031 任务同时评估。
  **覆盖 AC**: AC-35, AC-37
  **依赖**: 无

- [x] **T005**: 当前租户频道来源读取能力
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/channel_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/channel_repository_impl.py`
  **逻辑**: 保留 `find_all_referenced_source_ids()` 并新增 `find_channels_referencing_source(source_id)`；两者只读取当前 tenant Context 可见的 `channel/source_list`，在 Python 规范化、去空、去重/筛选，不新增 JSON_EXTRACT/JSON_CONTAINS。后者供知识路由与频道展示时间更新使用。
  **接口产出**: 平台 Worker 逐租户调用并自行判断快照是否完整。
  **覆盖 AC**: AC-01, AC-03, AC-24, AC-35
  **依赖**: 无

- [x] **T006**: 公共来源元数据幂等 Repository
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/channel_info_source_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/channel_info_source_repository_impl.py`
  **逻辑**: 将现有 `find_by_ids/find_all/batch_add` 明确为公共目录语义；新增 `upsert_metadata(sources)`，按外部 `id` 幂等插入/更新名称、图标、类型和描述，主键冲突回读后更新。不得以行存在推断远端订阅，不再提供对账删除公共元数据的调用路径。
  **跨 Feature 影响**: 频道详情继续消费同一模型；不改 HTTP schema。
  **覆盖 AC**: AC-09, AC-36, AC-37
  **依赖**: T004

- [x] **T007**: 知识同步配置只读 Repository
  **文件**:
  - `src/backend/bisheng/channel/domain/repositories/interfaces/channel_knowledge_sync_repository.py`
  - `src/backend/bisheng/channel/domain/repositories/implementations/channel_knowledge_sync_repository_impl.py`
  **逻辑**: 定义 `find_enabled_by_channel_ids(channel_ids)` 和 `find_by_id(sync_config_id)`。配置表没有 `tenant_id`，因此接口只接受已在当前 tenant Context 验证过的 channel IDs；按 ID 回读后调用方还必须通过当前租户 `ChannelRepository.find_by_id(config.channel_id)` 验证归属。不得新增 DAO 入口或写入投递状态。
  **接口产出**: `InformationKnowledgeDeliveryService` 的配置读取协议。
  **覆盖 AC**: AC-24, AC-31, AC-35
  **依赖**: 无

- [x] **T008**: Information 同步响应模型
  **文件**: `src/backend/bisheng/core/external/bisheng_information_client/response_schema.py`
  **逻辑**: 增加订阅项与分页响应模型，显式解析 `id/source_id/business_type/name/description/icon/original_url/follow_num/subscribed_at/last_sync_at/article_list_updated_at` 和 `currentPage/PageSize/totalCount`；时间为 Unix 秒、可空字段保持可空。文章响应模型继续保留稳定 `article.id`。
  **覆盖 AC**: AC-04, AC-09, AC-11, AC-12, AC-13, AC-14
  **依赖**: 无

### 外部 Client（Test-First）

- [x] **T009**: Information Client 完整分页与逐来源调用测试（红）
  **文件**: `src/backend/test/channel/test_information_sync_client.py`
  **测试上下文**: mock `AsyncHttpClient`，同时构造 HTTP 非 200、HTTP 200 + 业务 code 非 200、分页 total 变化、重复 ID、换 Key 后空 actual、文章异步分页等响应；断言异常中不含 API Key。
  **用例**:
  - 完整 `/subscriptions` 多页返回唯一 ID 集；任一页失败、重复 ID、`totalCount` 不一致或最终数量不等时整体失败。
  - `subscribe_one/unsubscribe_one` 每次 body 只有一个 `information_ids` 元素。
  - Client 每次请求动态读取当前配置，新 Key 不复用旧 Key actual。
  - 异步文章请求保留 `min_create_time/page/page_size` 并同时检查 HTTP/body code。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-08, AC-09, AC-11, AC-14, AC-34
  **依赖**: T008

- [x] **T010**: Information Client 同步查询能力实现（绿）
  **文件**: `src/backend/bisheng/core/external/bisheng_information_client/client.py`
  **逻辑**: 实现 `list_all_subscriptions(page_size=100)`、`subscribe_one(source_id)`、`unsubscribe_one(source_id)` 与 async `get_information_articles_page(...)`。完整分页冻结首个 total，校验页码、各页 total、ID 唯一与最终数量；请求始终从动态 `conf` 取 Key但绝不记录。保留现有公开 Client 方法兼容，频道业务不再调用批量订阅。
  **测试**: T009 全部通过。
  **覆盖 AC**: AC-04, AC-05, AC-06, AC-08, AC-09, AC-11, AC-14, AC-34
  **依赖**: T009

### Redis token 锁（Test-First）

- [x] **T011**: Information Redis 锁测试（红）
  **文件**: `src/backend/test/channel/test_information_redis_lock.py`
  **测试上下文**: fake Redis connection；模拟 NX 获取成功/失败、token 不匹配、续租失败、Redis 异常和超时所有权丢失。
  **用例**: 只有持有 token 才能 Lua 续租/释放；Redis 不可用返回“不可确认”而不是无锁继续；上下文退出不删除其他执行者的新 token。
  **覆盖 AC**: AC-19, AC-35
  **依赖**: 无

- [x] **T012**: Information Redis 锁实现（绿）
  **文件**: `src/backend/bisheng/worker/information/redis_lock.py`
  **逻辑**: 提供 token + TTL + Lua compare-refresh/release 的小型同步锁封装，支持平台 key `information:subscription-reconcile` 和来源 key `information:article-sync:{source_id}`。不得用本地文件/进程锁作为回退；调用方在续租失败后停止后续写入。
  **测试**: T011 全部通过。
  **覆盖 AC**: AC-19, AC-35
  **依赖**: T011

---

## Wave 2：平台订阅对账与频道契约

- [x] **T013**: 平台订阅对账 Service 测试（红）
  **文件**: `src/backend/test/channel/test_information_subscription_reconcile.py`（将 F031 旧“租户目录即 actual”断言改写为平台远端 actual 契约）
  **测试上下文**: 直接测试 Service，注入完整/不完整 `desired` 快照、fake Client、公共元数据 Repository 和指标 spy；不经 Celery。
  **用例**:
  - 全租户并集与 remote actual 计算 missing/extra；本地或远端不完整时远端写调用为零。
  - 稳定顺序逐个 subscribe/unsubscribe，单项失败继续，默认自动退订 true；关闭时只补订阅并报告 extra。
  - 自动退订前使用第二份完整 desired/actual；第二份失败时不取消。
  - 最终 reread 报告剩余漂移，读取失败报告 unknown；换 Key 以新 actual 重新补齐。
  - 指标含快照、漂移和有限失败样本，不含 Key。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-33, AC-34
  **依赖**: T005, T006, T010

- [x] **T014**: 平台订阅对账 Service 实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_subscription_reconcile_service.py`
  **逻辑**: 定义不可变 `DesiredSubscriptionSnapshot(ids, complete, failed_tenants)` 和 `reconcile(desired_v1, reload_desired)`；调用 Client 完整 actual，逐项收敛，退订前二次读取，最终确认并用 `emit_metric("information_subscription_reconcile", ...)` 输出结果。Service 不设置 tenant Context、不写 ORM、不持有 Redis 锁；公共元数据只 upsert 不删除。
  **测试**: T013 全部通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-33, AC-34
  **依赖**: T013

- [x] **T015**: 频道用户侧契约与公共目录测试（红）
  **文件**: `src/backend/test/channel/test_channel_source_subscription.py`（将 F031 同步订阅断言改写为 F060 周期最终一致契约）
  **测试上下文**: 复用现有 `ChannelService` mock fixture，覆盖 create/update/dismiss；检查现有请求/响应 schema 和路由不新增字段。
  **用例**:
  - create/update 保存 `source_list` 时不调用远端 subscribe/unsubscribe，也不再以本地目录行判断订阅成功。
  - 元数据查询失败只记录，已持久化频道不回滚；对账后公共 upsert 可补齐展示。
  - dismiss/租户卸载不删除公共来源元数据。
  - 现有频道、知识配置、手动添加文章接口签名保持不变。
  **覆盖 AC**: AC-09, AC-36, AC-37
  **依赖**: T006

- [x] **T016**: 频道 Service 移除同步订阅副作用（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/channel_service.py`
  **逻辑**: create/update 只持久化频道期望来源；删除远端 subscribe 判据和新来源一小时后旧 `sync_information_article` 调度，保留来源元数据 best-effort upsert；dismiss 不删除公共目录。保留 `add_articles_to_knowledge_space` 用户接口和默认 `skip_missing_and_duplicates=false`。不得改权限、成员、配额、审批或 HTTP schema。
  **跨 Feature 影响**: 仅替代 F031 信息源订阅生命周期；频道权限/审批代码不改。
  **测试**: T015 及既有频道创建/编辑/审批测试通过。
  **覆盖 AC**: AC-09, AC-36, AC-37
  **依赖**: T015

---

## Wave 3：公共文章同步

### ES 新增识别原语

- [x] **T017**: Article ES realtime mget 与逐项 bulk 测试（红）
  **文件**: `src/backend/test/channel/test_information_article_es_write.py`
  **测试上下文**: fake Elasticsearch client/helpers；构造部分文档已存在、bulk 部分失败、refresh 失败和边界重复。
  **用例**: `mget_existing_ids` 返回真实存在集合；`bulk_index_articles_detailed` 返回成功/失败 ID 映射而非仅成功数量；文档 ID 固定用上游 article ID；refresh 失败向调用方抛出，不能 best-effort 吞掉。
  **覆盖 AC**: AC-15, AC-16, AC-23, AC-25
  **依赖**: 无

- [x] **T018**: Article ES realtime mget 与逐项 bulk 实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/article_es_service.py`
  **逻辑**: 新增 async `mget_existing_ids(article_ids)`、`bulk_index_articles_detailed(articles_by_id)` 和严格 `refresh_index()`；保留现有方法兼容。详细 bulk 检查每个 item，日志只采样有限失败 ID，严格 refresh 不复用现有吞异常的 sync helper。
  **测试**: T017 全部通过。
  **覆盖 AC**: AC-15, AC-16, AC-23, AC-25, AC-34
  **依赖**: T017

### 文章 Service：远端门禁与空变化

- [x] **T019**: 文章远端门禁和水位测试（红）
  **文件**: `src/backend/test/channel/test_information_article_sync_readiness.py`
  **测试上下文**: fake subscription item、状态 Repository、Client、时区和指标；不访问真实 ES。
  **用例**:
  - 远端 actual 是唯一处理范围，同一 ID 去重；不读取 tenant desired。
  - `last_sync_at` 非业务日或 null 时文章请求为零且状态不推进。
  - 两个水位均相同直接跳过；仅 remote sync 变化但 article 水位相同只提交已检查状态。
  - 当天成功但无文章保存 processed 水位；指标区分 not_ready/no_change/empty，且不含 Key。
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-18, AC-33, AC-34
  **依赖**: T003, T010

- [x] **T020**: 文章 Service 远端门禁实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_article_sync_service.py`
  **逻辑**: 建立 `sync_source(subscription, lock_guard, dispatch_callback)` 主入口、业务时区解析、水位比较和 no-change/empty 快速提交；不从 `channel_info_source.update_time` 或 ES 最大时间推断进度。先实现 T019 范围，分页分支保持为后续 T022 增量实现的明确私有入口，不留延迟实现标记。
  **测试**: T019 全部通过。
  **覆盖 AC**: AC-11, AC-12, AC-13, AC-18, AC-33, AC-34
  **依赖**: T019

### 文章 Service：首次边界与完整分页

- [x] **T021**: 首次边界和包含式分页测试（红）
  **文件**: `src/backend/test/channel/test_information_article_sync_pagination.py`
  **测试上下文**: fake Client/State/ES；第一页最新 N、同秒超过 N、进程中断后新增、分页 total 变化、重复 ID、排序越界等输入。
  **用例**:
  - 首次默认 20/配置 1～100，先固化第 N 篇最小时间，再以 `>=` 完整扫描；同秒额外文章全包含。
  - 基线主键冲突使用先创建者；中断后继续原下界，新文章不能挤出失败文章。
  - 增量固定 min 时间，校验 total、唯一 ID、`create_time DESC,id DESC` 和边界。
  - 上游边界重复以 ID 幂等，不生成重复 ES 文档。
  **覆盖 AC**: AC-14, AC-15, AC-20, AC-21
  **依赖**: T018, T020

- [x] **T022**: 文章 Service 首次边界与分页实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_article_sync_service.py`
  **逻辑**: 增量实现首次边界状态机、固定下界完整分页、响应完整性/排序校验和上游 Article→`ArticleDocument` 转换。游标只使用秒级 create_time；禁止引入 `min_article_id`。首次无文章提交水位但保持 cursor null。
  **测试**: T021 与 T019 全部通过。
  **覆盖 AC**: AC-14, AC-15, AC-20, AC-21
  **依赖**: T021

### 文章 Service：部分成功、派发与提交

- [x] **T023**: 文章写入、锁丢失、派发和状态提交测试（红）
  **文件**: `src/backend/test/channel/test_information_article_sync_commit.py`
  **测试上下文**: fake ES detailed result、可失效 lock guard、dispatch spy、状态 CAS 与远端水位 reread。
  **用例**:
  - 每页严格 `mget → bulk → refresh → dispatch`；只派发写前不存在且本项成功的 ID。
  - bulk/refresh/分页/结果校验任一不完整或 lock 失效时不提交；已成功新增仍已派发。
  - 全部成功才提交 next cursor 与两个水位；CAS 冲突不覆盖。
  - 拉取后水位变化补拉一轮，第二轮仍变化则不提交留待下周期。
  - dispatch 失败不回滚 ES、不补发，指标记录真实漏投窗口。
  **覆盖 AC**: AC-16, AC-17, AC-19, AC-23, AC-33, AC-34, AC-35
  **依赖**: T018, T022

- [x] **T024**: 文章 Service 写入、派发与状态提交实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_article_sync_service.py`
  **逻辑**: 完成每页 detailed write、新增候选识别、严格 refresh、即时 dispatch、锁所有权检查、一次有界补拉和 Repository CAS 提交；用 `emit_metric("information_article_sync", ...)` 输出 result/lag/count/duration。任一失败不更新公共进度，且不吞异常结果。
  **测试**: T023、T021、T019 全部通过。
  **覆盖 AC**: AC-16, AC-17, AC-19, AC-23, AC-33, AC-34, AC-35
  **依赖**: T023

---

## Wave 4：知识空间一次投递

### 当前租户路由

- [x] **T025**: 知识路由 Service 测试（红）
  **文件**: `src/backend/test/channel/test_information_knowledge_routing.py`
  **测试上下文**: fake 当前租户 Channel/Config Repository、ArticleEsService、任务发送 spy；不同租户由 Worker 测试覆盖。
  **用例**:
  - 只从当前 tenant 验证过的频道 IDs 查配置；主频道取来源新增全集，子频道复用对应当前 filter group。
  - 缺规则/规则异常只记录该配置失败；多个空间/目录/配置分别派发，不跨配置去重。
  - `create_time/update_time > detected_at`、禁用或知识总开关关闭均不派发；重新开启不补旧批次。
  - 不读取 KnowledgeFile，不比较标题/正文/文件名/hash，不生成 delivery ID。
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-30, AC-31, AC-32, AC-33, AC-34
  **依赖**: T005, T007, T018

- [x] **T026**: 知识路由 Service 实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_knowledge_delivery_service.py`
  **逻辑**: 实现 `route_current_tenant(source_id, article_ids, detected_at, dispatch_config)`；按当前租户频道→启用配置读取，主/子频道筛选并发送配置消息。投递成功不得调用 `ChannelKnowledgeSyncDao.touch_update_time`；指标与日志只含有限 ID 样本。
  **测试**: T025 全部通过。
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-30, AC-31, AC-32, AC-33, AC-34
  **依赖**: T025

### 单配置逐篇执行

- [x] **T027**: 知识逐篇终态执行测试（红）
  **文件**: `src/backend/test/channel/test_information_knowledge_delivery.py`
  **测试上下文**: fake config/channel、`ChannelService.add_articles_to_knowledge_space`、用户身份和指标；每种异常单独构造。
  **用例**:
  - 执行前重新验证配置启用/生效时间、当前租户所属频道和目标；使用配置创建人及 payload tenant。
  - 每篇单独调用且 `skip_missing_and_duplicates=false`；一篇失败继续其他篇/目标。
  - accepted、article_missing、duplicate_name、target_missing、permission/quota/sensitive/system_failed 分类准确；失败不报告 accepted。
  - 后续 KnowledgeFile FAILED/TIMEOUT/违规不触发本链路再次调用；删除文件不恢复。
  - 不调用 Celery retry，不创建补偿或投递记录。
  **覆盖 AC**: AC-27, AC-28, AC-29, AC-30, AC-31, AC-33, AC-34
  **依赖**: T026

- [x] **T028**: 知识逐篇终态执行实现（绿）
  **文件**: `src/backend/bisheng/channel/domain/services/information_knowledge_delivery_service.py`
  **逻辑**: 增量实现 `deliver_to_config(tenant_id, sync_config_id, article_ids, detected_at)`；构造 `UserPayload(user_id=config.user_id, tenant_id=tenant_id)`，每篇复用既有知识导入链路并窄化异常分类，失败继续；发出 `information_knowledge_delivery` metric。不得修改/删除知识空间既有文件，也不 touch 配置时间。
  **测试**: T027 与 T025 全部通过。
  **覆盖 AC**: AC-27, AC-28, AC-29, AC-30, AC-31, AC-33, AC-34
  **依赖**: T027

---

## Wave 5：Celery Worker、随机调度与租户 Context

### 订阅 Worker

- [x] **T029**: 订阅 Dispatcher/执行任务测试（红）
  **文件**: `src/backend/test/channel/test_information_reconcile_worker.py`
  **测试上下文**: mock random、`apply_async`、Redis lock、`TenantDao.aget_active_ids`、Repository factory 和 Service。
  **用例**:
  - Dispatcher 在配置 `0～600` 内生成 countdown；不 `sleep`。
  - 执行任务锁失败/Redis 异常时不调用远端；锁成功时逐租户设置并恢复 ContextVar，任何租户失败令 desired snapshot incomplete。
  - 自动退订默认 true，周期默认 60 分钟由 schedule contract 验证；日志/指标无 Key。
  **覆盖 AC**: AC-01, AC-03, AC-06, AC-10, AC-33, AC-34, AC-35
  **依赖**: T012, T014

- [x] **T030**: 订阅 Dispatcher/执行任务实现（绿）
  **文件**: `src/backend/bisheng/worker/information/reconcile.py`
  **逻辑**: 定义 `dispatch_information_subscription_reconcile` 与 `reconcile_information_subscriptions`。前者只随机投递；后者持平台 token 锁，枚举全部活跃 tenant IDs，逐个设置/恢复 ContextVar并构造完整 desired snapshot，再调用 Service。Worker 不计算差集、不直接 ORM/HTTP；finally 比较 token 释放。
  **测试**: T029 全部通过。
  **覆盖 AC**: AC-01, AC-03, AC-06, AC-10, AC-33, AC-34, AC-35
  **依赖**: T029

### 文章 Worker

- [x] **T031**: 文章 Dispatcher/执行任务测试（红）
  **文件**:
  - `src/backend/test/channel/test_sync_information_article_tenant.py`（删除 F031 逐租户公网拉取旧测试）
  - `src/backend/test/channel/test_information_article_worker.py`（新建平台公共任务测试）
  **测试上下文**: mock random、远端完整 subscriptions、每来源 lock、Service 和频道更新时间 helper。
  **用例**:
  - Dispatcher 使用配置 countdown，默认 30 分钟 schedule；不 `sleep`。
  - 实际远端来源去重后每源一次；一个来源锁失败/同步异常不阻塞其他来源。
  - 锁续租/所有权丢失传入 Service 后停止保护外写；不同节点共享 Redis key。
  - 本轮成功写入后逐租户更新相关频道展示时间，但不把其当同步进度。
  **覆盖 AC**: AC-11, AC-19, AC-22, AC-33, AC-34, AC-35
  **依赖**: T012, T024

- [x] **T032**: 文章 Dispatcher/执行任务实现（绿）
  **文件**: `src/backend/bisheng/worker/information/article.py`
  **逻辑**: 用新 `dispatch_information_article_poll/sync_information_articles` 替代旧逐租户 `sync_information_article` 主链。执行任务只完整读取 remote actual、逐来源获取/续租锁并调用 Service；知识开关开启且新增成功时发送 route task。逐租户频道展示时间更新显式恢复 ContextVar，失败不影响公共状态。
  **测试**: T031 及旧文章检索/频道排序回归通过。
  **覆盖 AC**: AC-11, AC-19, AC-22, AC-23, AC-32, AC-33, AC-34, AC-35
  **依赖**: T031

### 知识 Worker

- [x] **T033**: 知识路由/单配置任务测试（红）
  **文件**: `src/backend/test/channel/test_information_knowledge_worker.py`
  **测试上下文**: mock活跃租户、Celery publish signals/headers、ContextVar、Service；模拟单租户失败、配置任务 header/payload 不一致和 Broker 重投。
  **用例**:
  - 平台 route 任务逐租户设置/恢复 ContextVar；某租户失败继续其余并记录终态。
  - 在目标 tenant Context 发布 config task，既有 signal 注入 `tenant_id` header；执行前 signal 恢复 ContextVar，任务校验 header 与 payload tenant 一致，缺失/不一致 fail closed。
  - 单配置任务没有 autoretry/retry；重复消息仍执行并把重名交给 Service 分类。
  - 知识总开关关闭时不发布，重新开启不扫描/补投。
  **覆盖 AC**: AC-24, AC-27, AC-28, AC-31, AC-32, AC-33, AC-34, AC-35
  **依赖**: T028

- [x] **T034**: 知识路由/单配置任务实现（绿）
  **文件**: `src/backend/bisheng/worker/information/knowledge_delivery.py`
  **逻辑**: 定义 `route_new_information_articles` 与 `deliver_information_articles_to_config`。route 枚举活跃租户并调用当前租户路由 Service；在各 tenant Context 内 `apply_async` 触发现有 header 注入。config 任务读取 ContextVar并校验 payload tenant，再调用逐篇 Service；所有任务无应用 retry，逐项结果已在 Service 终结。
  **测试**: T033 全部通过。
  **覆盖 AC**: AC-24, AC-27, AC-28, AC-31, AC-32, AC-33, AC-34, AC-35
  **依赖**: T033

### 注册与默认配置

- [x] **T035**: Celery 任务注册与 schedule 契约测试（红）
  **文件**: `src/backend/test/channel/test_information_worker_registration.py`
  **测试上下文**: 构造默认/自定义 `CeleryConf`，导入 Worker 注册模块。
  **用例**: 六个新任务名可发现；默认 schedule 仅包含两个 Dispatcher（3600/1800），旧每日/半小时直执任务不并行；自定义 schedule 不被默认覆盖；两个 steady-state 开关均 true，首次数量越界校验失败。
  **覆盖 AC**: AC-06, AC-10, AC-20, AC-22, AC-32, AC-36
  **依赖**: T001, T030, T032, T034

- [x] **T036**: Celery 任务注册切换（绿）
  **文件**: `src/backend/bisheng/worker/__init__.py`
  **逻辑**: 注册六个新任务，移除旧 `sync_information_article/reconcile_all_tenants` 导入；不新增 Information queue/Worker，不改变 `task_routes`，六个任务继续使用默认 `celery` queue。文件被知识空间接受后的既有解析/向量化任务仍按原路由使用 `knowledge_celery`。确认 `worker/main.py` 已加载 tenant publish/prerun/postrun signals，无需重复注册。
  **测试**: T035 全部通过。
  **覆盖 AC**: AC-10, AC-22, AC-24, AC-32, AC-35, AC-36
  **依赖**: T035

---

## Wave 6：集成回归、E2E 与评审

- [x] **T037**: DB/配置/公共目录集成测试
  **文件**: `src/backend/test/channel/test_information_infrastructure_integration.py`
  **测试上下文**: 使用项目 SQLModel test session/metadata 和配置 merge fixture；不连接真实 Information/ES。
  **用例**: 新表自动发现且无 tenant_id；状态 Repository 初始边界/CAS；`channel_info_source` 在不同 tenant Context 可见同一行；租户卸载表清单不包含它；新配置 key backfill 保留运维旧值；MySQL 生成 SQL 不含专属 JSON 操作。
  **覆盖 AC**: AC-20, AC-35, AC-36, AC-37
  **依赖**: T001, T003, T004, T006

- [x] **T038**: 订阅→文章→知识跨 Service 集成测试
  **文件**: `src/backend/test/channel/test_information_sync_integration.py`
  **测试上下文**: fake Information/Redis/ES/MinIO 边界，真实 Service/Repository interface 组合；两个 tenant Context、共享来源、主/子频道配置。
  **用例**: 两租户共享来源形成一个远端订阅/一次文章拉取；上游当天晚更新后下轮获取；包含边界不重复派发；首次中断保留范围；新增文章分别路由主/子频道；单目标失败继续，关闭开关不补投；日志/metrics 全程不含 Key。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37
  **依赖**: T016, T024, T028, T036, T037

- [x] **T039**: F060 聚焦回归执行
  **文件**: 无（验证任务）
  **命令**: 在 `src/backend/` 执行 `uv run pytest test/channel/test_information_*.py test/channel/test_channel_source_subscription.py test/channel/test_information_reconcile_worker.py`；旧逐租户文章测试已在 T031 被新平台任务测试替代，本任务不再修改测试文件。
  **通过标准**: 新增与受影响既有测试全绿；任何 baseline/环境失败单独报告，不得伪称通过。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-36, AC-37
  **依赖**: T038

- [x] **T040**: 后端格式、架构与静态检查
  **文件**: 无（验证任务）
  **命令**: 在 `src/backend/` 对本 Feature 修改文件执行 `uv run ruff format --check ...`、`uv run ruff check ...`；仓库根执行 `scripts/arch-guard.sh`。检查 common/core 不反向 import domain、Service 无 ORM SQL、日志使用 loguru `{}` 占位、无 API Key 输出。
  **通过标准**: changed-file lint 与 arch-guard 通过；DM8 兼容结论记录为静态审查/中央回归待跑，不冒充本地验证。
  **覆盖 AC**: AC-34, AC-35
  **依赖**: T039

- [x] **T041**: 生成 F060 E2E 分类与真实环境清单
  **文件**: `features/v3.0.0-beta1/060-information-source-subscription-reconciliation/e2e-checklist.md`
  **执行方式**: 使用 `e2e-test` skill 分类 AC。F060 无新增/修改 HTTP API 或页面，按 skill 规则不生成伪 API E2E；产出真实 Information/Redis/ES/MinIO、双租户、默认 Worker 与 DM8 的可执行清单，并由 T038 跨 Service 集成测试承担本地自动组合覆盖。
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-10, AC-11, AC-12, AC-15, AC-20, AC-22, AC-23, AC-24, AC-25, AC-27, AC-28, AC-31, AC-32, AC-34, AC-35, AC-36, AC-37
  **依赖**: T040

- [ ] **T042**: 执行 E2E 与手动运行清单
  **文件**: 无（验证任务）
  **命令/步骤**: 运行 T041 E2E；在可访问真实 Information/Redis/ES/MinIO 的测试环境按 Design §7.2 手动调用两个执行任务并核对远端订阅、状态表、ES、知识文件和 `BS_METRIC`。真实依赖不可用时明确列出未执行项及原因，不用 mock 结果替代。
  **通过标准**: 自动 E2E 通过且真实环境清单有证据，或由用户明确接受未执行范围。
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-10, AC-11, AC-12, AC-15, AC-20, AC-22, AC-23, AC-24, AC-25, AC-27, AC-28, AC-31, AC-32, AC-34, AC-35, AC-36, AC-37
  **依赖**: T041

- [x] **T043**: 最终代码评审与 SDD 收口
  **文件**:
  - `features/v3.0.0-beta1/060-information-source-subscription-reconciliation/design.md`
  - `features/v3.0.0-beta1/060-information-source-subscription-reconciliation/tasks.md`
  **逻辑**: 执行 `/code-review --base feat/3.0.0-beta1`，核对工作树只包含本 Feature 授权改动；逐项回填任务勾选、实现文件、测试证据和实际偏差指针。仅实现细节偏差覆盖更新 Design；推翻已确认决策先停下重新确认。
  **通过标准**: 无未处理 P0/P1，AC 追踪表与实际测试一致，README 状态更新为真实完成度。
  **依赖**: T042

---

## AC 追踪矩阵

| AC | 首要测试任务 | 主要实现任务 |
|---|---|---|
| AC-01 | T013, T029, T038 | T014, T030 |
| AC-02 | T013, T038 | T014 |
| AC-03 | T013, T029, T038 | T014, T030 |
| AC-04 | T009, T013, T038 | T010, T014 |
| AC-05 | T009, T013, T038 | T010, T014 |
| AC-06 | T013, T029, T035, T041 | T001, T014, T030 |
| AC-07 | T013, T038 | T014 |
| AC-08 | T013, T038 | T014 |
| AC-09 | T009, T013, T015, T038 | T010, T014, T016 |
| AC-10 | T029, T035, T041 | T001, T030, T036 |
| AC-11 | T019, T031, T038, T041 | T020, T032 |
| AC-12 | T019, T038, T041 | T020 |
| AC-13 | T019, T038 | T020 |
| AC-14 | T021, T038 | T022 |
| AC-15 | T017, T021, T038, T041 | T018, T022 |
| AC-16 | T023, T038 | T024 |
| AC-17 | T023, T038 | T024 |
| AC-18 | T019, T038 | T020 |
| AC-19 | T011, T023, T031, T038 | T012, T024, T032 |
| AC-20 | T021, T035, T037, T038, T041 | T001, T022 |
| AC-21 | T021, T038 | T022 |
| AC-22 | T031, T035, T041 | T001, T032, T036 |
| AC-23 | T017, T023, T025, T038, T041 | T018, T024, T026, T032 |
| AC-24 | T025, T033, T038, T041 | T026, T034 |
| AC-25 | T017, T025, T038, T041 | T018, T026 |
| AC-26 | T025, T038 | T026 |
| AC-27 | T027, T033, T038, T041 | T028, T034 |
| AC-28 | T027, T033, T038, T041 | T028, T034 |
| AC-29 | T027, T038 | T028 |
| AC-30 | T025, T027, T038 | T026, T028 |
| AC-31 | T025, T027, T033, T038, T041 | T026, T028, T034 |
| AC-32 | T025, T033, T035, T038, T041 | T001, T026, T034, T036 |
| AC-33 | T013, T019, T023, T025, T027, T029, T031, T033, T038 | T014, T020, T024, T026, T028, T030, T032, T034 |
| AC-34 | T009, T013, T019, T023, T025, T027, T029, T031, T033, T038, T041 | T010, T014, T020, T024, T026, T028, T030, T032, T034 |
| AC-35 | T011, T023, T029, T031, T033, T037, T038, T041 | T003, T004, T012, T024, T030, T032, T034, T036 |
| AC-36 | T015, T035, T037, T038, T041 | T016, T036 |
| AC-37 | T015, T037, T038, T041 | T004, T006, T016 |

---

## 实际偏差记录

> 这里只留一行指针；论证覆盖更新到 Design。推翻已确认决策时先停下重新确认。

- **T041 验证方式调整**：`e2e-test` skill 明确排除纯内部状态逻辑；F060 又明确不新增/修改 HTTP API 和页面，因此不创建名为 API E2E、实为 mock 单测的文件。实际产物改为 `e2e-checklist.md`，本地组合覆盖落在 T038；真实依赖执行仍由 T042 保持未完成。
- **T024 评审修复**：ES bulk 部分成功时，成功新文章先严格 refresh 并投递，随后以失败结果阻止公共水位提交。
- **T003 评审修复**：CAS 在锁定行时强制刷新 Identity Map，并在刷新前冻结预期旧值，避免跨 Session 更新被旧对象覆盖。
- **T032 评审修复**：知识投递开关关闭时，文章 Worker 不发布 route task；公共文章状态正常推进，重新开启不补投。
- **T014/T036 评审修复**：订阅对账在远端快照和逐项变更前续租平台锁，锁丢失即停止；Celery 配置按旧 task 全名清理升级残留 Beat 项，不影响其他自定义任务。
- **T022 评审修复**：空 `article_list_updated_at` 按未知水位进入分页；首次边界只在第一页完整覆盖配置数量后固化，避免部分页造成永久漏同步。

## 本地验证证据

- `uv run pytest test/channel -q`：本轮最终执行 144 项全绿（以最后一次命令输出为准）。
- F060 聚焦集合：订阅、文章、知识、Redis 锁、Worker 注册、状态表和跨 Service 集成测试全绿。
- 评审修复回归：`uv run pytest -q test/channel/test_information_*.py test/channel/test_channel_source_subscription.py`，68 项全绿；仅依赖库弃用告警。
- 39 个 F060 新增/实质修改 Python 文件的 `ruff format --check` / `ruff check`、`scripts/arch-guard.sh`、`git diff --check` 通过；三处只更新旧任务说明/卸载清单的历史文件保留既有文件级 Ruff baseline，未新增违规。
- 本地只完成 MySQL/DM8 兼容静态审查；真实 Information/Redis/ES/MinIO、DM8 和多节点链路见 T042，尚未执行。
- 代码评审以 worktree fork point `e9ac9cecc` 和当前 `feat/3.0.0-beta1` (`80bfd31a6`) 双重核对；base 已前进 50 个提交，F060 已跟踪修改中仅 `release-contract.md` 与其重叠。按“不提交、不夹带”约束未在脏工作树执行 merge/rebase，后续提交前需对齐 base 并重新跑 CI。
