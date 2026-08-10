# 需求说明 Requirements: 知识文件解析三级优先级与排队位置可视化

## 阅读摘要
- 本文档说明：在保持单一 `knowledge_celery` 队列和解析 Worker 总并发不变的前提下，按用户角色为文件解析任务提供高、中、低三级严格优先调度；一次文件解析尝试只使用一个 Celery delivery 和一个 queue ticket，并向排队用户展示前方约有多少文件解析尝试。
- 当前状态：`in-progress`（2026-08-09 生命周期修订待确认/实施）
- 需要重点确认：本次生命周期修订确认后才可进入 T013 实现；真实 Redis 优先顺序、三个同优文件完整生命周期 FIFO 和滚动发布行为必须在非生产环境完成 Worker 冒烟。
- 已确认的核心规则：角色配置等级、多角色取最高、超级管理员高优、系统任务低优、文件首次入队固化、一次文件尝试单消息/单 ticket、Worker 领取后立即进入 PROCESSING、接受中低优饥饿风险；排队位置使用应用侧 Redis 索引提供近似快照，不承诺稳定递减或预计完成时间。

## 元信息 Metadata
- Feature ID: `052-knowledge-file-parse-priority`
- Status: `in-progress`
- Mode: `implementation`
- Created: `2026-08-06`
- Updated: `2026-08-09`
- Source request: `为 knowledge_celery 中的文件解析任务增加基于用户角色的高、中、低三级 Redis 优先级，保持总并发不变；排队时展示当前前方剩余任务数。`

## 需求入口摘要 Intake Summary
- 问题 Problem: 当前 `knowledge_celery` 中所有用户的解析任务均按同一 FIFO 顺序等待，无法优先保障高等级角色用户。
- 当前状态 Current state: Redis 作为 Celery broker；Celery 5.5.3；`knowledge_celery` 当前把标题提取、首次解析和解析重试拆成独立消息；批量上传同优先级文件时，标题任务会先全部进入 FIFO，标题完成后新发布的正式解析消息落到队尾，导致单并发下出现“文件1标题→文件2标题→文件3标题→文件1正式解析”的阶段穿插。
- 目标结果 Target outcome: 管理员可在角色编辑页配置文件解析优先等级；文件首次进入解析链路时固化有效等级；等待中的高优任务优先于中、低优任务；初次解析在一个 delivery 内连续完成标题提取和正式解析，重试在一个 delivery 内连续完成旧向量清理和正式解析；Worker 领取后立即把文件置为 PROCESSING；一次文件尝试只创建一个 ticket；Worker 总并发不变；Platform 与首钢门户使用不含内部子阶段的近似等待文案，门户轮询或手动刷新时保留现有表格、原位更新最新字段。
- 影响对象 Affected users/systems: 平台角色管理页、角色配置 API、知识文件模型与迁移、文件上传/重试/重解析入口、Celery Redis transport、应用侧 Redis 排队索引、排队位置查询 API、Platform 文件上传解析进度 UI、首钢门户上传记录、knowledge Worker 启动配置和解析队列测试。
- 请求停止点 Requested stopping point: `tasks`

## 范围 Scope

### 包含 Includes
- 在“系统 → 角色与权限 → 角色管理”的新建/编辑角色弹窗中增加“文件解析优先等级”配置项，选项为高、中、低。
- 通过现有角色配置读写链路保存、校验和回显解析优先等级。
- 按文件所属租户解析用户在该租户内的有效角色；多角色取最高等级。
- 新角色和未配置的现有角色默认中优；超级管理员固定高优。
- 文件首次进入解析队列时持久化不可变优先级快照。
- 历史文件首次重试/重解析时按上传者当前有效角色计算并固化；无法找到上传者时固化为低优。
- 无用户归属的新系统解析任务使用低优；已有文件且有上传者的系统重解析仍按历史文件规则处理。
- 初次解析生命周期、解析重试生命周期以及运维重解析脚本统一使用文件快照投递 Redis 消息优先级。
- Redis 使用三个优先级档位；knowledge Worker 使用 `worker_prefetch_multiplier=1`。
- 保持 `knowledge_celery` 单队列和现有 Worker 总并发配置；新生产入口只投递初次解析或重试两类文件生命周期消息，标题提取不得再作为新生产消息二次入队。
- 使用应用自有 Redis ZSET/Hash 排队索引跟踪文件解析尝试的 queued/processing 生命周期；一次正常文件尝试只对应一个真实活动 ticket，并继续允许并发重复请求或 broker 重投递产生可独立观测的真实 ticket/attempt；不直接扫描 Celery broker 原始 List。
- 在 Platform 文件上传解析进度区和首钢门户上传记录中按 5 秒轮询批量位置接口；两端 queued 文件统一使用“排队中，前方约 N 个等待任务”的无阶段文案，Platform MAY 单独展示当前运行文件尝试数，门户不展示运行数；门户当前页文件按知识库分组查询，每组最多 100 个文件。
- 初次解析消息被 Worker 领取后立即把文件从 WAITING 改为 PROCESSING，再在同一 delivery 中尽力执行标题提取并连续进入正式解析；标题提取失败只记录日志，不得阻断正式解析或发布新的解析消息。
- 重试消息被 Worker 领取后立即把文件从 WAITING 改为 PROCESSING，再在同一 delivery 中连续完成旧向量清理和正式解析；重试不重新提取标题。
- 首钢门户上传记录首次打开或切换分页时可以展示列表加载态；当前页已有数据时，自动轮询、上传触发刷新和手动刷新必须保留现有表格，并按文件 ID 合并服务端最新字段，不得把整表替换为加载占位。
- 每次 Worker 实际领取都为逻辑 ticket 建立独立、可续期的 processing attempt；使 Worker 强制退出后的幽灵运行记录能在有界时间内从 `active_count` 中剔除，并保证同一 Celery `task_id` 的重投递与原执行重叠时互不覆盖；索引异常仍不得影响解析主链路。
- 排队位置接口除知识库权限外必须复用现有文件级有效可见性规则，覆盖 `knowledge_file:view_file`、资源所有者/管理员、部门文件审批授权和隐藏状态，不得仅凭知识库可读权限回显文件。
- 覆盖角色配置、优先级解析、快照、文件级单生命周期投递、排队位置计算、权限与降级、Redis 配置、部署入口和兼容路径的自动化测试。

### 不包含 Excludes
- 不拆分 `knowledge_high_celery`、`knowledge_medium_celery`、`knowledge_low_celery` 等独立队列。
- 不切换 RabbitMQ，不新增第三方依赖。
- 不实现加权公平、等待老化、每用户轮询、每租户限流或防饥饿机制。
- 不暂停、撤销或抢占已经开始执行或已经被 Worker 预取的低优任务。
- 不修改文件 Load、Transform、Ingest、向量写入和内容解析算法；只调整它们的 Celery 生命周期边界及任务领取时的状态切换时点。
- 不把 PDF Artifact 生成/同步、相似文档候选刷新、推荐投影刷新等不决定主解析状态的后置任务并入解析生命周期；它们继续使用既有独立或默认队列。
- 不修改 Celery/Redis broker 的全局 `visibility_timeout`、确认或重投递策略；本功能只如实观测可能并存的执行尝试，不解决业务任务重复执行。
- 不修改 `workflow_celery`、`knowledge_pdf_celery`、默认 `celery` 队列的任务归属和并发。
- 不在角色列表新增优先级展示列；本次仅在角色新建/编辑弹窗配置和回显。
- 不启用或实现 `docs/superpowers/specs/2026-05-20-file-parse-scheduler-design.md` 中的 OCR 分队列或按用户公平调度器。
- 不清空、搬迁或重写 Redis 中发布前已存在的 Celery 消息。
- 不为 Redis/Celery 队列设置容量上限或定义“队列满”阈值；只要文件处于有效 queued 状态即可展示位置。
- 不承诺排队数字稳定递减、绝对精确、预计开始时间或预计完成时间；后到高优任务可使中、低优文件的前方数量增加。
- 不直接 `LRANGE`、反序列化或依赖 Kombu 私有 broker key 计算位置。
- 不向查询者返回其他文件、用户、租户、角色等级或 Celery task 的身份明细。
- 不把本次排队索引升级为消息幂等、数据库 outbox 或强制去重机制；现有并发入口产生多个真实消息时只负责逐 ticket 正确观测。

## 需求列表 Requirements

### REQ-001: 角色可配置文件解析优先等级
作为角色管理员，我需要在角色新建和编辑弹窗中配置高、中、低文件解析优先等级，以便通过现有角色体系控制用户的解析排队等级。

#### 验收标准 Acceptance Criteria
- `AC-REQ-001-01`: WHEN 管理员新建或编辑可管理角色 THEN 系统 SHALL 展示“文件解析优先等级”单选配置，并只允许选择高、中、低三个值。
- `AC-REQ-001-02`: WHEN 管理员保存合法等级并重新打开角色 THEN 系统 SHALL 通过现有角色 API 持久化并回显相同等级，且不影响原有配额、菜单和作用域配置。
- `AC-REQ-001-03`: IF 新角色未显式选择等级，或现有角色缺少该配置 THEN 系统 SHALL 使用并回显中优先级。
- `AC-REQ-001-04`: IF API 收到高、中、低之外的配置值或错误类型 THEN 系统 SHALL 按现有角色配置校验错误契约拒绝保存。
- `AC-REQ-001-05`: IF 当前用户无权编辑目标角色 THEN 系统 SHALL 沿用现有角色权限拒绝路径，不得因新增配置绕过授权。
- `AC-REQ-001-06`: IF 租户配额 API 收到角色专用的文件解析优先等级键 THEN 系统 SHALL 将其作为非租户配额键拒绝，不得把角色调度策略写入 `Tenant.quota_config`。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01, AC-REQ-001-03 | V-AC-REQ-001-01 | frontend automated test + manual smoke | `src/frontend/platform/src/test/roleParsePriority.test.tsx` 验证选项和默认值；角色弹窗人工回显 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | API/service automated test | `src/backend/test/role/test_knowledge_parse_priority_role_config.py` 验证合法配置保留和 API 返回 |
| AC-REQ-001-04 | V-AC-REQ-001-04 | automated test | 参数化验证非法字符串、错误类型和未知值被现有错误码拒绝 |
| AC-REQ-001-05 | V-AC-REQ-001-05 | existing regression + targeted test | 复用角色更新权限测试，确认只扩展配置字段、不改变拒绝行为 |
| AC-REQ-001-06 | V-AC-REQ-001-06 | API/service automated test | 租户配额更新传入角色专用键时仍按未知键拒绝 |

### REQ-002: 按租户和多角色计算有效等级
作为文件上传用户，我需要系统根据我在文件所属租户内的角色计算唯一有效等级，以便多角色和多租户场景得到稳定、可解释的调度结果。

#### 验收标准 Acceptance Criteria
- `AC-REQ-002-01`: WHEN 普通用户在目标租户拥有一个或多个角色 THEN 系统 SHALL 只使用该租户内的有效角色，并取其中最高解析等级。
- `AC-REQ-002-02`: WHEN 用户任一有效角色为高优 THEN 结果 SHALL 为高优；否则任一角色为中优时结果 SHALL 为中优；仅当所有有效角色均为低优时结果 SHALL 为低优。
- `AC-REQ-002-03`: IF 用户没有有效角色、角色缺少配置或角色配置来自升级前版本 THEN 系统 SHALL 使用中优先级。
- `AC-REQ-002-04`: IF 操作者是全局超级管理员 THEN 系统 SHALL 使用高优先级，不受普通角色配置影响。
- `AC-REQ-002-05`: IF 解析工作没有可识别用户或文件上传者 THEN 系统 SHALL 使用低优先级。
- `AC-REQ-002-06`: IF 等级解析依赖发生非预期故障 THEN 系统 SHALL 记录上下文日志、降级为低优并继续投递，不得阻断文件解析。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01, AC-REQ-002-02, AC-REQ-002-03 | V-AC-REQ-002-01 | unit test | `src/backend/test/role/test_knowledge_parse_priority_service.py` 参数化覆盖租户隔离、多角色最高和缺省中优 |
| AC-REQ-002-04, AC-REQ-002-05 | V-AC-REQ-002-04 | unit test | 同一测试文件覆盖超级管理员高优及无用户低优 |
| AC-REQ-002-06 | V-AC-REQ-002-06 | unit test | 模拟 repository/FGA 依赖异常，验证低优降级、日志和继续返回 |

### REQ-003: 文件首次入队时固化优先级快照
作为平台运维人员，我需要每个文件拥有不可变的解析优先级快照，以便角色调整不会让同一文件的初次完整生命周期和后续重试改变等级。

#### 验收标准 Acceptance Criteria
- `AC-REQ-003-01`: WHEN 新文件首次请求进入任一解析任务 THEN 系统 SHALL 在发布消息前计算并持久化该文件的优先级快照。
- `AC-REQ-003-02`: WHEN 已有快照的文件再次解析或重试 THEN 系统 SHALL 直接复用原快照，不得重新读取当前角色覆盖它。
- `AC-REQ-003-03`: WHEN 角色等级或用户角色关系在快照生成后发生变化 THEN 已固化文件 SHALL 保持原等级，新文件 SHALL 使用变化后的有效等级。
- `AC-REQ-003-04`: WHEN 上线前创建且快照为空的历史文件首次重试或重解析 THEN 系统 SHALL 根据上传者在文件租户内的当前角色计算并固化；上传者缺失或不存在时固化为低优。
- `AC-REQ-003-05`: WHEN 同一无快照文件被并发请求入队 THEN 系统 SHALL 只接受第一个成功固化值，后续请求读取同一值，不得来回覆盖。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01, AC-REQ-003-02, AC-REQ-003-03 | V-AC-REQ-003-01 | repository/service automated test | `src/backend/test/knowledge/test_knowledge_parse_priority_snapshot.py` 验证首次固化、复用和角色变化隔离 |
| AC-REQ-003-04 | V-AC-REQ-003-04 | parameterized automated test | 历史文件有上传者、无上传者、用户不存在三种独立结果 |
| AC-REQ-003-05 | V-AC-REQ-003-05 | repository integration test | 条件更新/CAS 测试验证并发首次写不覆盖既有值，MySQL 行为本地验证、DM8 由 CI 验证 |

### REQ-004: 所有解析入口统一投递文件生命周期消息
作为文件解析链路维护者，我需要所有解析生产入口使用同一个文件生命周期投递契约，以便没有入口绕过快照、队列、优先级或重新引入阶段消息穿插。

#### 验收标准 Acceptance Criteria
- `AC-REQ-004-01`: WHEN 初次解析或解析重试被发布 THEN 每次文件尝试 SHALL 只发布一个消息到 `knowledge_celery`，并携带由文件快照映射得到的 Redis/Celery priority。
- `AC-REQ-004-02`: WHEN 初次解析生命周期执行标题提取并进入正式解析 THEN 系统 SHALL 在同一 Celery delivery 内直接连续执行，不得从标题步骤再次发布正式解析消息。
- `AC-REQ-004-03`: WHEN API、知识空间服务、开放接口、人工重试、批量重试或运维重解析脚本发布解析任务 THEN 所有入口 SHALL 经过统一解析投递服务，不得直接发布标题子任务或绕过等级处理。
- `AC-REQ-004-04`: WHEN 任务契约调整为文件级生命周期 THEN 现有正式解析/重试 task name、tenant header、callback、preview cache key、`acks_late`、文件快照优先级和调用方可观察的终态语义 SHALL 保持兼容；只允许增加生命周期识别所需的可选 header，并必须提供滚动发布兼容路径。
- `AC-REQ-004-05`: IF 新代码遗漏显式等级但直接发布受支持的文件生命周期任务 THEN 该消息 SHALL 至少使用中优默认值，而不是意外成为高优。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01, AC-REQ-004-02 | V-AC-REQ-004-01 | unit/integration contract test | `test_knowledge_parse_priority_dispatch.py` 与 lifecycle worker 测试验证每次尝试单消息、queue/priority/header，以及标题步骤不再发布后继消息 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | AST/source contract test | 扩展 `test_knowledge_parse_queue_routing.py`，扫描生产代码中的标题子任务直投、生命周期任务 `.delay()` 和未授权 `apply_async()` |
| AC-REQ-004-04 | V-AC-REQ-004-04 | affected regression + rollout compatibility test | 覆盖上传、重试、重解析、租户上下文、旧标题消息消费兼容和存量正式解析消息自然消费 |
| AC-REQ-004-05 | V-AC-REQ-004-05 | task configuration test | 检查受支持生命周期任务的默认 priority 均为中优映射值 |

### REQ-005: Redis 在单队列中按三级优先级取任务
作为平台运维人员，我需要 Redis broker 在同一个 `knowledge_celery` 中优先交付高等级等待任务，以便不增加队列和并发也能改善高等级用户的开始等待时间。

#### 验收标准 Acceptance Criteria
- `AC-REQ-005-01`: WHEN 系统构建 Celery Redis transport 配置 THEN 系统 SHALL 声明三个稳定业务等级到 Redis transport priority steps 的映射，并满足高优先于中优、中优先于低优；未使用的兼容档位不得形成第四个业务等级。
- `AC-REQ-005-02`: WHEN 同一 `knowledge_celery` 中同时存在尚未预取的高、中、低消息 THEN knowledge Worker SHALL 按高、中、低顺序取得消息；同一等级内保持 Redis List 的 FIFO 行为。
- `AC-REQ-005-03`: WHEN 启动任一受支持的 knowledge Worker 入口 THEN 该 Worker SHALL 使用 `worker_prefetch_multiplier=1` 或等价 `--prefetch-multiplier=1` 配置。
- `AC-REQ-005-04`: WHEN 启用三级优先级 THEN `KNOWLEDGE_CONCURRENCY`、旧 Docker knowledge concurrency 和调用方自定义 `-c` SHALL 保持原值，不得因为三级等级扩成三倍或拆分配额。
- `AC-REQ-005-05`: WHEN 检查最终任务路由 THEN `knowledge_celery` 的新生产白名单 SHALL 只允许初次解析和解析重试文件生命周期任务；旧标题任务只能作为滚动发布兼容消费者保留，不得再由新生产入口发布。
- `AC-REQ-005-06`: WHEN 启用 Redis priority transport THEN 默认、工作流和 PDF Worker 的队列职责、并发和任务路由 SHALL 保持不变。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-005-01 | V-AC-REQ-005-01 | config unit test | 扩展 `src/backend/test/celery/test_celery_redis_config.py`，覆盖单机、Sentinel 和 transport option 合并 |
| AC-REQ-005-02 | V-AC-REQ-005-02 | Redis integration smoke | 在非生产 Redis 发布三档消息并用 `-c 1` knowledge Worker 记录实际取得顺序；自动化层验证 Kombu 队列 key/priority 映射 |
| AC-REQ-005-03, AC-REQ-005-04 | V-AC-REQ-005-03 | deployment contract test | 检查 `src/backend/entrypoint.sh`、`docker/bisheng/entrypoint.sh` 和受支持启动入口的 prefetch 与 concurrency 参数 |
| AC-REQ-005-05, AC-REQ-005-06 | V-AC-REQ-005-05 | route/source contract regression | `test_knowledge_parse_queue_routing.py` 验证两类新生产生命周期任务、旧标题任务仅兼容消费及其他队列不变 |

### REQ-006: 升级、异常和回滚不得阻断解析
作为发布负责人，我需要新旧角色、历史文件和存量 broker 消息安全共存，以便滚动发布不丢任务、不破坏文件状态且可以回滚。

#### 验收标准 Acceptance Criteria
- `AC-REQ-006-01`: WHEN 数据库升级 THEN 系统 SHALL 以 MySQL、DM8 均兼容的方式增加可空文件优先级快照字段，且不批量回填历史文件。
- `AC-REQ-006-02`: WHEN 新旧 API/Worker 在滚动发布窗口短暂共存 THEN 缺少角色配置或文件快照的代码路径 SHALL 使用已定义默认规则，不因空值失败。
- `AC-REQ-006-03`: WHEN 部署新版本 THEN 系统 SHALL 不执行 `celery purge`、Redis key 删除或存量消息迁移；升级前已发布且没有 priority 的消息自然消费，其过渡期顺序不承诺重新分级。
- `AC-REQ-006-04`: WHEN priority 配置、快照写入或发布发生异常 THEN 系统 SHALL 保留现有错误边界和日志，不得静默丢弃已创建的 WAITING 文件。
- `AC-REQ-006-05`: WHEN 回滚应用代码 THEN 数据库可空快照字段 SHALL 可保留且不影响旧代码；若执行 migration downgrade，则只删除该新增字段，不改写角色 `quota_config` 的其他键。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-006-01, AC-REQ-006-05 | V-AC-REQ-006-01 | migration test + CI | Alembic upgrade/downgrade 结构检查；MySQL 本地/CI，DM8 CI |
| AC-REQ-006-02 | V-AC-REQ-006-02 | compatibility automated test | 空 role key、空 snapshot、旧请求 payload 和旧模型行参数化验证 |
| AC-REQ-006-03 | V-AC-REQ-006-03 | static release check + manual review | 部署脚本和文档不得包含 purge/删除；发布清单记录存量消息自然消费 |
| AC-REQ-006-04 | V-AC-REQ-006-04 | failure-path automated test | 模拟快照持久化、角色解析和 broker 发布失败，验证日志、异常传播或可重试状态 |

### REQ-007: 排队用户可查看当前解析位置快照
作为等待文件解析的用户，我需要看到当前文件解析尝试前方约有多少等待任务，以便了解系统仍在排队而不是无响应。

#### 验收标准 Acceptance Criteria
- `AC-REQ-007-01`: WHEN 当前用户有权查看的文件存在有效 queued ticket THEN 系统 SHALL 返回该文件解析尝试的 `ahead_waiting_count`、全局 `active_count`、`approximate=true` 和统一 `as_of` 时间；其中 `active_count` SHALL 统计当前租约有效的 Worker delivery attempt 数量，而不是去重后的 ticket 或文件数；前端 SHALL 展示“排队中，前方约 N 个等待任务”，不得展示标题提取/正式解析等内部子阶段，Platform MAY 把运行尝试数单独展示。
- `AC-REQ-007-02`: WHEN 系统计算 queued ticket 的 `ahead_waiting_count` THEN 结果 SHALL 等于所有更高业务等级的 queued ticket 数量，加上当前等级中排序序号更早的 queued ticket 数量；processing 数量不得混入该值。
- `AC-REQ-007-03`: WHEN 一次初次解析或重试被发布并执行 THEN 系统 SHALL 从发布到 delivery 结束始终使用同一个逻辑 ticket；内部标题提取、旧向量清理和正式解析步骤不得换票或新增 queued ticket。
- `AC-REQ-007-04`: WHEN queued ticket 被 Worker 取得 THEN 系统 SHALL 将其从 waiting 索引移除，并为本次 delivery 创建独立 processing attempt；WHEN 该尝试成功、失败、撤销或结束 THEN 系统 SHALL 只清理本 attempt，且仅在该逻辑 ticket 不再存在有效 attempt 时清理 ticket 的 processing 关联；文件进入终态后前端 SHALL 停止展示排队数量。
- `AC-REQ-007-05`: WHEN 后到的更高优先级任务进入队列或 Worker 并发消费改变队列 THEN 后续查询 MAY 返回增大或减小的快照；持续状态展示 SHALL 使用“约”且不得承诺稳定倒计时或 ETA。首钢门户上传完成时 MAY 按 `AC-REQ-007-14` 展示一次性的当前名次/等待总数快照，但不得把该 Toast 解释为后续稳定名次。
- `AC-REQ-007-06`: WHEN 客户端批量查询排队位置 THEN API SHALL 使用 `GET /api/v1/knowledge/{knowledge_id}/parse-queue-positions`、只接受 1～100 个正整数 `file_ids`，复用现有登录与 `PermissionService` 资源权限，并只返回属于当前租户、目标知识库且调用者有权查看的文件结果。
- `AC-REQ-007-07`: IF Redis 排队索引不可用、ticket 缺失/过期、索引与文件状态不一致或请求发生在发布/消费竞态窗口 THEN 系统 SHALL 返回 `state=unavailable` 或退化为普通“排队中”展示，不得返回 `ahead_waiting_count=0` 冒充队首，不得阻断实际 Celery 消息发布或解析执行。
- `AC-REQ-007-08`: WHEN 查询不处于 queued 状态的可见文件 THEN 系统 SHALL 返回 `processing | not_queued | unavailable` 中与可观察状态一致的结果，并仅在 `queued` 状态返回非空 `ahead_waiting_count`。
- `AC-REQ-007-09`: WHEN Worker 子进程、容器或连接在 processing 期间异常终止且结束回调未执行 THEN 该 processing attempt SHALL 在租约停止续期后于有界时间内退出全局 `active_count`；文件状态仍为 WAITING/PROCESSING 但无可靠活动 ticket/attempt 时 SHALL 返回 `unavailable`；同一 Celery `task_id` 每次被 Worker 领取时 SHALL 创建新的、不可预测的 `processing_attempt_id` 并关联到同一逻辑 `queue_ticket_id`，不得复用其他 delivery 的 attempt identity。
- `AC-REQ-007-10`: WHEN 同一文件因并发重试、重复请求或 broker 中真实重复消息而同时存在多个活动消息 THEN 索引 SHALL 分别保存每个 ticket，任一 ticket 的状态转换或清理不得覆盖其他 ticket；正常初次生命周期内部不得因标题到正式解析生成第二个 ticket；API SHALL 优先返回有效 processing 状态，否则返回该文件 queued ticket 中实际调度最靠前者的位置。
- `AC-REQ-007-11`: WHEN 调用者可读取目标知识库但不满足目标文件的现有有效可见性规则 THEN API SHALL 与不存在、跨租户或跨知识库文件相同地省略该文件；文件所有者、管理员、`knowledge_file:view_file` 授权以及适用的部门审批授权 SHALL 与现有知识空间文件可见性结果保持一致。
- `AC-REQ-007-12`: WHEN Redis transport 的 visibility timeout 在原 delivery 尚未完成时触发同一 Celery `task_id` 重投递 THEN 原 delivery 与新 delivery SHALL 分别拥有独立的有效 attempt、分别计入 `active_count`，任一 attempt 的心跳或结束清理不得续期、删除或覆盖另一个 attempt；无论两个 attempt 以何种顺序结束，只要仍有有效 attempt，逻辑 ticket SHALL 保持 processing，最后一个有效 attempt 结束或过期后才可清理该关联。
- `AC-REQ-007-13`: WHEN 首钢门户打开“上传记录”且当前页存在 WAITING/PROCESSING/REBUILDING 文件 THEN Client SHALL 按 `knowledge_id` 分组批量查询排队位置，并仅在 queued 文件状态区域展示“排队中，前方约 N 个等待任务”，不得展示内部子阶段或当前运行任务数；processing 与 unavailable SHALL 保留原“解析中/等待解析/重新解析”状态文案，终态文件不得触发位置查询，接口失败不得弹出高频错误提示。WHEN 当前页已有上传记录且发生自动轮询、上传触发刷新或手动刷新 THEN Client SHALL 保持表格可见并按文件 ID 合并最新字段；只有首次加载或切换分页 MAY 使用整表加载占位。
- `AC-REQ-007-14`: WHEN 首钢门户一次上传成功注册 M 个非重复文件且位置 API 返回可靠 queued 快照 THEN API SHALL 同时返回三个业务优先级全部 queued ticket 的全局 `waiting_count`，不包含 publishing 或 processing；IF 本次文件中最靠前 queued 文件的 `ahead_waiting_count > 0` 且 `waiting_count >= ahead_waiting_count + 1` THEN Client SHALL 用单条 success Toast 替换原“上传成功”，文案为“上传成功，M 个文件已进入队列，最前第 X/Y 名”，其中 `X=min(ahead_waiting_count)+1`、`Y=waiting_count`。重复文件、注册失败文件不计入 M；无前方任务、响应不可靠、Redis/位置查询失败或 X/Y 不一致时 SHALL 保留原“上传成功”，不得阻断上传或额外显示错误 Toast。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-007-01, AC-REQ-007-05, AC-REQ-007-08 | V-AC-REQ-007-01 | frontend component + API contract test | `FileUploadStep4`/`ProgressItem` 定向测试验证无阶段约数文案、可选运行数、终态停止和 unavailable 降级 |
| AC-REQ-007-02 | V-AC-REQ-007-02 | Redis repository/service integration test | 参数化验证 high/medium/low 公式、同级序号、后到高优插队和 processing 排除 |
| AC-REQ-007-03, AC-REQ-007-04 | V-AC-REQ-007-03 | task lifecycle integration test | 覆盖 publishing→queued→processing→finished、初次/重试单 ticket、内部步骤不换票及 attempt 清理 |
| AC-REQ-007-06 | V-AC-REQ-007-06 | API/security automated test | 覆盖 1～100 参数边界、未登录、无权限、跨租户、跨知识库和不泄露不可见文件 |
| AC-REQ-007-07 | V-AC-REQ-007-07 | failure-path automated test | 模拟 Redis 写入/查询失败、过期 ticket、发布竞态和状态不一致，验证解析不中断与 UI 安全降级 |
| AC-REQ-007-09 | V-AC-REQ-007-09 | Redis/worker lifecycle integration test | 模拟 processing attempt 心跳停止、租约过期、Worker 强制退出和同 task ID 再次被领取，验证 attempt identity 不复用、`active_count` 有界收敛与 unavailable 降级 |
| AC-REQ-007-10 | V-AC-REQ-007-10 | concurrent dispatch/lifecycle integration test | 并发为同一文件创建两个 ticket，验证逐 ticket 状态、processing 优先、queued 最靠前选择和互不清理 |
| AC-REQ-007-11 | V-AC-REQ-007-11 | API/security integration test | 覆盖知识库可读但文件无 `view_file`、部门审批未通过/已授权、授权撤销、隐藏状态及所有者/管理员路径 |
| AC-REQ-007-12 | V-AC-REQ-007-12 | Redis/worker overlapping-delivery integration test | 强制 visibility timeout 在原执行完成前重投递同 task ID，验证两个 attempt 同时计数、attempt-scoped 心跳/清理、先结束原 attempt 与先结束新 attempt 两种顺序，以及旧 attempt 过期后不影响新 attempt |
| AC-REQ-007-13 | V-AC-REQ-007-13 | Client API contract + portal component test | 验证门户按知识库分组查询待处理文件、queued 简化约数文案、processing/unavailable 降级、终态不查询，以及已有数据刷新期间表格持续可见并原位更新字段 |
| AC-REQ-007-14 | V-AC-REQ-007-14 | Redis service + Client upload hook test | 验证三级 queued 总数排除 publishing/processing；单/多文件最前名次、重复文件排除、无前方任务、无效快照和查询失败时 success Toast 的替换或安全降级 |

### REQ-008: 单次文件尝试在一个 Worker 生命周期内连续完成
作为文件上传用户，我需要同一文件的解析前处理和正式解析由同一次 Worker delivery 连续完成，以便单并发时不会先处理完其他文件的前置步骤再回头解析当前文件。

#### 验收标准 Acceptance Criteria
- `AC-REQ-008-01`: WHEN 初次解析消息被 Worker 领取 THEN 系统 SHALL 在标题提取开始前把文件从 WAITING 更新为 PROCESSING，并在同一 delivery 内依次执行标题提取和正式解析，期间不得让其他文件占用该 delivery 的并发槽。
- `AC-REQ-008-02`: IF 标题提取或别名生成失败 THEN 系统 SHALL 记录失败并继续当前 delivery 的正式解析；不得把标题失败直接写成文件终态，也不得新发布正式解析消息。
- `AC-REQ-008-03`: WHEN 重试消息被 Worker 领取 THEN 系统 SHALL 立即把文件从 WAITING 更新为 PROCESSING，并在同一 delivery 内依次完成旧向量清理和正式解析；重试不得重新执行标题提取。
- `AC-REQ-008-04`: WHEN 正式解析成功、普通异常或内容安全违规 THEN 当前 delivery SHALL 分别落库 SUCCESS、FAILED 或 VIOLATION，并沿用既有 remark/callback 终态语义。
- `AC-REQ-008-05`: WHEN 单个 `knowledge_celery` Worker 使用 `concurrency=1`、`prefetch_multiplier=1` 且同优先级依次上传文件 1、2、3 THEN 可观察执行顺序 SHALL 为“文件1完整初次生命周期→文件2完整初次生命周期→文件3完整初次生命周期”，不得出现三个文件标题任务先全部完成的阶段穿插。
- `AC-REQ-008-06`: WHEN 主解析进入终态 THEN PDF Artifact、相似文档候选、推荐投影等后置任务 MAY 按现有机制异步执行；它们 SHALL 不延迟或覆盖主文件解析终态，也不得被路由进 `knowledge_celery` 文件生命周期消息。

#### 验证方式 Verification Methods
| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-008-01, AC-REQ-008-02 | V-AC-REQ-008-01 | lifecycle worker automated test | 验证领取即 PROCESSING、标题成功/失败均在同一 delivery 进入正式解析，且没有后继 `apply_async` |
| AC-REQ-008-03, AC-REQ-008-04 | V-AC-REQ-008-03 | retry/terminal-state automated test | 验证重试同 delivery 清理与解析、不执行标题，以及 SUCCESS/FAILED/VIOLATION/remark/callback 契约 |
| AC-REQ-008-05 | V-AC-REQ-008-05 | real Redis/Celery single-concurrency integration smoke | 以三个同优文件记录 Worker 事件序列，证明每个文件生命周期连续且同级 FIFO |
| AC-REQ-008-06 | V-AC-REQ-008-06 | routing + affected regression test | 验证后置任务仍在既有队列异步执行且不改变主状态 |

## 非功能需求 Non-Functional Requirements
- `NFR-001`: 批量上传同一用户、同一租户的多个文件时，角色等级解析应批量复用，避免按文件产生角色查询 N+1。
- `NFR-002`: 文件快照固化必须幂等；并发投递不得覆盖已经存在的等级。
- `NFR-003`: 优先级解析必须限定文件所属 `tenant_id`，不得使用用户在其他租户的角色抬高当前文件等级。
- `NFR-004`: 新增持久字段和迁移必须同时兼容 MySQL 与 DM8；不得使用方言专属 JSON 查询或原始 SQL。
- `NFR-005`: 不新增第三方依赖；文件生命周期消息契约只做完成单 delivery 所需的最小兼容调整，结果后端保持不变。
- `NFR-006`: 关键日志至少包含 `file_id`、`tenant_id`、业务等级和 Celery priority；不得记录文件正文、token 或敏感凭据。
- `NFR-007`: Platform 新增文案必须覆盖 `zh-Hans` 与 `en-US` 并复用现有 `bs-ui` 组件；首钢门户上传记录沿用该页面现有的中文固定文案与 Client UI 组件。
- `NFR-008`: 排队位置查询不得扫描 Celery 原始 List；批量查询应使用 Redis pipeline 和 ZSET rank/cardinality 操作，使单 ticket 排名保持 `O(log N)`，文件归并成本只随该文件活动 ticket 数增长，单次请求最多 100 个文件。
- `NFR-009`: 逻辑排队索引 member 使用不可预测的 `queue_ticket_id`，每次 Worker delivery 使用独立、不可预测的 `processing_attempt_id`；Redis metadata 只保存两类 identity 的关联以及 `tenant_id`、`knowledge_id`、`file_id`、尝试类型（初次/重试）、内部优先级、序号、状态和时间，不保存文件名、用户名、正文或凭据。
- `NFR-010`: 所有排队索引 key 必须使用统一 Redis Cluster hash tag，支持项目现有单机、Sentinel 和 Cluster 客户端；ticket/attempt 硬 TTL 不得短于现有解析超时加安全余量。
- `NFR-011`: 前端轮询间隔默认 5 秒，同一轮不得并发重复请求；所有文件离开 queued/processing 后停止位置轮询。
- `NFR-012`: 排队索引属于非关键可观测旁路；索引故障必须记录 `ticket_id/file_id/tenant_id/attempt_kind`，processing 阶段还应记录当前 `attempt_id`，但不得改变解析任务的发布、确认、重试或文件状态机。
- `NFR-013`: processing 观测必须按 attempt 使用短周期、可续期租约；租约期限必须大于至少两个续期间隔，续期失败不得终止解析，过期 attempt 必须在租约期限加一次惰性清理周期内退出 `active_count`，不得依赖 24 小时 ticket TTL 才收敛。
- `NFR-014`: file→ticket 索引必须允许同一文件关联多个活动 ticket；逐 ticket 清理必须幂等，单个旧 ticket 不得删除、覆盖或续期同文件的其他 ticket。
- `NFR-015`: 文件可见性判定必须使用现有批量有效权限能力或抽取出的等价公共服务，单次最多 100 个文件不得串行执行 100 次独立权限网络调用；Repository 只负责租户和知识库归属读取，不得自行替代权限决策。
- `NFR-016`: processing 心跳、租约续期、过期清理和正常结束清理必须以 `processing_attempt_id` 校验归属并采用 attempt-scoped fencing；`active_count` SHALL 统计有效 attempt 租约，同一逻辑 ticket 的一个 attempt 不得延长或删除其他 attempt 的租约。
- `NFR-017`: 文件级生命周期合并不得增加 knowledge Worker 总并发、启动额外线程池或在同一 delivery 内异步并行处理多个文件；标题、清理与正式解析在该 delivery 的同一并发槽内串行执行。

## 澄清记录 Clarifications

### Session 2026-08-05
- Q: 采用哪种优先机制？ -> A: 单个 `knowledge_celery` + Redis 三级消息优先级 + `prefetch_multiplier=1` + 全链路显式继承。
- Q: 优先等级由什么决定？ -> A: 使用用户角色，在角色编辑弹窗增加优先等级配置项。
- Q: 文件等级何时确定？ -> A: 第一次入队时固化；标题提取、正式解析和重试均继承。
- Q: 是否接受严格优先导致中低优饥饿？ -> A: 接受。

### Session 2026-08-06
- Q: 多角色如何合并？ -> A: 取最高等级。
- Q: 默认、超级管理员和系统任务如何定级？ -> A: 新旧角色默认中优；超级管理员高优；无登录用户的系统任务低优。
- Q: 历史文件第一次重新入队如何定级？ -> A: 按上传者当前角色计算并固化；找不到上传者时低优。
- Q: 本次交付停止点？ -> A: 使用 `sdd-spec`，只生成到 `tasks.md`，暂不实现。
- Q: 队列繁忙时能否展示前方剩余数量？ -> A: 更新现有规格，采用应用侧 Redis ZSET/Hash 排队索引展示当前阶段的近似快照；运行任务数单独展示，不承诺稳定递减或 ETA。
- Q: 什么情况下展示？ -> A: 不新增“队列满”阈值；文件具有有效 queued ticket 时展示，索引不可用时退化为普通排队状态。
- Q: 排队位置如何解释？ -> A: 更高等级全部 queued 数量 + 同等级更早序号数量；标题、正式解析、重试分别按真实入队阶段重新计算。
- Q: Worker 强制退出导致 processing 回调不执行如何处理？ -> A: 每次 Worker delivery 使用独立 processing attempt 和短周期可续期租约；心跳停止后有界剔除 active count，文件状态没有可靠 ticket/attempt 时返回 unavailable。
- Q: 同一文件并发产生多个真实消息如何表示？ -> A: Redis 旁路不负责阻断主链路，改为 file→多个活动 ticket；API 先展示 processing，否则展示 queued 中实际调度最靠前者，逐 ticket 独立清理。
- Q: Redis visibility timeout 让同一 task ID 在原执行未结束时重投递如何表示？ -> A: `queue_ticket_id` 只表示逻辑消息，每次 delivery 生成新的 `processing_attempt_id`；两个 attempt 独立心跳、计数和清理，最后一个有效 attempt 消失后才结束逻辑 ticket 的 processing 关联。本功能不修改全局 visibility timeout，也不承诺阻止业务重复执行。
- Q: 首钢门户上传记录是否需要展示具体解析阶段和当前运行数？ -> A: 不需要；queued 时统一展示“排队中，前方约 N 个等待任务”，processing/unavailable 使用原状态文案。
- Q: 上传记录自动轮询或手动刷新是否重新加载整张表？ -> A: 当前页已有数据时保持表格可见，按文件 ID 合并最新字段；只有首次加载或切换分页显示整表加载态。
- Q: 位置 API 的文件权限如何判断？ -> A: 知识库访问只是第一层，文件结果必须复用现有有效文件可见性，包括 `view_file`、所有者/管理员、部门审批授权和隐藏状态；不可见 ID 直接省略。

### Session 2026-08-09
- Q: 多文件同优先级、单并发时，是否允许标题任务先全部执行再进入正式解析？ -> A: 不允许；解析调度单位必须改为一次文件完整生命周期。
- Q: 初次解析生命周期包含哪些步骤？ -> A: Worker 领取后立即置 PROCESSING，在同一 delivery 内连续执行标题提取和正式解析；标题提取是 best-effort，失败不阻断正式解析。
- Q: 重试生命周期包含哪些步骤？ -> A: Worker 领取后立即置 PROCESSING，在同一 delivery 内连续执行旧向量清理和正式解析，不重新提取标题。
- Q: PDF、相似文档和推荐投影是否纳入生命周期？ -> A: 不纳入；继续异步执行，不决定主解析终态。
- Q: queue ticket 与排队文案如何调整？ -> A: 一次文件解析尝试一个 ticket；排队数量按等待的生命周期尝试计算，不再展示标题/正式解析内部子阶段。

## 假设 Assumptions
- 当前生产 broker 仍为 Redis，项目锁定 Celery 5.5.3、Kombu 5.5.4；如 broker 或大版本变化，必须重新验证 priority 数值语义。
- “系统任务低优”指没有可识别用户或上传者的解析工作；系统批量重解析已有且可识别上传者的历史文件时，优先应用已确认的历史文件规则。
- 同一业务等级内的 FIFO 以消息仍停留在 Redis、尚未被 Worker 预取为前提。
- 当前角色管理权限、审计日志和租户自动注入机制继续作为安全边界，本功能不重新定义它们。
- 排队位置是查询时刻的全局 broker 等待快照；只返回聚合数量，不代表其他租户资源可见，也不提供其他任务身份。
- Redis 旁路不能可靠阻止 Celery broker 中既有或并发产生的重复消息，因此规格选择逐 ticket 可观测，而不是把应用 Redis 锁升级为任务发布的强依赖。
- 当前受支持的文件生命周期任务使用 `acks_late=True`、没有任务级硬时限，且当前 Redis broker 配置未覆盖 Kombu 5.5.4 默认 3600 秒 visibility timeout；大文件解析因此可能出现相同 `task_id` 的不同 delivery 真实重叠，规格按 attempt 如实观测这种重叠，不把逻辑 ticket 等同为唯一运行实例。

## 风险 Risks
- Redis priority 由 Celery/Kombu 通过多个 List 模拟，只提供近似优先，不是 broker 原生强保证。
- `prefetch_multiplier=1` 仍可能保留正在执行和少量已预取任务，高优任务无法抢占这些任务。
- 严格优先可能导致中、低优任务长期饥饿；用户已明确接受，本功能不增加老化或权重。
- Kombu 的 `queue_order_strategy` 只控制多个队列之间的轮询，不控制单个队列内部的消息优先级；实现不得为本功能把它改成 `priority`。组合队列开发入口不提供独立 knowledge Worker 的等待时延隔离，生产优先级验收必须使用独立 knowledge Worker。
- 发布前已经位于 Redis 基础 List 的无 priority 消息不会被重新分级，滚动发布期间可能暂时先于新中低优消息执行。
- 角色等级固化为文件快照会增加一个数据库字段；这是满足“后续角色变化不影响已有文件”的必要持久化成本。
- 应用侧索引与 Celery broker 发布无法组成同一原子事务；短暂 publishing/queued/processing 竞态或进程崩溃可能导致位置暂不可用，因此产品文案只能承诺近似快照。
- 中、低优文件的 `ahead_waiting_count` 可能因新高优任务到达而上升，这是严格优先规则的直接结果，不应被前端误判为任务倒退。
- Redis ticket 若清理不完整可能形成短期幽灵记录；实现必须使用状态 CAS、TTL 和查询时一致性检查，且不得通过危险的 broker key 扫描自动修复。
- Worker 异常退出不会执行正常结束回调；attempt-scoped processing 租约和心跳负责有界修正 `active_count`，但不会替代 Celery 自身的确认、重投递或文件超时策略。
- Redis visibility timeout 触发的重投递可能与原任务重叠；若把 `task_id` 直接作为 processing member，先结束的执行会错误清除仍在运行的执行。本规格通过独立 attempt identity、fenced cleanup 和两种结束顺序的集成测试隔离该风险，且明确不调整可能影响其他队列的全局 visibility timeout。
- 同一文件的多个活动 ticket 只应来自重复请求、滚动发布存量消息或 broker 重投递，不再来自正常标题→正式解析阶段交接；位置 API 只展示一个有效状态，不能据此承诺 broker 中只有一条消息。
- 单 lifecycle delivery 比原标题短任务更长，`acks_late` 与 Redis visibility timeout 导致重叠 delivery 的概率不会降低；现有 attempt lease 继续只负责如实观测，不提供业务幂等或执行锁。
- 滚动发布期间可能同时存在旧标题消息、旧正式解析消息和新文件生命周期消息；实现必须保留安全消费兼容，禁止通过 purge 消除存量消息。旧消息过渡期不保证“一文件一 ticket”，新生产入口完成切换后才保证正常尝试单 ticket。

## 需求质量门 Requirements Quality Gate
- [x] Every requirement has a stable `REQ-*` ID.
- [x] Every requirement has at least one `AC-*` acceptance criterion.
- [x] Every acceptance criterion has a stable `AC-*` ID.
- [x] Every acceptance criterion has at least one `V-*` verification ID.
- [x] Every acceptance criterion has a verification method.
- [x] Acceptance criteria sharing one behavior reuse an evidence target instead of duplicating commands.
- [x] No orphan `AC-*` or `V-*` entries exist.
- [x] Scope includes and excludes are explicit.
- [x] No critical ambiguity remains.
- [x] Requirements avoid implementation details unless explicitly required.
