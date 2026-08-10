# 任务拆分 Tasks: 知识文件解析三级优先级与排队位置可视化

## 阅读摘要
- 本文档用于指导 Agent 按任务实现角色等级、文件快照、文件级单 delivery 生命周期、Redis 单队列优先消费和排队位置近似展示。
- 每个任务必须保持在声明的边界内；不得拆分队列、增加解析并发或实现公平调度。
- task metadata 字段保持英文固定格式，便于 Agent 稳定读取。
- 推荐执行顺序：公共契约与角色解析 → 文件快照 → 统一投递 → 文件级生命周期合并 → Worker 配置 → 排队索引与生命周期 → 无阶段 API/前端 → 发布验证。
- 阅读摘要用于快速理解；任务依赖、边界、需求映射和验证映射以 task metadata 与 Coverage Matrix 为准。

## 元信息 Metadata
- Feature ID: `052-knowledge-file-parse-priority`
- Status: `in-progress`
- Related requirements: `specs/052-knowledge-file-parse-priority/requirements.md`
- Related design: `specs/052-knowledge-file-parse-priority/design.md`
- Created: `2026-08-06`
- Updated: `2026-08-09`

## 任务格式 Task Format

Every implementation task must include:
- Checkbox and task ID.
- Requirement ID.
- Acceptance criterion ID when behavioral.
- Verification method or verification ID.
- Boundary when scope-sensitive or parallel-safe.

共享同一交付行为或验证命令的 tasks 应组成 verification batch；只有确需新增基础设施时才创建独立 test harness task。不要为每个 AC、角色、状态或代码分支分别创建测试任务。

Task metadata order must stay stable:
1. `_Requirements: ..._`
2. `_Acceptance: ..._`
3. `_Verification: ..._`
4. `_Depends: ..._`
5. `_Boundary: ..._`

## 阶段 1：角色等级契约 Role Priority Contract

- [x] T001 定义统一业务等级并扩展角色配置校验
  - 实现 `KnowledgeParsePriority` 及 rank、Celery priority 的唯一映射：`high→0`、`medium→3`、`low→9`；业务代码不得散落硬编码数值。
  - 增加角色专用 quota validator，在现有 `Role.quota_config` 允许 `knowledge_file_parse_priority`，缺键按中优读取，只接受三个字符串枚举值；不得把该键加入租户也会使用的通用白名单。
  - 角色创建/更新改用角色专用入口；增加 Role/Tenant API/Service 定向测试，验证合法值保存/返回、缺键兼容、非法类型/值拒绝、租户配额拒绝该键和原有角色权限拒绝不变。
  - Done when: 角色配置后端契约可稳定保存三档值，旧 payload 无新增键仍通过，非法值沿用现有角色错误契约拒绝，租户配额无法写入该键；EG-001 的后端证据通过。
  - _Requirements: REQ-001, REQ-005_
  - _Acceptance: AC-REQ-001-02, AC-REQ-001-03, AC-REQ-001-04, AC-REQ-001-05, AC-REQ-001-06, AC-REQ-005-01, AC-REQ-004-05_
  - _Verification: V-AC-REQ-001-02, V-AC-REQ-001-04, V-AC-REQ-001-05, V-AC-REQ-001-06, V-AC-REQ-005-01, V-AC-REQ-004-05; EG-001_
  - _Depends: none_
  - _Boundary: backend priority enum and role quota validation only_

- [x] T002 [P] 实现租户范围的用户有效等级解析
  - 新增 Role Priority Repository interface/implementation，在与文件一致的现有租户上下文和自动注入机制下只读取指定用户的有效角色；不新增 DAO 入口，不手写 `WHERE tenant_id = ...` 或跨租户兜底。
  - 新增等级解析服务：多角色取最高、全局超级管理员固定高、可识别用户无角色/缺键为中、无用户或用户不存在为低、依赖异常记录上下文并降级低。
  - 使用参数化单元测试覆盖独立决策出口；验证其他租户的高等级角色不能抬高当前文件等级。
  - Done when: EG-002 覆盖租户隔离、多角色最高、默认、超级管理员、缺失用户和异常降级，且服务只通过 Repository/现有超管能力访问数据。
  - _Requirements: REQ-002_
  - _Acceptance: AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03, AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06_
  - _Verification: V-AC-REQ-002-01, V-AC-REQ-002-04, V-AC-REQ-002-06; EG-002_
  - _Depends: T001_
  - _Boundary: role domain repository and priority resolution service only_

- [x] T003 [P] 在角色新建/编辑弹窗接入等级配置
  - 从既有超长 `Roles.tsx` 抽出 `RoleParsePriorityField`，使用 Platform 现有 `bs-ui` 控件展示高、中、低单选，不新增角色列表列。
  - 新建角色和缺配置的旧角色回显中优；编辑提交时与其他 `quota_config` 键合并，不能覆盖配额、审批模式或作用域值。
  - 在 `zh-Hans/en-US` 的 `bs.json` 增加文案，并新增组件测试覆盖选项、默认、保存 payload 和重新打开回显。
  - Done when: 角色弹窗可以配置并回显三档值，旧角色显示中优，提交 payload 保留无关配置；EG-001 的前端证据通过。
  - _Requirements: REQ-001_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-03_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02; EG-001_
  - _Depends: T001_
  - _Boundary: platform role editor component, tests, and bs locale files only_

## 阶段 2：文件快照 File Snapshot

- [x] T004 实现文件优先级可空快照和原子固化
  - 为 `KnowledgeFile` 增加 nullable `parse_priority`；创建 MySQL/DM8 兼容 Alembic migration，只新增/删除该列，不回填历史行。
  - 扩展 Knowledge File Repository interface/implementation，以 ORM 条件更新实现 `NULL` 时首次写入，并在竞争后读取数据库最终值。
  - 增加 migration、Repository 和并发语义测试，覆盖首次固化、重复调用不覆盖、历史空值和文件不存在/数据库错误路径。
  - Done when: 同一文件并发首次定级只保留一个值，已固化值不可被角色变化或重试覆盖；MySQL upgrade/downgrade 通过，DM8 验证已进入 CI 门禁。
  - _Requirements: REQ-003, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-05, AC-REQ-006-01, AC-REQ-006-05_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-003-05, V-AC-REQ-006-01; EG-003, EG-006_
  - _Depends: T001_
  - _Boundary: knowledge file model/repository, one Alembic migration, and their tests_

- [x] T005 组合角色解析与文件快照决策
  - 实现快照服务：已有快照直接返回；新文件使用认证操作者；历史空快照使用上传者当前租户角色；上传者为空或用户不存在固化低优。
  - 快照写入采用 T004 的 CAS；批量同用户同租户操作复用一次角色解析结果，避免 N+1。
  - 角色/FGA 查询异常记录 `file_id/tenant_id/priority` 并以低优继续固化；快照持久化失败则抛出并禁止继续发布。
  - Done when: 新文件、历史文件、角色变化、缺失上传者、并发和批量复用均得到规格定义的最终快照，且失败边界可观察。
  - _Requirements: REQ-002, REQ-003, REQ-006_
  - _Acceptance: AC-REQ-002-04, AC-REQ-002-05, AC-REQ-002-06, AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-006-02, AC-REQ-006-04_
  - _Verification: V-AC-REQ-002-04, V-AC-REQ-002-06, V-AC-REQ-003-01, V-AC-REQ-003-04, V-AC-REQ-003-05, V-AC-REQ-006-02, V-AC-REQ-006-04; EG-002, EG-003, EG-006_
  - _Depends: T002, T004_
  - _Boundary: knowledge snapshot orchestration service and focused tests only_

## 阶段 3：统一任务投递 Dispatch Integration

- [x] T006 实现解析任务统一投递服务
  - 为标题提取、首次解析和解析重试提供单一投递入口；先取得文件最终快照，再调用 `apply_async` 显式设置 `queue="knowledge_celery"`、映射 priority 和业务等级 header。
  - 三个 Celery task 声明中优 `3` 为默认 priority，保护遗漏显式等级的新增直接发布；不得改变 task name、参数、tenant header、callback、preview key 或 `acks_late`。
  - 模拟 broker 发布失败，验证异常与现有业务边界一致地传播并记录，不能静默丢弃 WAITING 文件；本任务不引入 outbox。
  - Done when: 三类任务共享同一消息契约，显式值来自文件快照，遗漏值至少为中优，发布成功和失败均有 contract test 证据。
  - _Requirements: REQ-003, REQ-004, REQ-006_
  - _Acceptance: AC-REQ-003-01, AC-REQ-003-02, AC-REQ-004-01, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-006-04_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-004-01, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-006-04; EG-004, EG-006_
  - _Depends: T005_
  - _Boundary: knowledge parse dispatch service, three task defaults, and contract tests_
  - 2026-08-09 scope note: 本任务记录已完成的阶段消息投递基线；“标题/解析/重试三消息”契约已被 REQ-004/REQ-008 修订，最终行为由 T013 收敛，不能以本任务旧验收作为文件级生命周期完成证据。

- [x] T007 将所有生产入口和后继任务接入统一投递
  - 替换 `knowledge_service.py`、`knowledge_space_service.py`、`knowledge_utils.py`、开放接口所经服务以及运维重解析脚本中的三任务直接 `.delay()`/未授权 `apply_async()`。
  - 标题提取 `finally` 发布正式解析和解析重试时必须重读同一文件快照并显式投递，不依赖父 Celery request priority。
  - 扩展 source/AST guard，禁止生产路径重新引入绕过；只对受影响的上传、批量重试、重解析、标题后继和租户上下文运行一次回归批次。
  - Done when: 代码搜索与 guard 证明所有已知生产入口均通过统一服务，标题/正式解析/重试 priority 一致，原任务参数和状态行为回归通过。
  - _Requirements: REQ-003, REQ-004_
  - _Acceptance: AC-REQ-003-02, AC-REQ-003-03, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04_
  - _Verification: V-AC-REQ-003-01, V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04; EG-003, EG-004_
  - _Depends: T006_
  - _Boundary: existing knowledge task producer call sites, title/retry successor paths, script, and source guard_
  - 2026-08-09 scope note: 本任务保留为已完成的生产入口集中化基线；标题 `finally` 发布正式解析的行为已被 REQ-004-02 禁止，T013 必须移除该后继发布并把所有入口切换为文件生命周期消息。

## 阶段 3A：文件级生命周期合并 File Lifecycle Consolidation

- [x] T013 将初次解析与重试收敛为单 delivery 文件生命周期
  - 复用既有正式解析/重试 task name，并以可选 `knowledge_parse_attempt_kind=initial|retry` header 固定最小滚动兼容契约：新生产入口每次文件尝试只投递初次解析或重试一个消息，不再发布标题子任务。旧标题消息由新 Worker 直接执行完整初次生命周期且不发布后继；缺 header 的旧正式解析只执行 formal parse；旧重试沿用兼容路径。
  - 抽取可复用标题提取 helper 和可接受文件已处于 PROCESSING 的 parse core。初次解析 delivery 领取后先把 WAITING 更新为 PROCESSING，再在同一 task 调用栈内串行执行标题提取和 parse core；标题或别名生成失败只记录日志并继续。重试 delivery 领取后先置 PROCESSING，再串行执行旧向量清理和 parse core，不重新执行标题；不得二次要求 WAITING 或重复切换状态。
  - 保持文件快照 priority、tenant header、callback、preview cache key、`acks_late` 及 SUCCESS/FAILED/VIOLATION/remark 终态兼容；PDF Artifact、相似文档候选、推荐投影继续按既有异步路由执行，不进入本生命周期 ticket。
  - 更新 dispatcher、任务默认 priority、白名单/route source guard 和所有 producer；滚动发布采用 Worker-first，覆盖旧标题、旧正式解析、旧重试消息的安全消费，禁止 purge 或 broker key 删除。
  - 增加 lifecycle worker 自动化测试，验证领取即 PROCESSING、标题成功/失败都进入同 delivery 正式解析、重试先清理且不标题、没有内部 `apply_async`/新 ticket、三类终态及后置任务边界。
  - Done when: 新生产路径的一次初次/重试只产生一个 broker 消息和一个 ticket；同一 delivery 内完成已定义主生命周期；旧消息可安全自然消费；自动化证据覆盖状态时点、失败与终态契约。
  - _Requirements: REQ-004, REQ-005, REQ-006, REQ-008_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-004-05, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-06_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-004-05, V-AC-REQ-005-05, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-008-01, V-AC-REQ-008-03, V-AC-REQ-008-06; EG-004, EG-005, EG-006, EG-008_
  - _Depends: T007_
  - _Boundary: parse dispatcher/producers, knowledge file title/parse/retry workers, lifecycle task routes/defaults, focused compatibility and lifecycle tests only_

## 阶段 4：Worker 消费与部署 Worker and Deployment

- [x] T008 配置专用 knowledge Worker 的 Redis 优先消费
  - 合并 Redis/Sentinel `broker_transport_options`，保持 Kombu 兼容默认 steps `0/3/6/9`；业务只使用 `0/3/9`。
  - 保持 `queue_order_strategy=round_robin`；增加配置 contract test，防止把多队列轮询策略误改为 `priority`。
  - 在 `src/backend/entrypoint.sh` 与 `docker/bisheng/entrypoint.sh` 的 knowledge 入口增加 `--prefetch-multiplier=1` 或等价配置，原 `KNOWLEDGE_CONCURRENCY`、旧入口 concurrency 和调用方 `-c` 保持不变。
  - 保持 `knowledge_celery` 三任务白名单，默认/workflow/PDF 队列路由与并发不变；部署文档明确组合 `run_celery.py` 不是生产优先级 SLA 验收入口。
  - Done when: 配置与启动脚本 contract test 证明默认 steps 与 prefetch 生效、`queue_order_strategy` 未变化、Sentinel 选项未被覆盖，并发和所有队列白名单无变化。
  - _Requirements: REQ-004, REQ-005, REQ-006_
  - _Acceptance: AC-REQ-004-01, AC-REQ-005-01, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-02_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-005-01, V-AC-REQ-005-03, V-AC-REQ-005-05, V-AC-REQ-006-02; EG-005, EG-006_
  - _Depends: T001_
  - _Boundary: celery redis/queue config, supported worker entrypoints, run_celery compatibility, and contract tests_
  - 2026-08-09 scope note: priority steps、prefetch 1 和并发保持部分继续有效；“三任务白名单”的最终收敛由 T013 按 REQ-005-05 完成。

## 阶段 5：排队位置可视化 Queue Position Visibility

- [x] T010 实现 Cluster-safe Redis 排队索引与位置计算
  - 定义逻辑 queue ticket、processing attempt、`attempt_kind=initial|retry`/state schema 和 Repository interface；Redis implementation 使用统一 `{knowledge_parse_queue}` hash tag、全局 sequence、三级 waiting ZSET、attempt member 的 processing/processing lease ZSET、ticket/attempt Hash、ticket→attempt ZSET 和 file→active tickets ZSET，禁止可被后写覆盖的单值 current pointer。
  - 使用 Lua/CAS 实现 publishing 创建、queued→attempt processing 转换、attempt lease 续期/过期清理、attempt-scoped fencing、无有效 attempt 时条件清理逻辑 ticket、硬 TTL 和批量 pipeline 查询；过期清理必须比较目标 attempt 的 lease deadline/identity，不能删除已被并发心跳续期的健康 attempt 或同 ticket 的其他 attempt；不得读取 Celery/Kombu 私有 key 或消息内容。
  - 实现位置 Service 的核心公式：更高等级 queued 总数 + 同级更早 rank；processing 只按有效 delivery attempt 计入独立 active count。同一文件存在多个 ticket/attempt 时优先最早有效 attempt 所关联的 processing ticket，否则选择按优先级和 sequence 实际调度最靠前的 queued ticket；Redis 异常、过期/缺失 ticket/attempt 或状态不一致返回 unavailable。
  - 增加真实 Redis Repository/Service 集成测试，参数化覆盖三级公式、同级序号、后到高优插队、processing 排除、同文件多 ticket 归并/互不清理、同 ticket 多 attempt 同时计数与 fenced 清理、Cluster key slot、lease/TTL 与失败降级。
  - Done when: EG-007 证明批量位置计算只使用应用自有索引，单 ticket 排名为 `O(log N)`，同文件多个 ticket 和同 ticket 多个 attempt 可并存且清理互不覆盖，过期 attempt 不计入 active count，索引故障可安全降级。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-02, AC-REQ-007-07, AC-REQ-007-09, AC-REQ-007-10, AC-REQ-007-12_
  - _Verification: V-AC-REQ-007-02, V-AC-REQ-007-07, V-AC-REQ-007-09, V-AC-REQ-007-10, V-AC-REQ-007-12; EG-007_
  - _Depends: T001_
  - _Boundary: knowledge parse queue schema/repository/service core and focused Redis tests only_

- [x] T011 将单 ticket 生命周期接入文件级 delivery 与 Worker
  - 统一投递服务为一次初次/重试尝试生成一个 `queue_ticket_id` 并复用为 Celery `task_id`；最佳努力创建 publishing ticket，消息显式携带 ticket/attempt-kind/priority header，发布后条件转 queued，发布失败最佳努力清理。
  - 文件生命周期任务共享 processing lease guard：每次 Worker delivery 生成全新不可预测 `processing_attempt_id`，入口 begin/rebuild logical ticket 后创建独立 attempt，租约覆盖标题/清理/正式解析全部内部步骤；任务期间只续期自身 attempt，结束时 fenced 清理自身，只有无其他有效 attempt 时才清理逻辑 ticket。
  - 正常初次/重试的内部步骤不得换票或新增 queued ticket；显式重试、重新解析、并发重复请求、滚动存量消息和 broker 重投递仍按真实消息/实际 delivery 独立观测。同一 Celery `task_id` 重领时复用逻辑 ticket 但创建新 attempt；旧版本无 ticket 消息安全降级，不修改全局 `visibility_timeout`，不把 Redis 旁路变为业务去重锁。
  - 增加生命周期集成测试，覆盖发布方与 Worker 竞态、publishing→processing 快路径、初次/重试全步骤单 ticket、同文件异常并发双 ticket、attempt 心跳续期、Worker 强退/心跳停止、租约有界过期、visibility timeout 在原执行完成前重投递同 task ID、两个 attempt 同时计数、两种结束顺序、旧消息无 ticket 和索引失败不中断解析。
  - Done when: 一次正常文件尝试从发布到 delivery 结束始终只有一个逻辑 ticket；Worker 强退后 active count 在租约窗口内收敛，同 task ID 重叠 delivery 互不续期/清理且最后一个有效 attempt 消失前保持 processing，任一旧 ticket 无法删除同文件其他 ticket，旁路故障不改变 Celery 发布和主状态。
  - _Requirements: REQ-004, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-04, AC-REQ-006-04, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-07, AC-REQ-007-09, AC-REQ-007-10, AC-REQ-007-12, AC-REQ-008-01, AC-REQ-008-03_
  - _Verification: V-AC-REQ-004-01, V-AC-REQ-004-04, V-AC-REQ-006-04, V-AC-REQ-007-03, V-AC-REQ-007-07, V-AC-REQ-007-09, V-AC-REQ-007-10, V-AC-REQ-007-12, V-AC-REQ-008-01, V-AC-REQ-008-03; EG-004, EG-006, EG-007, EG-008_
  - _Depends: T010, T013_
  - _Boundary: unified lifecycle dispatcher, initial/retry knowledge task lease integration, queue-index compatibility, and lifecycle tests_

- [x] T012 增加安全批量位置 API 和文件上传进度展示
  - 抽取/复用与知识空间文件列表一致的公共批量文件有效可见性服务，组合现有 Knowledge Permission、`knowledge_file:view_file`、资源所有者/管理员、适用部门审批授权和隐藏状态；Repository 只读取当前租户/目标知识库候选文件，不在数据层决定权限。
  - 在 knowledge domain schema/service 与 API dependency 中实现 `GET /api/v1/knowledge/{knowledge_id}/parse-queue-positions`；校验 1～100 个正整数 file IDs，先验证知识库读取权限，再经过批量文件有效可见性过滤，只返回最终授权文件；不存在、跨租户、跨知识库和不可见 ID 均省略且不可区分。
  - 响应使用 `resp_200` 返回 `{items, active_count, approximate: true, as_of}`；不返回内部 priority、ticket、其他文件或错误堆栈。Redis 不可用时对已授权待处理文件返回 unavailable。
  - Platform controller 增加有类型查询；`FileUploadStep4` 在现有 5 秒状态轮询内批量查询未结束文件，禁止同轮重复并发；`ProgressItem` 只展示“排队中，前方约 N 个等待任务”的通用排队文案，可独立展示运行数，终态停止，unavailable 退化为普通排队文案且不高频 toast；不得读取或展示内部 stage。
  - Client knowledge API 增加同一批量位置查询契约；`PortalUploadedFilesDrawer` 复用现有 5 秒上传记录轮询，对当前页 WAITING/PROCESSING/REBUILDING 文件按知识库分组查询位置；门户 queued 状态只展示“排队中，前方约 N 个等待任务”，不展示阶段和运行数，processing/unavailable 静默退化为原状态文案，终态不查询。
  - 首钢门户上传记录首次打开或切换分页时使用整表加载态；已有当前页数据时，自动轮询、上传触发刷新和手动刷新保持现有 keyed rows，并按文件 ID 合并服务端最新字段，刷新失败不得清空已有记录。
  - 增加 API/security 与 Platform/Client 前端组件测试，覆盖参数上下限、未登录、知识库可读但文件无 `view_file`、所有者/管理员、部门审批未通过/已授权/撤销、隐藏状态、跨租户/跨知识库，以及 queued/processing/not_queued/unavailable、动态数字增加、门户按知识库分组、简化文案、已有数据静默刷新、终态停止和失败降级；批量权限路径不得产生 100 次串行网络检查。
  - Done when: 文件级有效权限与现有知识空间文件可见性回归结果一致，有权限用户可以看到安全近似快照；越权与存在性无数据泄露，位置服务故障不影响既有状态轮询和解析完成判断。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-01, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07, AC-REQ-007-08, AC-REQ-007-11, AC-REQ-007-13_
  - _Verification: V-AC-REQ-007-01, V-AC-REQ-007-06, V-AC-REQ-007-07, V-AC-REQ-007-11, V-AC-REQ-007-13; EG-007_
  - _Depends: T003, T011_
  - _Boundary: shared knowledge-file visibility service, knowledge_space_service visibility extraction/integration, queue-position schema/service/API, existing visibility regressions, Platform controller/upload progress UI/locales, Client knowledge API/portal upload-record UI, and their tests_

- [x] T014 增加门户上传成功后的队列名次 Toast
  - 扩展位置响应增加 nullable `waiting_count`；Repository 汇总 high/medium/low waiting ZSET 的 queued ticket 数，不包含 publishing/processing，索引异常返回 `null` 且不影响既有 items/active count 降级。
  - Client API 映射 `waiting_count`；门户上传完成后只使用非重复、成功注册文件 ID 查询位置，超过 100 个 ID 时分批请求，选择本批最靠前的可靠 queued 文件。
  - 最靠前文件前方存在任务且 `waiting_count >= ahead_waiting_count + 1` 时，以单条 success Toast 替换“上传成功”：“上传成功，M 个文件已进入队列，最前第 X/Y 名”；无前方任务、无可靠位置、无效 X/Y 或查询失败时保留“上传成功”，不得阻断上传或弹错误 Toast。
  - 增加后端 waiting 总数与 Client upload hook 定向测试，覆盖 processing/publishing 排除、单/多文件聚合、重复文件排除、无排队和查询失败降级。
  - Done when: API 可返回安全近似 queued 总数，门户上传成功只显示一条符合口径的 success Toast，失败路径保持原上传成功体验，后端定向回归、Client hook 测试与 production build 通过。
  - _Requirements: REQ-007_
  - _Acceptance: AC-REQ-007-05, AC-REQ-007-14_
  - _Verification: V-AC-REQ-007-14; EG-007_
  - _Depends: T010, T012_
  - _Boundary: knowledge parse queue repository/schema/service API response, Client knowledge API mapping, portal upload dialog hook, focused backend/Client tests and SDD evidence only_

## 阶段 6：发布与验证 Release and Verification

- [ ] T009 完成发布文档与跨边界验收证据
  - 更新 knowledge 架构与部署文档：角色/文件等级语义、`0/3/9` 映射、prefetch 1、初次/重试单 delivery 生命周期、单 ticket/逐 delivery attempt 索引、attempt lease/心跳/fencing、文件级权限、无阶段近似口径、并发不变、全局 visibility timeout 不变、组合入口限制、Worker→producer→frontend 部署顺序、旧消息兼容、无 purge 和回滚步骤。
  - 在非生产 Redis 以独立 knowledge Worker `-c 1` 发布交错的低/中/高等待消息，记录高→中→低、同级 FIFO 和位置公式；另发布三个同优初次解析文件，记录“文件1完整生命周期→文件2完整生命周期→文件3完整生命周期”、每次尝试单 ticket、领取即 PROCESSING、内部步骤不换票。继续覆盖异常多 ticket、Worker 强退后租约收敛、同 task ID 在原执行未完成时重投递、两个 attempt 同时计数与两种结束顺序、索引故障降级证据。
  - 运行受影响的 backend/frontend 定向批次、架构检查和 migration upgrade/downgrade；DM8 证据来自 Linux CI，不得用 macOS 静态推断代替。
  - 在 `verification.md` 记录命令、环境、结果、失败路径、未验证项和 Redis 存量消息自然消费确认；同一代码状态不重复运行相同批次。
  - Done when: EG-001～EG-008 均有可追踪证据，真实 Redis 顺序、三个同优文件的完整生命周期 FIFO、单 ticket/attempt 生命周期、attempt lease 有界收敛、重叠 delivery 隔离、文件级权限与双库 migration 门禁满足，发布/回滚不包含全局 visibility timeout 变更、broker purge、broker key 删除或消息迁移。
  - _Requirements: REQ-001, REQ-002, REQ-003, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008_
  - _Acceptance: AC-REQ-001-01, AC-REQ-001-02, AC-REQ-001-05, AC-REQ-001-06, AC-REQ-002-01, AC-REQ-002-06, AC-REQ-003-01, AC-REQ-003-04, AC-REQ-003-05, AC-REQ-004-01, AC-REQ-004-02, AC-REQ-004-03, AC-REQ-004-04, AC-REQ-005-01, AC-REQ-005-02, AC-REQ-005-03, AC-REQ-005-04, AC-REQ-005-05, AC-REQ-005-06, AC-REQ-006-01, AC-REQ-006-02, AC-REQ-006-03, AC-REQ-006-04, AC-REQ-006-05, AC-REQ-007-01, AC-REQ-007-02, AC-REQ-007-03, AC-REQ-007-04, AC-REQ-007-05, AC-REQ-007-06, AC-REQ-007-07, AC-REQ-007-08, AC-REQ-007-09, AC-REQ-007-10, AC-REQ-007-11, AC-REQ-007-12, AC-REQ-007-13, AC-REQ-007-14, AC-REQ-008-01, AC-REQ-008-02, AC-REQ-008-03, AC-REQ-008-04, AC-REQ-008-05, AC-REQ-008-06_
  - _Verification: V-AC-REQ-001-01, V-AC-REQ-001-02, V-AC-REQ-001-05, V-AC-REQ-001-06, V-AC-REQ-002-01, V-AC-REQ-002-06, V-AC-REQ-003-01, V-AC-REQ-003-04, V-AC-REQ-004-01, V-AC-REQ-004-03, V-AC-REQ-004-04, V-AC-REQ-005-01, V-AC-REQ-005-02, V-AC-REQ-005-03, V-AC-REQ-005-05, V-AC-REQ-006-01, V-AC-REQ-006-02, V-AC-REQ-006-03, V-AC-REQ-006-04, V-AC-REQ-007-01, V-AC-REQ-007-02, V-AC-REQ-007-03, V-AC-REQ-007-06, V-AC-REQ-007-07, V-AC-REQ-007-09, V-AC-REQ-007-10, V-AC-REQ-007-11, V-AC-REQ-007-12, V-AC-REQ-007-13, V-AC-REQ-007-14, V-AC-REQ-008-01, V-AC-REQ-008-03, V-AC-REQ-008-05, V-AC-REQ-008-06; EG-001, EG-002, EG-003, EG-004, EG-005, EG-006, EG-007, EG-008_
  - _Depends: T003, T008, T012, T013, T014_
  - _Boundary: docs, verification.md, read-only verification commands, non-production Redis smoke, and CI evidence only_

## 阶段 7：实现期间的停止条件 Stop Conditions

发生下列任一情况时停止实现并更新/重新确认规格，不得自行扩大范围：
- 生产必须使用同时消费多个队列的 `run_celery.py`，无法启用独立 knowledge Worker。
- broker 不再是 Redis，或 Celery/Kombu 版本变化导致 priority 数值/steps 语义不同。
- 产品要求中低优最大等待时间、防饥饿、每用户/每租户公平或任务抢占。
- 角色等级需要独立数据库字段、权限资源或审计模型，而不再允许复用 `quota_config`。
- 文件优先级需要随角色变化动态更新，否定“首次入队固化”。
- DM8 无法实现与 MySQL 等价的原子首次写语义。
- 产品要求排队数字稳定递减、绝对精确、固定名次或 ETA；这些目标需要应用调度器/outbox，而不是当前旁路索引。
- 产品要求定义队列容量、“满”阈值、拒绝上传或背压；这属于新的容量控制需求。
- 排队位置需要扩展到 Platform/Client 的其他文件列表、开放 API 或实时推送；当前仅覆盖 Platform 文件上传解析进度区和首钢门户上传记录。
- Redis Cluster 无法通过统一 hash tag 支持所需状态 CAS，或排队索引被要求成为任务发布的强依赖。
- 产品要求从 broker 层强制保证同一文件只有一个解析消息、而不接受逐 ticket 近似观测；这需要另行设计幂等 dispatch/outbox，超出当前可观测旁路范围。

## 覆盖矩阵 Coverage Matrix
| Requirement | Acceptance Criteria | Tasks | Verification |
|---|---|---|---|
| REQ-001 | AC-REQ-001-01 | T003, T009 | V-AC-REQ-001-01 |
| REQ-001 | AC-REQ-001-02 | T001, T003, T009 | V-AC-REQ-001-02 |
| REQ-001 | AC-REQ-001-03 | T001, T003 | V-AC-REQ-001-01, V-AC-REQ-001-02 |
| REQ-001 | AC-REQ-001-04 | T001 | V-AC-REQ-001-04 |
| REQ-001 | AC-REQ-001-05 | T001, T009 | V-AC-REQ-001-05 |
| REQ-001 | AC-REQ-001-06 | T001, T009 | V-AC-REQ-001-06 |
| REQ-002 | AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03 | T002, T009 | V-AC-REQ-002-01 |
| REQ-002 | AC-REQ-002-04, AC-REQ-002-05 | T002, T005 | V-AC-REQ-002-04 |
| REQ-002 | AC-REQ-002-06 | T002, T005, T009 | V-AC-REQ-002-06 |
| REQ-003 | AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03 | T004, T005, T006, T007, T009 | V-AC-REQ-003-01 |
| REQ-003 | AC-REQ-003-04 | T005, T009 | V-AC-REQ-003-04 |
| REQ-003 | AC-REQ-003-05 | T004, T005, T009 | V-AC-REQ-003-05 |
| REQ-004 | AC-REQ-004-01 | T006, T007, T011, T013, T009 | V-AC-REQ-004-01 |
| REQ-004 | AC-REQ-004-02 | T011, T013, T009 | V-AC-REQ-004-01 |
| REQ-004 | AC-REQ-004-03 | T007, T013, T009 | V-AC-REQ-004-03 |
| REQ-004 | AC-REQ-004-04 | T006, T007, T011, T013, T009 | V-AC-REQ-004-04 |
| REQ-004 | AC-REQ-004-05 | T001, T006, T013 | V-AC-REQ-004-05 |
| REQ-005 | AC-REQ-005-01 | T001, T008, T009 | V-AC-REQ-005-01 |
| REQ-005 | AC-REQ-005-02 | T009 | V-AC-REQ-005-02 |
| REQ-005 | AC-REQ-005-03, AC-REQ-005-04 | T008, T009 | V-AC-REQ-005-03 |
| REQ-005 | AC-REQ-005-05, AC-REQ-005-06 | T008, T013, T009 | V-AC-REQ-005-05 |
| REQ-006 | AC-REQ-006-01 | T004, T009 | V-AC-REQ-006-01 |
| REQ-006 | AC-REQ-006-02 | T005, T008, T009 | V-AC-REQ-006-02 |
| REQ-006 | AC-REQ-006-03 | T009 | V-AC-REQ-006-03 |
| REQ-006 | AC-REQ-006-04 | T005, T006, T009 | V-AC-REQ-006-04 |
| REQ-006 | AC-REQ-006-05 | T004, T009 | V-AC-REQ-006-01 |
| REQ-007 | AC-REQ-007-01, AC-REQ-007-05, AC-REQ-007-08 | T012, T009 | V-AC-REQ-007-01 |
| REQ-007 | AC-REQ-007-02 | T010, T009 | V-AC-REQ-007-02 |
| REQ-007 | AC-REQ-007-03, AC-REQ-007-04 | T011, T009 | V-AC-REQ-007-03 |
| REQ-007 | AC-REQ-007-06 | T012, T009 | V-AC-REQ-007-06 |
| REQ-007 | AC-REQ-007-07 | T010, T011, T012, T009 | V-AC-REQ-007-07 |
| REQ-007 | AC-REQ-007-09 | T010, T011, T009 | V-AC-REQ-007-09 |
| REQ-007 | AC-REQ-007-10 | T010, T011, T009 | V-AC-REQ-007-10 |
| REQ-007 | AC-REQ-007-11 | T012, T009 | V-AC-REQ-007-11 |
| REQ-007 | AC-REQ-007-12 | T010, T011, T009 | V-AC-REQ-007-12 |
| REQ-007 | AC-REQ-007-13 | T012, T009 | V-AC-REQ-007-13 |
| REQ-007 | AC-REQ-007-14 | T014, T009 | V-AC-REQ-007-14 |
| REQ-008 | AC-REQ-008-01, AC-REQ-008-02 | T013, T011, T009 | V-AC-REQ-008-01 |
| REQ-008 | AC-REQ-008-03, AC-REQ-008-04 | T013, T011, T009 | V-AC-REQ-008-03 |
| REQ-008 | AC-REQ-008-05 | T009 | V-AC-REQ-008-05 |
| REQ-008 | AC-REQ-008-06 | T013, T009 | V-AC-REQ-008-06 |

## 建议验证批次 Verification Batches
| Batch | Scope | Suggested command/evidence |
|---|---|---|
| EG-001 | 角色配置后端 + 角色弹窗前端 | Role 定向 pytest；单个 Vitest 组件测试；角色权限回归 |
| EG-002 | 角色有效等级决策 | 参数化 service/repository 单元测试 |
| EG-003 | 文件快照与并发 | Knowledge Repository/Service 集成测试；MySQL + DM8 CI |
| EG-004 | 文件生命周期投递与全入口收敛 | Dispatch/task contract、禁止标题后继发布的 source guard、旧消息兼容和受影响 knowledge 回归 |
| EG-005 | Redis priority 与 Worker 隔离 | Celery config/entrypoint contract；非生产 Redis `-c 1` 冒烟 |
| EG-006 | 兼容、失败、发布和回滚 | migration upgrade/downgrade、失败路径、发布清单与 `verification.md` |
| EG-007 | 单 ticket、processing attempt/lease、位置 API 与 UI | Redis lifecycle/rank、正常尝试不换票、异常多 ticket 并发、Worker 强退、同 task ID 重叠 delivery/两种结束顺序、文件级权限/部门审批、API 参数边界、Platform/Client 无阶段组件测试 |
| EG-008 | 文件级单 delivery 主生命周期 | 初次/重试 Worker 定向测试、PROCESSING 时点、标题失败继续、清理/终态回归、后置任务路由 contract、非生产 Redis/Celery `-c 1` 三个同优文件完整生命周期顺序证据 |

## 任务质量门 Task Quality Gate
- [x] Every task references at least one requirement ID.
- [x] Every behavioral task references acceptance criteria.
- [x] Every acceptance criterion is covered by at least one task or verification entry.
- [x] Every task has an observable done condition.
- [x] Dependencies are explicit where ordering is not obvious.
- [x] Boundary annotations prevent unrelated code edits.
- [x] Tasks sharing one behavior or command use a verification batch instead of duplicate verification tasks.
- [x] Test work covers distinct outcomes/risks and does not duplicate the same behavior across test layers.
- [x] No task implements work outside requirements or design.

## 实现记录 Implementation Notes
- 2026-08-09 规格修订前已经落地的角色、优先级、排队索引和前端能力继续作为实现基线；T006/T007 的阶段消息行为已被新规格部分取代，不能视为 T013 已完成。
- 2026-08-09 已完成 T013，并按最终规格收敛 T010/T011/T012：生产入口使用初次/重试单消息，Worker 单 delivery 覆盖主生命周期，Redis ticket 使用 `attempt_kind`，两端 UI 不读取内部 stage。T009 的真实 Worker/Redis 与双数据库发布门禁仍未完成。
- 实现时若 migration head、实际 i18n namespace 或现有测试文件名已变化，应先检索并使用当时真实路径；不得因此改变已确认行为。
- `docs/superpowers/specs/2026-05-20-file-parse-scheduler-design.md` 仅作为历史背景，不是本 feature 的实现依据；禁止顺带启用 OCR 分队列或公平调度器。
