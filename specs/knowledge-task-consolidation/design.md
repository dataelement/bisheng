# 知识库任务精简：设计说明

## 元信息 Metadata

- Feature ID: `knowledge-task-consolidation`
- Status: `local-verified`
- Related requirements: `requirements.md`
- Created: `2026-09-23`
- Updated: `2026-09-23`

## 上下文与目标

规划基于本地当前工作区，不代表部署状态。知识库 Worker 定义经 AST 枚举共 53 个；统计任务另在 telemetry 中。相似候选已经在解析成功后直接执行，旧任务已在本会话先前改动中移除。

实施后 AST 枚举为 49 个，四个目标入口已移除。实际验证和环境边界见 verification.md。

已核对的关键落点均以仓库根目录为基准：

- src/backend/bisheng/worker/knowledge/portal_recommendation.py：prepare 在读取配置、增加 desired_generation 后投递 rebuild；单条、批量、资源刷新均复用 refresh_file。
- src/backend/bisheng/worker/knowledge/file_title_worker.py、file_worker.py：旧标题入口委托首次解析，首次解析直接执行普通标题函数。
- src/backend/bisheng/worker/knowledge/portal_hot_search.py：两个重建入口均调用 _rebuild_async，但重试配置不同。
- src/backend/bisheng/knowledge/domain/services/portal_hot_search_admin_service.py：手动触发返回任务名称，需要随生产者一起改。
- src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py：删除和部分更新已经使用批量刷新 helper，不能假设当前一律逐文件投递。
- src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_redis_repository.py：已有租户 key、desired_generation、版本池和激活保护。

## 边界承诺 Boundary Commitments

| Boundary | Allowed Change | Disallowed Change | Revalidation Trigger |
|---|---|---|---|
| Worker 调度 | 合并本期入口、调整对应生产者与注册 | 改队列数量、调整其他维护任务频率 | 出现额外任务或调度范围 |
| 数据 | 批量调用已有仓储；推荐池请求上下文使用现有 Redis | 数据库 Schema、推荐排序、全文结构、权限规则变更 | 需要新表或改变业务版本含义 |
| API | 同步热搜返回的实际任务名称 | 返回结构、鉴权、业务响应变化 | 外部调用方依赖旧任务名称 |
| 工作区 | 新 spec 及实施时列出的目标落点 | 覆盖相似计算改动、迁移/清理等其他进行中的修改 | 目标文件出现新增并行改动 |

- Allowed dependencies: `none`，使用已有 Celery、Redis、数据库仓储。
- 遵守现有分层，新增原子 Redis 操作放仓储层，不把存储脚本嵌入业务入口。

## 方案一：推荐池准备与计算在一次交付内完成

目标链路：租户分发/配置变更 → 单个重建任务 → 初始化本次上下文 → 计算 → 验证并激活。

1. 保留现有 rebuild 的注册名称作为唯一租户重建任务，删除 prepare 的 Celery 包装。所有入口直接投递 rebuild；跨租户 fanout 保留。
2. 准备阶段改为普通协程，直接 await _rebuild_shared_pools_async，不能在事件循环里嵌套同步 run_async_task。
3. 统一消息携带稳定 request_id 与请求创建时间；一次请求生成后，Celery retry 和同消息重投递复用它。租户由现有 header/context 传递并校验。
4. 为避免“已增加 generation 但丢失返回值”导致重试分配新 generation，仓储新增原子 get-or-create：按 tenant_id/request_id 保存 generation、config_version、fingerprint，并原子增加 desired_generation。相关 key 使用现有租户 hash tag。执行前查询已有上下文，存在则复用，不从新配置覆写。
5. 上下文保留期建议 7 天，覆盖现有三次退避重试与恢复窗口；请求超过同一窗口直接作为过期请求跳过，避免 key 已过期后旧消息重新占用最新 generation。这是计划中的新边界，需要在发布说明中明确；不是生产现状。
6. 配置已改变或请求已被更新 generation 取代时沿用现有拒绝激活机制。已成功激活的同一请求重投递直接返回完成，不重复建设池。保留构建前后配置检查、完整性检查、CAS 激活、三次退避重试和 1800 秒执行限制。
7. Redis 领取失败、超时或上下文不完整时失败重试；不得生成替代版本绕过问题。普通 .retry 与 Worker 丢失后的重投递都纳入验证。

取舍：仅把准备函数内联而不保护请求上下文更短，但会改变重试期间版本分配语义，因此采用小范围 Redis 请求记录，不引入新的通用调度系统。

## 方案二：删除标题旧任务入口

删除 extract_knowledge_file_title_celery 及其独有装饰器/import、Worker 注册、路由白名单与模板条目。保留 file_title_worker.py 中 extract_and_generate_alias 及其单测，不因删除任务而删除整个模块。

run_initial_knowledge_parse_lifecycle 继续处理标题，再执行正式解析；run_retry_knowledge_parse_lifecycle 保持不处理标题。梳理 KNOWLEDGE_PARSE_COMPAT_TASKS 的所有使用者后移除旧标题成员，不能误伤首次解析/重试/全文修复的路由或优先级配置。

## 方案三：统一热搜入口，保留触发策略

保留 rebuild_portal_hot_search_snapshot 的注册名称，增加 trigger 参数（manual / scheduled）。管理接口传 manual，定时租户 fanout 传 scheduled，未传参数的既有定时消息按 scheduled 处理。

- 两种来源直接调用同一个 _rebuild_async 和已有互斥锁。
- 通过显式重试分支保留 scheduled 最多三次退避重试、manual 不自动重试；不要直接给统一任务加无条件 autoretry。
- 定时生产者传递原有 1800 秒限制，手动入口不额外扩大或缩小原限制。不得把 threads 池下的 time_limit 当作可靠强杀证明。
- 管理接口返回统一 task_name，权限判断、租户 header、task_id 返回方式不变。
- 删除 trigger_portal_hot_search_rebuild 的旧注册与对应独立任务测试，测试两种来源的结果和失败策略。

## 方案四：统一推荐投影有界批次

保留批量任务注册名称，消息改为 events 列表，每个事件为 file_id、projection_version（允许普通更新为空）、deleted。tenant_id 仍由本批 header/context 决定，禁止混租户。

保留调用端现有单条/批量 helper 作为普通适配函数，统一发布同一个批量任务，删除单条 Celery 注册。这样调用方不必为了形式统一大面积改写。

- 单条普通更新的空版本继续由源记录推导，不统一替换成当前时间。
- 原批量显式更新/删除在业务调用时生成一次事件版本，切分批次和重试时复用，不在消费时重新生成。
- 先删除完全相同的事件，再按每批 100 条分片；保留同文件非等价事件顺序，不简单用“最后一条”覆盖显式删除或不同版本。
- 每批使用一个会话/事务，失败整批回滚并最多五次退避重试；批次之间独立。沿用仓储现有版本与删除保护，不把“消费者有锁”当作版本保护的替代品。
- 已有列表调用维持列表提交，资源级分页、增量/全量校准继续使用各自任务；跨任务上传完成事件不做延时聚合。
- 部分批次投递成功而后续 broker 失败时，不报告全部投递成功；记录失败批次，沿用现有生产者异常处理与周期校准。该方案不新建可靠 Outbox，也不宣称解决现有投递丢失问题。

## 文件结构计划 File Structure Plan

| Path（相对仓库根目录） | Action | Responsibility | Linked Requirement |
|---|---|---|---|
| src/backend/bisheng/worker/knowledge/portal_recommendation.py | modify | 推荐池单任务、统一投影批次与生产 helper | REQ-001, REQ-004 |
| src/backend/bisheng/knowledge/domain/repositories/interfaces/portal_recommendation_redis_repository.py | modify | 请求上下文仓储契约 | REQ-001 |
| src/backend/bisheng/knowledge/domain/repositories/implementations/portal_recommendation_redis_repository.py | modify | 请求上下文原子领取、读取与保留期 | REQ-001 |
| src/backend/bisheng/worker/knowledge/file_title_worker.py | modify | 仅删除旧任务包装，保留标题函数 | REQ-002 |
| src/backend/bisheng/core/config/celery_queues.py | modify | 删除旧标题路由成员 | REQ-002 |
| src/backend/bisheng/config_3002.yaml、config_3003.yaml 及全仓命中的部署模板 | modify | 删除旧任务精确路由，不改其他配置 | REQ-002, REQ-005 |
| src/backend/bisheng/worker/knowledge/portal_hot_search.py | modify | 统一热搜任务及分发 | REQ-003 |
| src/backend/bisheng/knowledge/domain/services/portal_hot_search_admin_service.py | modify | 手动生产者与响应任务名 | REQ-003 |
| src/backend/bisheng/worker/__init__.py | modify | 同步移除任务注册 | REQ-001, REQ-002, REQ-003, REQ-004 |
| src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py、src/backend/bisheng/approval/domain/services/shougang_approval_handler.py | inspect / modify only if needed | 核对业务列表粒度、租户与版本参数；禁止扩大审批行为改动 | REQ-004 |
| src/backend/test/knowledge/test_portal_recommendation_worker.py、test_portal_recommendation_redis_repository.py、test_portal_recommendation_projection.py | modify | 版本并发、批次事务和投递数量验证 | REQ-001, REQ-004 |
| src/backend/test/knowledge/test_file_title_worker.py、test_knowledge_file_parse_lifecycle.py、test_knowledge_parse_processing_lease.py；src/backend/test/celery/test_knowledge_parse_queue_routing.py | modify / run | 普通函数、解析链路、交付跟踪与模板引用 | REQ-002, REQ-005 |
| src/backend/test/knowledge/test_portal_hot_search_worker.py、test_portal_hot_search_api.py | modify | 热搜任务、来源、锁与响应契约 | REQ-003 |

## 需求追踪与验证策略

| Requirement | Acceptance Criteria | Design Element | Verification Strategy |
|---|---|---|---|
| REQ-001 | AC-001, AC-002, AC-003 | 方案一 | V-001：并发/状态 V3，Worker 定向回归 + 原子 Redis 集成；多 AC 复用同批证据 |
| REQ-002 | AC-004, AC-005 | 方案二 | V-002：跨入口 V2；保留普通函数测试，首次/重试及模板检查 |
| REQ-003 | AC-006, AC-007 | 方案三 | V-003：API/Worker V2；参数化触发来源，不重复测试排序算法 |
| REQ-004 | AC-008, AC-009, AC-010, AC-011 | 方案四 | V-004：事务/乱序 V3；调用计数与数据库结果验证，MySQL/DM8 不引入方言差异 |
| REQ-005 | AC-012, AC-013 | 边界和发布方案 | V-005 静态检查；V-006 受控环境冒烟与发布说明 |

各实现批次只运行其相关测试；最终运行受影响测试文件的并集一次。若已有失败，在同一环境与实现前基线对照，不将已有失败归因于本次修改。真实 Redis、Worker/Broker 和可用数据库实例验证分开记录；缺失则标 MANUAL_REQUIRED，不以 mock 通过代替真实依赖结论。

## 发布与回滚方案（仅规划）

1. 分批提交，记录每批代码版本与验证证据；不自动提交用户其他改动。
2. 发布前盘点目标旧任务的 queued、reserved、active、scheduled/retry 消息及生产者，包括 API、Beat、Worker 派生任务。共享队列不整体 purge。
3. 在维护窗口停止目标生产入口，保留旧 Worker 消费已存在消息；确认目标旧消息处理完毕。无法排空时先制定定向重投方案并单独确认，不让新 Worker 默默丢弃旧消息。
4. Worker、API、Beat 按同一消息契约切换，再恢复入口。最终代码不保留旧包装，因而不支持无约束混跑。
5. 观察未注册任务、租户不匹配、generation 拒绝、重试耗尽、批次失败和队列等待时间；收益以实际投递计数核对。
6. 回滚时先停止新生产者，处理新参数消息，再同步回退生产者与 Worker。Redis 请求上下文按保留期自然过期，不回退 active_generation，不删除业务推荐数据。

## 设计质量门

- [x] 五项需求全部映射到设计和验证。
- [x] 四个独立变更批次、文件边界和任务参数变更明确。
- [x] 正常任务、重试、跨租户分发与恢复机制未混为一类。
- [x] 真实依赖验证与发布不作为本轮已完成内容。
