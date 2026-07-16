# Tasks：首页个性化推荐（F056）

**关联规格**: [spec.md](./spec.md)
**版本**: v2.5.0-sg
**基线依赖**: feat/2.5.0-sg、现有 shougang_portal_config、knowledge、telemetry、permission 与 knowledge_celery

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-07-15 用户确认；两轮规格审查后 LGTM |
| tasks.md | ✅ 已拆解 | 三轮评审后 LGTM；第三轮经用户明确授权并记录流程偏差 |
| 实现 | ✅ 核心实现完成 | 两个功能分支均完成代码、定向回归和跨仓审查，保留本地且未 commit/push |
| 上线门禁 | ⛔ 集成环境阻塞 | T068 性能、T069 强制 E2E 与 DM8 实库迁移仍须在完整集成环境完成 |

## 开发模式

- BiSheng 后端 Test-First：测试任务先于配对实现任务；基础设施任务按仓库规则前置。
- 门户后端 Test-First；门户前端 Test-Alongside，但测试任务仍先定义契约。
- BiSheng Platform/Client 本特性均无改动；门户前端是独立仓库分区，不与 BiSheng 前端任务混写。
- 所有新表包含 tenant_id，并注册租户自动过滤；业务代码不得手写租户过滤。
- 权限只复用 PermissionService 与请求级完整权限上下文，custom ACL 和异常一律失败关闭。
- MySQL/DM8 双库迁移必须可升级、可回滚，并把当前两个 Alembic head 合并为单 head。
- Worker 子任务通过 Celery headers 传播 tenant_id，并由 prerun ContextVar 恢复；统一进入 knowledge_celery。
- 每个实现任务完成后执行 /task-review；最后强制执行 /e2e-test 与 /code-review。

## 执行阶段

1. T001-T008：基础设施与共享契约。
2. T009-T018：聚合配置、精确部门绑定与迁移。
3. T019-T031：推荐算法、权限选择、browse 与行为遥测。
4. T032-T040：投影、池、Worker、对账与事件触发。
5. T041-T064：门户配置、首页、更多页、搜索和预览。
6. T065-T070：文档、回归、性能、E2E 与代码审查。

## 实施结果汇总

| 任务范围 | 状态 | 结果 |
|----------|------|------|
| T001-T065 | ✅ 完成 | BiSheng、门户后端/前端及方案文档均已实现 |
| T066 | ✅ 完成 | BiSheng 核心定向 191 passed；compileall、单 Alembic head、离线 MySQL/DM8 编译及架构/RBAC 守卫通过 |
| T067 | ✅ 完成（含基线偏差） | Portal 定向后端 55 passed、前端 28 passed、定向 ESLint 与生产构建通过 |
| T068 | ⛔ BLOCKED | 缺完整压测环境，未形成可声明的 P95 结论 |
| T069 | ⛔ BLOCKED | 缺完整集成环境、当前用户 token 与权限场景数据 |
| T070 | ✅ 完成 | 跨仓审查无 P0/P1/P2 新问题；可进入集成环境门禁 |

> 下方复选框同步实际执行状态；T068/T069 保持未完成并作为正式上线前强制门禁。

---

## Tasks

### 阶段 1：基础设施与共享契约

- [x] **T001 基础设施：部门业务域 ORM 与 Repository 接口**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/models/department_business_domain.py
  - src/backend/bisheng/shougang_portal_config/domain/repositories/interfaces/department_business_domain_repository.py
  **逻辑**:
  - 定义 tenant_id、department_id、business_domain_code、审计时间及租户内唯一约束。
  - 接口提供按部门读取、按部门集合读取、同 session 全量替换和删除；写入只 flush、不 commit。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T002 基础设施：推荐投影 ORM 与 Repository 接口**
  **文件**:
  - src/backend/bisheng/knowledge/domain/models/portal_recommendation_file_projection.py
  - src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_repository.py
  **逻辑**:
  - 定义文件/空间、业务域、公开性、推荐资格、ACL 范围、源更新时间与投影版本。
  - Repository 接口提供幂等 upsert/delete、轻量候选查询、watermark 与分页对账，不暴露 ORM 给 Service。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T003 基础设施：MySQL/DM8 兼容迁移**
  **文件**:
  - src/backend/bisheng/core/database/alembic/versions/v2_5_0_sg_f056_portal_recommendation.py
  **逻辑**:
  - down_revision 同时引用 f057_message_push_outbox 与 f058_approval_notification_outbox，升级后保持单 head。
  - 创建 T001/T002 两表、唯一约束和 spec 所列索引；使用 dialect_helpers，upgrade/downgrade 对称且幂等守卫。
  **回滚**: 先删索引和唯一约束，再按依赖顺序删除两表。
  **覆盖 AC**: —（基础设施）
  **依赖**: T001, T002

- [x] **T004 基础设施：BiSheng 聚合配置 Schema**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/schemas/portal_config_schema.py
  **逻辑**:
  - 在 portal 下新增 department_business_domain_bindings；推荐配置增加 Top N、四个算法参数、影子模式与灰度。
  - 保留旧配置默认迁移，并校验 1 <= section_page_size <= home_total_count <= 50 及全部范围。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T005 基础设施：专用配置 Repository 契约**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/repositories/interfaces/portal_admin_config_repository.py
  - src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_state_repository.py
  **逻辑**:
  - 配置接口支持租户物理 key、SELECT FOR UPDATE、flush 不提交和唯一冲突重试。
  - Redis 接口覆盖池、用户兴趣 Top 50、90 天浏览、行为版本、240 秒 Top N 与 generation CAS；所有 key 使用既有租户前缀和同一 tenant hash-tag。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T006 基础设施：推荐常量和 browse/遥测 Schema**
  **文件**:
  - src/backend/bisheng/knowledge/domain/constants.py
  - src/backend/bisheng/knowledge/domain/schemas/knowledge_space_schema.py
  **逻辑**:
  - 声明 personalized_v1、10000 候选、10 件批次、200 检查、700ms、500 投影补偿等硬预算。
  - 扩展 browse 请求/响应以及 portal_search、entry_point、recommendation_scene 字段，保持旧调用兼容。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T007 基础设施：通用遥测枚举与事件 Schema**
  **文件**:
  - src/backend/bisheng/common/constants/enums/telemetry.py
  - src/backend/bisheng/common/schemas/telemetry/event_data_schema.py
  **逻辑**:
  - 增加 PORTAL_SEARCH；阅读事件增加入口和推荐场景。
  - tenant_id 由服务端注入，搜索词规范化后仅写 ES，禁止原始词进入 Redis 或普通日志。
  **覆盖 AC**: —（基础设施）
  **依赖**: 无

- [x] **T008 基础设施：租户模型注册**
  **文件**:
  - src/backend/bisheng/core/database/tenant_filter.py
  **逻辑**:
  - 强制导入两个新租户模型，使自动过滤和 tenant_id 写入生效。
  **覆盖 AC**: —（基础设施）
  **依赖**: T001, T002

### 阶段 2：聚合配置、绑定与迁移

- [x] **T009 测试：聚合配置校验、版本和事务**
  **文件**:
  - src/backend/test/shougang_portal_config/test_personalized_recommendation_config.py
  **测试**:
  - 覆盖旧配置默认迁移、合法/非法范围、无效业务域、绑定规范化和清空全量替换。
  - 并发保存断言当前租户版本唯一严格递增；任一失败断言配置和绑定均未提交。
  - 热度配置 fingerprint 变化在保存成功后递增 desired generation 并投递携带不可变 generation/fingerprint 的重算任务；稳定打散参数只失效 Top N。
  - 部门绑定成功变化只发布新旧绑定差集涉及部门的用户域/Top N 失效，不全租户清理；失败事务不发布失效事件。
  - internal 未认证为 401/403，合法管理员只读取 token 当前租户。
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07, AC-08, AC-09, AC-22, AC-51
  **依赖**: T001, T004, T005

- [x] **T010 实现：专用配置与绑定 Repository**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/repositories/implementations/portal_admin_config_repository_impl.py
  - src/backend/bisheng/shougang_portal_config/domain/repositories/implementations/department_business_domain_repository_impl.py
  **逻辑**:
  - 物理 key：tenant 1 使用 shougang_portal_config，其他租户使用带 tenant_id 的 key。
  - 配置行锁读取、flush 写入；绑定在同一 AsyncSession 内按规范化结果全量替换，不调用自动 commit 的 BaseRepository 写方法。
  **配对测试**: T009
  **覆盖 AC**: AC-01, AC-05, AC-07, AC-08
  **依赖**: T009

- [x] **T011 实现：聚合配置 Service 的原子保存**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/services/portal_config_service.py
  - src/backend/bisheng/shougang_portal_config/domain/services/department_business_domain_service.py
  **逻辑**:
  - 验证业务域存在，规范化编码并去重；在一个事务里锁配置、计算 old_version+1、写聚合配置和绑定。
  - 唯一冲突按有界次数重试；成功返回服务端版本并按变化范围失效缓存，失败完整回滚且不发布失效事件。
  - 提交成功后比较旧/新 fingerprint：热度参数变化通过状态 Repository 递增 desired generation，再投递携带该 generation/fingerprint 的不可变重算任务；稳定打散参数变化仅失效 Top N。
  - 绑定提交成功后计算新旧绑定差集，只按受影响 department_ids 分页投递用户业务域与 Top N 失效；事务回滚时不投递。
  **配对测试**: T009
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07, AC-08, AC-22
  **依赖**: T010

- [x] **T012 实现：聚合配置 Endpoint 认证与响应**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/api/endpoints/portal_config.py
  **逻辑**:
  - 保持既有 GET/PUT 路由和 UnifiedResponseModel；PUT 返回服务端新版本。
  - internal 注入 UserPayload.get_admin_user，只按当前 token 的 tenant_id 读取，不增加独立绑定/推荐同步接口。
  **配对测试**: T009
  **覆盖 AC**: AC-08, AC-51
  **依赖**: T011

- [x] **T013 测试：主部门精确绑定与无继承**
  **文件**:
  - src/backend/test/shougang_portal_config/test_department_business_domain.py
  **测试**:
  - 唯一主部门多业务域去重；父子部门各自绑定但绝不继承。
  - 主+次部门只读主部门；0 个或多个主部门、无绑定时返回空特征且不查询次部门。
  - 两租户同部门 ID 的绑定互不影响。
  **覆盖 AC**: AC-02, AC-03, AC-04
  **依赖**: T001

- [x] **T014 实现：用户业务域精确解析**
  **文件**:
  - src/backend/bisheng/shougang_portal_config/domain/services/department_business_domain_service.py
  **逻辑**:
  - 查询全部 is_primary=true 行并要求恰好一条；不复用会 first() 吞重复的旧 DAO。
  - 返回主部门精确绑定的去重编码；0 个或多个主部门均返回无业务域特征，不修改部门权限继承语义。
  **配对测试**: T013
  **覆盖 AC**: AC-02, AC-03, AC-04, AC-22
  **依赖**: T011, T013

- [x] **T015 测试：迁移结构、双库与回滚**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_migration.py
  **测试**:
  - MySQL/DM8 编译或真实 fixture 校验两表、唯一约束、索引与 server default。
  - 断言 revision 合并当前两 heads，upgrade 后单 head，downgrade 干净移除本特性对象。
  **覆盖 AC**: AC-49
  **依赖**: T003

- [x] **T016 实现：迁移兼容修正与测试 fixture**
  **文件**:
  - src/backend/bisheng/core/database/alembic/versions/v2_5_0_sg_f056_portal_recommendation.py
  - src/backend/test/fixtures/table_definitions.py
  **逻辑**:
  - 根据 T015 补齐 DM8 长度、默认值和索引兼容；SQLite 测试 fixture 注册两表。
  **配对测试**: T015
  **覆盖 AC**: AC-49
  **依赖**: T015

- [x] **T017 测试：配置变化 generation 与 CAS**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_pool_generation.py
  **测试**:
  - 给定连续 desired generations，乱序完成只能由最新 generation 切 active。
  - CAS 拒绝旧 generation/fingerprint；重算期间旧 active pool 仍可用。
  **覆盖 AC**: AC-09
  **依赖**: T005

- [x] **T018 实现：Redis 状态 Repository 与 CAS**
  **文件**:
  - src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_redis_repository.py
  **逻辑**:
  - 实现接口全部状态；多键 CAS 使用同一 tenant hash slot 或单 state HASH，避免 Redis Cluster CROSSSLOT。
  - active 指针包含 generation、pool version、配置 fingerprint；仅 desired generation 且大于 active 才原子切换。
  **配对测试**: T017
  **覆盖 AC**: AC-09, AC-22, AC-32
  **依赖**: T017

### 阶段 3：算法、权限、browse 与行为

- [x] **T019 测试：动态打分、已读扣分和稳定打散**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_algorithm.py
  **测试**:
  - 四特征按 0.30/0.40/0.15/0.15 对有效特征动态归一化。
  - 0-7/8-30/31-90/>90 天分别 -80/-50/-30/0 且不删除已读候选。
  - 阈值内按 tenant/user/周期/file 稳定，阈值外不跨组；配置边界确定。
  **覆盖 AC**: AC-19, AC-20, AC-21, AC-22
  **依赖**: T006

- [x] **T020 实现：在线打分与稳定排序**
  **文件**:
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_service.py
  **逻辑**:
  - 定义轻量候选合并、特征有效性、动态分母、最近浏览扣分和分组稳定打散。
  - 稳定键严格为 tenant_id、user_id、周期 bucket、space_id、file_id；无关配置版本不得改变同周期排序。
  **配对测试**: T019
  **覆盖 AC**: AC-13, AC-19, AC-20, AC-21, AC-22
  **依赖**: T019

- [x] **T021 测试：候选池合并、3:1 和 14+3**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_pool.py
  **测试**:
  - 有业务域只读业务域+兴趣；无业务域用兴趣+通用；首轮不足才合并通用并整体重排。
  - 多池按 space_id/file_id 去重保留特征；不超 10000 全参与，超出按业务域轮询熔断。
  - 业务域/通用池热门:新鲜 3:1、单路回填、单空间可填满 500，以及连续 14 天+3 天冷却。
  - 近 30 天浏览按 user_id+file_id+自然日去重；自然来源权重 1，首页及推荐列表用配置权重，并按配置半衰期衰减。
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-36
  **依赖**: T018

- [x] **T022 实现：共享池、兴趣池和候选组装**
  **文件**:
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_pool_service.py
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_service.py
  **逻辑**:
  - 实现 3:1 交错、去重回填、14+3 状态；池按租户/业务域/版本存储，默认容量 500。
  - 热度按用户/文件/自然日去重、来源权重和半衰期计算；配置 fingerprint 作为 generation 目标，不直接覆盖 active pool。
  - 在线候选按 spec 两轮策略组装；超过 10000 才熔断并记录指标，不执行旧 30/20/10 截断。
  **配对测试**: T021
  **覆盖 AC**: AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-36
  **依赖**: T021

- [x] **T023 测试：权限后置选择与无泄露**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_permission.py
  **测试**:
  - 公共正常文件快速通过，删除/违规/非主版本/非成功拒绝；custom ACL 不进共享池。
  - 非公共文件执行完整 view_file；投影滞后、刚撤权、连续拒绝、单文件异常和整体上下文异常均失败关闭。
  - 每批 10、最多 200、700ms、实际数量；无权元数据不进入响应/普通日志。
  - 缓存命中仍复核权限，失权后丢弃并重算。
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T020, T022

- [x] **T024 实现：渐进权限选择**
  **文件**:
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_service.py
  **逻辑**:
  - 排序后按 10 件分批复用请求级权限上下文；非公共逐文件执行 PermissionService view_file。
  - 单文件异常记录脱敏指标并继续；整体异常返回已确认部分/空，不弱化校验；在 Top N、200 或 700ms 任一条件达成时停止。
  - 240 秒 Top N 缓存保存顺序但每次读取实时复核权限。
  **配对测试**: T023
  **覆盖 AC**: AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-32
  **依赖**: T023

- [x] **T025 测试：personalized_v1 browse API**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_api.py
  **测试**:
  - 登录用户个性化响应使用 UnifiedResponseModel，固定 has_more=false/next_cursor=null，数量不足返回实际数据。
  - 旧 latest_selected 和其他 browse 模式回归不变；安全 HTTP 200 空/部分与内部错误语义可区分。
  **覆盖 AC**: AC-29, AC-30, AC-31
  **依赖**: T024

- [x] **T026 实现：browse 分流与 Endpoint 委托**
  **文件**:
  - src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py
  - src/backend/bisheng/knowledge/api/endpoints/shougang_portal.py
  **逻辑**:
  - 在 _browse_shougang_portal_files_impl 对 personalized_v1 独立分流，不改变旧模式。
  - Endpoint 只校验/委托并复用现有响应映射；安全部分/空结果保持 HTTP 200。
  **配对测试**: T025
  **覆盖 AC**: AC-29, AC-30, AC-31
  **依赖**: T025

- [x] **T027 测试：搜索与阅读行为状态**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_behavior.py
  **测试**:
  - portal_search 注入 tenant、规范化写 ES、递增行为版本并投递兴趣重算；Redis 无原始搜索词。
  - build_interest_top50 查询 ES 近 90 天最多 20 个规范化去重 query，按时间衰减与出现次数加权；当前 query 立即并入本轮。
  - 每个 query 的内容命中按标题 4、标签 3、摘要 1 合并去重，保留 Top 50 到 Redis，TTL 固定 30 分钟。
  - 阅读来源和 recommendation_scene 正确写入，90 天浏览 ZSET 只保留最近一次并递增版本。
  - ES/Redis 缺失按冷启动或可重试语义，不阻塞首页。
  **覆盖 AC**: AC-33, AC-34, AC-35, AC-46, AC-48
  **依赖**: T007, T018

- [x] **T028 实现：通用遥测写入与推荐行为 Service**
  **文件**:
  - src/backend/bisheng/common/telemetry/portal_event_service.py
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_behavior_service.py
  **逻辑**:
  - common 层仅校验并写含 tenant_id 的 ES 事件，不导入 knowledge。
  - knowledge 行为服务负责 Redis write-through、行为版本和兴趣任务；build_interest_top50 使用近 90 天最多 20 个去重 query 的时间/次数权重，再按标题 4、标签 3、摘要 1 合并当前 query 命中，写 Top 50、TTL 30 分钟。
  - Redis 仅保存 file_id/score 等派生兴趣，不保存原始 query；异常按关键/非关键边界记录，不静默吞掉。
  **配对测试**: T027
  **覆盖 AC**: AC-34, AC-35, AC-46, AC-48
  **依赖**: T027

- [x] **T029 实现：遥测 Endpoint 编排**
  **文件**:
  - src/backend/bisheng/knowledge/api/endpoints/shougang_portal.py
  - src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py
  **逻辑**:
  - portal_search 和阅读事件先调用通用 ES 写入，再由 knowledge 行为服务更新派生状态。
  - 当前登录用户和租户由依赖注入，客户端 tenant/user 字段不可信。
  **配对测试**: T027
  **覆盖 AC**: AC-33, AC-34, AC-35
  **依赖**: T028

- [x] **T030 测试：90 天搜索事实源与清理**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_telemetry_repository.py
  **测试**:
  - 兴趣查询强制 tenant_id、user_id、portal_search 和 UTC 90 天窗口。
  - delete-by-query 仅删除当前租户 90 天前 portal_search，不删其他事件、边界内事件或其他租户。
  **覆盖 AC**: AC-34, AC-48, AC-52
  **依赖**: T007

- [x] **T031 实现：ES 遥测 Repository**
  **文件**:
  - src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_telemetry_repository.py
  - src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_telemetry_repository_impl.py
  **逻辑**:
  - 查询和删除都显式强制当前 ContextVar tenant_id；不假设未启用的 ES 租户索引前缀。
  - 返回近 90 天最多 20 个按时间倒序、规范化去重并附出现次数的 query 特征；提供标题/标签/摘要字段匹配结果供 build_interest_top50 使用。
  - 不把原文写入 Redis；ES 异常交由 Worker 重试。
  **配对测试**: T030
  **覆盖 AC**: AC-34, AC-48, AC-52
  **依赖**: T030

### 阶段 4：投影与 Worker

- [x] **T032 测试：投影资格、业务域复用和幂等**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_projection.py
  **测试**:
  - 复用 file_encoding/split_rule 解析，规范化业务域；不向 knowledge_file 增字段。
  - 发布、删除、移动、状态、版本、业务域和 ACL 变化幂等 upsert/delete，只改受影响文件或子树。
  - custom ACL 不 recommendable；池缺失仅从投影最多 500 条补偿。
  **覆盖 AC**: AC-25, AC-27, AC-43, AC-47
  **依赖**: T002

- [x] **T033 实现：投影 Repository 与解析 Service**
  **文件**:
  - src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_repository_impl.py
  - src/backend/bisheng/knowledge/domain/services/portal_recommendation_projection_service.py
  **逻辑**:
  - Repository 用投影索引做有界查询、水位和分页对账；Service 复用现有解析 helper 计算资格与版本。
  - 不扫描完整知识文件表，不把池/投影当权限依据。
  **配对测试**: T032
  **覆盖 AC**: AC-25, AC-27, AC-43, AC-47
  **依赖**: T032

- [x] **T034 测试：Worker 租户、周期、幂等和 CAS**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_worker.py
  **测试**:
  - 发布任务 headers 携带 tenant_id，prerun 恢复 ContextVar，DB/Redis/ES 全程租户隔离。
  - 6 小时热度/共享池、每日 watermark、每周分页全量、每日 90 天 ES 清理正确注册。
  - 重试幂等，ES 暂不可用保留旧池，乱序 generation 不回切。
  **覆盖 AC**: AC-09, AC-18, AC-43, AC-44, AC-45, AC-48, AC-52
  **依赖**: T018, T031, T033

- [x] **T035 实现：推荐 Celery 任务**
  **文件**:
  - src/backend/bisheng/worker/knowledge/portal_recommendation.py
  **逻辑**:
  - 定义增量投影、兴趣、6 小时重算、每日增量/清理和每周全量子任务，统一 knowledge_celery。
  - Beat 根任务分页 fan-out 活跃租户，每个子任务显式 tenant headers；任务体用 run_async_task 并让关键异常进入重试。
  **配对测试**: T034
  **覆盖 AC**: AC-09, AC-18, AC-43, AC-44, AC-45, AC-48, AC-52
  **依赖**: T034

- [x] **T036 实现：Worker 路由、Beat 与导入**
  **文件**:
  - src/backend/bisheng/core/config/settings.py
  - src/backend/bisheng/worker/__init__.py
  **逻辑**:
  - 注册任务路由与 6 小时/每日/每周 schedule；确保 beat fan-out 不继承默认 tenant 1。
  - 显式导入 portal_recommendation，保持现有任务配置兼容。
  **配对测试**: T034
  **覆盖 AC**: AC-44, AC-45, AC-52
  **依赖**: T035

- [x] **T037 测试：文件/权限/主部门变化触发**
  **文件**:
  - src/backend/test/knowledge/test_portal_recommendation_invalidation_hooks.py
  **测试**:
  - 发布、解析状态、编码、移动、删除、ACL/空间权限和主部门变化只发布受影响资源及当前 tenant。
  - 事务失败不发布成功事件；重复事件可由 Worker 幂等处理。
  **覆盖 AC**: AC-22, AC-43, AC-45
  **依赖**: T035

- [x] **T038 实现：文件生命周期投影触发**
  **文件**:
  - src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py
  - src/backend/bisheng/approval/domain/services/shougang_approval_handler.py
  **逻辑**:
  - 在事务成功后的编码、移动、删除和审批发布路径发布租户化增量任务。
  **配对测试**: T037
  **覆盖 AC**: AC-43, AC-45
  **依赖**: T037

- [x] **T039 实现：文件解析状态投影触发**
  **文件**:
  - src/backend/bisheng/worker/knowledge/file_worker.py
  **逻辑**:
  - 文件解析成功、失败、版本状态变化持久化成功后调用统一投影增量任务；事件携带 tenant/resource/version。
  - 不在事务提交前发布成功事件，重复投递由投影 Worker 幂等消化。
  **配对测试**: T037
  **覆盖 AC**: AC-43, AC-45
  **依赖**: T037

- [x] **T040 实现：权限与部门失效触发**
  **文件**:
  - src/backend/bisheng/permission/domain/services/permission_service.py
  - src/backend/bisheng/user/domain/services/user_department_service.py
  **逻辑**:
  - 统一授权成功后按文件/文件夹子树/空间发布投影失效；主部门提交成功后清用户域与 Top N。
  - 事件只携 tenant/resource/version，不记录无权资源元数据到普通日志。
  **配对测试**: T037
  **覆盖 AC**: AC-22, AC-27, AC-43, AC-45
  **依赖**: T037

### 阶段 5：门户配置、首页、更多、搜索与预览

- [x] **T041 测试：门户配置兼容、管理 API 与远端版本**
  **文件**:
  - backend/tests/test_personalized_portal_config.py
  - backend/tests/test_department_business_domain_config.py
  **测试**:
  - 旧配置加载默认值、合法/非法推荐参数、无效/重复部门绑定、清空保存。
  - GET/POST department-business-domains 与既有 recommendation 路由；远端整份聚合 PUT 接收服务端版本。
  - 同一门户部署使用 runtime 管理 token 对应的单一 BiSheng tenant。
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07, AC-08, AC-42, AC-51
  **依赖**: T012

- [x] **T042 实现：门户配置 Schema 与默认迁移**
  **文件**:
  - backend/app/schemas/portal_config.py
  - backend/app/config/portal_config.py
  **逻辑**:
  - 与 BiSheng portal 子配置同构；增加绑定、Top N、四参数、影子和灰度。
  - 加载旧 JSON 时补默认，保存时执行交叉范围和业务域引用校验。
  **配对测试**: T041
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07, AC-42
  **依赖**: T041

- [x] **T043 实现：门户配置 Service 与聚合同步**
  **文件**:
  - backend/app/services/config_store.py
  - backend/app/services/portal_admin_config_store.py
  **逻辑**:
  - 分区更新后仍调用既有 /api/v1/shougang-portal/config 整份 PUT，不新增 BiSheng 独立接口。
  - ConfigStore Protocol 与 PortalAdminConfigStore.upsert_document 同步改为返回 BiSheng 规范化文档和服务端 version，旧本地实现返回等价结果。
  - 内部 GET/PUT 使用 runtime 管理 token，单个门户部署只绑定该 token 对应租户。
  **配对测试**: T041
  **覆盖 AC**: AC-01, AC-05, AC-07, AC-08, AC-51
  **依赖**: T042

- [x] **T044 实现：门户配置分区更新与版本返回**
  **文件**:
  - backend/app/services/portal_config_service.py
  **逻辑**:
  - update_department_business_domains 与既有 update_recommendation 都用 T043 返回的规范化聚合文档刷新本地状态。
  - 返回新配置分区与服务端 version，不回用客户端旧 version；远端失败时不发布半完成的本地配置。
  **配对测试**: T041
  **覆盖 AC**: AC-01, AC-05, AC-07, AC-08
  **依赖**: T043

- [x] **T045 实现：门户部门绑定管理路由**
  **文件**:
  - backend/app/api/routes/admin_config.py
  **逻辑**:
  - 新增 GET/POST /api/v1/admin/config/department-business-domains；推荐参数继续现有 recommendation。
  - 复用管理员认证，返回规范化分区与服务端 version；部门树读取可复用，但不复用旧知识库绑定写语义。
  **配对测试**: T041
  **覆盖 AC**: AC-01, AC-05, AC-07
  **依赖**: T044

- [x] **T046 测试：门户可信用户与租户身份**
  **文件**:
  - backend/tests/test_portal_auth_identity.py
  **测试**:
  - BiSheng /api/v1/user/info 的 id/user_id 与 tenant_id 被解析进 PortalUserView、序列化到 Redis 会话并可向后读取旧会话。
  - 缺少可信 id 时不让前端或 account 冒充内部 user_id；灰度服务按安全旧逻辑处理。
  **覆盖 AC**: AC-37, AC-42
  **依赖**: 无

- [x] **T047 实现：门户会话扩展可信身份**
  **文件**:
  - backend/app/schemas/auth.py
  - backend/app/services/portal_auth_service.py
  **逻辑**:
  - PortalUserView 增加向后兼容的 user_id、tenant_id；登录校验从 BiSheng user/info 服务端字段读取并进入 PortalSession。
  - Redis 旧会话缺字段时可反序列化，但不得由客户端请求参数覆盖可信身份。
  **配对测试**: T046
  **覆盖 AC**: AC-37, AC-42
  **依赖**: T046

- [x] **T048 测试：门户首页灰度、影子、缓存和降级**
  **文件**:
  - backend/tests/test_personalized_home.py
  - backend/tests/test_portal_home_cache_service.py
  **测试**:
  - 匿名始终 latest_selected 且保留公共缓存；登录用户绕过完整首页公共缓存。
  - 精确 SHA-256 稳定桶在 0/10/50/100 分流；影子优先并始终返回旧结果。
  - 个性化传输/5xx/业务失败用当前用户 token 降级；安全 200 空/部分不降级。
  - 首页只取 section_page_size，推荐模式以向后兼容 SSE 可选字段返回。
  **覆盖 AC**: AC-23, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42
  **依赖**: T044, T047

- [x] **T049 实现：门户首页服务和缓存边界**
  **文件**:
  - backend/app/services/knowledge_service.py
  - backend/app/services/portal_home_cache_service.py
  **逻辑**:
  - raw = tenant_id:user_id:personalized_v1 的 UTF-8，取 SHA-256 前 8 字节大端无符号 mod 100。
  - 登录命中灰度请求 personalized_v1；异常用同一用户 token 请求 latest_selected；匿名旧链路与缓存不变。
  - 影子后台计算只记指标不改变响应；登录用户不写/读完整首页公共缓存。
  **配对测试**: T048
  **覆盖 AC**: AC-23, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42
  **依赖**: T048

- [x] **T050 实现：首页 SSE Route 分流**
  **文件**:
  - backend/app/api/routes/knowledge.py
  **逻辑**:
  - 从 PortalSession 取得可信 tenant_id/user_id 传给首页服务；登录用户绕过完整首页公共缓存。
  - 保持既有 SSE 事件结构，只在推荐区块增加可选 recommendation_mode，供更多页和预览使用。
  **配对测试**: T048
  **覆盖 AC**: AC-37, AC-38, AC-39, AC-40
  **依赖**: T047, T049

- [x] **T051 测试：门户搜索遥测和预览入口**
  **文件**:
  - backend/tests/test_portal_search_telemetry.py
  - backend/tests/test_portal_preview_entry_point.py
  **测试**:
  - 登录用户三类显式动作各上报一次；筛选、排序、分页、重试不产生新搜索事件。
  - preview 透传 home_recommendation/recommendation_list/search 等 entry_point 与 personalized_v1/latest_selected 场景。
  **覆盖 AC**: AC-33, AC-35
  **依赖**: T029

- [x] **T052 实现：门户搜索遥测 Schema 与服务**
  **文件**:
  - backend/app/schemas/knowledge.py
  - backend/app/services/portal_telemetry_service.py
  **逻辑**:
  - 请求只接受 query 与 entry_point；entry_point 限 search_page、home_hot_keyword，用户和租户永远从会话注入。
  - 遥测服务转发 portal_search 以及阅读 entry_point/recommendation_scene，不记录搜索原文到普通日志。
  **配对测试**: T051
  **覆盖 AC**: AC-33, AC-35
  **依赖**: T051

- [x] **T053 实现：门户搜索与预览后端路由**
  **文件**:
  - backend/app/api/routes/knowledge.py
  **逻辑**:
  - 新增认证 portal_search 路由并委托 T052；筛选、分页和重试路由不自动上报。
  - preview 路由透传准确 entry_point 与 recommendation_scene，兼容旧二值入口。
  **配对测试**: T051
  **覆盖 AC**: AC-33, AC-35
  **依赖**: T052

- [x] **T054 测试：前端绑定与推荐配置**
  **文件**:
  - frontend/tests/departmentBusinessDomainBindings.test.ts
  - frontend/tests/portalConfig.test.ts
  **测试**:
  - 部门精确单选、业务域多选、无继承开关、重复部门/非法空值校验和清空保存。
  - Top N、四参数、影子和 0-100 灰度边界；旧配置默认兼容。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07, AC-42
  **依赖**: T045

- [x] **T055 实现：前端配置 API 与独立绑定面板**
  **文件**:
  - frontend/src/api/adminConfig.ts
  - frontend/src/pages/admin/DepartmentBusinessDomainBindingsPanel.tsx
  **逻辑**:
  - 增加绑定 GET/POST DTO，并接受服务端 version；部门使用精确单选，业务域从配置 domains 多选。
  - 不提供继承开关，禁止重复部门并支持删除行/清空绑定。
  **配对测试**: T054
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-07
  **依赖**: T054

- [x] **T056 实现：推荐配置面板与样式**
  **文件**:
  - frontend/src/pages/admin/RecommendationPersonalizationPanel.tsx
  - frontend/src/pages/AdminPage.module.css
  **逻辑**:
  - 提供 Top N、四参数、影子和灰度控件及行内范围错误；样式复用管理页 token 和响应式规则。
  **配对测试**: T054
  **覆盖 AC**: AC-06, AC-42
  **依赖**: T055

- [x] **T057 实现：管理页挂载独立面板**
  **文件**:
  - frontend/src/pages/AdminPage.tsx
  **逻辑**:
  - 独立挂载部门业务域绑定与推荐个性化面板，保持现有页面结构。
  - 不把精确绑定合入业务域/知识空间旧表单；保存后使用 API 返回的新 version 刷新。
  **配对测试**: T054
  **覆盖 AC**: AC-01, AC-02, AC-06, AC-42
  **依赖**: T055, T056

- [x] **T058 测试：前端首页与更多页回归**
  **文件**:
  - frontend/tests/personalizedRecommendationFlow.test.ts
  - frontend/tests/latestSelectedRecommendation.test.ts
  **测试**:
  - SSE recommendation_mode 驱动更多链接；personalized_v1 一次取 home_total_count、保持顺序、无无限滚动。
  - 首页不足和 13 篇结果正确；匿名及 latest_selected 源码/行为回归不变。
  - 点击首页热门词在导航前只上报一次 portal_search(entry_point=home_hot_keyword)，重渲染不重复。
  **覆盖 AC**: AC-33, AC-37, AC-38, AC-39, AC-40, AC-41
  **依赖**: T050

- [x] **T059 实现：前端 SSE 消费与首页**
  **文件**:
  - frontend/src/api/content.ts
  - frontend/src/pages/HomePage.tsx
  **逻辑**:
  - HomeStreamEvent/streamHomeContent 保留可选 recommendation_mode；首页用实际模式构造更多链接和预览 context。
  - 首页热门词点击调用 portal_search(entry_point=home_hot_keyword) 一次；推荐卡预览向 Modal 传 home_recommendation 与实际 recommendation_mode。
  - 匿名和旧事件缺字段时保持 latest_selected 既有行为。
  **配对测试**: T058
  **覆盖 AC**: AC-33, AC-35, AC-37, AC-38, AC-39, AC-40
  **依赖**: T058

- [x] **T060 实现：个性化更多页一次加载**
  **文件**:
  - frontend/src/pages/ListPage.tsx
  **逻辑**:
  - 识别 personalized_v1，以 home_total_count 一次请求完整 Top N、保持服务端顺序并关闭后续分页/无限滚动。
  - 推荐列表预览向 Modal 传 entry_point=recommendation_list 和 recommendation_scene=personalized_v1；旧列表使用兼容场景。
  - 结果不足展示实际数量；latest_selected 和普通列表分页流程不变。
  **配对测试**: T058
  **覆盖 AC**: AC-40, AC-41
  **依赖**: T058, T059

- [x] **T061 测试：前端显式搜索与预览来源**
  **文件**:
  - frontend/tests/searchTelemetry.test.ts
  - frontend/tests/filePreview.test.ts
  **测试**:
  - 回车、搜索按钮、热门词各上报一次；筛选、排序、分页、retry、重渲染不报。
  - iframe URL、DetailPage 与 fetchFilePreview 精确携带 home_recommendation、recommendation_list、search 和 recommendation_scene，旧调用有安全默认。
  **覆盖 AC**: AC-33, AC-35
  **依赖**: T053

- [x] **T062 实现：前端显式搜索遥测**
  **文件**:
  - frontend/src/pages/SearchPage.tsx
  - frontend/src/api/content.ts
  **逻辑**:
  - 搜索 API 只发送 query 与 search_page/home_hot_keyword；显式动作使用动作 ID 去重。
  - 搜索结果预览向 Modal 传 entry_point=search、recommendation_scene=null。
  - 筛选、排序、分页、retry 与组件重渲染不得调用遥测 API。
  **配对测试**: T061
  **覆盖 AC**: AC-33
  **依赖**: T061

- [x] **T063 实现：预览 Modal 与 URL 上下文**
  **文件**:
  - frontend/src/components/FilePreviewModal.tsx
  - frontend/src/utils/filePreview.ts
  **逻辑**:
  - Modal props 接收 entry_point/recommendation_scene；resolvePreviewModalFrameUrl 将其编码进 iframe URL。
  - 消费 T059/T060/T062 调用方传入的统一 context，不再把所有 embed 视作搜索。
  **配对测试**: T061
  **覆盖 AC**: AC-35
  **依赖**: T059, T060, T061, T062

- [x] **T064 实现：DetailPage 与预览 API 透传**
  **文件**:
  - frontend/src/pages/DetailPage.tsx
  - frontend/src/api/content.ts
  **逻辑**:
  - DetailPage 从 URL 读取 entry_point/recommendation_scene 并传给 fetchFilePreview。
  - fetchFilePreview 同时向后端携带两个字段；旧 URL 缺字段时使用 other/null，不误报首页来源。
  **配对测试**: T061
  **覆盖 AC**: AC-35
  **依赖**: T063

### 阶段 6：文档、回归、性能与门禁

- [x] **T065 文档：门户技术方案改为聚合配置同步**
  **文件**:
  - docs/specs/2026-07-14-首页个性化推荐技术方案.md
  **逻辑**:
  - 第 12.2、实现清单和配置同步表删除两个独立 BiSheng 同步接口。
  - 改为复用 PUT /api/v1/shougang-portal/config，并说明配置+规范化绑定表同事务提交和服务端返回新版本。
  **覆盖 AC**: AC-01, AC-08
  **依赖**: T043

- [x] **T066 验证：BiSheng 定向回归与架构守卫**
  **文件**: 本 tasks.md 实际偏差记录
  **验证**:
  - cwd=src/backend：按新增测试文件运行 .venv/bin/python -m pytest；对改动路径运行 uv run ruff check。
  - 逐文件运行 scripts/arch-guard.sh，运行 scripts/check-rbac-rebac-leak.sh，并用 uv run alembic heads 断言单 head。
  - 失败命令、退出码和已知无关失败写入实际偏差记录。
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19, AC-20, AC-21, AC-22, AC-23, AC-24, AC-25, AC-26, AC-27, AC-28, AC-29, AC-30, AC-31, AC-32, AC-34, AC-35, AC-36, AC-43, AC-44, AC-45, AC-46, AC-47, AC-48, AC-49, AC-51, AC-52
  **依赖**: T012, T014, T016, T018, T020, T022, T024, T026, T029, T031, T033, T036, T038, T039, T040

- [x] **T067 验证：门户后端与前端回归**
  **文件**: 本 tasks.md 实际偏差记录
  **验证**:
  - cwd=portal/backend：.venv/bin/python -m pytest backend tests 的新增和受影响文件。
  - cwd=portal/frontend：npm test、npm run lint、npm run build。
  - 记录失败命令、退出码与环境缺失，不新增不存在的门户 ruff/架构守卫命令。
  **覆盖 AC**: AC-01, AC-02, AC-05, AC-06, AC-07, AC-08, AC-23, AC-33, AC-35, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42, AC-51
  **依赖**: T045, T047, T050, T053, T057, T059, T060, T062, T063, T064, T065

- [ ] **T068 验证：推荐性能预算**
  **文件**: features/v2.5.0-sg/056-home-personalized-recommendation/performance-results.md
  **验证**:
  - 用 10000 轻量候选、最多 200 权限检查、不同通过率及 1/20/100/200 空间验证推荐 P95 <800ms、首个 SSE 区块 P95 <1s。
  - 分离打分、权限上下文、权限批次和 SSE 首块耗时；真实服务缺失时只标记 BLOCKED，不用单元时间冒充 P95。
  **覆盖 AC**: AC-24, AC-28, AC-32, AC-50
  **依赖**: T066, T067

- [ ] **T069 强制门禁：E2E**
  **文件**: features/v2.5.0-sg/056-home-personalized-recommendation/e2e-results.md
  **验证**:
  - 按 /e2e-test 运行匿名、登录灰度、影子、失败降级、更多页、配置保存、搜索和预览入口。
  - 使用真实当前用户 token 验证 custom ACL/撤权；缺环境时记录阻塞条件和可复现步骤，不伪造通过。
  **覆盖 AC**: AC-23, AC-27, AC-29, AC-30, AC-33, AC-35, AC-37, AC-38, AC-39, AC-40, AC-41, AC-42
  **依赖**: T066, T067

- [x] **T070 强制门禁：两仓代码审查**
  **文件**: 本 tasks.md 实际偏差记录
  **验证**:
  - BiSheng 执行 /code-review --base feat/2.5.0-sg；门户执行 /code-review --base master。
  - 复核 git diff、租户/权限/事务边界、未跟踪文件和测试证据；关闭 HIGH/MEDIUM 后更新实现状态。
  **覆盖 AC**: AC-07, AC-27, AC-29, AC-30, AC-39, AC-45, AC-51
  **依赖**: T068, T069

---

## 实际偏差记录

| 任务 | 计划偏差 | 原因与影响 | 处理 |
|------|----------|------------|------|
| SDD tasks review | 超过仓库默认最多两轮，执行第三轮修订与复审 | 第二轮仍发现缓存失效、兴趣 Top 50、热门词遥测和门户接口拆分缺口；用户于 2026-07-15 明确授权继续 | 第三轮已关闭报告问题，随后创建功能分支并完成实现 |
| T066 BiSheng 定向与静态门禁 | 核心定向 191 passed / 6 warnings；扩展基线集合另有 6 个 setup errors | 基线测试引用当前服务不存在的 `force_sync_user_for_maintenance`；全量 changed Ruff 另有 329 个历史错误 | 未扩大修改范围；新增 F056 文件 Ruff 通过，新增代码行命中 0；compileall、单 Alembic head、架构与 RBAC/ReBAC 守卫通过 |
| T066 数据库迁移 | MySQL 与 DM8 均完成离线编译；未执行 DM8 实库升级/回滚 | 本机无 `dmSQLAlchemy` 与可连接 DM8 实例 | 按仓库 `DaMengImpl` 机制离线验证，两库均生成 2 张表与 5 个索引；实库验证保留为上线门禁 |
| T067 Portal 后端全量 | 345 passed / 8 failed | 2 个存量 QA 展示名断言与 `master` 当前路由行为不一致；2 个存量 chat fake 未实现已有上游路由；4 个因环境缺 `pytest-asyncio` | F056 定向 55 passed，`compileall` 通过；不修改无关基线 |
| T067 Portal 前端全量 | `npm test` 被 2 类存量 TypeScript 错误阻塞；`npm run lint` 有 13 errors/6 warnings | QA template 测试缺 `home_icon/homeIcon`，存量测试仍导入已不存在的 `fetchHomeContent`；lint 命中无关存量文件 | F056 定向 28 passed，定向 ESLint 通过，`npm run build` 通过 |
| T068 性能 | BLOCKED | 当前工作区无可连通的 DB/Redis/ES/OpenFGA/BiSheng/Portal 完整压测环境与账号 | 见 `performance-results.md`；不用单元测试耗时冒充 P95 |
| T069 E2E | BLOCKED | 缺完整集成环境、当前用户 token 和 custom ACL/撤权测试数据 | 见 `e2e-results.md`；保留上线前强制场景和解除阻塞条件 |
| T070 跨仓代码审查 | PASS | 无 P0/P1/P2 新问题；此前 generic 投影补偿、ES 有界分页、UTC watermark、上海自然日、14+3、生命周期失效及 AC-47 补建问题均已关闭 | 允许交付集成环境；正式全量前仍需通过 T068、T069 与 DM8 实库门禁 |

## 上线完成定义（尚待 T068、T069 与 DM8 实库门禁）

- 每项任务目标文件与 tasks.md 一致，配对测试先完成并通过，L1 task review 无 HIGH。
- 52 条 AC 均有可执行证据；数据库、Redis、ES、权限和 Worker 均保持租户隔离。
- 两仓功能分支保留本地，不 commit、不 push；技术方案纳入门户功能分支。
