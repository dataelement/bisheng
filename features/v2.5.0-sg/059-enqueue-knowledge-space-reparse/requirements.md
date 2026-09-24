# 需求说明 Requirements：知识空间文件重解析任务入队脚本

## 阅读摘要

- 本文档定义一个新的后端运维脚本：复用现有 `reparse_knowledge_space_files.py` 的文件筛选语义，把命中的文件交给 `knowledge_celery` worker 重试解析。
- 新脚本默认 dry-run；只有显式传入 `--apply` 才更新文件状态并发布 Celery 任务。
- 脚本只证明任务成功发布到 broker，不等待或宣称 worker 已完成解析。
- 当前状态：`confirmed`，已获授权生成 `tasks.md` 并进入实现。

## 元信息 Metadata

- Feature ID: `059-enqueue-knowledge-space-reparse`
- Status: `implemented; automated verification passed`
- Mode: `spec-then-implement`
- Created: `2026-07-28`
- Updated: `2026-07-28`
- Version: `v2.5.0-sg`
- Source request: 参考 `scripts/reparse_knowledge_space_files.py` 新增脚本，将筛选出的文件重新投入 worker 队列解析。

## 需求入口摘要 Intake Summary

- 问题 Problem: 现有维护脚本在本地进程内直接清理向量并解析文件，无法复用线上 `knowledge_celery` worker 的并发、运行环境和任务调度能力。
- 当前状态 Current state: `src/backend/scripts/reparse_knowledge_space_files.py` 已具备完整的知识空间、目录、文件、空间级别和状态筛选能力；`retry_knowledge_file_celery` 已具备清理旧向量并重新解析的 worker 行为，但只接受 `WAITING/PROCESSING` 文件。
- 目标结果 Target outcome: 运维人员使用相同筛选语义预览文件，并在显式执行时把每个文件安全切换为待解析状态、携带正确租户上下文发布到 `knowledge_celery`。
- 影响对象 Affected users/systems: 后端运维脚本、`KnowledgeFile` 状态字段、Celery broker、`knowledge_celery` worker、多租户上下文。
- 请求停止点 Requested stopping point: 先完成规格并确认，再生成任务计划和实现。

## 范围 Scope

### 包含 Includes

- 新增独立 Python 运维脚本及 shell 包装器，不替换现有本地直解析脚本。
- 复用现有脚本的候选文件收集函数及以下筛选语义：
  - 无范围参数时扫描全部知识空间真实文件。
  - `--space-id`、`--folder-id`、`--file-id` 多值并集。
  - `--space-level` 与上述范围交集。
  - `--status`、`--include-inflight`、`--only-inflight` 的现有默认值、互斥关系和状态集合。
- 默认 dry-run，仅输出选择摘要；`--apply` 才允许数据库写入和消息发布。
- 入队前重新读取文件并复核类型、空间归属和有效状态，避免筛选后状态变化被覆盖。
- 发布前把目标文件更新为 `WAITING`，清空 `remark`、`simhash`，并把 `similar_status` 设为 `0`。
- 使用 `retry_knowledge_file_celery`，显式向 `knowledge_celery` 发布任务，并在消息 header 中写入文件所属 `tenant_id`。
- 单文件发布失败时恢复该文件发布前的四个字段，继续处理其他文件，并在最终摘要和退出码中准确报告失败。
- 新增定向自动化测试和运维 README 说明。

### 不包含 Excludes

- 不修改 `retry_knowledge_file_celery`、`parse_knowledge_file_celery` 或 worker 路由。
- 不在脚本进程内删除 Milvus/Elasticsearch 数据或执行解析 pipeline；旧向量清理由现有重试 worker 完成。
- 不等待 Celery 任务执行完成，不轮询最终文件状态，不把“成功入队”描述成“解析成功”。
- 不新增数据库字段、Schema、Alembic migration、依赖、配置项、API 或前端功能。
- 不撤回已经成功发布的任务，也不提供跨 MySQL 与 Celery broker 的分布式事务。
- 不修改原脚本已有筛选结果、默认状态集合或本地解析行为。

## 需求列表 Requirements

### REQ-001：保持候选文件筛选与 dry-run 安全语义

作为平台运维人员，我需要用与现有重解析脚本一致的筛选条件预览候选文件，以便在不产生副作用的前提下确认影响范围。

#### 验收标准 Acceptance Criteria

- `AC-REQ-001-01`: WHEN 不传范围参数或组合使用 `--space-id`、`--folder-id`、`--file-id`、`--space-level` THEN 新脚本 SHALL 复用现有候选收集逻辑并得到相同的真实文件集合、去重规则和跳过统计。
- `AC-REQ-001-02`: WHEN 不传 `--status`、显式重复传入 `--status`、使用 `--include-inflight` 或 `--only-inflight` THEN 新脚本 SHALL 沿用原脚本的状态集合与参数互斥规则。
- `AC-REQ-001-03`: WHEN 未传入 `--apply` THEN 新脚本 SHALL 只输出选择摘要，不更新任何 `KnowledgeFile` 字段且不调用 Celery 发布接口。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-001-01 | V-AC-REQ-001-01 | automated unit/regression test | 复用 `collect_candidate_files`，并执行现有筛选测试与新脚本参数透传断言 |
| AC-REQ-001-02 | V-AC-REQ-001-02 | parameterized CLI unit test | 默认、显式状态及互斥参数结果与原脚本一致 |
| AC-REQ-001-03 | V-AC-REQ-001-03 | automated side-effect test | mock DB update 与 Celery publisher 均为 0 次调用 |

### REQ-002：以正确状态和租户上下文发布重试解析任务

作为平台运维人员，我需要候选文件由其所属租户的知识库 worker 执行完整重试解析，以便复用现有向量清理和解析链路。

#### 验收标准 Acceptance Criteria

- `AC-REQ-002-01`: WHEN `--apply` 处理一个仍满足筛选状态的真实知识空间文件 THEN 脚本 SHALL 在发布前将其持久化为 `status=WAITING`、`remark=""`、`simhash=None`、`similar_status=0`。
- `AC-REQ-002-02`: WHEN 文件状态在筛选后、发布前已变为本次有效状态集合之外，或记录已删除/变成目录/不再属于知识空间 THEN 脚本 SHALL 跳过该记录且不得发布任务。
- `AC-REQ-002-03`: WHEN 状态更新成功 THEN 脚本 SHALL 调用 `retry_knowledge_file_celery.apply_async`，参数包含目标 `file_id`，queue 为 `knowledge_celery`，header 中 `tenant_id` 等于文件所属租户。
- `AC-REQ-002-04`: WHEN 多个租户的文件同时命中 THEN 每个任务 SHALL 使用各自文件的 `tenant_id`，不得回退为默认租户或复用上一文件上下文。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-002-01 | V-AC-REQ-002-01 | automated unit test | 持久化对象四个字段的调用断言 |
| AC-REQ-002-02 | V-AC-REQ-002-02 | parameterized race/eligibility test | 删除、目录、状态漂移、非空间四类结果均不发布 |
| AC-REQ-002-03 | V-AC-REQ-002-03 | Celery publisher mock test | `args`、`queue`、`headers` 精确断言 |
| AC-REQ-002-04 | V-AC-REQ-002-04 | multi-tenant parameterized test | 两个不同租户生成互不污染的 task headers |

### REQ-003：单文件发布失败可补偿并准确汇报

作为平台运维人员，我需要单个文件发布失败不污染其数据库状态、也不阻断其余候选文件，以便批量维修能够得到可追踪的部分成功结果。

#### 验收标准 Acceptance Criteria

- `AC-REQ-003-01`: WHEN Celery 发布接口在确认成功前抛出异常 THEN 脚本 SHALL 尝试恢复该文件发布前的 `status`、`remark`、`simhash`、`similar_status`，记录发布异常，并继续处理其他文件。
- `AC-REQ-003-02`: WHEN 补偿恢复也失败 THEN 脚本 SHALL 同时报告发布错误与恢复错误，不得把文件计为成功或静默吞掉异常。
- `AC-REQ-003-03`: WHEN 任一文件发布失败或补偿失败 THEN 最终摘要 SHALL 区分 `selected`、`enqueued`、`skipped`、`failed`，进程 SHALL 返回非零退出码；全部候选均成功发布或合法跳过时返回 `0`。
- `AC-REQ-003-04`: WHEN 任务成功发布 THEN 脚本 SHALL 只输出“成功入队”，不得等待或宣称文件解析成功。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-003-01 | V-AC-REQ-003-01 | automated failure-path test | publisher 抛错后字段按快照恢复，后续文件仍被处理 |
| AC-REQ-003-02 | V-AC-REQ-003-02 | automated double-failure test | 输出/结果对象同时保留 publish 与 rollback 错误 |
| AC-REQ-003-03 | V-AC-REQ-003-03 | report and exit-code test | 部分失败返回非零，全部成功或合法跳过返回 `0` |
| AC-REQ-003-04 | V-AC-REQ-003-04 | output contract test | 日志和摘要只使用 enqueue/queued 语义 |

### REQ-004：符合现有运维脚本交付与兼容约束

作为平台运维人员，我需要脚本可从后端根目录直接运行并有清晰文档，以便在现有部署环境中安全使用。

#### 验收标准 Acceptance Criteria

- `AC-REQ-004-01`: WHEN 从 `src/backend/` 执行 Python 脚本或 shell 包装器 THEN 本地源码导入、解释器探测和参数转发 SHALL 符合 `scripts/AGENTS.md` 约定。
- `AC-REQ-004-02`: WHEN 运维人员阅读 `scripts/README.md` 或执行 `--help` THEN SHALL 能看到 dry-run、`--apply`、筛选参数、成功入队定义、worker 前置条件及 in-flight 重复解析风险。
- `AC-REQ-004-03`: WHEN 运行定向测试与静态检查 THEN 新增脚本、测试和包装器 SHALL 不引入依赖、方言专有 SQL、worker/API/Schema 变更或架构守卫违规。

#### 验证方式 Verification Methods

| Acceptance ID | Verification ID | Method | Evidence Target |
|---|---|---|---|
| AC-REQ-004-01 | V-AC-REQ-004-01 | CLI smoke test | shell 语法检查及 Python `--help` 成功 |
| AC-REQ-004-02 | V-AC-REQ-004-02 | static documentation review | README 与 argparse help 包含必要操作和风险说明 |
| AC-REQ-004-03 | V-AC-REQ-004-03 | targeted pytest + Ruff + compile check | 定向测试、`ruff format --check`、`ruff check`、`compileall`、`git diff --check` |

## 非功能需求 Non-Functional Requirements

- `NFR-001`: 默认路径必须是无副作用 dry-run；任何数据库写入和消息发布都必须由 `--apply` 显式授权。
- `NFR-002`: 跨租户选择使用 `bypass_tenant_filter()`，但每个 worker 任务必须恢复到资源所属租户，不能以跨租户 bypass 状态执行解析。
- `NFR-003`: 不使用 MySQL 或 DM8 方言专有 SQL；复用现有 ORM/DAO 与 Celery 任务接口。
- `NFR-004`: 单文件失败不得停止批次；异常不得静默吞掉，最终退出码必须可供自动化运维判断。
- `NFR-005`: 不自行引入固定并发、批量大小或限速配置；发布按候选顺序逐文件进行，worker 并发由现有队列配置控制。

## 澄清记录 Clarifications

### Session 2026-07-28

- Q: 是否完整保留原脚本筛选参数和默认 dry-run？ -> A: 是。
- Q: 是否将文件设为 `WAITING`、清空重解析相关字段并投递 `retry_knowledge_file_celery`？ -> A: 是。
- Q: 是否只确认入队、不等待解析；单文件发布失败恢复原字段、继续处理并返回非零？ -> A: 是。

## 假设 Assumptions

- 新脚本暂定名为 `enqueue_reparse_knowledge_space_files.py`，名称只影响运维入口，不改变已确认行为。
- 成功调用 `apply_async` 并返回 task result 视为 broker 接受发布；不检查 worker 在线状态或任务最终结果。
- `--concurrency` 属于原脚本的本地解析执行参数，不是筛选参数，因此不在新脚本保留；新脚本逐文件发布。

## 风险 Risks

- MySQL 状态更新与 Celery broker 发布无法组成原子事务。发布异常可能存在“broker 已接受但客户端未收到确认”的不确定窗口；脚本只能按调用结果补偿并准确报告，不能保证跨系统 exactly-once。
- 显式选择 `WAITING/PROCESSING/REBUILDING` 文件可能与既有任务重复执行；这些状态继续保持显式 opt-in，并在 CLI/README 中提示风险。
- 大范围无过滤执行可能一次发布大量任务；dry-run 摘要是执行前的强制安全观察点，但本 Feature 不新增 broker 限流器或队列容量探测。
- 当前工作区已有用户对 `src/backend/scripts/README.md` 的未提交修改；实现阶段只能做最小追加并保留现有内容。

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
